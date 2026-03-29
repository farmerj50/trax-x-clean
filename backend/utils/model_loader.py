# 📂 backend/utils/model_loader.py

import os
import joblib
import logging
import pandas as pd
from utils.train_xgboost import train_xgboost_with_optuna  # ✅ XGBoost trainer


from utils.feature_engineering import engineer_features  # ✅ Feature engineering module




# ✅ Logging Configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ✅ Model Paths
MODELS_DIR = r"C:\Users\gabby\trax-x\backend\models"
XGB_MODEL_PATH = os.path.join(MODELS_DIR, "optimized_xgb_model.joblib")
XGB_FEATURES_PATH = os.path.join(MODELS_DIR, "xgb_features.pkl")
ANOMALY_MODEL_PATH = os.path.join(MODELS_DIR, "anomaly_model.pkl")

# ✅ Global Caches (avoid reloading repeatedly)
xgb_cache = {"model": None, "features": None}
anomaly_cache = {"model": None}

# ✅ Load XGBoost (fallbacks to training)
def load_xgb_model(force_retrain=False):
    try:
        if xgb_cache["model"] is None or force_retrain:
            logging.info("📌 Loading XGBoost model...")

            if not os.path.exists(XGB_MODEL_PATH) or not os.path.exists(XGB_FEATURES_PATH) or force_retrain:
                logging.warning("⚠️ XGBoost model or features missing. Triggering training...")
                train_xgboost_with_optuna()

            xgb_cache["model"] = joblib.load(XGB_MODEL_PATH)
            xgb_cache["features"] = joblib.load(XGB_FEATURES_PATH)

            logging.info("✅ XGBoost model & features loaded.")
        return xgb_cache["model"], xgb_cache["features"]

    except Exception as e:
        logging.error(f"❌ Failed to load XGBoost model: {e}", exc_info=True)
        return None, None

# ✅ Load Anomaly Model (fallbacks to training)
def load_anomaly_model(tickers: list = None, force_retrain=False):
    """
    Loads the anomaly model. Trains a new one if not found or force_retrain is True.
    Accepts optional ticker list for retraining if needed.
    """
    try:
        if anomaly_cache["model"] is None or force_retrain:
            logging.info("📌 Loading anomaly model...")

            if not os.path.exists(ANOMALY_MODEL_PATH) or force_retrain:
                logging.warning("⚠️ Anomaly model not found! Training new anomaly model...")

                if tickers:
                    from utils.train_anomaly_model import train_anomaly_model
                    train_anomaly_model(tickers)
                else:
                    from utils.train_anomaly_model import get_recent_tickers_from_aggregates
                    train_anomaly_model(get_recent_tickers_from_aggregates())

            anomaly_cache["model"] = joblib.load(ANOMALY_MODEL_PATH)
            logging.info("✅ Anomaly model loaded.")

        return anomaly_cache["model"]

    except Exception as e:
        logging.error(f"❌ Failed to load anomaly model: {e}", exc_info=True)
        return None

