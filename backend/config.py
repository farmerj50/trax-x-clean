import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Prefer backend/.env for server-only secrets. The repo-root .env remains a
# compatibility fallback for older local setups and frontend-safe REACT_APP_*.
load_dotenv(BASE_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")


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
ENABLE_LSTM_STARTUP_TRAINING = os.getenv("ENABLE_LSTM_STARTUP_TRAINING", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

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
MARKET_SIGNALS_SUBSCRIBE = os.getenv("MARKET_SIGNALS_SUBSCRIBE", "").strip()

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

# Social signal tracker
ENABLE_SOCIAL_SIGNAL_TRACKER = os.getenv("ENABLE_SOCIAL_SIGNAL_TRACKER", "true").strip().lower() in {"1", "true", "yes", "on"}
SOCIAL_PROVIDER_TIMEOUT_SECONDS = float(os.getenv("SOCIAL_PROVIDER_TIMEOUT_SECONDS", "8"))
SOCIAL_SIGNAL_FETCH_LIMIT = int(os.getenv("SOCIAL_SIGNAL_FETCH_LIMIT", "25"))
SOCIAL_SIGNAL_HISTORY_LIMIT = int(os.getenv("SOCIAL_SIGNAL_HISTORY_LIMIT", "72"))
SOCIAL_SIGNAL_STATE_PATH = LOG_DIR / "social_signal_state.json"
SOCIAL_REDDIT_URL = os.getenv("SOCIAL_REDDIT_URL", "").strip()
SOCIAL_STOCKTWITS_URL = os.getenv("SOCIAL_STOCKTWITS_URL", "").strip()
SOCIAL_X_URL = os.getenv("SOCIAL_X_URL", "").strip()
SOCIAL_CUSTOM_URL = os.getenv("SOCIAL_CUSTOM_URL", "").strip()
SOCIAL_CRYPTO_WATCHLIST = [
    item.strip().upper()
    for item in os.getenv("SOCIAL_CRYPTO_WATCHLIST", "BTC,ETH,SOL,DOGE").split(",")
    if item.strip()
]
PREDICTION_MARKET_TOPICS = [
    item.strip()
    for item in os.getenv("PREDICTION_MARKET_TOPICS", "earnings,fda approval,defense contract,election,rate cut").split(",")
    if item.strip()
]

# Contact alerts
ALERT_CONTACTS_PATH = LOG_DIR / "alert_contacts.json"
ALERT_DEFAULT_SUBJECT = os.getenv("ALERT_DEFAULT_SUBJECT", "Trax-X alert subscription").strip() or "Trax-X alert subscription"
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME).strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "").strip()
ALERT_EVENT_LOG_PATH = LOG_DIR / "alert_event_log.json"
ALERT_EVENT_COOLDOWN_MINUTES = int(os.getenv("ALERT_EVENT_COOLDOWN_MINUTES", "180"))

# App authentication layer
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
AUTH_STATE_PATH = LOG_DIR / "auth_state.json"
AUTH_SESSION_COOKIE = os.getenv("AUTH_SESSION_COOKIE", "trax_x_session").strip() or "trax_x_session"
AUTH_SESSION_TTL_HOURS = float(os.getenv("AUTH_SESSION_TTL_HOURS", "12"))
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
AUTH_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "Lax").strip() or "Lax"
AUTH_MIN_PASSWORD_LENGTH = int(os.getenv("AUTH_MIN_PASSWORD_LENGTH", "12"))
AUTH_LOGIN_MAX_ATTEMPTS = int(os.getenv("AUTH_LOGIN_MAX_ATTEMPTS", "5"))
AUTH_LOGIN_WINDOW_SECONDS = int(os.getenv("AUTH_LOGIN_WINDOW_SECONDS", "300"))
AUTH_ALLOWED_ORIGINS = tuple(
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "AUTH_ALLOWED_ORIGINS",
        ",".join(
            [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:3001",
                "http://127.0.0.1:3001",
                "http://localhost:3002",
                "http://127.0.0.1:3002",
                "http://localhost:5000",
                "http://127.0.0.1:5000",
                "https://trax-x-clean-production.up.railway.app",
                "https://keen-hope-production-4a15.up.railway.app",
            ]
        ),
    ).split(",")
    if origin.strip()
)

