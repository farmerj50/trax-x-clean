from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from math import log10
from typing import Any

import requests
from cachetools import TTLCache
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

import config
from utils.premarket_detector import detect_premarket_setup
from utils.fetch_ticker_news import fetch_ticker_news


API_KEY = config.POLYGON_API_KEY
SNAPSHOT_CACHE = TTLCache(maxsize=1, ttl=45)
NEWS_CACHE = TTLCache(maxsize=256, ttl=180)
BAR_CACHE = TTLCache(maxsize=512, ttl=20)
analyzer = SentimentIntensityAnalyzer()

CONTRACT_KEYWORDS = {
    "contract",
    "award",
    "federal",
    "government",
    "dod",
    "pentagon",
    "army",
    "navy",
    "air force",
    "agency",
}
EARNINGS_KEYWORDS = {"earnings", "guidance", "revenue", "eps", "forecast"}
APPROVAL_KEYWORDS = {"approval", "fda", "clearance", "trial", "phase"}
UPGRADE_KEYWORDS = {"upgrade", "initiated", "buy rating", "price target"}
MERGER_KEYWORDS = {"acquire", "acquisition", "merger", "deal", "takeover"}
POLITICAL_KEYWORDS = {"senator", "congress", "representative", "house", "senate"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _first_positive(*values: Any, default: float = 0.0) -> float:
    for value in values:
        parsed = _safe_float(value, default=0.0)
        if parsed > 0:
            return parsed
    return default


def _fetch_snapshot_rows() -> list[dict]:
    cached = SNAPSHOT_CACHE.get("rows")
    if cached is not None:
        return cached

    url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
    try:
        response = requests.get(url, params={"apiKey": API_KEY}, timeout=20)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Polygon snapshot request failed: {exc}") from exc
    rows = response.json().get("tickers", []) or []
    SNAPSHOT_CACHE["rows"] = rows
    return rows


def _fetch_recent_minute_bars(ticker: str, window_minutes: int = 15) -> list[dict]:
    cache_key = f"{str(ticker).upper()}:{window_minutes}"
    cached = BAR_CACHE.get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    session_date = now.date().isoformat()
    url = f"https://api.polygon.io/v2/aggs/ticker/{str(ticker).upper()}/range/1/minute/{session_date}/{session_date}"
    response = requests.get(
        url,
        params={
            "adjusted": "true",
            "sort": "asc",
            "limit": 5000,
            "apiKey": API_KEY,
        },
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json().get("results", []) or []
    cutoff_ms = int((now - timedelta(minutes=max(window_minutes * 2, 20))).timestamp() * 1000)
    recent_rows = [row for row in rows if _safe_float(row.get("t")) >= cutoff_ms]
    trimmed = recent_rows[-max(window_minutes, 12):]
    BAR_CACHE[cache_key] = trimmed
    return trimmed


def _session_change_pct(row: dict, price: float, prev_close: float) -> float:
    session = row.get("session") or {}
    minute = row.get("min") or {}
    candidates = [
        row.get("todaysChangePerc"),
        row.get("todaysChangePercent"),
        row.get("preMarketChangePercent"),
        row.get("preMarketChangePerc"),
        row.get("premarketChangePercent"),
        row.get("premarketChangePerc"),
        row.get("earlyTradingChangePercent"),
        row.get("earlyTradingChangePerc"),
        session.get("preMarketChangePercent"),
        session.get("preMarketChangePerc"),
        session.get("premarketChangePercent"),
        session.get("premarketChangePerc"),
        session.get("earlyTradingChangePercent"),
        session.get("earlyTradingChangePerc"),
        minute.get("changePercent"),
    ]
    for value in candidates:
        if value is None:
            continue
        return _safe_float(value, 0.0)
    if price > 0 and prev_close > 0:
        return ((price - prev_close) / prev_close) * 100.0
    return 0.0


def _extract_sector(row: dict) -> str:
    session = row.get("session") or {}
    for value in [
        row.get("sector"),
        row.get("sic_description"),
        row.get("sicDescription"),
        row.get("market_sector"),
        row.get("industry"),
        session.get("sector"),
    ]:
        text = str(value or "").strip()
        if text:
            return text
    return "Unclassified"


def _extract_company_name(row: dict) -> str:
    for value in [row.get("name"), row.get("ticker"), (row.get("details") or {}).get("name")]:
        text = str(value or "").strip()
        if text:
            return text
    return str(row.get("ticker") or "").upper()


def _extract_market_cap(row: dict) -> float:
    details = row.get("details") or {}
    return _first_positive(
        row.get("market_cap"),
        row.get("marketCap"),
        details.get("market_cap"),
        details.get("marketCap"),
        default=0.0,
    )


def _parse_snapshot_row(row: dict) -> dict | None:
    ticker = str(row.get("ticker") or "").upper().strip()
    if not ticker:
        return None

    day = row.get("day") or {}
    prev_day = row.get("prevDay") or {}
    last_trade = row.get("lastTrade") or {}
    session = row.get("session") or {}
    minute = row.get("min") or {}

    prev_close = _first_positive(prev_day.get("c"), day.get("o"), default=0.0)
    price = _first_positive(
        minute.get("c"),
        minute.get("o"),
        minute.get("h"),
        minute.get("l"),
        row.get("preMarketPrice"),
        row.get("premarketPrice"),
        row.get("earlyTradingPrice"),
        session.get("preMarketPrice"),
        session.get("premarketPrice"),
        session.get("earlyTradingPrice"),
        session.get("price"),
        day.get("c"),
        last_trade.get("p"),
        prev_close,
        default=0.0,
    )
    if price <= 0:
        return None

    premarket_volume = _first_positive(
        minute.get("av"),
        minute.get("v"),
        minute.get("dv"),
        row.get("preMarketVolume"),
        row.get("premarketVolume"),
        row.get("earlyTradingVolume"),
        session.get("preMarketVolume"),
        session.get("premarketVolume"),
        session.get("earlyTradingVolume"),
        day.get("v"),
        default=0.0,
    )
    premarket_high = _first_positive(
        minute.get("h"),
        minute.get("c"),
        row.get("preMarketHigh"),
        row.get("premarketHigh"),
        row.get("earlyTradingHigh"),
        session.get("preMarketHigh"),
        session.get("premarketHigh"),
        session.get("earlyTradingHigh"),
        session.get("high"),
        day.get("h"),
        price,
        default=price,
    )
    premarket_low = _first_positive(
        minute.get("l"),
        minute.get("c"),
        row.get("preMarketLow"),
        row.get("premarketLow"),
        row.get("earlyTradingLow"),
        session.get("preMarketLow"),
        session.get("premarketLow"),
        session.get("earlyTradingLow"),
        session.get("low"),
        day.get("l"),
        price,
        default=price,
    )
    prev_volume = _first_positive(prev_day.get("v"), default=0.0)
    gap_percent = _session_change_pct(row, price, prev_close)
    baseline_volume = max(prev_volume * 0.10, 100_000.0)
    relative_volume = premarket_volume / baseline_volume if baseline_volume > 0 else 0.0
    distance_to_high_pct = ((premarket_high - price) / premarket_high) * 100.0 if premarket_high > 0 else 0.0

    return {
        "ticker": ticker,
        "companyName": _extract_company_name(row),
        "price": round(price, 4),
        "prevClose": round(prev_close, 4),
        "gapPercent": round(gap_percent, 4),
        "premarketVolume": round(premarket_volume, 0),
        "premarketHigh": round(premarket_high, 4),
        "premarketLow": round(premarket_low, 4),
        "distanceToPremarketHighPct": round(max(distance_to_high_pct, 0.0), 4),
        "relativeVolume": round(relative_volume, 4),
        "marketCap": round(_extract_market_cap(row), 0),
        "sector": _extract_sector(row),
        "primaryExchange": str(row.get("primary_exchange") or row.get("primaryExchange") or "").strip(),
    }


def _fetch_news_cached(ticker: str, limit: int = 4) -> list[dict]:
    cache_key = f"{ticker}:{limit}"
    cached = NEWS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    news_items = fetch_ticker_news(ticker, limit=limit)
    NEWS_CACHE[cache_key] = news_items
    return news_items


def _classify_catalyst(headlines: list[str]) -> str:
    text = " ".join(headlines).lower()
    if any(keyword in text for keyword in CONTRACT_KEYWORDS):
        return "contract"
    if any(keyword in text for keyword in APPROVAL_KEYWORDS):
        return "approval"
    if any(keyword in text for keyword in EARNINGS_KEYWORDS):
        return "earnings"
    if any(keyword in text for keyword in MERGER_KEYWORDS):
        return "merger"
    if any(keyword in text for keyword in UPGRADE_KEYWORDS):
        return "analyst"
    return "news"


def _headline_sentiment(news_items: list[dict]) -> tuple[float, list[str]]:
    if not news_items:
        return 0.0, []

    scores = []
    headlines = []
    for item in news_items[:4]:
        title = str(item.get("title") or "").strip()
        summary = str(item.get("description") or item.get("summary") or "").strip()
        text = f"{title}. {summary}".strip(". ")
        if title:
            headlines.append(title)
        if not text:
            continue
        scores.append(analyzer.polarity_scores(text).get("compound", 0.0))

    if not scores:
        return 0.0, headlines
    return sum(scores) / len(scores), headlines


def _sector_stats(rows: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("sector") or "Unclassified")].append(row)

    stats: dict[str, dict] = {}
    for sector, entries in grouped.items():
        if not entries:
            continue
        avg_gap = sum(_safe_float(item.get("gapPercent")) for item in entries) / len(entries)
        avg_rvol = sum(_safe_float(item.get("relativeVolume")) for item in entries) / len(entries)
        stats[sector] = {
            "avg_gap": avg_gap,
            "avg_rvol": avg_rvol,
            "count": len(entries),
        }
    return stats


def _volume_score(base: dict) -> float:
    premarket_volume = _safe_float(base.get("premarketVolume"))
    relative_volume = _safe_float(base.get("relativeVolume"))
    absolute_component = _clip((premarket_volume / 2_500_000.0) * 55.0)
    relative_component = _clip((relative_volume / 4.0) * 45.0)
    return round(_clip(absolute_component + relative_component), 2)


def _gap_score(base: dict, sentiment: float) -> float:
    gap_percent = abs(_safe_float(base.get("gapPercent")))
    gap_component = _clip((gap_percent / 12.0) * 80.0)
    alignment_bonus = 20.0 if sentiment >= 0.15 and _safe_float(base.get("gapPercent")) > 0 else 0.0
    return round(_clip(gap_component + alignment_bonus), 2)


def _sentiment_score(sentiment: float) -> float:
    return round(_clip((sentiment + 1.0) * 50.0), 2)


def _catalyst_score(news_items: list[dict], sentiment: float, catalyst_type: str) -> float:
    headline_count = len(news_items)
    base = min(headline_count * 18.0, 54.0)
    sentiment_component = _clip(abs(sentiment) * 30.0)
    catalyst_bonus = {
        "contract": 26.0,
        "approval": 24.0,
        "earnings": 22.0,
        "merger": 20.0,
        "analyst": 16.0,
        "news": 12.0,
    }.get(catalyst_type, 10.0)
    return round(_clip(base + sentiment_component + catalyst_bonus), 2)


def _liquidity_score(base: dict) -> float:
    price = _safe_float(base.get("price"))
    premarket_volume = _safe_float(base.get("premarketVolume"))
    market_cap = _safe_float(base.get("marketCap"))
    price_component = 30.0 if 2.0 <= price <= 250.0 else 18.0 if price > 0.5 else 5.0
    volume_component = _clip((premarket_volume / 1_500_000.0) * 45.0)
    cap_component = 25.0 if market_cap >= 2_000_000_000 else 18.0 if market_cap >= 300_000_000 else 10.0
    return round(_clip(price_component + volume_component + cap_component), 2)


def _float_pressure_score(base: dict) -> float:
    market_cap = _safe_float(base.get("marketCap"))
    relative_volume = _safe_float(base.get("relativeVolume"))
    if market_cap <= 0:
        cap_component = 35.0
    else:
        cap_component = _clip(100.0 - ((log10(max(market_cap, 1.0)) - 7.0) / 5.0) * 100.0)
    participation_component = _clip((relative_volume / 5.0) * 40.0)
    return round(_clip((cap_component * 0.6) + participation_component), 2)


def _sector_strength_score(base: dict, sector_lookup: dict[str, dict]) -> float:
    sector = str(base.get("sector") or "Unclassified")
    sector_data = sector_lookup.get(sector) or {}
    avg_gap = abs(_safe_float(sector_data.get("avg_gap")))
    avg_rvol = _safe_float(sector_data.get("avg_rvol"))
    gap_component = _clip((avg_gap / 5.0) * 55.0)
    volume_component = _clip((avg_rvol / 3.0) * 45.0)
    return round(_clip(gap_component + volume_component), 2)


def _options_score(base: dict) -> float:
    price = _safe_float(base.get("price"))
    market_cap = _safe_float(base.get("marketCap"))
    if price >= 5 and market_cap >= 2_000_000_000:
        return 72.0
    if price >= 3 and market_cap >= 500_000_000:
        return 58.0
    return 34.0


def _contract_score(catalyst_type: str, headlines: list[str]) -> float:
    text = " ".join(headlines).lower()
    keyword_hits = sum(1 for keyword in CONTRACT_KEYWORDS if keyword in text)
    base = 65.0 if catalyst_type == "contract" else 12.0
    return round(_clip(base + (keyword_hits * 5.0)), 2)


def _political_signal_score(headlines: list[str]) -> float:
    text = " ".join(headlines).lower()
    if any(keyword in text for keyword in POLITICAL_KEYWORDS):
        return 28.0
    return 0.0


def _published_datetime(item: dict) -> datetime | None:
    raw_value = item.get("published_utc") or item.get("publishedUtc") or item.get("published")
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _news_age_minutes(news_items: list[dict]) -> float | None:
    now = datetime.now(timezone.utc)
    published_times = [published for item in news_items if (published := _published_datetime(item)) is not None]
    if not published_times:
        return None
    freshest = max(published_times)
    return max((now - freshest).total_seconds() / 60.0, 0.0)


def _live_volume_metrics(ticker: str) -> dict[str, float]:
    bars = _fetch_recent_minute_bars(ticker, window_minutes=15)
    if not bars:
        return {
            "minuteBarCount": 0.0,
            "volumeLast5Min": 0.0,
            "volumePrev5Min": 0.0,
            "volumeAcceleration": 0.0,
        }

    volumes = [_safe_float(row.get("v")) for row in bars]
    last_5 = sum(volumes[-5:])
    prev_5 = sum(volumes[-10:-5]) if len(volumes) >= 10 else sum(volumes[:-5])
    if prev_5 > 0:
        acceleration = last_5 / prev_5
    elif last_5 > 0 and len(volumes) >= 3:
        acceleration = 2.0
    else:
        acceleration = 0.0

    return {
        "minuteBarCount": float(len(bars)),
        "volumeLast5Min": round(last_5, 2),
        "volumePrev5Min": round(prev_5, 2),
        "volumeAcceleration": round(acceleration, 4),
    }


def _early_gap_score(base: dict) -> float:
    gap_percent = _safe_float(base.get("gapPercent"))
    if gap_percent <= 0:
        return 0.0
    if gap_percent < 1.0:
        return round(_clip((gap_percent / 1.0) * 30.0), 2)
    if gap_percent <= 4.0:
        center_distance = abs(gap_percent - 2.5)
        return round(_clip(100.0 - (center_distance * 22.0), 45.0, 100.0), 2)
    if gap_percent <= 8.0:
        return round(_clip(68.0 - ((gap_percent - 4.0) * 11.0), 18.0, 68.0), 2)
    return 8.0


def _breakout_proximity_score(base: dict) -> float:
    gap_percent = _safe_float(base.get("gapPercent"))
    distance_pct = _safe_float(base.get("distanceToPremarketHighPct"))
    if gap_percent <= 0:
        return 0.0
    if distance_pct <= 0.4:
        return 100.0
    if distance_pct <= 1.0:
        return 90.0
    if distance_pct <= 2.0:
        return 78.0
    if distance_pct <= 3.5:
        return 55.0
    if distance_pct <= 5.0:
        return 32.0
    return 12.0


def _early_participation_score(base: dict) -> float:
    relative_volume = _safe_float(base.get("relativeVolume"))
    premarket_volume = _safe_float(base.get("premarketVolume"))
    rvol_component = _clip((relative_volume / 2.5) * 70.0)
    absolute_component = _clip((premarket_volume / 600_000.0) * 30.0)
    return round(_clip(rvol_component + absolute_component), 2)


def _live_volume_acceleration_score(volume_acceleration: float) -> float:
    if volume_acceleration >= 3.0:
        return 100.0
    if volume_acceleration >= 2.0:
        return 92.0
    if volume_acceleration >= 1.5:
        return 76.0
    if volume_acceleration >= 1.2:
        return 58.0
    if volume_acceleration >= 1.0:
        return 40.0
    if volume_acceleration >= 0.8:
        return 24.0
    return 8.0


def _early_catalyst_score(sentiment: float, catalyst_type: str, headline_count: int) -> float:
    catalyst_bonus = {
        "contract": 100.0,
        "approval": 94.0,
        "earnings": 88.0,
        "merger": 82.0,
        "analyst": 72.0,
        "news": 58.0,
    }.get(catalyst_type, 40.0)
    headline_bonus = min(max(headline_count, 0), 4) * 6.0
    sentiment_bonus = _clip(max(sentiment, 0.0) * 20.0)
    return round(_clip(catalyst_bonus + headline_bonus + sentiment_bonus), 2)


def _news_freshness_score(news_items: list[dict]) -> float:
    age_minutes = _news_age_minutes(news_items)
    if age_minutes is None:
        return 10.0
    if age_minutes <= 30:
        return 100.0
    if age_minutes <= 60:
        return 82.0
    if age_minutes <= 120:
        return 58.0
    if age_minutes <= 240:
        return 34.0
    return 18.0


def _extension_penalty(gap_percent: float) -> float:
    positive_gap = max(gap_percent, 0.0)
    if positive_gap > 25.0:
        return 55.0
    if positive_gap > 15.0:
        return 40.0
    if positive_gap > 8.0:
        return 20.0
    return 0.0


def _early_pressure_score(base: dict, sentiment: float, catalyst_type: str, headline_count: int) -> tuple[float, dict[str, float]]:
    components = {
        "gapSweetSpotScore": _early_gap_score(base),
        "participationScore": _early_participation_score(base),
        "breakoutProximityScore": _breakout_proximity_score(base),
        "floatPressureProxyScore": _float_pressure_score(base),
        "catalystSupportScore": _early_catalyst_score(sentiment, catalyst_type, headline_count),
        "sentimentAlignmentScore": round(_clip(max(sentiment, 0.0) * 100.0), 2),
    }
    score = (
        components["gapSweetSpotScore"] * 0.24
        + components["participationScore"] * 0.24
        + components["breakoutProximityScore"] * 0.22
        + components["catalystSupportScore"] * 0.18
        + components["floatPressureProxyScore"] * 0.08
        + components["sentimentAlignmentScore"] * 0.04
    )
    return round(_clip(score), 2), components


def _live_early_pressure_score(base: dict, sentiment: float, catalyst_type: str, news_items: list[dict]) -> tuple[float, dict[str, float]]:
    live_metrics = _live_volume_metrics(str(base.get("ticker") or ""))
    gap_percent = _safe_float(base.get("gapPercent"))
    components = {
        "gapSweetSpotScore": _early_gap_score(base),
        "volumeAccelerationScore": _live_volume_acceleration_score(_safe_float(live_metrics.get("volumeAcceleration"))),
        "participationScore": _early_participation_score(base),
        "breakoutProximityScore": _breakout_proximity_score(base),
        "catalystSupportScore": _early_catalyst_score(sentiment, catalyst_type, len(news_items)),
        "newsFreshnessScore": _news_freshness_score(news_items),
        "floatPressureProxyScore": _float_pressure_score(base),
        "extensionPenalty": _extension_penalty(gap_percent),
    }
    score = (
        components["gapSweetSpotScore"] * 0.20
        + components["volumeAccelerationScore"] * 0.28
        + components["participationScore"] * 0.12
        + components["breakoutProximityScore"] * 0.18
        + components["catalystSupportScore"] * 0.10
        + components["newsFreshnessScore"] * 0.08
        + components["floatPressureProxyScore"] * 0.04
        - components["extensionPenalty"]
    )
    return round(_clip(score), 2), {
        **components,
        **live_metrics,
    }


def _early_pressure_state(base: dict, early_pressure_score: float) -> str:
    gap_percent = _safe_float(base.get("gapPercent"))
    distance_pct = _safe_float(base.get("distanceToPremarketHighPct"))
    if gap_percent > 0 and distance_pct <= 1.5 and early_pressure_score >= 75:
        return "near_breakout"
    if gap_percent > 0 and distance_pct <= 3.0 and early_pressure_score >= 60:
        return "building_pressure"
    if gap_percent > 0 and distance_pct > 3.0 and early_pressure_score >= 50:
        return "early_watch"
    if gap_percent <= 0:
        return "not_applicable"
    return "extended_or_low_quality"


def _live_early_pressure_state(base: dict, early_pressure_score: float, breakdown: dict[str, float]) -> str:
    gap_percent = _safe_float(base.get("gapPercent"))
    distance_pct = _safe_float(base.get("distanceToPremarketHighPct"))
    volume_acceleration = _safe_float(breakdown.get("volumeAcceleration"))
    if gap_percent <= 0:
        return "not_applicable"
    if gap_percent > 15.0:
        return "extended_or_low_quality"
    if early_pressure_score >= 72 and distance_pct <= 2.0 and volume_acceleration >= 1.4:
        return "near_breakout"
    if early_pressure_score >= 58 and distance_pct <= 4.0 and volume_acceleration >= 1.1:
        return "building_pressure"
    if early_pressure_score >= 42:
        return "early_watch"
    return "extended_or_low_quality"


def _weighted_score(components: dict[str, float]) -> float:
    score = (
        components["premarketVolumeScore"] * 0.22
        + components["gapStrengthScore"] * 0.14
        + components["catalystScore"] * 0.18
        + components["sentimentScore"] * 0.10
        + components["liquidityScore"] * 0.12
        + components["floatPressureScore"] * 0.08
        + components["sectorStrengthScore"] * 0.08
        + components["optionsScore"] * 0.05
        + components["contractScore"] * 0.02
        + components["politicalSignalScore"] * 0.01
    )
    return round(_clip(score), 2)


def _conviction(score: float) -> str:
    if score >= 85:
        return "high"
    if score >= 70:
        return "medium"
    return "low"


def _setup_type(base: dict, catalyst_type: str, score: float, sentiment: float) -> str:
    gap_percent = _safe_float(base.get("gapPercent"))
    if score >= 82 and catalyst_type in {"contract", "approval", "earnings", "merger"}:
        return "momentum_continuation"
    if score >= 74 and sentiment >= 0.15 and gap_percent > 0:
        return "catalyst_breakout"
    if gap_percent < 0 and score >= 68:
        return "reversal_watch"
    if score < 60:
        return "fade_candidate"
    return "sympathy_watch"


def _risk_summary(base: dict, score: float, sentiment: float) -> str:
    gap_percent = abs(_safe_float(base.get("gapPercent")))
    premarket_volume = _safe_float(base.get("premarketVolume"))
    if gap_percent >= 10 and premarket_volume < 750_000:
        return "Large gap with lighter participation increases open-fade risk."
    if sentiment < -0.15:
        return "Headline tone is mixed-to-negative, so continuation quality is weaker."
    if score >= 82:
        return "Strong setup, but opening volatility can still shake weak entries."
    return "Catalyst quality is moderate, so confirmation after the open still matters."


def _ai_summary(base: dict, catalyst_type: str, score: float, sentiment: float) -> str:
    ticker = base.get("ticker")
    volume = _safe_float(base.get("relativeVolume"))
    gap = _safe_float(base.get("gapPercent"))
    if score >= 85:
        return f"{ticker} is showing a high-conviction premarket move backed by {catalyst_type} context and elevated participation."
    if sentiment >= 0.2 and volume >= 1.5:
        return f"{ticker} has credible premarket interest with positive headline tone and above-normal activity."
    if gap >= 0:
        return f"{ticker} is moving with some catalyst support, but it still needs open confirmation."
    return f"{ticker} is active premarket, though the move currently looks less durable than the top-ranked names."


def _build_relationships(stock: dict, peer_rows: list[dict], headlines: list[str]) -> dict:
    related_tickers = [
        row["ticker"]
        for row in peer_rows
        if row.get("ticker") != stock.get("ticker") and row.get("sector") == stock.get("sector")
    ][:3]

    nodes = [
        {"id": stock["ticker"], "label": stock["ticker"], "type": "stock"},
        {"id": stock["sector"], "label": stock["sector"], "type": "sector"},
        {"id": stock["catalystType"], "label": stock["catalystType"].replace("_", " "), "type": "catalyst"},
    ]
    edges = [
        {"source": stock["ticker"], "target": stock["sector"], "label": "sector"},
        {"source": stock["ticker"], "target": stock["catalystType"], "label": "catalyst"},
    ]

    for peer in related_tickers:
        nodes.append({"id": peer, "label": peer, "type": "peer"})
        edges.append({"source": stock["ticker"], "target": peer, "label": "sympathy"})

    for index, headline in enumerate(headlines[:3], start=1):
        node_id = f"headline-{stock['ticker']}-{index}"
        nodes.append({"id": node_id, "label": headline[:44], "type": "headline"})
        edges.append({"source": stock["ticker"], "target": node_id, "label": "news"})

    return {
        "sector": stock["sector"],
        "relatedTickers": related_tickers,
        "headlines": headlines[:3],
        "graph": {"nodes": nodes, "edges": edges},
    }


def _enrich_candidate(base: dict, sector_lookup: dict[str, dict]) -> dict:
    news_items = _fetch_news_cached(base["ticker"], limit=4)
    sentiment, headlines = _headline_sentiment(news_items)
    catalyst_type = _classify_catalyst(headlines)
    early_pressure_score, early_pressure_breakdown = _early_pressure_score(
        base,
        sentiment,
        catalyst_type,
        len(news_items),
    )
    score_breakdown = {
        "premarketVolumeScore": _volume_score(base),
        "gapStrengthScore": _gap_score(base, sentiment),
        "catalystScore": _catalyst_score(news_items, sentiment, catalyst_type),
        "sentimentScore": _sentiment_score(sentiment),
        "liquidityScore": _liquidity_score(base),
        "floatPressureScore": _float_pressure_score(base),
        "sectorStrengthScore": _sector_strength_score(base, sector_lookup),
        "optionsScore": _options_score(base),
        "contractScore": _contract_score(catalyst_type, headlines),
        "politicalSignalScore": _political_signal_score(headlines),
    }
    score = _weighted_score(score_breakdown)
    detector = detect_premarket_setup(
        {
            **base,
            "sentiment": sentiment,
            "catalystType": catalyst_type,
            "marketCap": base.get("marketCap"),
            "earlyPressureBreakdown": early_pressure_breakdown,
        }
    )
    return {
        **base,
        "score": score,
        "conviction": _conviction(score),
        "setupType": _setup_type(base, catalyst_type, score, sentiment),
        "catalystType": catalyst_type,
        "headlineCount": len(news_items),
        "sentiment": round(sentiment, 4),
        "liquidityGrade": "A" if score_breakdown["liquidityScore"] >= 80 else "B" if score_breakdown["liquidityScore"] >= 60 else "C",
        "entryQuality": "A" if score >= 85 else "B" if score >= 70 else "C",
        "confidence": round(score / 100.0, 2),
        "risk": _risk_summary(base, score, sentiment),
        "aiSummary": _ai_summary(base, catalyst_type, score, sentiment),
        "earlyPressureScore": early_pressure_score,
        "earlyPressureState": _early_pressure_state(base, early_pressure_score),
        "earlyPressureBreakdown": early_pressure_breakdown,
        "detectorScore": detector["detectorScore"],
        "detectorState": detector["detectorState"],
        "triggerFlags": detector["triggerFlags"],
        "scoreBreakdown": score_breakdown,
        "headlines": headlines,
        "newsItems": news_items[:4],
    }


def _enrich_candidates(base_rows: list[dict], sector_lookup: dict[str, dict]) -> list[dict]:
    if not base_rows:
        return []

    with ThreadPoolExecutor(max_workers=min(8, max(2, len(base_rows)))) as executor:
        enriched = list(executor.map(lambda base: _enrich_candidate(base, sector_lookup), base_rows))
    enriched.sort(
        key=lambda item: (
            _safe_float(item.get("earlyPressureScore")),
            _safe_float(item.get("premarketVolume")),
            -abs(_safe_float(item.get("distanceToPremarketHighPct"))),
        ),
        reverse=True,
    )
    return enriched


def _apply_filters(rows: list[dict], filters: dict[str, Any]) -> list[dict]:
    min_gap_pct = _safe_float(filters.get("min_gap_pct"), 0.0)
    min_volume = _safe_float(filters.get("min_volume"), 0.0)
    sector = str(filters.get("sector") or "").strip().lower()
    positive_only = str(filters.get("positive_only", "false")).strip().lower() in {"1", "true", "yes", "on"}

    filtered = []
    for row in rows:
        if abs(_safe_float(row.get("gapPercent"))) < min_gap_pct:
            continue
        if _safe_float(row.get("premarketVolume")) < min_volume:
            continue
        if sector and sector not in str(row.get("sector") or "").lower():
            continue
        if positive_only and _safe_float(row.get("sentiment")) < 0:
            continue
        filtered.append(row)
    return filtered


def _initial_candidate_pool(limit: int = 45, *, min_premarket_volume: float = 100_000.0) -> list[dict]:
    parsed_rows = []
    for raw_row in _fetch_snapshot_rows():
        parsed = _parse_snapshot_row(raw_row)
        if not parsed:
            continue

        price = _safe_float(parsed.get("price"))
        premarket_volume = _safe_float(parsed.get("premarketVolume"))
        gap_percent = _safe_float(parsed.get("gapPercent"))
        relative_volume = _safe_float(parsed.get("relativeVolume"))
        market_cap = _safe_float(parsed.get("marketCap"))
        distance_to_high = _safe_float(parsed.get("distanceToPremarketHighPct"))

        if price < 0.5:
            continue
        if premarket_volume < min_premarket_volume:
            continue

        # Broad universe first. Do not kill names just because they are not already huge movers.
        if gap_percent <= -12:
            continue
        if gap_percent >= 35:
            continue

        # Lower-cap / lower-float proxy gets some preference, but not enough to dominate.
        if market_cap <= 0:
            float_proxy_bonus = 8.0
        elif market_cap <= 300_000_000:
            float_proxy_bonus = 10.0
        elif market_cap <= 2_000_000_000:
            float_proxy_bonus = 6.0
        else:
            float_proxy_bonus = 2.0

        # Sweet spot: small positive gaps rank best.
        if gap_percent < 0:
            gap_component = 0.0
        elif gap_percent < 1.0:
            gap_component = 10.0 + (gap_percent * 10.0)
        elif gap_percent <= 4.0:
            gap_component = 28.0 - (abs(gap_percent - 2.5) * 4.0)
        elif gap_percent <= 8.0:
            gap_component = 18.0 - ((gap_percent - 4.0) * 2.5)
        else:
            gap_component = max(0.0, 8.0 - ((gap_percent - 8.0) * 1.2))

        # Participation matters more than absolute extension.
        rvol_component = min(relative_volume, 8.0) * 8.0
        volume_component = min(premarket_volume / 500_000.0, 8.0) * 6.0

        # Prefer names trading closer to premarket highs.
        if distance_to_high <= 0.5:
            proximity_component = 18.0
        elif distance_to_high <= 1.5:
            proximity_component = 14.0
        elif distance_to_high <= 3.0:
            proximity_component = 9.0
        elif distance_to_high <= 5.0:
            proximity_component = 4.0
        else:
            proximity_component = 0.0

        # Penalize obvious/chased names.
        extension_penalty = 0.0
        if gap_percent > 8.0:
            extension_penalty += 14.0
        if gap_percent > 15.0:
            extension_penalty += 20.0
        if gap_percent > 25.0:
            extension_penalty += 28.0

        candidate_pool_score = (
            gap_component
            + rvol_component
            + volume_component
            + proximity_component
            + float_proxy_bonus
            - extension_penalty
        )

        parsed_rows.append(
            {
                **parsed,
                "_candidatePoolScore": round(candidate_pool_score, 4),
            }
        )

    parsed_rows.sort(
        key=lambda row: (
            _safe_float(row.get("_candidatePoolScore")),
            _safe_float(row.get("relativeVolume")),
            -_safe_float(row.get("distanceToPremarketHighPct")),
            _safe_float(row.get("premarketVolume")),
        ),
        reverse=True,
    )
    return parsed_rows[: max(limit, 150)]


def _select_enrichment_seeds(rows: list[dict], *, top_limit: int, multiplier: int, minimum: int) -> list[dict]:
    seed_count = max(top_limit * multiplier, minimum)
    return rows[:seed_count]


def _apply_early_watch_filters(rows: list[dict], filters: dict[str, Any]) -> list[dict]:
    requested_gap = _safe_float(filters.get("min_gap_pct"), 0.0)
    requested_volume = _safe_float(filters.get("min_volume"), 0.0)
    effective_min_gap = min(requested_gap, 1.0) if requested_gap > 0 else 0.5
    effective_min_volume = min(requested_volume, 100_000.0) if requested_volume > 0 else 50_000.0
    sector = str(filters.get("sector") or "").strip().lower()
    positive_only = str(filters.get("positive_only", "false")).strip().lower() in {"1", "true", "yes", "on"}

    filtered = []
    for row in rows:
        gap_percent = _safe_float(row.get("gapPercent"))
        if gap_percent <= 0 or abs(gap_percent) < effective_min_gap:
            continue
        if _safe_float(row.get("premarketVolume")) < effective_min_volume:
            continue
        if sector and sector not in str(row.get("sector") or "").lower():
            continue
        if positive_only and _safe_float(row.get("sentiment")) < 0:
            continue
        filtered.append(row)
    return filtered


def _build_live_early_watch(rows: list[dict], top_limit: int) -> list[dict]:
    if not rows:
        return []

    seed_rows = sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("earlyPressureScore")),
            _safe_float(row.get("relativeVolume")),
            -abs(_safe_float(row.get("distanceToPremarketHighPct"))),
        ),
        reverse=True,
    )[: max(top_limit * 3, 18)]

    def _rescore_live_row(row: dict) -> dict:
        live_score, live_breakdown = _live_early_pressure_score(
            row,
            _safe_float(row.get("sentiment")),
            str(row.get("catalystType") or "news"),
            row.get("newsItems") or [],
        )
        detector = detect_premarket_setup(
            {
                **row,
                "earlyPressureBreakdown": live_breakdown,
                "earlyPressureScore": live_score,
            }
        )
        return {
            **row,
            "earlyPressureScore": live_score,
            "earlyPressureState": _live_early_pressure_state(row, live_score, live_breakdown),
            "earlyPressureBreakdown": live_breakdown,
            "detectorScore": detector["detectorScore"],
            "detectorState": detector["detectorState"],
            "triggerFlags": detector["triggerFlags"],
        }

    with ThreadPoolExecutor(max_workers=min(8, max(2, len(seed_rows)))) as executor:
        rescored = list(executor.map(_rescore_live_row, seed_rows))

    ranked = sorted(
        [row for row in rescored if str(row.get("detectorState")) in {"triggered", "arming", "watch"}],
        key=lambda row: (
            _safe_float(row.get("detectorScore")),
            _safe_float(row.get("earlyPressureScore")),
            _safe_float((row.get("earlyPressureBreakdown") or {}).get("volumeAcceleration")),
            -abs(_safe_float(row.get("distanceToPremarketHighPct"))),
        ),
        reverse=True,
    )[:top_limit]
    if ranked:
        return ranked

    return sorted(
        rescored,
        key=lambda row: (
            _safe_float(row.get("detectorScore")),
            _safe_float(row.get("earlyPressureScore")),
        ),
        reverse=True,
    )[:top_limit]


