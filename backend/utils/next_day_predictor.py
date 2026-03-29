import os
import pandas as pd
import numpy as np
import joblib
import lightgbm as lgb
from datetime import datetime

# Define your logs directory
LOG_DIR = r"C:\\Users\\gabby\\trax-x\\backend\\log_dir"
NEXT_DAY_PICKS_CSV = os.path.join(LOG_DIR, "next_day_picks.csv")

# Train a very simple model using past volatility, volume surge, and RSI


def load_aggregate_data(agg_folder="C:\\aggregates_day"):
    all_files = [os.path.join(agg_folder, f) for f in os.listdir(agg_folder) if f.endswith(".csv")]
    df = pd.concat((pd.read_csv(f) for f in all_files), ignore_index=True)
    return df


def feature_engineer(df):
    df = df.copy()
    df["price_change"] = (df["close"] - df["open"]) / df["open"]
    df["volatility"] = (df["high"] - df["low"]) / df["low"]
    df["volume_surge"] = df["volume"] / df["volume"].rolling(window=5, min_periods=1).mean()
    return df


def train_next_day_model(df):
    df = df.copy()
    df.dropna(inplace=True)

    features = ["open", "high", "low", "close", "volume", "volatility", "volume_surge"]
    target = "price_change"

    X = df[features]
    y = df[target]

    model = lgb.LGBMRegressor(n_estimators=200)
    model.fit(X, y)
    return model


def predict_top_picks(model, df, n_top=10):
    df = df.copy()
    features = ["open", "high", "low", "close", "volume", "volatility", "volume_surge"]
    df["predicted_gain"] = model.predict(df[features])
    
    # Sort by best predicted gains
    df = df.sort_values("predicted_gain", ascending=False)

    picks = df.head(n_top).copy()
    picks["entry_price"] = picks["open"]
    picks["target_exit"] = picks["entry_price"] * (1 + picks["predicted_gain"])

    picks.to_csv(NEXT_DAY_PICKS_CSV, index=False)
    return picks


def run_next_day_pipeline():
    data = load_aggregate_data()
    data = feature_engineer(data)
    model = train_next_day_model(data)
    picks = predict_top_picks(model, data)
    return picks


if __name__ == "__main__":
    picks = run_next_day_pipeline()
    print(picks)
