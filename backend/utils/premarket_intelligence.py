from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import log10
from typing import Any

import requests
from cachetools import TTLCache
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

import config
from utils.fetch_ticker_news import fetch_ticker_news


API_KEY = config.POLYGON_API_KEY
SNAPSHOT_CACHE = TTLCache(maxsize=1, ttl=45)
NEWS_CACHE = TTLCache(maxsize=256, ttl=180)
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
    response = requests.get(url, params={"apiKey": API_KEY}, timeout=20)
    response.raise_for_status()
    rows = response.json().get("tickers", []) or []
    SNAPSHOT_CACHE["rows"] = rows
    return rows


def _session_change_pct(row: dict, price: float, prev_close: float) -> float:
    session = row.get("session") or {}
    candidates = [
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

    prev_close = _first_positive(prev_day.get("c"), day.get("o"), default=0.0)
    price = _first_positive(
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
        row.get("preMarketVolume"),
        row.get("premarketVolume"),
        row.get("earlyTradingVolume"),
        session.get("preMarketVolume"),
        session.get("premarketVolume"),
        session.get("earlyTradingVolume"),
        day.get("v"),
        default=0.0,
    )
    prev_volume = _first_positive(prev_day.get("v"), default=0.0)
    gap_percent = _session_change_pct(row, price, prev_close)
    relative_volume = (premarket_volume / prev_volume) * 10.0 if prev_volume > 0 else 0.0

    return {
        "ticker": ticker,
        "companyName": _extract_company_name(row),
        "price": round(price, 4),
        "prevClose": round(prev_close, 4),
        "gapPercent": round(gap_percent, 4),
        "premarketVolume": round(premarket_volume, 0),
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


def _enrich_candidates(base_rows: list[dict], sector_lookup: dict[str, dict]) -> list[dict]:
    enriched = []
    for base in base_rows:
        news_items = _fetch_news_cached(base["ticker"], limit=4)
        sentiment, headlines = _headline_sentiment(news_items)
        catalyst_type = _classify_catalyst(headlines)
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
        enriched.append(
            {
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
                "scoreBreakdown": score_breakdown,
                "headlines": headlines,
                "newsItems": news_items[:4],
            }
        )
    enriched.sort(key=lambda item: (item["score"], item["premarketVolume"], item["gapPercent"]), reverse=True)
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


def _initial_candidate_pool(limit: int = 45) -> list[dict]:
    parsed_rows = []
    for raw_row in _fetch_snapshot_rows():
        parsed = _parse_snapshot_row(raw_row)
        if not parsed:
            continue
        price = _safe_float(parsed.get("price"))
        premarket_volume = _safe_float(parsed.get("premarketVolume"))
        if price < 0.5 or premarket_volume < 100_000:
            continue
        parsed_rows.append(parsed)

    parsed_rows.sort(
        key=lambda row: (
            abs(_safe_float(row.get("gapPercent"))) * 3.0
            + _safe_float(row.get("relativeVolume")) * 15.0
            + min(_safe_float(row.get("premarketVolume")) / 1_000_000.0, 8.0) * 8.0
        ),
        reverse=True,
    )
    return parsed_rows[:limit]


def get_premarket_intelligence(*, limit: int = 8, filters: dict[str, Any] | None = None) -> dict:
    filters = filters or {}
    top_limit = max(3, min(int(limit), 15))
    base_rows = _initial_candidate_pool(limit=max(top_limit * 4, 30))
    if not base_rows:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "marketSession": "premarket",
            "topPicks": [],
            "heatmap": [],
            "stocks": [],
            "marketSummary": {
                "bullishCount": 0,
                "bearishCount": 0,
                "highestConvictionSector": "Unclassified",
            },
            "filters": filters,
        }

    sector_lookup = _sector_stats(base_rows)
    enriched = _enrich_candidates(base_rows, sector_lookup)
    filtered = _apply_filters(enriched, filters)

    if not filtered:
        filtered = enriched

    bullish_count = sum(1 for row in filtered if _safe_float(row.get("gapPercent")) >= 0)
    bearish_count = sum(1 for row in filtered if _safe_float(row.get("gapPercent")) < 0)
    sector_scores = Counter()
    for row in filtered[:20]:
        sector_scores[str(row.get("sector") or "Unclassified")] += _safe_float(row.get("score"))

    top_picks = filtered[:top_limit]
    heatmap_rows = filtered[: min(max(top_limit * 4, 24), 40)]

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
                "liquidityGrade": row["liquidityGrade"],
                "entryQuality": row["entryQuality"],
                "confidence": row["confidence"],
                "risk": row["risk"],
                "aiSummary": row["aiSummary"],
            }
            for row in top_picks
        ],
        "heatmap": [
            {
                "ticker": row["ticker"],
                "score": row["score"],
                "gapPercent": row["gapPercent"],
                "sector": row["sector"],
                "sizeMetric": row["premarketVolume"],
                "colorMetric": row["sentiment"],
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
                "catalystType": row["catalystType"],
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
        },
        "filters": filters,
    }


def get_premarket_detail(ticker: str) -> dict | None:
    symbol = str(ticker or "").upper().strip()
    if not symbol:
        return None

    base_rows = _initial_candidate_pool(limit=40)
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
        "relativeVolume": stock["relativeVolume"],
        "marketCap": stock["marketCap"],
        "sector": stock["sector"],
        "headlineCount": stock["headlineCount"],
        "catalystType": stock["catalystType"],
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