def _fallback_early_watch(rows: list[dict], top_limit: int) -> list[dict]:
    positive_rows = [row for row in rows if _safe_float(row.get("gapPercent")) > 0]
    if not positive_rows:
        positive_rows = list(rows)
    return sorted(
        positive_rows,
        key=lambda row: (
            _safe_float(row.get("earlyPressureScore")),
            _safe_float(row.get("relativeVolume")),
            -abs(_safe_float(row.get("distanceToPremarketHighPct"))),
        ),
        reverse=True,
    )[:top_limit]


def get_premarket_intelligence(*, limit: int = 8, filters: dict[str, Any] | None = None) -> dict:
    filters = filters or {}
    top_limit = max(3, min(int(limit), 15))
    base_rows = _initial_candidate_pool(limit=max(top_limit * 10, 150), min_premarket_volume=75_000.0)
    if not base_rows:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "marketSession": "premarket",
            "topPicks": [],
            "earlySetupWatch": [],
            "heatmap": [],
            "stocks": [],
            "marketSummary": {
                "bullishCount": 0,
                "bearishCount": 0,
                "highestConvictionSector": "Unclassified",
                "earlySetupCount": 0,
            },
            "filters": filters,
        }

    sector_lookup = _sector_stats(base_rows)
    enriched = _enrich_candidates(
        _select_enrichment_seeds(base_rows, top_limit=top_limit, multiplier=5, minimum=30),
        sector_lookup,
    )
    filtered = _apply_filters(enriched, filters)
    early_filtered = _apply_early_watch_filters(filtered or enriched, filters)

    if not filtered:
        filtered = enriched

    bullish_count = sum(1 for row in filtered if _safe_float(row.get("gapPercent")) >= 0)
    bearish_count = sum(1 for row in filtered if _safe_float(row.get("gapPercent")) < 0)
    sector_scores = Counter()
    for row in filtered[:20]:
        sector_scores[str(row.get("sector") or "Unclassified")] += _safe_float(row.get("score"))

    confirmed_candidates = sorted(
        filtered,
        key=lambda row: (
            _safe_float(row.get("score")),
            _safe_float(row.get("premarketVolume")),
            _safe_float(row.get("gapPercent")),
        ),
        reverse=True,
    )
    top_pick_candidates = sorted(
        filtered,
        key=lambda row: (
            _safe_float(row.get("detectorScore")),
            _safe_float(row.get("earlyPressureScore")),
            _safe_float((row.get("earlyPressureBreakdown") or {}).get("volumeAcceleration")),
            -_safe_float(row.get("distanceToPremarketHighPct")),
            _safe_float(row.get("relativeVolume")),
        ),
        reverse=True,
    )

    top_picks = top_pick_candidates[:top_limit]
    heatmap_rows = confirmed_candidates[: min(max(top_limit * 4, 24), 40)]
    if not early_filtered:
        early_filtered = [row for row in (filtered or enriched) if _safe_float(row.get("gapPercent")) > 0]
    early_watch = _build_live_early_watch(early_filtered, top_limit)
    if not early_watch:
        early_watch = _fallback_early_watch(filtered or enriched, top_limit)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "marketSession": "premarket",
        "topPicks": [
            {
                "ticker": row["ticker"],
                "companyName": row["companyName"],
                "score": row["score"],
                "conviction": row["conviction"],
                "setupType": row["setupType"],
                "gapPercent": row["gapPercent"],
                "premarketVolume": row["premarketVolume"],
                "relativeVolume": row["relativeVolume"],
                "price": row["price"],
                "marketCap": row["marketCap"],
                "sector": row["sector"],
                "catalystType": row["catalystType"],
                "headlineCount": row["headlineCount"],
                "sentiment": row["sentiment"],
                "premarketHigh": row["premarketHigh"],
                "distanceToPremarketHighPct": row["distanceToPremarketHighPct"],
                "liquidityGrade": row["liquidityGrade"],
                "entryQuality": row["entryQuality"],
                "confidence": row["confidence"],
                "earlyPressureScore": row["earlyPressureScore"],
                "earlyPressureState": row["earlyPressureState"],
                "detectorScore": row["detectorScore"],
                "detectorState": row["detectorState"],
                "triggerFlags": row["triggerFlags"],
                "risk": row["risk"],
                "aiSummary": row["aiSummary"],
            }
            for row in top_picks
        ],
        "earlySetupWatch": [
            {
                "ticker": row["ticker"],
                "companyName": row["companyName"],
                "score": row["score"],
                "earlyPressureScore": row["earlyPressureScore"],
                "earlyPressureState": row["earlyPressureState"],
                "gapPercent": row["gapPercent"],
                "premarketVolume": row["premarketVolume"],
                "relativeVolume": row["relativeVolume"],
                "price": row["price"],
                "premarketHigh": row["premarketHigh"],
                "distanceToPremarketHighPct": row["distanceToPremarketHighPct"],
                "sector": row["sector"],
                "catalystType": row["catalystType"],
                "headlineCount": row["headlineCount"],
                "sentiment": row["sentiment"],
                "aiSummary": row["aiSummary"],
                "detectorScore": row["detectorScore"],
                "detectorState": row["detectorState"],
                "triggerFlags": row["triggerFlags"],
            }
            for row in early_watch
        ],
        "heatmap": [
            {
                "ticker": row["ticker"],
                "score": row["score"],
                "gapPercent": row["gapPercent"],
                "sector": row["sector"],
                "sizeMetric": row["premarketVolume"],
                "colorMetric": row["sentiment"],
                "earlyPressureScore": row["earlyPressureScore"],
                "distanceToPremarketHighPct": row["distanceToPremarketHighPct"],
                "catalystType": row["catalystType"],
                "aiSummary": row["aiSummary"],
            }
            for row in heatmap_rows
        ],
        "stocks": [
            {
                "ticker": row["ticker"],
                "companyName": row["companyName"],
                "score": row["score"],
                "conviction": row["conviction"],
                "setupType": row["setupType"],
                "gapPercent": row["gapPercent"],
                "premarketVolume": row["premarketVolume"],
                "relativeVolume": row["relativeVolume"],
                "price": row["price"],
                "marketCap": row["marketCap"],
                "sector": row["sector"],
                "headlineCount": row["headlineCount"],
                "sentiment": row["sentiment"],
                "premarketHigh": row["premarketHigh"],
                "distanceToPremarketHighPct": row["distanceToPremarketHighPct"],
                "catalystType": row["catalystType"],
                "earlyPressureScore": row["earlyPressureScore"],
                "earlyPressureState": row["earlyPressureState"],
                "detectorScore": row["detectorScore"],
                "detectorState": row["detectorState"],
                "triggerFlags": row["triggerFlags"],
                "liquidityGrade": row["liquidityGrade"],
                "entryQuality": row["entryQuality"],
                "aiSummary": row["aiSummary"],
            }
            for row in heatmap_rows
        ],
        "marketSummary": {
            "bullishCount": bullish_count,
            "bearishCount": bearish_count,
            "highestConvictionSector": sector_scores.most_common(1)[0][0] if sector_scores else "Unclassified",
            "earlySetupCount": len(early_watch),
        },
        "filters": filters,
    }


