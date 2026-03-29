import os
import pandas as pd
import numpy as np
import logging
from flask_socketio import emit
from xgboost import XGBClassifier
from joblib import load
import requests
import config

# ✅ Polygon.io API Key
POLYGON_API_KEY = config.POLYGON_API_KEY

# ✅ Model Paths (Ensure correct model is used)
MODEL_DIR = config.MODELS_DIR
OPTIMIZED_MODEL_PATH = config.XGB_MODEL_PATH  # ✅ Correct model
FEATURES_PATH = config.XGB_FEATURES_PATH

# ✅ Ensure model directory exists
if not os.path.exists(MODEL_DIR):
    logging.error(f"❌ ERROR: Model directory does not exist: {MODEL_DIR}. Training is required!")
    exit(1)  # Stop execution if model directory is missing

# ✅ Load Trained Optimized XGBoost Model (NO TRAINING)
def load_xgboost_model():
    """
    Loads the optimized XGBoost model.
    If missing, logs an error and exits (instead of training).
    """
    if not os.path.exists(OPTIMIZED_MODEL_PATH) or not os.path.exists(FEATURES_PATH):
        logging.error("❌ ERROR: Trained XGBoost model or feature list not found. Train the model first!")
        exit(1)  # Stop execution if model is missing

    try:
        model = load(OPTIMIZED_MODEL_PATH)
        features = load(FEATURES_PATH)
        logging.info(f"✅ Successfully loaded optimized XGBoost model from: {OPTIMIZED_MODEL_PATH}")
        logging.info(f"✅ Features in trained XGBoost model: {features}")
        return model, features
    except Exception as e:
        logging.error(f"❌ ERROR loading optimized XGBoost model: {e}")
        exit(1)  # Stop execution if model loading fails

# ✅ Load the trained optimized model
xgb_model, feature_columns = load_xgboost_model()

# ✅ Fetch Live Stock Data
def fetch_live_stock_data(ticker):
    """Fetch real-time stock data from Polygon.io."""
    try:
        url = f"https://api.polygon.io/v2/last/trade/{ticker}?apiKey={POLYGON_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return {
            "ticker": ticker,
            "price": data["results"]["p"],
            "timestamp": data["results"]["t"]
        }
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error fetching live stock data for {ticker}: {e}")
        return None

# ✅ Preprocess Real-Time Data for AI/ML Prediction
def preprocess_live_data(price, volume, sentiment_score):
    """Prepare real-time data for AI/ML prediction."""
    return {
        "price_change": np.random.uniform(-0.05, 0.05),  # Replace with actual price change
        "volatility": np.random.uniform(0.01, 0.05),    # Replace with actual volatility
        "volume": volume,
        "sentiment_score": sentiment_score,
        "rsi": np.random.uniform(30, 70),  # Replace with actual RSI calculation
        "macd_diff": np.random.uniform(-1, 1),  # Replace with actual MACD calculation
        "adx": np.random.uniform(10, 40),
        "atr": np.random.uniform(0.5, 2),
        "mfi": np.random.uniform(20, 80),
        "macd_line": np.random.uniform(-1, 1),
        "macd_signal": np.random.uniform(-1, 1),
    }

# ✅ Real-Time Stock Tracking via WebSocket
def track_stock_event(data):
    """Real-time stock tracking using WebSocket."""
    ticker = data.get("ticker")
    if not ticker:
        return emit("error", {"message": "Ticker is missing"})

    try:
        # Fetch live stock data
        live_data = fetch_live_stock_data(ticker)
        if not live_data:
            return emit("error", {"message": "Failed to fetch live stock data."})

        # Preprocess data for prediction
        processed_data = preprocess_live_data(
            live_data["price"], volume=1000, sentiment_score=0.5  # Replace with actual values
        )
        features_df = pd.DataFrame([processed_data])[feature_columns]

        # Predict using the optimized XGBoost model
        prediction = xgb_model.predict(features_df)[0]

        # Emit real-time stock update
        emit("stock_update", {
            "ticker": live_data["ticker"],
            "price": live_data["price"],
            "timestamp": live_data["timestamp"],
            "recommendation": "Buy" if prediction == 1 else "Sell" if prediction == -1 else "Hold"
        })
    except Exception as e:
        emit("error", {"message": str(e)})

