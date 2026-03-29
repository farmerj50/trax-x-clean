from datetime import datetime, timedelta

import pandas as pd
import requests
from cachetools import TTLCache

import config

API_KEY = config.POLYGON_API_KEY
SNAPSHOT_CACHE = TTLCache(maxsize=1, ttl=45)
BAR_CACHE = TTLCache(maxsize=500, ttl=300)


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fetch_snapshot_universe():
    if "snapshot" in SNAPSHOT_CACHE:
        return SNAPSHOT_CACHE["snapshot"]

    url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?apiKey={API_KEY}"
    response = requests.get(url, timeout=12)
    response.raise_for_status()
    rows = response.json().get("tickers", [])
    SNAPSHOT_CACHE["snapshot"] = rows
    return rows


def _fetch_daily_bars(ticker: str, days: int = 80) -> pd.DataFrame:
    cache_key = f"{ticker}:{days}"
    if cache_key in BAR_CACHE:
        return BAR_CACHE[cache_key]

    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days)
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
        f"{start_date}/{end_date}?adjusted=true&sort=asc&limit={days}&apiKey={API_KEY}"
    )
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    rows = response.json().get("results", [])
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "t": "timestamp"}, inplace=True)
    BAR_CACHE[cache_key] = df
    return df


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _scanner_row_from_snapshot(row: dict):
    day = row.get("day") or {}
    prev_day = row.get("prevDay") or {}
    ticker = str(row.get("ticker") or "").upper()
    price = _safe_float(day.get("c"), 0.0) or _safe_float((row.get("lastTrade") or {}).get("p"), 0.0) or _safe_float(prev_day.get("c"), 0.0)
    vwap = _safe_float(day.get("vw"), 0.0) or price
    volume = _safe_float(day.get("v"), 0.0) or _safe_float(prev_day.get("v"), 0.0)
    prev_volume = _safe_float(prev_day.get("v"), 0.0)
    pct_change = _safe_float(row.get("todaysChangePerc"), 0.0)
    if not ticker or price <= 0 or volume <= 0:
        return None

    rvol = (volume / prev_volume) if prev_volume > 0 else 0.0
    day_notional = volume * vwap
    above_vwap = price >= vwap if vwap > 0 else False

    daily = _fetch_daily_bars(ticker, days=80)
    if daily.empty or len(daily) < 25:
        return None

    daily = daily.copy()
    daily["ema8"] = _ema(daily["close"], 8)
    daily["ema21"] = _ema(daily["close"], 21)
    high20 = float(daily["high"].tail(20).max())
    dist_to_breakout_pct = ((high20 - price) / high20) * 100 if high20 > 0 else 999.0
    ema8_above_ema21 = bool(float(daily["ema8"].iloc[-1]) > float(daily["ema21"].iloc[-1]))

    return {
        "ticker": ticker,
        "price": round(price, 4),
        "rvol": round(rvol, 4),
        "dist_to_breakout_pct": round(max(dist_to_breakout_pct, 0.0), 4),
        "above_vwap": above_vwap,
        "ema8_above_ema21": ema8_above_ema21,
        "day_change_pct": round(pct_change, 4),
        "day_notional": round(day_notional, 2),
    }


def get_latest_scanner_rows(limit: int = 15) -> list[dict]:
    rows = _fetch_snapshot_universe()
    candidates = []
    for row in rows:
        try:
            scanned = _scanner_row_from_snapshot(row)
        except Exception:
            scanned = None
        if not scanned:
            continue
        candidates.append(scanned)

    if not candidates:
        return []

    df = pd.DataFrame(candidates)
    df = df[
        (df["price"].between(10, 80))
        & (df["rvol"] >= 1.0)
        & (df["day_change_pct"] >= 1.0)
        & (df["day_notional"] >= 20_000_000)
    ].copy()
    if df.empty:
        return []

    df["scan_score"] = (
        df["rvol"] * 20
        + (df["day_change_pct"].clip(lower=0, upper=8) * 6)
        + ((1.5 - df["dist_to_breakout_pct"]).clip(lower=0) * 18)
        + (df["above_vwap"].astype(int) * 8)
        + (df["ema8_above_ema21"].astype(int) * 8)
    )
    return df.sort_values("scan_score", ascending=False).head(limit).drop(columns=["scan_score"]).to_dict(orient="records")


def get_scanner_row_for_ticker(ticker: str):
    ticker = str(ticker or "").upper().strip()
    if not ticker:
        return None

    rows = _fetch_snapshot_universe()
    match = next((row for row in rows if str(row.get("ticker") or "").upper() == ticker), None)
    if not match:
        return None

    try:
        return _scanner_row_from_snapshot(match)
    except Exception:
        return None
