from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any

import requests
from cachetools import TTLCache
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

import config
from utils.fetch_ticker_news import fetch_ticker_news


analyzer = SentimentIntensityAnalyzer()
SOCIAL_CACHE = TTLCache(maxsize=512, ttl=90)
STATE_LOCK = RLock()
STATE_MEMORY: dict[str, Any] | None = None

PREDICTION_CATALYSTS = {"approval", "earnings", "merger", "contract", "analyst"}
THEME_KEYWORDS = {
    "approval": {"approval", "fda", "clearance", "phase", "trial"},
    "earnings": {"earnings", "guidance", "revenue", "eps", "forecast"},
    "contract": {"contract", "award", "government", "dod", "pentagon"},
    "merger": {"merger", "deal", "takeover", "acquisition", "acquire"},
    "politics": {"election", "senate", "house", "congress", "president", "tariff"},
    "crypto": {"bitcoin", "btc", "eth", "ethereum", "solana", "dogecoin", "crypto"},
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _provider_configs() -> list[tuple[str, str]]:
    providers = [
        ("reddit", config.SOCIAL_REDDIT_URL),
        ("stocktwits", config.SOCIAL_STOCKTWITS_URL),
        ("x", config.SOCIAL_X_URL),
        ("custom", config.SOCIAL_CUSTOM_URL),
    ]
    return [(name, url) for name, url in providers if str(url or "").strip()]


def _asset_key(asset: dict) -> str:
    asset_class = str(asset.get("assetClass") or "stock").strip().lower()
    symbol = str(asset.get("ticker") or asset.get("symbol") or asset.get("eventTopic") or "").strip().upper()
    return f"{asset_class}:{symbol}"


def _load_state() -> dict[str, Any]:
    global STATE_MEMORY
    if STATE_MEMORY is not None:
        return STATE_MEMORY

    path = Path(config.SOCIAL_SIGNAL_STATE_PATH)
    with STATE_LOCK:
        if STATE_MEMORY is not None:
            return STATE_MEMORY
        if not path.exists():
            STATE_MEMORY = {"assets": {}}
            return STATE_MEMORY
        try:
            STATE_MEMORY = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            STATE_MEMORY = {"assets": {}}
        return STATE_MEMORY


def _save_state(state: dict[str, Any]) -> None:
    global STATE_MEMORY
    path = Path(config.SOCIAL_SIGNAL_STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    payload = json.dumps(state, ensure_ascii=True, separators=(",", ":"))
    with STATE_LOCK:
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(path)
        STATE_MEMORY = state


def _normalize_provider_payload(provider: str, payload: Any) -> list[dict]:
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = (
            payload.get("results")
            or payload.get("items")
            or payload.get("posts")
            or payload.get("mentions")
            or payload.get("data")
            or payload.get("messages")
            or []
        )
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("items") or raw_items.get("results") or []
    else:
        raw_items = []

    normalized = []
    for raw in raw_items[: config.SOCIAL_SIGNAL_FETCH_LIMIT]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("headline") or "").strip()
        body = str(
            raw.get("text")
            or raw.get("body")
            or raw.get("content")
            or raw.get("message")
            or raw.get("summary")
            or ""
        ).strip()
        text = ". ".join(part for part in [title, body] if part).strip(". ")
        if not text:
            continue

        compound = raw.get("sentiment")
        if compound is None:
            compound = raw.get("compound")
        if compound is None:
            compound = analyzer.polarity_scores(text).get("compound", 0.0)

        confidence = raw.get("confidence")
        confidence_score = _safe_float(confidence, 0.0)
        if 0.0 < confidence_score <= 1.0:
            confidence_score *= 100.0

        normalized.append(
            {
                "provider": provider,
                "source": str(raw.get("source") or provider).strip() or provider,
                "text": text,
                "sentiment": round(max(min(_safe_float(compound, 0.0), 1.0), -1.0), 4),
                "engagement": round(
                    _safe_float(raw.get("engagement"))
                    + _safe_float(raw.get("likes"))
                    + _safe_float(raw.get("retweets"))
                    + _safe_float(raw.get("comments"))
                    + _safe_float(raw.get("score"))
                    + _safe_float(raw.get("upvotes")),
                    2,
                ),
                "mentions": round(
                    max(
                        _safe_float(raw.get("mentions")),
                        _safe_float(raw.get("mention_count")),
                        _safe_float(raw.get("count")),
                        1.0,
                    ),
                    2,
                ),
                "confidence": round(_clip(confidence_score), 2),
                "publishedAt": (_parse_datetime(raw.get("published_at") or raw.get("timestamp") or raw.get("created_at")) or datetime.now(timezone.utc)).isoformat(),
                "url": str(raw.get("url") or raw.get("link") or "").strip(),
            }
        )
    return normalized


def _fetch_provider_posts(provider: str, url: str, asset: dict) -> dict:
    symbol = str(asset.get("ticker") or asset.get("eventTopic") or "").strip()
    asset_class = str(asset.get("assetClass") or "stock").strip().lower()
    cache_key = f"{provider}:{asset_class}:{symbol}"
    cached = SOCIAL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "symbol": symbol,
        "ticker": symbol,
        "query": asset.get("eventTopic") or symbol,
        "asset_class": asset_class,
        "limit": config.SOCIAL_SIGNAL_FETCH_LIMIT,
    }
    try:
        response = requests.get(url, params=params, timeout=config.SOCIAL_PROVIDER_TIMEOUT_SECONDS)
        response.raise_for_status()
        posts = _normalize_provider_payload(provider, response.json())
        result = {"provider": provider, "status": "ok", "items": posts, "count": len(posts)}
    except requests.exceptions.RequestException as exc:
        result = {"provider": provider, "status": "error", "items": [], "count": 0, "error": str(exc)}
    SOCIAL_CACHE[cache_key] = result
    return result


