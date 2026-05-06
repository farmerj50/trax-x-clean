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


def _compute_score(gap: float, rvol: float, accel: float, has_catalyst: bool) -> float:
    gap_s = _clip(min(gap / 10.0, 1.0) * 100.0)
    rvol_s = _clip(min(rvol / 4.0, 1.0) * 100.0)
    accel_s = _clip(min(accel / 3.0, 1.0) * 100.0)
    bonus = 10.0 if has_catalyst else 0.0
    return round(_clip(gap_s * 0.35 + rvol_s * 0.35 + accel_s * 0.20 + bonus), 2)


def _build_result(score: float, state: str, flags: list[str]) -> dict:
    return {
        "detectorScore": score,
        "detectorState": state,
        "triggerFlags": flags,
    }


def _classify_low_price_mover(
    gap: float,
    rvol: float,
    accel: float,
    pm_volume: float,
    price: float,
    vwap: float,
    bar_count: float,
    has_catalyst: bool,
) -> dict:
    """$1–$5 tier: cheap stocks need much heavier confirmation to filter noise."""
    if pm_volume < 300_000:
        return _build_result(0.0, "rejected", ["insufficient_liquidity"])
    if gap <= 0:
        return _build_result(0.0, "rejected", ["no_positive_gap"])
    if bar_count < 8:
        return _build_result(0.0, "rejected", ["insufficient_bars"])

    above_vwap = price > vwap if vwap > 0 else False
    if not above_vwap:
        return _build_result(0.0, "rejected", ["below_vwap"])

    trigger_flags = ["low_price_runner"]

    if gap >= 8.0 and rvol >= 3.0 and accel >= 2.0:
        trigger_flags += ["gap_confirmed", "high_participation", "volume_surge", "above_vwap"]
        return _build_result(_compute_score(gap, rvol, accel, has_catalyst), "triggered", trigger_flags)

    if gap >= 5.0 and rvol >= 2.0 and accel >= 1.5:
        trigger_flags += ["gap_confirmed", "volume_build", "above_vwap"]
        return _build_result(_compute_score(gap, rvol, accel, has_catalyst), "arming", trigger_flags)

    if gap >= 4.0 and rvol >= 2.0:
        trigger_flags.append("small_gap_watch")
        return _build_result(_compute_score(gap, rvol, accel, has_catalyst), "watch", trigger_flags)

    return _build_result(0.0, "rejected", [])


def _classify_standard_mover(
    gap: float,
    rvol: float,
    accel: float,
    pm_volume: float,
    price: float,
    vwap: float,
    bar_count: float,
    has_catalyst: bool,
) -> dict:
    """Standard tier >$5: institutional volume, clean momentum."""
    if pm_volume < 100_000:
        return _build_result(0.0, "rejected", ["insufficient_liquidity"])
    if gap <= 0:
        return _build_result(0.0, "rejected", ["no_positive_gap"])
    if bar_count < 8:
        return _build_result(0.0, "rejected", ["insufficient_bars"])

    above_vwap = price > vwap if vwap > 0 else False
    trigger_flags: list[str] = []

    if gap >= 5.0 and rvol >= 2.0 and accel >= 1.5 and above_vwap:
        trigger_flags += ["gap_confirmed", "high_participation", "volume_surge", "above_vwap"]
        return _build_result(_compute_score(gap, rvol, accel, has_catalyst), "triggered", trigger_flags)

    if gap >= 3.0 and rvol >= 1.5 and accel >= 1.2 and above_vwap:
        trigger_flags += ["gap_confirmed", "volume_build", "above_vwap"]
        return _build_result(_compute_score(gap, rvol, accel, has_catalyst), "arming", trigger_flags)

    if gap >= 2.0 and rvol >= 1.2:
        trigger_flags.append("small_gap_watch")
        return _build_result(_compute_score(gap, rvol, accel, has_catalyst), "watch", trigger_flags)

    if has_catalyst and gap >= 1.5 and rvol >= 1.2:
        trigger_flags.append("catalyst_watch")
        return _build_result(_compute_score(gap, rvol, accel, has_catalyst), "watch", trigger_flags)

    return _build_result(0.0, "ignore", [])


def detect_premarket_setup(row: dict) -> dict:
    gap = _safe_float(row.get("gapPercent"))
    rvol = _safe_float(row.get("relativeVolume"))
    pm_volume = _safe_float(row.get("premarketVolume"))
    price = _safe_float(row.get("price"))
    vwap = _safe_float(row.get("premarketVwap"), default=price)
    catalyst = str(row.get("catalystType") or "none").lower()

    breakdown = row.get("earlyPressureBreakdown") or {}
    bar_count = _safe_float(breakdown.get("minuteBarCount"))
    accel = _safe_float(breakdown.get("volumeAcceleration"))

    has_catalyst = catalyst not in {"none", "", "news"}

    if price < 1.0:
        return _build_result(0.0, "rejected", [])
    if price > 50.0:
        return _build_result(0.0, "rejected", [])

    if price <= 5.0:
        return _classify_low_price_mover(gap, rvol, accel, pm_volume, price, vwap, bar_count, has_catalyst)

    return _classify_standard_mover(gap, rvol, accel, pm_volume, price, vwap, bar_count, has_catalyst)
