from typing import Iterable


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _sentiment_score(news_items: Iterable[dict], analyzer) -> tuple[float, list[str]]:
    items = list(news_items or [])
    if not items or analyzer is None:
        return 0.0, []

    compounds = []
    reasons = []
    for item in items[:3]:
        title = str(item.get("title") or "")
        description = str(item.get("description") or item.get("summary") or "")
        text = f"{title}. {description}".strip()
        if not text:
            continue
        compound = analyzer.polarity_scores(text).get("compound", 0.0)
        compounds.append(compound)
        if title:
            reasons.append(title[:90])

    if not compounds:
        return 0.0, []

    avg_compound = sum(compounds) / len(compounds)
    score = _clip((avg_compound + 0.2) / 0.8) * 10.0
    return score, reasons


def _build_trade_plan(item, daily, intra) -> dict:
    price = float(item.get("price", 0.0) or 0.0)
    vwap = float(item.get("vwap", price) or price)
    high_20 = float(daily.get("high_20", 0.0) or 0.0)
    ema21 = float(daily.get("ema21", 0.0) or 0.0)
    near_breakout = bool(intra.get("near_breakout"))

    trigger = high_20 if high_20 > 0 else price * 1.01
    if near_breakout and price >= trigger * 0.995:
        entry = max(price, trigger) * 1.001
    else:
        entry = trigger * 1.002

    support = max(vwap if vwap > 0 else 0.0, ema21 if ema21 > 0 else 0.0, price * 0.94)
    raw_stop = support * 0.995 if support > 0 else entry * 0.96
    stop = min(raw_stop, entry * 0.97)
    if stop >= entry:
        stop = entry * 0.97

    risk = max(entry - stop, entry * 0.01)
    target1 = entry + risk
    target2 = entry + risk * 2.0

    return {
        "trigger": round(trigger, 2),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
    }


def _build_alert_state(
    price: float,
    score: float,
    plan: dict,
    *,
    live_min_score: float = 85.0,
    near_min_score: float = 75.0,
    near_distance_pct: float = 1.0,
) -> dict:
    trigger = float(plan.get("trigger", 0.0) or 0.0)
    distance_pct = ((trigger - price) / trigger) * 100.0 if trigger > 0 else 999.0
    trigger_hit = price >= trigger if trigger > 0 else False

    if score >= live_min_score and trigger_hit:
        label = "LIVE"
        color = "#f97316"
    elif score >= near_min_score and distance_pct <= near_distance_pct:
        label = "NEAR"
        color = "#22c55e"
    elif score >= 70:
        label = "WATCH"
        color = "#93c5fd"
    else:
        label = "LOW"
        color = "#9ca3af"

    return {
        "label": label,
        "color": color,
        "trigger_hit": trigger_hit,
        "distance_to_trigger_pct": round(distance_pct, 2),
    }


def alert_priority(label: str) -> int:
    order = {
        "LIVE": 3,
        "NEAR": 2,
        "WATCH": 1,
        "LOW": 0,
    }
    return order.get(str(label or "").upper(), 0)