def _headline_sentiment(news_items: list[dict]) -> tuple[float, list[str]]:
    if not news_items:
        return 0.0, []

    scores = []
    headlines = []
    for item in news_items[:4]:
        title = str(item.get("title") or "").strip()
        summary = str(item.get("description") or item.get("summary") or "").strip()
        text = ". ".join(part for part in [title, summary] if part).strip(". ")
        if title:
            headlines.append(title)
        if not text:
            continue
        scores.append(analyzer.polarity_scores(text).get("compound", 0.0))
    if not scores:
        return 0.0, headlines
    return sum(scores) / len(scores), headlines


def _news_proxy(asset: dict) -> tuple[list[dict], float, list[str]]:
    news_items = list(asset.get("newsItems") or [])
    asset_class = str(asset.get("assetClass") or "stock").strip().lower()
    ticker = str(asset.get("ticker") or "").strip().upper()
    if not news_items and asset_class == "stock" and ticker:
        news_items = fetch_ticker_news(ticker, limit=4)
    news_sentiment, headlines = _headline_sentiment(news_items)
    return news_items[:4], news_sentiment, headlines


def _post_metrics(posts: list[dict]) -> dict[str, Any]:
    if not posts:
        return {
            "socialSentiment": 0.0,
            "socialMomentumScore": 0.0,
            "investorConfidenceScore": 8.0,
            "socialMentions": 0.0,
            "socialEngagement": 0.0,
            "socialPostCount": 0,
            "socialProviders": [],
            "socialDrivers": [],
        }

    sentiments = [_safe_float(item.get("sentiment")) for item in posts]
    mentions = sum(max(_safe_float(item.get("mentions"), 1.0), 1.0) for item in posts)
    engagement = sum(_safe_float(item.get("engagement")) for item in posts)
    sources = sorted({str(item.get("source") or item.get("provider") or "").strip() for item in posts if item.get("source") or item.get("provider")})
    provider_count = max(len(sources), 1)
    freshest = max((_parse_datetime(item.get("publishedAt")) for item in posts), default=datetime.now(timezone.utc))
    age_hours = max((datetime.now(timezone.utc) - freshest).total_seconds() / 3600.0, 0.0)

    positive_count = sum(1 for score in sentiments if score >= 0.15)
    negative_count = sum(1 for score in sentiments if score <= -0.15)
    neutral_count = max(len(sentiments) - positive_count - negative_count, 0)

    recency_score = 100.0 if age_hours <= 3 else 82.0 if age_hours <= 8 else 60.0 if age_hours <= 24 else 36.0
    mention_score = _clip((mentions / 30.0) * 60.0 + (len(posts) / 12.0) * 40.0)
    engagement_score = _clip((engagement / 600.0) * 100.0)
    diversity_score = _clip((provider_count / 3.0) * 100.0)
    social_sentiment = round(sum(sentiments) / len(sentiments), 4)
    sentiment_score = _clip((social_sentiment + 1.0) * 50.0)
    confidence_score = _clip(
        sentiment_score * 0.40
        + mention_score * 0.24
        + engagement_score * 0.16
        + diversity_score * 0.12
        + recency_score * 0.08
    )
    momentum_score = _clip(
        mention_score * 0.42
        + engagement_score * 0.20
        + recency_score * 0.18
        + diversity_score * 0.12
        + sentiment_score * 0.08
    )

    tone_counts = Counter(
        "bullish" if score >= 0.15 else "bearish" if score <= -0.15 else "neutral"
        for score in sentiments
    )
    drivers = [
        f"{tone_counts.get('bullish', 0)} bullish / {neutral_count} neutral / {negative_count} bearish posts",
        f"{int(round(mentions))} mention-weighted hits across {provider_count} sources",
        f"{int(round(engagement))} engagement points",
    ]

    return {
        "socialSentiment": social_sentiment,
        "socialMomentumScore": round(momentum_score, 2),
        "investorConfidenceScore": round(confidence_score, 2),
        "socialMentions": round(mentions, 2),
        "socialEngagement": round(engagement, 2),
        "socialPostCount": len(posts),
        "socialProviders": sources,
        "socialDrivers": drivers,
    }


