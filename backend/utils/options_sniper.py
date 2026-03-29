from datetime import datetime

import numpy as np
import pandas as pd


def explain_underlying_breakout_setup(row: dict) -> dict:
    price = float(row.get("price", 0) or 0)
    rvol = float(row.get("rvol", 0) or 0)
    dist = float(row.get("dist_to_breakout_pct", 999) or 999)
    above_vwap = bool(row.get("above_vwap", False))
    ema_stack = bool(row.get("ema8_above_ema21", False))
    day_change = float(row.get("day_change_pct", 0) or 0)
    day_notional = float(row.get("day_notional", 0) or 0)

    checks = {
        "price_ok": 5 <= price <= 120,
        "rvol_ok": rvol >= 1.3,
        "dist_ok": dist <= 6.0,
        "ema_stack_ok": ema_stack,
        "day_change_ok": day_change >= 1,
        "day_notional_ok": day_notional >= 10_000_000,
    }
    return {
        "price": price,
        "rvol": rvol,
        "dist_to_breakout_pct": dist,
        "above_vwap": above_vwap,
        "ema8_above_ema21": ema_stack,
        "day_change_pct": day_change,
        "day_notional": day_notional,
        "above_vwap_preferred": above_vwap,
        "passes": all(checks.values()),
        "checks": checks,
    }


