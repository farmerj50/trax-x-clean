from flask import Blueprint, jsonify, request
import pandas as pd
import numpy as np
from pathlib import Path
import logging
from utils.polygon_data import fetch_ohlcv_batch

# Heuristic, lightweight next-day pick selector.
# Uses local EOD aggregates (no live calls) and always returns up to `limit` tickers.

next_day_picks_bp = Blueprint("next_day_picks", __name__)
AGGREGATES_DIR = Path(__file__).resolve().parent.parent / "data" / "aggregates_day"


def load_aggregates(target_date: str | None = None) -> pd.DataFrame:
    files = sorted(AGGREGATES_DIR.glob("*.csv"))
    if not files:
        return pd.DataFrame()

    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    if "window_start" not in df.columns:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["window_start"], unit="ns", errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["date"])

    if target_date is None:
        target_date = df["date"].max()
    return df[df["date"] == target_date]


def rank_candidates(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    if df.empty:
        return df

    # Baseline liquidity/price sanity
    df = df[(df["volume"] > 300_000) & (df["close"].between(1, 1500))].copy()
    if df.empty:
        return df

    # Features
    df["range"] = df["high"] - df["low"]
    df["range_pct"] = np.where(df["close"] > 0, df["range"] / df["close"], 0)
    df["body"] = df["close"] - df["open"]
    df["body_pct"] = np.where(df["close"] > 0, df["body"] / df["close"], 0)
    df["day_change_pct"] = np.where(df["open"] > 0, df["close"] / df["open"] - 1, 0)

    # Relative volume vs ticker median
    df["rel_volume"] = df.groupby("ticker")["volume"].transform(lambda s: s / (s.median() + 1e-9))

    # ATR proxy from recent ranges
    df["atr_proxy"] = df.groupby("ticker")["range"].transform(lambda s: s.rolling(5).mean())
    df["atr_pct"] = np.where(df["close"] > 0, df["atr_proxy"] / df["close"], np.nan)

    # Keep latest record per ticker
    df = df.sort_values(["date", "window_start"]).groupby("ticker").tail(1)

    # Simple score blending momentum, range, and volume
    df["score"] = (
        df["day_change_pct"].fillna(0) * 0.35
        + df["range_pct"].fillna(0) * 0.25
        + df["rel_volume"].clip(0, 5).fillna(0) * 0.25
        + df["body_pct"].fillna(0) * 0.15
    )

    return (
        df.sort_values("score", ascending=False)
        .head(limit)
        .loc[:, ["ticker", "open", "close", "high", "low", "score", "atr_pct", "range_pct", "date"]]
    )


@next_day_picks_bp.route("/api/next-day-picks", methods=["GET"])
def next_day_picks():
    try:
        target_date = request.args.get("date")
        limit = int(request.args.get("limit", 5))
        logging.info("Fetching heuristic next-day picks...")

        df = load_aggregates(target_date)
        if df.empty:
            return jsonify({"candidates": [], "message": "No aggregate data found"}), 200

        ranked = rank_candidates(df, limit=limit)
        if ranked.empty:
            return jsonify({"candidates": [], "message": "No candidates after filters"}), 200

        # Refresh with live Polygon close/HL if available
        live_df = fetch_ohlcv_batch(ranked["ticker"].tolist(), days=5)
        if not live_df.empty:
            live_last = (
                live_df.sort_values("t")
                .groupby("ticker")
                .tail(1)
                .rename(columns={"close": "live_close", "high": "live_high", "low": "live_low"})
            )
            ranked = ranked.merge(live_last[["ticker", "live_close", "live_high", "live_low"]], on="ticker", how="left")

        candidates = []
        for _, row in ranked.iterrows():
            price_for_entry = row.get("live_close") if not pd.isna(row.get("live_close")) else row["close"]
            entry = float(price_for_entry)
            atr_pct = row["atr_pct"] if not pd.isna(row["atr_pct"]) else 0.01
            stop = round(entry * (1 - max(0.01, atr_pct)), 2)
            target_base = row.get("live_high") if not pd.isna(row.get("live_high")) else row["high"]
            # If we have a live high, bias target upward a bit; else use ATR-based RR.
            target = round(max(target_base, entry * (1 + max(0.02, atr_pct * 2.5))), 2)

            candidates.append(
                {
                    "ticker": row["ticker"],
                    "entry_price": round(entry, 2),
                    "stop_loss": stop,
                    "target_price": target,
                    "score": round(float(row["score"]), 4),
                    "notes": "Momentum/volume/range heuristic with live price refresh",
                }
            )

        return jsonify({"candidates": candidates, "date_used": ranked["date"].iloc[0]}), 200

    except Exception as e:
        logging.error(f"Error in next_day_picks heuristic: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
