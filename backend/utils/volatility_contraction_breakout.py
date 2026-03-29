import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
from cachetools import TTLCache

import config

API_KEY = config.POLYGON_API_KEY

BAR_CACHE = TTLCache(maxsize=1000, ttl=3600)
SNAPSHOT_CACHE = TTLCache(maxsize=1, ttl=60)


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    b = b.replace(0, np.nan)
    return (a / b).replace([np.inf, -np.inf], np.nan)


def _rvol(series: pd.Series, window: int = 20) -> pd.Series:
    return _safe_div(series, series.rolling(window).mean())


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def detect_volatility_contraction_breakout(
    df: pd.DataFrame,
    spike_lookback: int = 20,
    spike_pct_threshold: float = 0.15,
    spike_rvol_threshold: float = 2.5,
    consolidation_bars: int = 4,
    max_consolidation_range_pct: float = 0.08,
    require_higher_lows: bool = True,
    require_volume_dryup: bool = True,
    breakout_buffer_pct: float = 0.003,
) -> pd.DataFrame:
    data = df.copy().reset_index(drop=True)
    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    data["pct_change"] = data["close"].pct_change()
    data["rvol"] = _rvol(data["volume"], 20)
    data["atr"] = _atr(data, 14)

    data["spike_bar"] = (
        ((data["close"] / data["close"].shift(1)) - 1 >= spike_pct_threshold)
        & (data["rvol"] >= spike_rvol_threshold)
    )
    data["recent_spike_context"] = ((data["close"] / data["close"].shift(spike_lookback)) - 1) >= spike_pct_threshold
    data["in_consolidation"] = False
    data["consolidation_high"] = np.nan
    data["consolidation_low"] = np.nan
    data["breakout_trigger"] = np.nan
    data["breakout_now"] = False
    data["pattern_score"] = 0.0
    data["spike_idx"] = np.nan

    for i in range(spike_lookback + consolidation_bars, len(data)):
        prior = data.iloc[: i - consolidation_bars]
        spike_candidates = prior.index[prior["spike_bar"]].tolist()
        if not spike_candidates:
            continue

        spike_idx = spike_candidates[-1]
        start = spike_idx + 1
        end = i
        window_df = data.iloc[start:end]
        if len(window_df) < consolidation_bars:
            continue

        recent_cons = window_df.tail(consolidation_bars)
        cons_high = recent_cons["high"].max()
        cons_low = recent_cons["low"].min()
        cons_range_pct = (cons_high - cons_low) / cons_high if cons_high else np.inf
        tight_enough = cons_range_pct <= max_consolidation_range_pct

        higher_lows_ok = True
        if require_higher_lows:
            lows = recent_cons["low"].values
            higher_lows_ok = all(lows[j] >= lows[j - 1] * 0.995 for j in range(1, len(lows)))

        vol_dryup_ok = True
        if require_volume_dryup:
            spike_vol = data.loc[spike_idx, "volume"]
            avg_cons_vol = recent_cons["volume"].mean()
            vol_dryup_ok = avg_cons_vol < spike_vol * 0.75

        spike_high = data.loc[spike_idx, "high"]
        spike_low = data.loc[spike_idx, "low"]
        spike_mid = spike_low + ((spike_high - spike_low) * 0.5)
        holds_midpoint = recent_cons["close"].mean() >= spike_mid

        is_cons = tight_enough and higher_lows_ok and vol_dryup_ok and holds_midpoint
        if not is_cons:
            continue

        breakout_level = cons_high * (1 + breakout_buffer_pct)
        current_close = data.loc[i, "close"]
        breakout_now = current_close > breakout_level

        score = 0
        score += 30 if tight_enough else 0
        score += 20 if higher_lows_ok else 0
        score += 20 if vol_dryup_ok else 0
        score += 15 if holds_midpoint else 0
        score += 15 if breakout_now else 0

        data.loc[i, "in_consolidation"] = True
        data.loc[i, "consolidation_high"] = cons_high
        data.loc[i, "consolidation_low"] = cons_low
        data.loc[i, "breakout_trigger"] = breakout_level
        data.loc[i, "breakout_now"] = breakout_now
        data.loc[i, "pattern_score"] = float(score)
        data.loc[i, "spike_idx"] = float(spike_idx)

    return data