def filter_underlying_breakout_setups(df: pd.DataFrame) -> pd.DataFrame:
    required = {
        "ticker",
        "price",
        "rvol",
        "dist_to_breakout_pct",
        "above_vwap",
        "ema8_above_ema21",
        "day_change_pct",
        "day_notional",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    out = df.copy()
    out = out[
        (out["price"].between(5, 120))
        & (out["rvol"] >= 1.3)
        & (out["dist_to_breakout_pct"] <= 6.0)
        & (out["ema8_above_ema21"] == True)
        & (out["day_change_pct"] >= 1)
        & (out["day_notional"] >= 10_000_000)
    ].copy()

    score = (
        (out["rvol"] * 25)
        + ((6.0 - out["dist_to_breakout_pct"]).clip(lower=0) * 8)
        + (out["day_change_pct"].clip(upper=8) * 5)
        + (out["above_vwap"].astype(int) * 10)
        + (out["ema8_above_ema21"].astype(int) * 10)
    )
    out["setup_score"] = score.round(2)
    return out.sort_values("setup_score", ascending=False)


def add_dte(option_chain: pd.DataFrame, today=None) -> pd.DataFrame:
    out = option_chain.copy()
    today = pd.Timestamp.today().normalize() if today is None else pd.Timestamp(today).normalize()
    out["expiry"] = pd.to_datetime(out["expiry"]).dt.normalize()
    out["dte"] = (out["expiry"] - today).dt.days
    return out


def select_small_account_contracts(
    option_chain: pd.DataFrame,
    min_ask: float = 0.30,
    max_ask: float = 2.50,
    min_dte: int = 3,
    max_dte: int = 21,
    min_delta: float = 0.20,
    max_delta: float = 0.65,
    min_oi: int = 100,
    min_volume: int = 20,
    max_spread_pct: float = 0.20,
    option_type: str = "call",
    return_debug: bool = False,
) -> pd.DataFrame:
    required = {
        "ticker",
        "expiry",
        "strike",
        "type",
        "bid",
        "ask",
        "volume",
        "open_interest",
        "delta",
    }
    missing = required - set(option_chain.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    chain = add_dte(option_chain)
    chain["spread"] = chain["ask"] - chain["bid"]
    chain["spread_pct"] = np.where(chain["ask"] > 0, chain["spread"] / chain["ask"], np.nan)

    debug = {
        "chain_rows": int(len(chain)),
        "after_type_filter": 0,
        "after_price_filter": 0,
        "after_dte_filter": 0,
        "after_delta_filter": 0,
        "after_liquidity_filter": 0,
        "after_spread_filter": 0,
        "final_candidates": 0,
    }

    out = chain[chain["type"].str.lower() == option_type.lower()].copy()
    debug["after_type_filter"] = int(len(out))

    out = out[out["ask"].between(min_ask, max_ask)].copy()
    debug["after_price_filter"] = int(len(out))

    out = out[out["dte"].between(min_dte, max_dte)].copy()
    debug["after_dte_filter"] = int(len(out))

    out = out[out["delta"].between(min_delta, max_delta)].copy()
    debug["after_delta_filter"] = int(len(out))

    out = out[
        (out["open_interest"] >= min_oi)
        & (out["volume"] >= min_volume)
        & (out["bid"] > 0)
    ].copy()
    debug["after_liquidity_filter"] = int(len(out))

    out = out[out["spread_pct"] <= max_spread_pct].copy()
    debug["after_spread_filter"] = int(len(out))

    out["contract_score"] = (
        (out["delta"] * 40)
        + ((1 - out["spread_pct"]).clip(lower=0) * 30)
        + (np.log1p(out["open_interest"]) * 5)
        + (np.log1p(out["volume"]) * 5)
        + ((2.50 - out["ask"]).clip(lower=0) * 8)
    ).round(2)

    out = out.sort_values("contract_score", ascending=False)
    debug["final_candidates"] = int(len(out))

    if return_debug:
        return out, debug
    return out


def build_option_sniper_candidates(
    stock_setups: pd.DataFrame,
    option_chains_by_ticker: dict,
    top_contracts_per_ticker: int = 3,
    return_debug: bool = False,
):
    rows = []
    debug_by_ticker = {}
    stock_debug = {}
    for _, stock in stock_setups.iterrows():
        ticker = str(stock.get("ticker") or "").upper()
        if ticker:
            stock_debug[ticker] = explain_underlying_breakout_setup(stock.to_dict())
    filtered_stocks = filter_underlying_breakout_setups(stock_setups)

    for _, stock in filtered_stocks.iterrows():
        ticker = stock["ticker"]
        chain = option_chains_by_ticker.get(ticker)
        if chain is None or chain.empty:
            debug_by_ticker[ticker] = {"chain_rows": 0, "final_candidates": 0}
            continue

        try:
            contract_result = select_small_account_contracts(chain, return_debug=True)
            if isinstance(contract_result, tuple) and len(contract_result) == 2:
                contracts, contract_debug = contract_result
            else:
                contracts = contract_result if isinstance(contract_result, pd.DataFrame) else pd.DataFrame()
                contract_debug = {"chain_rows": int(len(chain)), "final_candidates": int(len(contracts))}
            debug_by_ticker[ticker] = contract_debug
        except Exception as exc:
            debug_by_ticker[ticker] = {
                "chain_rows": int(len(chain)),
                "final_candidates": 0,
                "error": "contract_filter_failed",
                "detail": str(exc),
            }
            continue

        if contracts.empty:
            continue

        for _, contract in contracts.head(top_contracts_per_ticker).iterrows():
            rows.append(
                {
                    "ticker": ticker,
                    "stock_price": stock["price"],
                    "setup_score": stock["setup_score"],
                    "rvol": stock["rvol"],
                    "dist_to_breakout_pct": stock["dist_to_breakout_pct"],
                    "expiry": contract["expiry"].date().isoformat(),
                    "strike": contract["strike"],
                    "type": contract["type"],
                    "bid": contract["bid"],
                    "ask": contract["ask"],
                    "delta": contract["delta"],
                    "volume": contract["volume"],
                    "open_interest": contract["open_interest"],
                    "spread_pct": round(contract["spread_pct"], 4),
                    "contract_score": contract["contract_score"],
                    "combined_score": round(stock["setup_score"] + contract["contract_score"], 2),
                }
            )

    result = pd.DataFrame()
    if rows:
        result = pd.DataFrame(rows).sort_values("combined_score", ascending=False).reset_index(drop=True)

    if return_debug:
        return result, debug_by_ticker, stock_debug
    return result


def build_candidates_from_payload(stock_rows: list, option_chains: dict, top_contracts_per_ticker: int = 3) -> dict:
    stock_df = pd.DataFrame(stock_rows)
    chain_map = {ticker: pd.DataFrame(rows) for ticker, rows in (option_chains or {}).items()}
    result, contract_debug, stock_debug = build_option_sniper_candidates(
        stock_df,
        chain_map,
        top_contracts_per_ticker=top_contracts_per_ticker,
        return_debug=True,
    )
    return {
        "count": 0 if result.empty else len(result),
        "candidates": [] if result.empty else result.to_dict(orient="records"),
        "contract_debug": contract_debug,
        "stock_debug": stock_debug,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
