import os
import pandas as pd
import numpy as np
import joblib
import lightgbm as lgb
from datetime import datetime

LOG_DIR = r"C:\Users\gabby\trax-x\backend\log_dir"
NEXT_DAY_PICKS_CSV = os.path.join(LOG_DIR, "next_day_picks.csv")

def load_aggregate_data(agg_folder="c:\\aggregates_day"):
    all_files = [os.path.join(agg_folder, f) for f in os.listdir(agg_folder) if f.endswith(".csv")]
    df = pd.concat((pd.read_csv(f) for f in all_files), ignore_index=True)
    return df

def feature_engineer(df):
    df = df.copy()
    df["price_change"] = (df["close"] - df["open"]) / df["open"]
    df["volatility"] = (df["high"] - df["low"]) / df["low"]
    df["volume_surge"] = df["volume"] / df["volume"].rolling(window=5, min_periods=1).mean()
    return df

def predict_next_day_candidates(model_path="path_to_model.pkl"):
    model = joblib.load(model_path)
    df = load_aggregate_data()
    df = feature_engineer(df)
    X = df[["price_change", "volatility", "volume_surge"]]
    preds = model.predict(X)
    df["next_day_signal"] = preds
    return df[df["next_day_signal"] == 1]

def preprocess_next_day_candidates(df):
    df = df.copy()

    df["price_change"] = (df["close"] - df["open"]) / df["open"]
    df["volatility"] = (df["high"] - df["low"]) / df["low"]
    df["volume_surge"] = df["volume"] / df["volume"].rolling(window=5, min_periods=1).mean()

    # Example: Signal if volatility + volume surge criteria met
    df["next_day_signal"] = (
        (df["volatility"] > 0.02) & 
        (df["volume_surge"] > 1.5)
    ).astype(int)

    return df[df["next_day_signal"] == 1]  # Only return stocks that matched