def calculate_ai_pick_score(
    item,
    daily,
    intra,
    *,
    news_items=None,
    flow_stats=None,
    analyzer=None,
    alert_config=None,
):
    price = float(item.get("price", 0.0) or 0.0)
    pct_change = float(item.get("pct_change", 0.0) or 0.0)
    rvol = float(item.get("rvol", 0.0) or 0.0)
    day_notional = float(item.get("day_notional", 0.0) or 0.0)

    daily = daily or {}
    intra = intra or {}
    flow_stats = flow_stats or {}

    dist_to_high_20 = float(daily.get("dist_to_high_20", 1.0) or 1.0)
    atr_ratio = (
        float(daily.get("atr5", 0.0) or 0.0) / max(float(daily.get("atr20", 0.0) or 0.0), 1e-9)
        if daily.get("has_data")
        else 1.0
    )
    range_ratio = (
        float(daily.get("range5", 0.0) or 0.0) / max(float(daily.get("range20", 0.0) or 0.0), 1e-9)
        if daily.get("has_data")
        else 1.0
    )

    momentum = (
        8.0 * _clip((float(intra.get("rsi14", 50.0) or 50.0) - 50.0) / 20.0)
        + 6.0 * _clip(pct_change / 5.0)
        + 6.0 * _clip(rvol / 3.0)
    )

    volume = (
        8.0 * _clip(rvol / 3.0)
        + 6.0 * _clip(float(intra.get("rvol5", 0.0) or 0.0) / 2.5)
        + 6.0 * _clip(day_notional / 3_000_000_000.0)
    )

    trend = (
        7.0 * (1.0 if float(daily.get("ema8", 0.0) or 0.0) > float(daily.get("ema21", 0.0) or 0.0) else 0.0)
        + 4.0 * (1.0 if daily.get("higher_lows") else 0.0)
        + 4.0 * _clip(float(daily.get("return_20d", 0.0) or 0.0) / 0.12)
    )

    breakout = (
        10.0 * _clip((0.08 - dist_to_high_20) / 0.08)
        + 5.0 * (1.0 if intra.get("near_breakout") else 0.0)
    )

    volatility = (
        5.0 * _clip((0.95 - atr_ratio) / 0.45)
        + 5.0 * _clip((0.95 - range_ratio) / 0.45)
    )
    if intra.get("consecutive_wide_3"):
        volatility = min(10.0, volatility + 2.0)

    flow_buy_count = float(flow_stats.get("buy_count", 0.0) or 0.0)
    flow_sell_count = float(flow_stats.get("sell_count", 0.0) or 0.0)
    flow_total = flow_buy_count + flow_sell_count
    buy_bias = (flow_buy_count / flow_total) if flow_total > 0 else 0.0
    options_flow = (
        6.0 * _clip(float(flow_stats.get("count_over_threshold", 0.0) or 0.0) / 3.0)
        + 4.0 * _clip(buy_bias / 0.75)
    )

    news_score, news_reasons = _sentiment_score(news_items or [], analyzer)

    components = {
        "momentum": round(momentum, 1),
        "volume": round(volume, 1),
        "trend": round(trend, 1),
        "breakout": round(breakout, 1),
        "news": round(news_score, 1),
        "options": round(options_flow, 1),
        "volatility": round(volatility, 1),
    }
    score = round(sum(components.values()), 1)

    tier = "WATCH"
    if score >= 90:
        tier = "STRONG"
    elif score >= 80:
        tier = "GOOD"
    elif score < 70:
        tier = "WATCH"

    reason_pairs = [
        ("Momentum", components["momentum"]),
        ("Volume Surge", components["volume"]),
        ("Trend Strength", components["trend"]),
        ("Breakout Setup", components["breakout"]),
        ("News Sentiment", components["news"]),
        ("Options Flow", components["options"]),
        ("Volatility Expansion", components["volatility"]),
    ]
    reason_pairs.sort(key=lambda pair: pair[1], reverse=True)
    reasons = [label for label, value in reason_pairs if value >= 6.0][:3]

    if dist_to_high_20 <= 0.03:
        reasons.append("Near 20d High")
    if rvol >= 2.0:
        reasons.append("High RVOL")
    if pct_change >= 3.0:
        reasons.append("Strong Day Move")

    deduped_reasons = []
    seen = set()
    for reason in reasons:
        if reason in seen:
            continue
        deduped_reasons.append(reason)
        seen.add(reason)

    plan = _build_trade_plan(item, daily, intra)
    alert = _build_alert_state(price, score, plan, **(alert_config or {}))

    return {
        "symbol": item.get("symbol"),
        "price": round(price, 2),
        "pct_change": round(pct_change, 2),
        "rvol": round(rvol, 2),
        "day_notional": round(day_notional, 0),
        "score": score,
        "tier": tier,
        "reasons": deduped_reasons[:4],
        "components": components,
        "dist_to_high_20_pct": round(dist_to_high_20 * 100.0, 2),
        "news_count": len(list(news_items or [])),
        "above_vwap": price >= float(item.get("vwap", price) or price),
        "plan": plan,
        "alert": alert,
    }