def _history_metrics(asset: dict, current: dict) -> dict[str, Any]:
    with STATE_LOCK:
        state = _load_state()
        asset_key = _asset_key(asset)
        history = list((state.get("assets") or {}).get(asset_key) or [])
        recent_history = history[-6:]
        previous = recent_history[-1] if recent_history else None

        social_velocity = current["socialCompositeScore"] - _safe_float((previous or {}).get("socialCompositeScore"))
        confidence_velocity = current["investorConfidenceScore"] - _safe_float((previous or {}).get("investorConfidenceScore"))
        mention_velocity = current["socialMentions"] - _safe_float((previous or {}).get("socialMentions"))

        positive_build = 0
        for item in recent_history[-3:]:
            if _safe_float(item.get("socialCompositeScore")) >= 55.0:
                positive_build += 1

        stage = "idle"
        if current["socialCompositeScore"] >= 80 and social_velocity >= 6:
            stage = "explosive"
        elif current["socialCompositeScore"] >= 68 and social_velocity >= 2:
            stage = "building"
        elif current["socialCompositeScore"] >= 54:
            stage = "early"
        elif social_velocity <= -5:
            stage = "cooling"

        price_move = abs(_safe_float(asset.get("gapPercent")))
        if stage == "explosive":
            projected_lead_days = 1.0 if price_move >= 4 else 2.0
        elif stage == "building":
            projected_lead_days = 2.0 if price_move >= 2 else 3.0
        elif stage == "early":
            projected_lead_days = 3.0
        else:
            projected_lead_days = 0.0

        alert_state = "quiet"
        if stage in {"explosive", "building"} and current["investorConfidenceScore"] >= 65:
            alert_state = "early_alert"
        elif stage == "early" and current["socialCompositeScore"] >= 58:
            alert_state = "watch"
        elif stage == "cooling":
            alert_state = "cooling"

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "socialCompositeScore": round(current["socialCompositeScore"], 2),
            "investorConfidenceScore": round(current["investorConfidenceScore"], 2),
            "socialMentions": round(current["socialMentions"], 2),
            "socialSentiment": round(current["socialSentiment"], 4),
            "socialMomentumScore": round(current["socialMomentumScore"], 2),
        }
        history.append(snapshot)
        if len(history) > config.SOCIAL_SIGNAL_HISTORY_LIMIT:
            history = history[-config.SOCIAL_SIGNAL_HISTORY_LIMIT :]
        state.setdefault("assets", {})[asset_key] = history
        _save_state(state)

    return {
        "socialTrendStage": stage,
        "socialAlertState": alert_state,
        "projectedLeadDays": round(projected_lead_days, 1),
        "socialVelocity": round(social_velocity, 2),
        "confidenceVelocity": round(confidence_velocity, 2),
        "mentionVelocity": round(mention_velocity, 2),
        "buildPersistence": positive_build,
        "history": history[-4:],
    }


