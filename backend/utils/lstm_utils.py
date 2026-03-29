import os
import joblib
import tensorflow as tf
from tensorflow.keras.models import load_model, Model  # type: ignore
from tensorflow.keras.utils import get_custom_objects  # type: ignore
from tensorflow.keras.layers import LeakyReLU  # type: ignore
from utils.train_model import train_and_cache_lstm_model  # ✅ Import the function from train_model.py
import logging

# Define model paths
MODELS_DIR = "C:/Users/gabby/trax-x/backend/models"
XGB_MODEL_PATH = os.path.join(MODELS_DIR, "optimized_xgb_model.joblib")
XGB_FEATURES_PATH = os.path.join(MODELS_DIR, "xgb_features.pkl")
LSTM_MODEL_PATH_KERAS = os.path.join(MODELS_DIR, "cnn_lstm_attention_model.keras")  # ✅ Keras Format
LSTM_MODEL_PATH_H5 = os.path.join(MODELS_DIR, "cnn_lstm_attention_model.h5")  # ✅ H5 Format
LSTM_SCALER_PATH = os.path.join(MODELS_DIR, "cnn_lstm_attention_scaler.pkl")
TICKER_ENCODER_PATH = os.path.join(MODELS_DIR, "xgb_ticker_encoder.pkl")

# Cache for models
lstm_cache = {"model": None, "scaler": None}

def load_lstm_model():
    """
    Load the LSTM model and scaler from disk if available.
    Ensures that the scaler retains feature names for proper LSTM input processing.
    """
    try:
        logging.info("📥 Step 1: Checking for saved LSTM model and scaler...")

        # ✅ Verify Scaler Exists
        if not os.path.exists(LSTM_SCALER_PATH):
            logging.error(f"❌ LSTM scaler missing at {LSTM_SCALER_PATH}! Falling back to XGBoost.")
            return None, None

        scaler = joblib.load(LSTM_SCALER_PATH)

        # ✅ Verify Model Paths
        model_path = None
        if os.path.exists(LSTM_MODEL_PATH_KERAS):
            model_path = LSTM_MODEL_PATH_KERAS
            logging.info(f"🔍 Found Keras model at {LSTM_MODEL_PATH_KERAS}")
        elif os.path.exists(LSTM_MODEL_PATH_H5):
            model_path = LSTM_MODEL_PATH_H5
            logging.info(f"🔍 Found H5 model at {LSTM_MODEL_PATH_H5}")
        else:
            logging.error("❌ No valid LSTM model found! Falling back to XGBoost.")
            return None, None

        # ✅ Attempt Model Loading
        try:
            logging.info(f"🔄 Loading LSTM model from {model_path}...")
            model = load_model(model_path, compile=False)
        except (ValueError, IOError) as e:
            logging.error(f"❌ ERROR: Could not load LSTM model. {e}")
            return None, None
        except Exception as e:
            logging.error(f"❌ Unexpected error while loading LSTM model: {e}", exc_info=True)
            return None, None

        # ✅ Ensure Model is a Valid Keras Model
        if isinstance(model, tuple):
            logging.error("❌ Model returned as tuple. Extracting first element.")
            model = model[0]  

        logging.info(f"✅ Model successfully loaded: {model.__class__.__name__} | Type: {type(model)}")

        if not isinstance(model, (tf.keras.Model, tf.keras.Sequential)):
            logging.error(f"❌ Invalid model type: {type(model)}. Expected tf.keras.Model.")
            return None, None

        return model, scaler

    except Exception as e:
        logging.error(f"❌ Unexpected error in load_lstm_model: {e}", exc_info=True)
        return None, None







