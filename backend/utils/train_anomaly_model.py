import os
import joblib
import logging
import pandas as pd
from sklearn.ensemble import IsolationForest
from datetime import datetime

from utils.feature_engineering import engineer_features
from utils.polygon_data import fetch_ohlcv_batch

AGGREGATES_DIR = r"C:\aggregates_day"
SAVE_PATH = r"C:\Users\gabby\trax-x\backend\models\anomaly_model.pkl"
logging.basicConfig(level=logging.INFO)


def get_recent_tickers_from_aggregates(days_back: int = 3) -> list:
    all_files = [
        os.path.join(AGGREGATES_DIR, f)
        for f in os.listdir(AGGREGATES_DIR)
        if f.endswith('.csv')
    ]
    if not all_files:
        raise ValueError("❌ No aggregate CSVs found.")

    df = pd.concat(pd.read_csv(f) for f in all_files)
    df['window_start'] = pd.to_datetime(df['window_start'], unit='ns', errors='coerce')
    df = df.dropna(subset=['window_start'])

    cutoff = datetime.now() - pd.Timedelta(days=days_back)
    recent = df[df['window_start'] >= cutoff]

    filtered = recent[
        (recent['volume'] > 500_000) & 
        (recent['close'].between(5, 150))
    ]

    tickers = filtered['ticker'].dropna().unique().tolist()
    logging.info(f"🎯 Selected {len(tickers)} tickers from aggregates.")
    return tickers


def train_anomaly_model(tickers: list):
    logging.info("🛠️ Training anomaly model...")
    df = fetch_ohlcv_batch(tickers, days=10)
    if df.empty:
        raise ValueError("❌ No OHLCV data pulled.")

    df = engineer_features(df)

    feature_cols = [
        "pct_change_1d", "pct_change_5d", "pct_change_10d",
        "relative_volume", "atr%", "distance_50ema",
        "distance_200ema", "days_since_20d_high"
    ]

    X = df[feature_cols].dropna()
    if X.empty:
        raise ValueError("❌ No usable rows for model training.")

    model = IsolationForest(n_estimators=100, contamination=0.01, random_state=42)
    model.fit(X[feature_cols])
    joblib.dump(model, SAVE_PATH)
    logging.info(f"✅ Anomaly model saved to: {SAVE_PATH}")
    return model


def load_anomaly_model():
    if os.path.exists(SAVE_PATH):
        return joblib.load(SAVE_PATH)
    return None


def check_and_train_anomaly_model(tickers: list):
    """
    Ensures model file exists, or trains and saves it.
    """
    if os.path.exists(SAVE_PATH):
        logging.info("✅ Anomaly model already exists.")
        return
    logging.warning("⚠️ Anomaly model not found. Training now...")
    train_anomaly_model(tickers)


def get_or_train_anomaly_model(tickers: list):
    """
    Safe accessor: trains if missing, always returns model.
    """
    model = load_anomaly_model()
    if model is not None:
        logging.info("📦 Anomaly model loaded.")
        return model

    logging.warning("📦 Model not found — training from scratch.")
    return train_anomaly_model(tickers)


if __name__ == "__main__":
    try:
        logging.info("🔍 Running anomaly model training script...")
        tickers = get_recent_tickers_from_aggregates()
        check_and_train_anomaly_model(tickers)
        logging.info("✅ Training complete.")
    except Exception as e:
        logging.error(f"❌ Training failed: {e}", exc_info=True)