def _recommendation(asset: dict, current: dict, news_sentiment: float, headlines: list[str]) -> dict[str, Any]:
    asset_class = str(asset.get("assetClass") or "stock").strip().lower()
    ticker = str(asset.get("ticker") or asset.get("eventTopic") or "").strip().upper()
    social_score = _safe_float(current.get("socialCompositeScore"))
    confidence = _safe_float(current.get("investorConfidenceScore"))
    social_sentiment = _safe_float(current.get("socialSentiment"))
    stage = str(current.get("socialTrendStage") or "idle")
    projected_lead_days = _safe_float(current.get("projectedLeadDays"))
    price = _safe_float(asset.get("price"))
    market_cap = _safe_float(asset.get("marketCap"))

    bullish = social_sentiment >= 0.15 and social_score >= 58
    bearish = social_sentiment <= -0.15 and social_score >= 52
    options_ready = price >= 5.0 and market_cap >= 300_000_000

    instrument = "watchlist"
    action = "monitor"
    thesis = "Social participation is not yet strong enough to outrank the rest of the tape."

    if asset_class == "prediction_market":
        if bullish:
            instrument = "event_contract_yes"
            action = "buy_bias"
            thesis = "Social discussion and confidence are building around the event outcome."
        elif bearish:
            instrument = "event_contract_no"
            action = "buy_bias"
            thesis = "Social discussion is leaning against the event outcome."
    elif asset_class == "crypto":
        if bullish and confidence >= 60:
            instrument = "crypto_spot"
            action = "accumulate"
            thesis = "Crypto chatter is accelerating with constructive sentiment and sustained attention."
        elif bearish and confidence >= 58:
            instrument = "crypto_risk_off"
            action = "hedge_or_avoid"
            thesis = "Crypto social flow is deteriorating before price has fully reacted."
    else:
        if bullish and options_ready and stage in {"building", "explosive"}:
            instrument = "call_option"
            action = "buy_bias"
            thesis = "Social momentum is leading the setup and the name is liquid enough for directional options."
        elif bullish:
            instrument = "stock"
            action = "buy_bias"
            thesis = "Social interest is carrying the setup with supportive headline tone."
        elif bearish and options_ready:
            instrument = "put_option"
            action = "buy_bias"
            thesis = "Negative social tone is dominating before the move looks fully priced."
        elif bearish:
            instrument = "stock_avoid"
            action = "avoid_or_short_watch"
            thesis = "Social participation is pointing away from long exposure."

    summary = thesis
    if headlines:
        summary = f"{thesis} Lead headline: {headlines[0][:96]}"

    return {
        "instrument": instrument,
        "action": action,
        "direction": "bullish" if bullish else "bearish" if bearish else "neutral",
        "projectedLeadDays": round(projected_lead_days, 1),
        "summary": summary,
        "headlineSentiment": round(news_sentiment, 4),
    }


def _social_summary(asset: dict, current: dict, recommendation: dict[str, Any]) -> str:
    ticker = str(asset.get("ticker") or asset.get("eventTopic") or "").strip().upper()
    stage = str(current.get("socialTrendStage") or "idle")
    coverage = str(current.get("socialCoverageStatus") or "degraded")
    if coverage != "live_social":
        return f"{ticker} is running on degraded social coverage, so the tracker is leaning more heavily on news and stored trend data."
    if stage in {"building", "explosive"}:
        return f"{ticker} has a {stage} social trend with confidence at {round(_safe_float(current.get('investorConfidenceScore')), 1)} and a {recommendation['instrument']} bias."
    if stage == "early":
        return f"{ticker} is showing early social accumulation with a projected lead window of about {recommendation['projectedLeadDays']} days."
    return f"{ticker} has only light social confirmation right now, so it stays on watch rather than upgrade."


def _collect_social_posts(asset: dict) -> tuple[list[dict], list[dict]]:
    provider_results = []
    for provider, url in _provider_configs():
        provider_results.append(_fetch_provider_posts(provider, url, asset))

    posts = []
    for item in provider_results:
        posts.extend(item.get("items") or [])
    return posts, provider_results


def _derive_theme_from_text(text: str) -> str:
    lowered = str(text or "").lower()
    for label, keywords in THEME_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return label
    return "general"


