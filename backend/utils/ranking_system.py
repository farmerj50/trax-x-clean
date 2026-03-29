import pandas as pd
import numpy as np


def _norm(s: pd.Series) -> pd.Series:
    s = s.replace([np.inf, -np.inf], np.nan).fillna(0)
    std = s.std()
    if std == 0 or np.isnan(std):
        return s * 0
    return (s - s.mean()) / (std + 1e-9)


def _series_or_zeros(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return df[col]
    return pd.Series(0, index=df.index)


def rank_candidates(candidates: pd.DataFrame, regime: str) -> pd.DataFrame:
    candidates = candidates.copy()

    next_day = _series_or_zeros(candidates, "next_day_up_prob")
    anomaly = _series_or_zeros(candidates, "anomaly_score")
    volatility = _series_or_zeros(candidates, "volatility")

    candidates["rank_score"] = (
        _norm(next_day) * 0.5 +
        _norm(anomaly) * 0.3 +
        _norm(volatility) * 0.2
    )
    return candidates.sort_values("rank_score", ascending=False)
