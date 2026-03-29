# 📂 File: utils/pre_scan_filter.py
import pandas as pd

def pre_scan_filter(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # ✅ Price Range Filter
    df = df[df["close"].between(5, 150)]

    # ✅ Liquidity Filter
    df = df[df["volume"] > 500_000]

    # ✅ Volatility Filter (ATR% proxy)
    df = df[((df["high"] - df["low"]) / df["close"]) > 0.02]

    return df
