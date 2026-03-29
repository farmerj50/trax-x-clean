import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
from cachetools import TTLCache
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

import config
from utils.cashflow_quality import get_cashflow_quality, get_financials_metrics

API_KEY = config.POLYGON_API_KEY

BAR_CACHE = TTLCache(maxsize=1000, ttl=3600)
SNAPSHOT_CACHE = TTLCache(maxsize=1, ttl=60)


def _market_status():
    url = f"https://api.polygon.io/v1/marketstatus/now?apiKey={API_KEY}"
    try:
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.warning(f"Market status fetch failed: {e}")
        return {}


def _is_market_open():
    status = _market_status()
    return bool(status.get("market")) and status.get("market") == "open"


def _fetch_snapshot_universe():
    if "snapshot" in SNAPSHOT_CACHE:
        return SNAPSHOT_CACHE["snapshot"]

    url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?apiKey={API_KEY}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    tickers = data.get("tickers", [])
    SNAPSHOT_CACHE["snapshot"] = tickers
    return tickers


def _fetch_grouped_daily(date_str: str):
    url = (
        f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/"
        f"{date_str}?adjusted=true&apiKey={API_KEY}"
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", [])


def _get_latest_trading_date():
    today = datetime.utcnow().date()
    for i in range(7):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            return d.strftime("%Y-%m-%d")
    return today.strftime("%Y-%m-%d")


def _fetch_daily_bars(ticker: str, days: int = 260):
    cache_key = f"{ticker}:{days}"
    if cache_key in BAR_CACHE:
        return BAR_CACHE[cache_key]

    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days)
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
        f"{start_date}/{end_date}?adjusted=true&sort=asc&limit={days}&apiKey={API_KEY}"
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("results", [])
    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df.rename(
        columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "t": "timestamp"},
        inplace=True,
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    BAR_CACHE[cache_key] = df
    return df


def _compute_breakout_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["range_pct"] = (df["high"] - df["low"]) / df["close"]
    df["price_change"] = (df["close"] - df["open"]) / df["open"]
    df["volatility"] = (df["high"] - df["low"]) / df["low"]

    df["rsi"] = RSIIndicator(close=df["close"], window=14, fillna=True).rsi()
    df["atr"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14, fillna=True
    ).average_true_range()
    df["atr_pct"] = (df["atr"] / df["close"]).replace([np.inf, -np.inf], np.nan)

    df["rvol_3d"] = df["volume"].rolling(3, min_periods=1).mean() / df["volume"].rolling(20, min_periods=5).mean()
    df["range_5d_avg"] = df["range_pct"].rolling(5, min_periods=3).mean()
    df["range_20d_median"] = df["range_pct"].rolling(20, min_periods=10).median()
    df["atr_pct_10d_avg"] = df["atr_pct"].rolling(10, min_periods=5).mean()
    df["high_20d"] = df["high"].rolling(20, min_periods=10).max()
    df["high_55d"] = df["high"].rolling(55, min_periods=20).max()

    df["ret_3d"] = df["close"].pct_change(3)
    df["exp_move_3d"] = df["ret_3d"].abs().rolling(252, min_periods=60).quantile(0.80)
    return df


def _setup_score(latest: pd.Series) -> float:
    proximity = (latest["high_20d"] - latest["close"]) / latest["high_20d"] if latest["high_20d"] else 1
    proximity_score = max(0.0, 1 - (proximity / 0.02)) if proximity <= 0.02 else 0.0
    compression_score = 1.0 if latest["atr_pct"] < (latest["atr_pct_10d_avg"] * 0.9) else 0.0
    range_score = 1.0 if latest["range_5d_avg"] < latest["range_20d_median"] else 0.0
    rvol_score = min(1.0, (latest["rvol_3d"] / 1.5)) if latest["rvol_3d"] else 0.0
    return (proximity_score + compression_score + range_score + rvol_score) / 4.0


def _resilience_score(rs_20: float, rs_200: float) -> float:
    score = 0.5
    score += np.clip(rs_20, -0.1, 0.1) * 2.5
    score += np.clip(rs_200, -0.2, 0.2) * 1.25
    return float(np.clip(score, 0, 1))


def _earnings_score(metrics: dict) -> float:
    rev_growth = metrics.get("revenue_ttm_growth")
    ni_growth = metrics.get("net_income_ttm_growth")
    if rev_growth is None and ni_growth is None:
        return 0.0

    vals = [v for v in [rev_growth, ni_growth] if v is not None]
    avg = float(np.mean(vals)) if vals else 0.0
    avg = float(np.clip(avg, -0.2, 0.5))
    return (avg + 0.2) / 0.7