def get_premarket_detail(ticker: str) -> dict | None:
    symbol = str(ticker or "").upper().strip()
    if not symbol:
        return None

    base_rows = _initial_candidate_pool(limit=80, min_premarket_volume=50_000.0)
    exact = next((row for row in base_rows if row.get("ticker") == symbol), None)
    if exact is None:
        snapshot_match = None
        for raw_row in _fetch_snapshot_rows():
            if str(raw_row.get("ticker") or "").upper() == symbol:
                snapshot_match = _parse_snapshot_row(raw_row)
                break
        exact = snapshot_match

    if exact is None:
        return None

    peer_rows = base_rows if base_rows else [exact]
    sector_lookup = _sector_stats(peer_rows)
    enriched = _enrich_candidates([exact], sector_lookup)
    if not enriched:
        return None
    stock = enriched[0]
    live_early_score, live_early_breakdown = _live_early_pressure_score(
        stock,
        _safe_float(stock.get("sentiment")),
        str(stock.get("catalystType") or "news"),
        stock.get("newsItems") or [],
    )
    detector = detect_premarket_setup(
        {
            **stock,
            "earlyPressureBreakdown": live_early_breakdown,
            "earlyPressureScore": live_early_score,
        }
    )
    stock = {
        **stock,
        "earlyPressureScore": live_early_score,
        "earlyPressureState": _live_early_pressure_state(stock, live_early_score, live_early_breakdown),
        "earlyPressureBreakdown": live_early_breakdown,
        "detectorScore": detector["detectorScore"],
        "detectorState": detector["detectorState"],
        "triggerFlags": detector["triggerFlags"],
    }

    relationships = _build_relationships(stock, peer_rows, stock.get("headlines") or [])
    return {
        "ticker": stock["ticker"],
        "companyName": stock["companyName"],
        "score": stock["score"],
        "conviction": stock["conviction"],
        "setupType": stock["setupType"],
        "price": stock["price"],
        "gapPercent": stock["gapPercent"],
        "premarketVolume": stock["premarketVolume"],
        "premarketHigh": stock["premarketHigh"],
        "distanceToPremarketHighPct": stock["distanceToPremarketHighPct"],
        "relativeVolume": stock["relativeVolume"],
        "marketCap": stock["marketCap"],
        "sector": stock["sector"],
        "headlineCount": stock["headlineCount"],
        "catalystType": stock["catalystType"],
        "earlyPressureScore": stock["earlyPressureScore"],
        "earlyPressureState": stock["earlyPressureState"],
        "earlyPressureBreakdown": stock["earlyPressureBreakdown"],
        "detectorScore": stock["detectorScore"],
        "detectorState": stock["detectorState"],
        "triggerFlags": stock["triggerFlags"],
        "liquidityGrade": stock["liquidityGrade"],
        "entryQuality": stock["entryQuality"],
        "aiSummary": stock["aiSummary"],
        "risk": stock["risk"],
        "confidence": stock["confidence"],
        "scoreBreakdown": stock["scoreBreakdown"],
        "headlines": stock["newsItems"],
        "relationships": relationships,
        "aiAnalysis": {
            "summary": stock["aiSummary"],
            "risk": stock["risk"],
            "confidence": stock["confidence"],
            "verdict": "watchlist_priority" if stock["score"] >= 80 else "watchlist_secondary",
        },
    }
