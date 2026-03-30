import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent


def require_env(key: str) -> str:
    """Return an environment variable or raise a clear error if missing."""
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


# External API keys (required)
POLYGON_API_KEY = require_env("POLYGON_API_KEY")
ALPHA_VANTAGE_API_KEY = require_env("ALPHA_VANTAGE_API_KEY")

# Paths
MODELS_DIR = BASE_DIR / "models"
LOG_DIR = BASE_DIR / "log_dir"
AGGREGATES_DIR = PROJECT_ROOT / "aggregates_day"

# Model artifacts
LSTM_MODEL_PATH = MODELS_DIR / "cnn_lstm_attention_model.keras"
SCALER_PATH = MODELS_DIR / "cnn_lstm_attention_scaler.pkl"
XGB_MODEL_PATH = MODELS_DIR / "optimized_xgb_model.joblib"
XGB_FEATURES_PATH = MODELS_DIR / "xgb_features.pkl"
TICKER_ENCODER_PATH = MODELS_DIR / "xgb_ticker_encoder.pkl"

# CSV output paths
FILTERED_CSV_PATH = LOG_DIR / "filtered_before_xgboost.csv"
XGB_CSV_PATH = LOG_DIR / "filtered_after_xgboost.csv"
FINAL_AI_CSV_PATH = LOG_DIR / "final_ai_predictions.csv"

# WebSocket
POLYGON_WS_URL = "wss://delayed.polygon.io/stocks"
ENABLE_LEGACY_POLYGON_WS = os.getenv("ENABLE_LEGACY_POLYGON_WS", "false").strip().lower() in {"1", "true", "yes", "on"}

# Market signal pipeline
ENABLE_MARKET_SIGNALS = os.getenv("ENABLE_MARKET_SIGNALS", "true").strip().lower() in {"1", "true", "yes", "on"}
MARKET_SIGNALS_BIG_PRINT_THRESHOLD = float(os.getenv("MARKET_SIGNALS_BIG_PRINT_THRESHOLD", "10000000"))
MARKET_SIGNALS_SUBSCRIBE = os.getenv("MARKET_SIGNALS_SUBSCRIBE", "T.*,Q.*")

# Options flow (Intrinio)
ENABLE_OPTIONS_FLOW_SIGNALS = os.getenv("ENABLE_OPTIONS_FLOW_SIGNALS", "false").strip().lower() in {"1", "true", "yes", "on"}
INTRINIO_API_KEY = os.getenv("INTRINIO_API_KEY", "").strip()
INTRINIO_UNUSUAL_ACTIVITY_URL = os.getenv(
    "INTRINIO_UNUSUAL_ACTIVITY_URL",
    "https://api-v2.intrinio.com/options/unusual_activity",
).strip()
OPTIONS_FLOW_POLL_SECONDS = int(os.getenv("OPTIONS_FLOW_POLL_SECONDS", "15"))
OPTIONS_FLOW_MIN_PREMIUM = float(os.getenv("OPTIONS_FLOW_MIN_PREMIUM", "10000000"))
OPTIONS_FLOW_MAX_ITEMS = int(os.getenv("OPTIONS_FLOW_MAX_ITEMS", "100"))