def enrich_asset_with_social(asset: dict) -> dict:
    if not config.ENABLE_SOCIAL_SIGNAL_TRACKER:
        return {
            **asset,
            "socialCompositeScore": 0.0,
            "socialMomentumScore": 0.0,
            "investorConfidenceScore": 0.0,
            "socialSentiment": 0.0,
            "socialMentions": 0.0,
            "socialEngagement": 0.0,
            "socialPostCount": 0,
            "socialProviders": [],
            "socialCoverageStatus": "disabled",
            "socialTrendStage": "idle",
            "socialAlertState": "quiet",
            "projectedLeadDays": 0.0,
            "socialVelocity": 0.0,
            "confidenceVelocity": 0.0,
            "mentionVelocity": 0.0,
            "socialDrivers": [],
            "socialRecommendation": {"instrument": "watchlist", "action": "monitor", "direction": "neutral", "projectedLeadDays": 0.0, "summary": ""},
            "socialSummary": "Social tracking is disabled in configuration.",
            "socialSourceHealth": [],
            "socialHistory": [],
        }

    news_items, news_sentiment, headlines = _news_proxy(asset)
    posts, provider_results = _collect_social_posts(asset)
    post_metrics = _post_metrics(posts)
    has_live_social = any(item.get("status") == "ok" and (item.get("count") or 0) > 0 for item in provider_results)

    news_score = _clip((news_sentiment + 1.0) * 50.0)
    social_composite = _clip(
        post_metrics["socialMomentumScore"] * 0.46
        + post_metrics["investorConfidenceScore"] * 0.26
        + news_score * 0.18
        + min(max(_safe_float(asset.get("relativeVolume")), 0.0), 5.0) * 2.0
    )
    if not has_live_social:
        social_composite = round(_clip(news_score * 0.55 + social_composite * 0.20), 2)

    current = {
        **post_metrics,
        "socialCompositeScore": round(social_composite, 2),
        "socialCoverageStatus": "live_social" if has_live_social else "degraded_news_proxy",
    }
    history_metrics = _history_metrics(asset, current)
    current.update(history_metrics)
    recommendation = _recommendation(asset, current, news_sentiment, headlines)

    return {
        **asset,
        "newsItems": news_items,
        "socialCompositeScore": current["socialCompositeScore"],
        "socialMomentumScore": current["socialMomentumScore"],
        "investorConfidenceScore": current["investorConfidenceScore"],
        "socialSentiment": round(current["socialSentiment"], 4),
        "socialMentions": current["socialMentions"],
        "socialEngagement": current["socialEngagement"],
        "socialPostCount": current["socialPostCount"],
        "socialProviders": current["socialProviders"],
        "socialCoverageStatus": current["socialCoverageStatus"],
        "socialTrendStage": current["socialTrendStage"],
        "socialAlertState": current["socialAlertState"],
        "projectedLeadDays": current["projectedLeadDays"],
        "socialVelocity": current["socialVelocity"],
        "confidenceVelocity": current["confidenceVelocity"],
        "mentionVelocity": current["mentionVelocity"],
        "buildPersistence": current["buildPersistence"],
        "socialDrivers": current["socialDrivers"],
        "socialRecommendation": recommendation,
        "socialSummary": _social_summary(asset, current, recommendation),
        "socialSourceHealth": provider_results,
        "socialHistory": current["history"],
        "socialTheme": _derive_theme_from_text(" ".join(headlines) or str(asset.get("eventTopic") or asset.get("ticker") or "")),
    }


def enrich_equity_rows_with_social(rows: list[dict]) -> list[dict]:
    return [enrich_asset_with_social({**row, "assetClass": "stock"}) for row in rows]


def _ensure_social_asset(asset: dict, asset_class: str) -> dict:
    if "socialCompositeScore" in asset and "socialRecommendation" in asset:
        return asset
    return enrich_asset_with_social({**asset, "assetClass": asset_class})


def _prediction_market_candidates(equity_rows: list[dict], event_topics: list[str] | None = None) -> list[dict]:
    if event_topics:
        return [
            {
                "ticker": _slugify(topic).upper()[:24] or "EVENT",
                "eventTopic": topic,
                "companyName": topic,
                "assetClass": "prediction_market",
                "price": 0.0,
                "relativeVolume": 0.0,
            }
            for topic in event_topics
        ]

    derived = []
    for row in equity_rows:
        catalyst = str(row.get("catalystType") or "").strip().lower()
        if catalyst not in PREDICTION_CATALYSTS:
            continue
        derived.append(
            {
                "ticker": f"{str(row.get('ticker') or '')}-{catalyst}".upper()[:24],
                "eventTopic": f"{str(row.get('ticker') or '').upper()} {catalyst}",
                "companyName": f"{str(row.get('ticker') or '').upper()} {catalyst}",
                "assetClass": "prediction_market",
                "newsItems": list(row.get("newsItems") or []),
                "relativeVolume": _safe_float(row.get("relativeVolume")),
                "price": _safe_float(row.get("price")),
                "gapPercent": _safe_float(row.get("gapPercent")),
                "catalystType": catalyst,
            }
        )
        if len(derived) >= 5:
            break
    return derived


