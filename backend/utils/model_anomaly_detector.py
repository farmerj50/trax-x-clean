# 📂 File: utils/model_anomaly_detector.py

import pandas as pd
import numpy as np
from utils.indicators import preprocess_data_with_indicators


def detect_anomalies(df, model):
    """
    Applies Isolation Forest to detect outliers.
    Assumes the model was trained on a known subset of engineered features.
    """
    feature_cols = [
        "pct_change_1d", "pct_change_5d", "pct_change_10d",
        "relative_volume", "atr%", "distance_50ema",
        "distance_200ema", "days_since_20d_high"
    ]

    features = df[feature_cols].copy()
    features = features.dropna()

    # Align df with features used (remove rows with NaNs in selected columns)
    df = df.loc[features.index]

    scores = model.decision_function(features)
    df["anomaly_score"] = scores

    return df