def _fetch_snapshot_universe() -> list:
    if "snapshot" in SNAPSHOT_CACHE:
        return SNAPSHOT_CACHE["snapshot"]

    url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?apiKey={API_KEY}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    tickers = response.json().get("tickers", [])
    SNAPSHOT_CACHE["snapshot"] = tickers
    return tickers


def _fetch_daily_bars(ticker: str, days: int = 120) -> pd.DataFrame:
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
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    BAR_CACHE[cache_key] = df
    return df


def prefilter_small_caps(df: pd.DataFrame) -> bool:
    if df.empty or len(df) < 20:
        return False
    last = df.iloc[-1]
    avg_dollar_volume = (df["close"] * df["volume"]).tail(20).mean()
    return bool(
        0.50 <= last["close"] <= 10.0
        and avg_dollar_volume >= 500_000
        and df["volume"].tail(1).iloc[0] >= 200_000
    )


def generate_volatility_contraction_breakouts(
    universe_limit: int = 300,
    min_price: float = 0.5,
    max_price: float = 10.0,
    min_day_volume: float = 5_000_000,
    min_day_change_pct: float = 8.0,
    min_rvol: float = 2.0,
) -> list:
    try:
        snapshot = _fetch_snapshot_universe()
    except Exception as exc:
        logging.warning(f"Volatility contraction snapshot fetch failed: {exc}")
        return []

    rows = []
    for item in snapshot:
        day = item.get("day", {})
        prev_day = item.get("prevDay", {})
        symbol = str(item.get("ticker") or "").upper()
        price = day.get("c") or (item.get("lastTrade") or {}).get("p") or prev_day.get("c")
        volume = day.get("v") or prev_day.get("v")
        prev_volume = prev_day.get("v")
        pct_change = item.get("todaysChangePerc")
        if not symbol or price is None or volume is None or pct_change is None:
            continue
        rvol = (volume / prev_volume) if prev_volume else 0.0
        if (
            price >= min_price
            and price <= max_price
            and volume >= min_day_volume
            and pct_change >= min_day_change_pct
            and rvol >= min_rvol
        ):
            rows.append(
                {
                    "ticker": symbol,
                    "price": float(price),
                    "day_volume": float(volume),
                    "pct_change": float(pct_change),
                    "rvol": float(rvol),
                }
            )

    if not rows:
        return []

    base_df = pd.DataFrame(rows).sort_values(["rvol", "day_volume"], ascending=False).head(universe_limit)
    results = []

    for _, row in base_df.iterrows():
        ticker = row["ticker"]
        try:
            df = _fetch_daily_bars(ticker, days=120)
            if not prefilter_small_caps(df):
                continue
            scanned = detect_volatility_contraction_breakout(df)
            if scanned.empty:
                continue
            last = scanned.iloc[-1]
            if not (bool(last["in_consolidation"]) or bool(last["breakout_now"])):
                continue

            notes = []
            if bool(last["breakout_now"]):
                notes.append("Breakout active")
            else:
                notes.append("Tight consolidation")
            if bool(last["in_consolidation"]):
                notes.append("Holding coil")
            if pd.notna(last["spike_idx"]):
                notes.append("Spike then pause")

            results.append(
                {
                    "ticker": ticker,
                    "close": round(float(last["close"]), 4),
                    "volume": int(row["day_volume"]),
                    "rvol": round(float(row["rvol"]), 2),
                    "pct_change": round(float(row["pct_change"]), 2),
                    "in_consolidation": bool(last["in_consolidation"]),
                    "breakout_now": bool(last["breakout_now"]),
                    "breakout_trigger": round(float(last["breakout_trigger"]), 4) if pd.notna(last["breakout_trigger"]) else None,
                    "pattern_score": round(float(last["pattern_score"]), 2),
                    "consolidation_high": round(float(last["consolidation_high"]), 4) if pd.notna(last["consolidation_high"]) else None,
                    "consolidation_low": round(float(last["consolidation_low"]), 4) if pd.notna(last["consolidation_low"]) else None,
                    "notes": notes,
                }
            )
        except Exception as exc:
            logging.warning(f"Skipping {ticker} in volatility contraction scan: {exc}")

    if not results:
        return []

    out = pd.DataFrame(results).sort_values(
        by=["breakout_now", "pattern_score", "rvol"],
        ascending=[False, False, False],
    )
    return out.reset_index(drop=True).to_dict(orient="records")