# Trading execution layer
ENABLE_TRADING = os.getenv("ENABLE_TRADING", "false").strip().lower() in {"1", "true", "yes", "on"}
TRADING_PROVIDER = os.getenv("TRADING_PROVIDER", "paper").strip().lower() or "paper"
TRADING_MODE = os.getenv("TRADING_MODE", "paper").strip().lower() or "paper"
TRADING_STATE_PATH = LOG_DIR / "trading_state.json"
TRADING_STARTING_CASH = float(os.getenv("TRADING_STARTING_CASH", "100000"))
TRADING_PAPER_AUTO_FILL = os.getenv("TRADING_PAPER_AUTO_FILL", "true").strip().lower() in {"1", "true", "yes", "on"}
TRADING_MAX_ORDER_NOTIONAL = float(os.getenv("TRADING_MAX_ORDER_NOTIONAL", "100"))
TRADING_MAX_ORDER_QTY = float(os.getenv("TRADING_MAX_ORDER_QTY", "100"))
TRADING_ALLOWED_SYMBOLS = tuple(
    symbol.strip().upper()
    for symbol in os.getenv("TRADING_ALLOWED_SYMBOLS", "").split(",")
    if symbol.strip()
)
TRADING_ALLOW_SHORT_SELLS = os.getenv("TRADING_ALLOW_SHORT_SELLS", "false").strip().lower() in {"1", "true", "yes", "on"}
TRADING_REQUIRE_MARKET_OPEN = os.getenv("TRADING_REQUIRE_MARKET_OPEN", "false").strip().lower() in {"1", "true", "yes", "on"}

# Alpaca Broker API. Keep these backend-only.
ALPACA_BROKER_ENV = os.getenv("ALPACA_BROKER_ENV", "sandbox").strip().lower() or "sandbox"
ALPACA_BROKER_IS_SANDBOX = ALPACA_BROKER_ENV == "sandbox"
ALPACA_BROKER_API_BASE = os.getenv(
    "ALPACA_BROKER_API_BASE",
    "https://broker-api.sandbox.alpaca.markets"
    if ALPACA_BROKER_IS_SANDBOX
    else "https://broker-api.alpaca.markets",
).strip().rstrip("/")
ALPACA_BROKER_AUTH_MODE = os.getenv("ALPACA_BROKER_AUTH_MODE", "client_credentials").strip().lower() or "client_credentials"
ALPACA_BROKER_AUTH_BASE = os.getenv(
    "ALPACA_BROKER_AUTH_BASE",
    "https://authx.sandbox.alpaca.markets" if ALPACA_BROKER_IS_SANDBOX else "https://authx.alpaca.markets",
).strip().rstrip("/")
ALPACA_BROKER_API_KEY = os.getenv("ALPACA_BROKER_API_KEY", "").strip()
ALPACA_BROKER_API_SECRET = os.getenv("ALPACA_BROKER_API_SECRET", "").strip()
ALPACA_BROKER_ENABLED = os.getenv("ALPACA_BROKER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
ALPACA_BROKER_ACCOUNT_ID = os.getenv("ALPACA_BROKER_ACCOUNT_ID", "").strip()
ALPACA_BROKER_FIRM_ACCOUNT_NUMBER = os.getenv("ALPACA_BROKER_FIRM_ACCOUNT_NUMBER", "").strip()
ALPACA_BROKER_TIMEOUT_SECONDS = float(os.getenv("ALPACA_BROKER_TIMEOUT_SECONDS", "15"))
ALPACA_BROKER_ALLOW_ORDERS = os.getenv("ALPACA_BROKER_ALLOW_ORDERS", "false").strip().lower() in {"1", "true", "yes", "on"}