def generate_three_day_breakouts(
    universe_limit: int = 150,
    min_price: float = 3.0,
    min_dollar_vol: float = 10_000_000,
    relaxed: bool = False,
):
    market_open = _is_market_open()

    if market_open:
        snapshot = _fetch_snapshot_universe()
        rows = []
        for item in snapshot:
            day = item.get("day", {})
            last = item.get("last", {})
            close = day.get("c") or last.get("p")
            volume = day.get("v")
            if close is None or volume is None:
                continue
            rows.append({
                "ticker": item.get("ticker"),
                "close": close,
                "volume": volume,
                "dollar_vol": close * volume,
            })
        base_df = pd.DataFrame(rows)
    else:
        date_str = _get_latest_trading_date()
        grouped = _fetch_grouped_daily(date_str)
        base_df = pd.DataFrame(grouped)
        if not base_df.empty:
            base_df.rename(columns={"T": "ticker", "c": "close", "v": "volume"}, inplace=True)
            base_df["dollar_vol"] = base_df["close"] * base_df["volume"]

    if base_df.empty:
        return []

    universe = base_df[
        (base_df["close"] >= min_price) &
        (base_df["dollar_vol"] >= min_dollar_vol)
    ].sort_values("dollar_vol", ascending=False).head(universe_limit)

    spy_df = _fetch_daily_bars("SPY", days=260)
    spy_df = _compute_breakout_features(spy_df) if not spy_df.empty else pd.DataFrame()
    if spy_df.empty or len(spy_df) < 50:
        logging.warning("SPY data unavailable for resilience scoring.")
        spy_50ma = None
        spy_ret20 = 0
        spy_ret200 = 0
    else:
        spy_ret20 = spy_df["close"].pct_change(20).iloc[-1]
        spy_ret200 = spy_df["close"].pct_change(200).iloc[-1] if len(spy_df) >= 200 else 0
        spy_50ma = spy_df["close"].rolling(50).mean().iloc[-1]
        spy_close = spy_df["close"].iloc[-1]
        spy_below_50 = spy_50ma is not None and spy_close < spy_50ma

    results = []
    stats = {
        "universe": len(universe),
        "no_bars": 0,
        "proximity": 0,
        "already_breakout": 0,
        "atr_contraction": 0,
        "range_compression": 0,
        "rvol_build": 0,
        "spy_filter": 0,
        "passed": 0,
    }

    for _, row in universe.iterrows():
        ticker = row["ticker"]
        df = _fetch_daily_bars(ticker, days=260)
        if df.empty or len(df) < 60:
            stats["no_bars"] += 1
            continue

        df = _compute_breakout_features(df)
        latest = df.iloc[-1]

        if latest["high_20d"] <= 0 or np.isnan(latest["high_20d"]):
            stats["proximity"] += 1
            continue

        proximity_20 = (latest["high_20d"] - latest["close"]) / latest["high_20d"]
        proximity_55 = None
        if latest["high_55d"] and not np.isnan(latest["high_55d"]):
            proximity_55 = (latest["high_55d"] - latest["close"]) / latest["high_55d"]

        proximity_limit_20 = 0.05 if relaxed else 0.03
        proximity_limit_55 = 0.08 if relaxed else 0.05

        within_20 = proximity_20 <= proximity_limit_20
        within_55 = proximity_55 is not None and proximity_55 <= proximity_limit_55

        if not (within_20 or within_55):
            stats["proximity"] += 1
            continue

        if latest["close"] > latest["high_20d"]:
            stats["already_breakout"] += 1
            continue

        atr_mult = 0.98 if relaxed else 0.9
        if latest["atr_pct"] >= (latest["atr_pct_10d_avg"] * atr_mult):
            stats["atr_contraction"] += 1
            continue

        range_mult = 1.1 if relaxed else 1.0
        if latest["range_5d_avg"] >= (latest["range_20d_median"] * range_mult):
            stats["range_compression"] += 1
            continue

        rvol_min = 1.05 if relaxed else 1.2
        if latest["rvol_3d"] < rvol_min:
            stats["rvol_build"] += 1
            continue

        if spy_df is not None and not spy_df.empty:
            ticker_ret20 = df["close"].pct_change(20).iloc[-1]
            ticker_ret200 = df["close"].pct_change(200).iloc[-1] if len(df) >= 200 else 0
        else:
            ticker_ret20 = 0
            ticker_ret200 = 0

        rs_20 = ticker_ret20 - spy_ret20
        rs_200 = ticker_ret200 - spy_ret200

        if spy_df is not None and not spy_df.empty:
            spy_close = spy_df["close"].iloc[-1]
            spy_below_50 = spy_50ma is not None and spy_close < spy_50ma
            if spy_below_50 and rs_20 <= 0:
                stats["spy_filter"] += 1
                continue

        setup = _setup_score(latest)
        quality = {
            "cashflow_strong": 1.0,
            "cashflow_positive": 0.7,
            "ocf_only": 0.4,
            "no_data": 0.0,
        }
        cf = get_cashflow_quality(ticker)
        quality_score = quality.get(cf.get("quality_tag", "no_data"), 0.0)

        metrics = get_financials_metrics(ticker)
        earnings_score = _earnings_score(metrics)
        resilience = _resilience_score(rs_20, rs_200)

        final_score = (
            setup * 0.35 +
            quality_score * 0.30 +
            earnings_score * 0.20 +
            resilience * 0.15
        )

        exp_move = latest["exp_move_3d"]
        if exp_move is None or np.isnan(exp_move) or exp_move <= 0:
            exp_move = 0.03

        entry = latest["close"]
        target = entry * (1 + exp_move)
        stop = entry * (1 - exp_move * 0.5)

        results.append({
            "ticker": ticker,
            "rank_score": final_score,
            "price_change": float(latest["price_change"]) if not np.isnan(latest["price_change"]) else 0,
            "volatility": float(latest["volatility"]) if not np.isnan(latest["volatility"]) else 0,
            "rsi": float(latest["rsi"]) if not np.isnan(latest["rsi"]) else 0,
            "entry_point": float(entry),
            "stop_loss": float(stop),
            "target_price": float(target),
            "quality_tag": cf.get("quality_tag", "no_data"),
            "earnings_score": earnings_score,
            "rs_20": float(rs_20),
            "rs_200": float(rs_200),
        })
        stats["passed"] += 1

    logging.info(f"3-day breakouts stats: {stats} (relaxed={relaxed})")
    results.sort(key=lambda x: x["rank_score"], reverse=True)
    return results[:25]
