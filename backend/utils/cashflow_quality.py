import os
import json
import logging
from datetime import datetime, timedelta
import requests
import pandas as pd
import config

API_KEY = config.POLYGON_API_KEY

BASE_URL = "https://api.polygon.io/v3/reference/financials"
CACHE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "cache_cashflow.json")
)
CACHE_TTL_DAYS = 7


def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.warning(f"Failed to load cashflow cache: {e}")
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _is_cache_fresh(entry: dict) -> bool:
    updated_at = entry.get("updated_at")
    if not updated_at:
        return False
    try:
        updated_dt = datetime.fromisoformat(updated_at)
    except ValueError:
        return False

    if datetime.utcnow() - updated_dt > timedelta(days=CACHE_TTL_DAYS):
        return False

    report_date = entry.get("last_report_date")
    if report_date:
        try:
            report_dt = datetime.fromisoformat(report_date)
            if (datetime.utcnow().date() - report_dt.date()).days <= 2:
                return False
        except ValueError:
            return False

    return True


def _pick_first(d: dict, keys: list):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _extract_quarter_values(results: list) -> dict:
    ocf_vals = []
    capex_vals = []
    net_income_vals = []
    revenue_vals = []
    last_report_date = None

    for item in results:
        filing_date = item.get("filing_date") or item.get("report_date") or item.get("end_date")
        if filing_date and not last_report_date:
            last_report_date = filing_date

        financials = item.get("financials", {})
        cash_flow = financials.get("cash_flow_statement", {})
        income = financials.get("income_statement", {})

        ocf = _pick_first(cash_flow, [
            "net_cash_flow_from_operating_activities",
            "net_cash_provided_by_operating_activities",
            "cash_flow_from_operating_activities",
            "operating_cash_flow",
        ])
        capex = _pick_first(cash_flow, [
            "capital_expenditure",
            "capital_expenditures",
            "capital_expenditure_total",
        ])
        net_income = _pick_first(income, [
            "net_income",
            "net_income_loss",
            "net_income_attributable_to_parent",
            "net_income_common_stockholders",
        ])
        revenue = _pick_first(income, [
            "revenues",
            "revenue",
            "total_revenue",
            "sales",
        ])

        ocf_vals.append(ocf)
        capex_vals.append(capex)
        net_income_vals.append(net_income)
        revenue_vals.append(revenue)

    return {
        "ocf_vals": ocf_vals,
        "capex_vals": capex_vals,
        "net_income_vals": net_income_vals,
        "revenue_vals": revenue_vals,
        "last_report_date": last_report_date,
    }


def _sum_ttm(vals: list, abs_vals: bool = False):
    if len(vals) < 4 or any(v is None for v in vals[:4]):
        return None
    cleaned = [abs(v) if abs_vals else v for v in vals[:4]]
    return sum(cleaned)


def _fetch_financials(ticker: str, limit: int = 4) -> dict:
    params = {
        "ticker": ticker,
        "timeframe": "quarterly",
        "limit": limit,
        "apiKey": API_KEY,
    }
    resp = requests.get(BASE_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data


def get_cashflow_quality(ticker: str) -> dict:
    cache = _load_cache()
    entry = cache.get(ticker, {})
    if entry and _is_cache_fresh(entry):
        return entry

    try:
        payload = _fetch_financials(ticker, limit=8)
        results = payload.get("results", [])
        if not results:
            raise ValueError("No financials results")

        extracted = _extract_quarter_values(results)
        ocf_ttm = _sum_ttm(extracted["ocf_vals"])
        capex_ttm = _sum_ttm(extracted["capex_vals"], abs_vals=True)
        net_income_ttm = _sum_ttm(extracted["net_income_vals"])
        revenue_ttm = _sum_ttm(extracted["revenue_vals"])

        ocf_ttm_prev = _sum_ttm(extracted["ocf_vals"][4:8])
        net_income_ttm_prev = _sum_ttm(extracted["net_income_vals"][4:8])
        revenue_ttm_prev = _sum_ttm(extracted["revenue_vals"][4:8])

        fcf_ttm = None
        if ocf_ttm is not None and capex_ttm is not None:
            fcf_ttm = ocf_ttm - capex_ttm

        tag = "no_data"
        if ocf_ttm is not None and fcf_ttm is not None:
            if ocf_ttm > 0 and fcf_ttm > 0:
                if revenue_ttm and revenue_ttm > 0 and (fcf_ttm / revenue_ttm) > 0.05:
                    tag = "cashflow_strong"
                else:
                    tag = "cashflow_positive"
        elif ocf_ttm is not None and ocf_ttm > 0 and net_income_ttm is not None and net_income_ttm > 0:
            tag = "ocf_only"

        entry = {
            "ticker": ticker,
            "quality_tag": tag,
            "ocf_ttm": ocf_ttm,
            "capex_ttm": capex_ttm,
            "fcf_ttm": fcf_ttm,
            "net_income_ttm": net_income_ttm,
            "revenue_ttm": revenue_ttm,
            "ocf_ttm_prev": ocf_ttm_prev,
            "net_income_ttm_prev": net_income_ttm_prev,
            "revenue_ttm_prev": revenue_ttm_prev,
            "last_report_date": extracted["last_report_date"],
            "updated_at": datetime.utcnow().isoformat(),
        }
        cache[ticker] = entry
        _save_cache(cache)
        return entry
    except Exception as e:
        logging.warning(f"Cashflow fetch failed for {ticker}: {e}")
        entry["quality_tag"] = entry.get("quality_tag", "no_data")
        cache[ticker] = entry
        _save_cache(cache)
        return entry


def get_financials_metrics(ticker: str) -> dict:
    """
    Returns revenue/net income TTM growth metrics using cached financials.
    """
    entry = get_cashflow_quality(ticker)
    revenue_ttm = entry.get("revenue_ttm")
    revenue_ttm_prev = entry.get("revenue_ttm_prev")
    net_income_ttm = entry.get("net_income_ttm")
    net_income_ttm_prev = entry.get("net_income_ttm_prev")

    metrics = {}
    if revenue_ttm is not None and revenue_ttm_prev not in (None, 0):
        metrics["revenue_ttm_growth"] = (revenue_ttm - revenue_ttm_prev) / abs(revenue_ttm_prev)
    else:
        metrics["revenue_ttm_growth"] = None

    if net_income_ttm is not None and net_income_ttm_prev not in (None, 0):
        metrics["net_income_ttm_growth"] = (net_income_ttm - net_income_ttm_prev) / abs(net_income_ttm_prev)
    else:
        metrics["net_income_ttm_growth"] = None

    return metrics


def annotate_cashflow_quality(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "ticker" not in df.columns:
        df["quality_tag"] = "no_data"
        return df

    tags = []
    for ticker in df["ticker"].astype(str).tolist():
        info = get_cashflow_quality(ticker)
        tags.append(info.get("quality_tag", "no_data"))

    df["quality_tag"] = tags
    return df