def build_social_tracker_dashboard(
    *,
    equity_rows: list[dict] | None = None,
    tickers: list[str] | None = None,
    crypto_symbols: list[str] | None = None,
    event_topics: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    top_limit = max(3, min(int(limit), 15))
    equity_rows = list(equity_rows or [])
    requested_tickers = [str(item or "").upper().strip() for item in (tickers or []) if str(item or "").strip()]

    if requested_tickers:
        indexed = {str(row.get("ticker") or "").upper(): row for row in equity_rows}
        equity_rows = [
            indexed.get(symbol)
            or {
                "ticker": symbol,
                "companyName": symbol,
                "sector": "Unclassified",
                "price": 0.0,
                "marketCap": 0.0,
                "relativeVolume": 0.0,
                "gapPercent": 0.0,
                "assetClass": "stock",
            }
            for symbol in requested_tickers
        ]

    crypto_symbols = [str(item or "").upper().strip() for item in (crypto_symbols or config.SOCIAL_CRYPTO_WATCHLIST) if str(item or "").strip()]
    crypto_assets = [
        {
            "ticker": symbol,
            "companyName": symbol,
            "assetClass": "crypto",
            "sector": "Crypto",
            "price": 0.0,
            "marketCap": 0.0,
            "relativeVolume": 0.0,
            "gapPercent": 0.0,
        }
        for symbol in crypto_symbols[: top_limit]
    ]
    event_assets = _prediction_market_candidates(
        equity_rows,
        event_topics if event_topics is not None else None,
    )
    if not event_assets:
        event_assets = _prediction_market_candidates(
            equity_rows,
            config.PREDICTION_MARKET_TOPICS[:top_limit],
        )

    enriched_equities = [_ensure_social_asset(row, "stock") for row in equity_rows[: max(top_limit * 3, 12)]]
    enriched_crypto = [_ensure_social_asset(asset, "crypto") for asset in crypto_assets]
    enriched_events = [_ensure_social_asset(asset, "prediction_market") for asset in event_assets[:top_limit]]

    all_assets = enriched_equities + enriched_crypto + enriched_events
    ranked_assets = sorted(
        all_assets,
        key=lambda item: (
            _safe_float(item.get("socialCompositeScore")),
            _safe_float(item.get("investorConfidenceScore")),
            _safe_float(item.get("socialMomentumScore")),
            _safe_float(item.get("socialMentions")),
        ),
        reverse=True,
    )

    alerts = [
        item
        for item in ranked_assets
        if str(item.get("socialAlertState") or "") in {"early_alert", "watch"}
    ][:top_limit]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "providers": {
            "configured": [name for name, _ in _provider_configs()],
            "trackerEnabled": bool(config.ENABLE_SOCIAL_SIGNAL_TRACKER),
            "historyPath": str(config.SOCIAL_SIGNAL_STATE_PATH),
        },
        "leaders": ranked_assets[:top_limit],
        "alerts": alerts,
        "stocks": enriched_equities[:top_limit],
        "crypto": sorted(enriched_crypto, key=lambda item: _safe_float(item.get("socialCompositeScore")), reverse=True)[:top_limit],
        "predictionMarkets": sorted(enriched_events, key=lambda item: _safe_float(item.get("socialCompositeScore")), reverse=True)[:top_limit],
        "summary": {
            "topSocialTicker": (ranked_assets[0].get("ticker") if ranked_assets else ""),
            "earlyAlertCount": len([item for item in ranked_assets if str(item.get("socialAlertState")) == "early_alert"]),
            "watchCount": len([item for item in ranked_assets if str(item.get("socialAlertState")) == "watch"]),
            "liveCoverageCount": len([item for item in ranked_assets if str(item.get("socialCoverageStatus")) == "live_social"]),
        },
    }
