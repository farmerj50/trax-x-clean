import logging
import numpy as np
import pandas as pd

REQUIRED_BASE = [
    "ticker", "close", "volume",
    "high", "low", "open",
]

OPTIONAL_WARN = [
    "rsi", "macd", "atr", "sma_20", "ema_9",
    "relative_volume",
]


def validate_features(df: pd.DataFrame, scanner_name: str = "pipeline") -> pd.DataFrame:
    missing = [c for c in REQUIRED_BASE if c not in df.columns]
    if missing:
        raise ValueError(f"[{scanner_name}] missing required features: {missing}")

    for c in OPTIONAL_WARN:
        if c not in df.columns:
            logging.warning(f"[WARN] {scanner_name}: {c} not present")

    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=["close", "volume"])

    return df
