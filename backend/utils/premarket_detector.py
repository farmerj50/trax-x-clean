from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def detect_premarket_setup(row: dict) -> dict:
    gap_percent = _safe_float(row.get("gapPercent"))
    premarket_volume = _safe_float(row.get("premarketVolume"))
    relative_volume = _safe_float(row.get("relativeVolume"))
    distance_to_high = _safe_float(row.get("distanceToPremarketHighPct"))
    sentiment = _safe_float(row.get("sentiment"))
    catalyst_type = str(row.get("catalystType") or "news")
    market_cap = _safe_float(row.get("marketCap"))

    breakdown = row.get("earlyPressureBreakdown") or {}
    volume_acceleration = _safe_float(breakdown.get("volumeAcceleration"))
    news_freshness_score = _safe_float(breakdown.get("newsFreshnessScore"))
    breakout_score = _safe_float(breakdown.get("breakoutProximityScore"))

    trigger_flags = []
    score = 0.0

    if 1.0 <= gap_percent <= 4.0:
        score += 18.0
        trigger_flags.append("gap_sweet_spot")
    elif 0.5 <= gap_percent < 1.0:
        score += 10.0
        trigger_flags.append("small_positive_gap")
    elif gap_percent > 8.0:
        score -= 18.0
        trigger_flags.append("extended_gap")

    if volume_acceleration >= 2.0:
        score += 28.0
        trigger_flags.append("volume_surge")
    elif volume_acceleration >= 1.4:
        score += 18.0
        trigger_flags.append("volume_build")
    elif volume_acceleration < 0.9:
        score -= 10.0

    if distance_to_high <= 1.0:
        score += 22.0
        trigger_flags.append("tight_to_high")
    elif distance_to_high <= 2.0:
        score += 14.0
        trigger_flags.append("near_high")
    elif distance_to_high > 5.0:
        score -= 12.0

    if relative_volume >= 2.0:
        score += 12.0
        trigger_flags.append("high_participation")
    elif relative_volume >= 1.2:
        score += 8.0

    if premarket_volume >= 100_000:
        score += 6.0
    elif premarket_volume < 40_000:
        score -= 8.0

    if catalyst_type in {"contract", "approval", "earnings", "merger"}:
        score += 12.0
        trigger_flags.append("strong_catalyst")
    elif catalyst_type == "analyst":
        score += 7.0
        trigger_flags.append("analyst_catalyst")

    if news_freshness_score >= 80:
        score += 10.0
        trigger_flags.append("fresh_news")
    elif news_freshness_score <= 20:
        score -= 6.0

    if sentiment >= 0.20:
        score += 6.0
        trigger_flags.append("positive_tone")
    elif sentiment < -0.10:
        score -= 10.0

    if 0 < market_cap <= 500_000_000:
        score += 8.0
        trigger_flags.append("lower_float_proxy")
    elif market_cap >= 10_000_000_000:
        score -= 4.0

    if gap_percent >= 25.0:
        score -= 40.0
        trigger_flags.append("parabolic")
    elif gap_percent >= 15.0:
        score -= 26.0
        trigger_flags.append("too_extended")

    detector_score = round(_clip(score), 2)

    if (
        detector_score >= 70
        and volume_acceleration >= 1.4
        and distance_to_high <= 2.0
        and gap_percent < 8.0
    ):
        state = "triggered"
    elif detector_score >= 55 and gap_percent > 0:
        state = "arming"
    elif detector_score >= 40 and gap_percent > 0:
        state = "watch"
    else:
        state = "ignore"

    return {
        "detectorScore": detector_score,
        "detectorState": state,
        "triggerFlags": trigger_flags,
        "volumeAcceleration": volume_acceleration,
        "distanceToPremarketHighPct": distance_to_high,
        "breakoutScore": breakout_score,
    }
