from flask import Flask, g, jsonify, request
from flask_cors import CORS
import requests
import os
import sys
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np
import json
import math
import threading
from datetime import datetime, timedelta
import time
from sklearn.preprocessing import LabelEncoder
import tensorflow as tf
from utils.indicators import generate_trade_signals
from utils.fetch_candlestick_data import fetch_candlestick_data
from utils.polygon_data import fetch_ohlcv_batch

# ✅ WebSocket & Flask SocketIO
import websocket
from flask_socketio import SocketIO

# ✅ Machine Learning & AI
from joblib import dump, load
import joblib

# ✅ Sentiment Analysis
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# ✅ Visualization
import matplotlib.pyplot as plt
import mplfinance as mpf

# ✅ Caching & Utility
from cachetools import TTLCache, cached

# Import utility functions
from utils.scheduler import initialize_scheduler
from utils.fetch_stock_performance import fetch_stock_performance
from utils.fetch_ticker_news import fetch_ticker_news
from utils.sentiment_plot import fetch_sentiment_trend, generate_sentiment_plot

from dotenv import load_dotenv  # ✅ Import dotenv
from utils.fetch_historical_performance import fetch_historical_data
# ✅ Import indicators.py for technical analysis
from utils.indicators import preprocess_data_with_indicators
from utils.train_model import train_and_cache_lstm_model
from utils.train_xgboost import train_xgboost_with_optuna
from utils.lstm_utils import load_lstm_model
from utils.model_loader import load_xgb_model  
from utils.train_xgboost import load_training_data
from utils.train_model import train_xgboost_with_optuna
from utils.train_xgboost import tune_xgboost_hyperparameters
from utils.indicators import preprocess_number_one_strategy
from utils.indicators import compute_macd
from routes.next_day_picks import next_day_picks_bp
from routes.options_routes import options_bp
from routes.alert_contacts import alert_contacts_bp
from routes.premarket_intelligence import premarket_intelligence_bp
from routes.social_tracker import social_tracker_bp
from routes.trading import trading_bp
from routes.auth import auth_bp
from auth_layer import service as auth_service
from utils.three_day_breakouts import generate_three_day_breakouts
from utils.volatility_contraction_breakout import generate_volatility_contraction_breakouts
from utils.ai_picks import alert_priority, calculate_ai_pick_score
from utils.contact_alerts import dispatch_alert_event
from utils.signal_engine import SignalEngine
from utils.market_stream import PolygonMarketStream
from utils.options_flow import IntrinioOptionsFlowPoller
from utils.options_data import fetch_option_chain_for_ticker
import logging
import config

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

# Initialize Flask app and SocketIO
app = Flask(__name__)
CORS(
    app,
    supports_credentials=True,
    origins=list(config.AUTH_ALLOWED_ORIGINS),
    allow_headers=["Content-Type", "Authorization"],
)


@app.before_request
def require_authenticated_user():
    try:
        auth_service.validate_request_origin(request)
    except auth_service.AuthError as exc:
        return jsonify({"error": str(exc), "authenticated": False}), exc.status_code

    if auth_service.is_public_path(request.path, request.method):
        return None
    try:
        session = auth_service.get_session(auth_service.get_token_from_request(request))
    except auth_service.AuthError as exc:
        return jsonify({"error": str(exc), "authenticated": False}), exc.status_code
    if not session:
        return jsonify({"error": "Authentication required.", "authenticated": False}), 401
    g.current_user = session["user"]
    return None


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "trax-x-backend",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "config": {
                "market_signals_enabled": bool(config.ENABLE_MARKET_SIGNALS),
                "options_flow_enabled": bool(config.ENABLE_OPTIONS_FLOW_SIGNALS),
                "trading_enabled": bool(config.ENABLE_TRADING),
                "trading_mode": config.TRADING_MODE,
                "trading_provider": config.TRADING_PROVIDER,
                "alpaca_broker_enabled": bool(config.ALPACA_BROKER_ENABLED),
                "polygon_api_key_configured": bool(POLYGON_API_KEY),
                "alpha_vantage_api_key_configured": bool(ALPHA_VANTAGE_API_KEY),
            },
        }
    ), 200


def _dispatch_ai_pick_alerts(picks: list[dict]) -> None:
    for item in list(picks or [])[:4]:
        alert = item.get("alert") or {}
        label = str(alert.get("label") or "").upper()
        if label not in {"LIVE", "NEAR"}:
            continue
        try:
            dispatch_alert_event(
                {
                    "page": "/stocks",
                    "eventType": "ai_pick",
                    "symbol": item.get("symbol"),
                    "label": label,
                    "instrument": "stock",
                    "recommendation": ", ".join(item.get("reasons") or []),
                    "score": item.get("score"),
                    "price": item.get("price"),
                    "summary": f"AI pick scored {item.get('score')} with {label} urgency.",
                }
            )
        except Exception as exc:
            logging.warning(f"AI pick alert dispatch failed: {exc}")


def _dispatch_crypto_signal_alert(signal: dict) -> None:
    score = float(signal.get("score", 0.0) or 0.0)
    if score < 0.55:
        return
    label = "LIVE" if score >= 0.8 else "WATCH"
    try:
        dispatch_alert_event(
            {
                "page": "/crypto",
                "eventType": "crypto_signal",
                "symbol": signal.get("ticker"),
                "label": label,
                "instrument": "crypto_spot",
                "recommendation": signal.get("momentum") or "monitor",
                "score": score,
                "price": signal.get("entry"),
                "summary": signal.get("comment") or "",
            }
        )
    except Exception as exc:
        logging.warning(f"Crypto alert dispatch failed: {exc}")

# then later when setting up app
app.register_blueprint(auth_bp)
app.register_blueprint(next_day_picks_bp)
app.register_blueprint(options_bp)
app.register_blueprint(alert_contacts_bp)
app.register_blueprint(premarket_intelligence_bp)
app.register_blueprint(social_tracker_bp)
app.register_blueprint(trading_bp)

MAX_RETRIES = 10  # Increased retries
WAIT_TIME = 5  # Increased wait time (seconds)


MODELS_DIR = config.MODELS_DIR
LSTM_MODEL_PATH = config.LSTM_MODEL_PATH
SCALER_PATH = config.SCALER_PATH
XGB_MODEL_PATH = config.XGB_MODEL_PATH
XGB_FEATURES_PATH = config.XGB_FEATURES_PATH
TICKER_ENCODER_PATH = config.TICKER_ENCODER_PATH 
LOG_DIR = config.LOG_DIR
FILTERED_CSV_PATH = config.FILTERED_CSV_PATH
XGB_CSV_PATH = config.XGB_CSV_PATH
FINAL_AI_CSV_PATH = config.FINAL_AI_CSV_PATH



# ✅ Define Log Directory and Ensure It Exists
LOG_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# ✅ Paths for CSV Logging
filtered_csv_path = str(FILTERED_CSV_PATH)
xgb_csv_path = str(XGB_CSV_PATH)

# ✅ Cache for LSTM Model (Fix the issue)
lstm_cache = {"model": None, "scaler": None}

# ✅ Load LSTM model at startup
if lstm_cache["model"] is None or lstm_cache["scaler"] is None:
    print("Checking for saved LSTM model...")

    model, scaler = load_lstm_model()
    if isinstance(model, tuple):
     logging.error(f"❌ ERROR: LSTM model is returning a tuple instead of a valid model! Type: {type(model)}")
    elif model is None:
     logging.warning("⚠️ LSTM model is missing. Falling back to XGBoost.")
    else:
     logging.info(f"✅ Loaded LSTM model successfully. Type: {type(model)}")

    if model is not None and scaler is not None:
       lstm_cache["model"], lstm_cache["scaler"] = model, scaler
       print("Loaded saved LSTM model successfully.")
    elif config.ENABLE_LSTM_STARTUP_TRAINING:
       print("LSTM model or scaler missing. Startup training is enabled; retraining now...")
       lstm_cache["model"], lstm_cache["scaler"] = train_and_cache_lstm_model()
    else:
       print("LSTM model or scaler missing. Skipping startup retraining.")

# Fix 'NoneType' object error in logging
logging.raiseExceptions = False  # Disable logging-related exceptions
logging.basicConfig(level=logging.INFO)  # Set default log level

# If using Flask logging, make sure it's initialized properly:
gunicorn_error_handlers = logging.getLogger("gunicorn.error")
app.logger.handlers = gunicorn_error_handlers.handlers
app.logger.setLevel(logging.INFO)

# ✅ Fix Gevent and Logging Conflict
socketio = SocketIO(app, cors_allowed_origins="*")

tickers = set()
# Ensure models/ directory exists
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Polygon.io WebSocket URL (Delayed by 15 minutes)
POLYGON_WS_URL = config.POLYGON_WS_URL
# Polygon.io API Key
POLYGON_API_KEY = config.POLYGON_API_KEY

# Get Alpha Vantage API Key from Environment
ALPHA_VANTAGE_API_KEY = config.ALPHA_VANTAGE_API_KEY
latest_stock_prices = {}  # Store the latest stock prices
if "legacy_ws_thread_lock" not in globals():
    legacy_ws_app = None
    legacy_ws_thread = None
    legacy_ws_thread_lock = threading.Lock()
    legacy_ws_runner_active = False
# Function to subscribe to tickers in WebSocket connection

def check_and_train_models():
    """
    Ensures both XGBoost & LSTM models exist, retraining them if missing.
    """

    # ✅ CHECK & TRAIN XGBOOST
    if not os.path.exists(XGB_MODEL_PATH) or not os.path.exists(XGB_FEATURES_PATH):
        logging.info("⚠️ XGBoost Model or Feature List Not Found! Training Now...")
        train_xgboost_with_optuna()
    else:
        logging.info("✅ XGBoost Model Found. No Need to Retrain.")

    # ✅ CHECK & TRAIN LSTM
    if lstm_cache.get("model") is None or lstm_cache.get("scaler") is None:
        print("Checking for saved LSTM model...")

        model, scaler = load_lstm_model()

        if model is not None and scaler is not None:
         lstm_cache["model"], lstm_cache["scaler"] = model, scaler
         print("Loaded saved LSTM model successfully.")
        else:
          print("LSTM model or scaler missing. Retraining now...")
          lstm_cache["model"], lstm_cache["scaler"] = train_and_cache_lstm_model()


    print("Model check complete. Both XGBoost and LSTM are ready.")
def classify_sentiment(score):
    """
    Convert a VADER compound sentiment score into a label.
    """
    if score >= 0.05:
        return "positive"
    elif score <= -0.05:
        return "negative"
    else:
        return "neutral"

def fetch_and_process_sentiment_data(ticker):
    """
    Fetch sentiment data for the given ticker from news sources, apply VADER sentiment analysis, 
    and classify sentiment as positive, neutral, or negative.
    """
    try:
        # Fetch news articles for the ticker
        news_data = fetch_ticker_news(ticker)

        # Process and analyze sentiment for each article
        for article in news_data:
            sentiment_score = analyzer.polarity_scores(article["title"])["compound"]
            article["sentiment"] = classify_sentiment(sentiment_score)

        return news_data  # Return enriched articles with sentiment labels
    except Exception as e:
        print(f"❌ Error fetching sentiment data: {e}")
        return []

def subscribe_to_tickers(ws=None):
    target_ws = ws or legacy_ws_app
    if target_ws is None:
        return
    if tickers:
        tickers_list = ",".join(tickers)
        message = json.dumps({"action": "subscribe", "params": f"AM.{tickers_list}"})
        target_ws.send(message)
        print(f"📡 Subscribed to: {tickers_list}")

# WebSocket event handlers
def on_message(ws, message):
    data = json.loads(message)
    if isinstance(data, list):
        for event in data:
            if "sym" in event and "c" in event:
                stock_data = {"ticker": event["sym"], "price": event["c"]}
                latest_stock_prices[event["sym"]] = event["c"]  # Store the latest price
                socketio.emit("stock_update", stock_data)
                print(f"📊 Live Update: {stock_data}")

def on_error(ws, error):
    print(f"❌ WebSocket Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("WebSocket closed, reconnecting in 5 seconds...")
    threading.Timer(5, ensure_websocket_thread_running).start()

def on_open(ws):
    subscribe_to_tickers(ws)

# Start WebSocket connection
def start_websocket_thread():
    global legacy_ws_app, legacy_ws_runner_active
    with legacy_ws_thread_lock:
        if legacy_ws_runner_active:
            return
        legacy_ws_runner_active = True
    try:
        ws = websocket.WebSocketApp(
            f"{POLYGON_WS_URL}?apiKey={POLYGON_API_KEY}",
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        legacy_ws_app = ws
        ws.on_open = on_open
        ws.run_forever()
    finally:
        with legacy_ws_thread_lock:
            legacy_ws_runner_active = False
        legacy_ws_app = None


def ensure_websocket_thread_running():
    if not config.ENABLE_LEGACY_POLYGON_WS:
        logging.info("Legacy Polygon websocket is disabled by ENABLE_LEGACY_POLYGON_WS.")
        return
    global legacy_ws_thread
    with legacy_ws_thread_lock:
        if legacy_ws_thread and legacy_ws_thread.is_alive():
            return
        legacy_ws_thread = threading.Thread(target=start_websocket_thread, daemon=True)
        legacy_ws_thread.start()

# API to dynamically add tickers for live tracking
@app.route('/api/add_ticker', methods=['POST'])
def add_ticker():
    data = request.get_json()
    ticker = data.get("ticker")
    if ticker:
        global tickers
        tickers.add(ticker.upper())
        ensure_websocket_thread_running()
        subscribe_to_tickers()  # Ensure real-time updates
        return jsonify({"message": f"{ticker} added to live updates."}), 200
    return jsonify({"error": "Ticker not provided."}), 400

# API Route for Real-Time Stock Data
@app.route('/api/live-data', methods=['GET'])
def live_data():
    try:
        ticker = request.args.get("ticker")
        if not ticker:
            return jsonify({"error": "Ticker parameter is missing"}), 400
        price = latest_stock_prices.get(ticker.upper(), "No data yet")
        return jsonify({"ticker": ticker, "price": price}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# Initialize Sentiment Analyzer
analyzer = SentimentIntensityAnalyzer()


# Caching (TTLCache)
historical_data_cache = TTLCache(maxsize=10, ttl=300)

def fetch_alpha_historical_data(ticker, interval="5min", output_size="full"):
    """
    Fetch historical stock data from Alpha Vantage and ensure data consistency.
    """
    api_key = ALPHA_VANTAGE_API_KEY

    url = (
        f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY"
        f"&symbol={ticker}&interval={interval}&outputsize={output_size}&apikey={api_key}"
    )

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        print(f"📊 Raw API Response Keys: {list(data.keys())}")  # Debugging

        time_series_key = f"Time Series ({interval})"
        if time_series_key not in data:
            print(f"⚠️ No historical data found for {ticker}. Response: {data}")
            return pd.DataFrame()

        records = data[time_series_key]

        # ✅ Convert JSON to DataFrame
        df = pd.DataFrame.from_dict(records, orient="index")
        df.index = pd.to_datetime(df.index)

        print(f"📊 Raw DataFrame Columns Before Renaming: {df.columns.tolist()}")  # Debugging

        # ✅ Rename columns correctly
        rename_mapping = {
            "1. open": "o",
            "2. high": "h",
            "3. low": "l",
            "4. close": "c",
            "5. volume": "volume"
        }

        df.rename(columns=rename_mapping, inplace=True)

        # ✅ Debugging: Check if volume column exists
        if "v" not in df.columns:
            print("❌ ERROR: Volume column ('5. volume') was not correctly renamed!")
            print(f"Current columns: {df.columns.tolist()}")  # Print column names for debugging

        print(f"📊 Sample Row After Renaming:\n{df.head(1)}")  # Print one row for validation

        # ✅ Convert data types to float
        try:
            df = df.astype(float)
        except ValueError as e:
            print(f"❌ Data type conversion error: {e}")
            print(f"📌 Current DataFrame:\n{df.head()}")  # Debugging output

        print(f"✅ {ticker} historical data fetched and formatted successfully.")
        return df

    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching Alpha Vantage data for {ticker}: {e}")
        return pd.DataFrame()
# Function to analyze sentiment
def analyze_sentiment(text):
    sentiment = analyzer.polarity_scores(text)
    return sentiment["compound"]
# Initialize sentiment analyzer
analyzer = SentimentIntensityAnalyzer()

def money_flow_index(high, low, close, volume, window=14):
    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    positive_flow = money_flow.where(typical_price > typical_price.shift(1), 0)
    negative_flow = money_flow.where(typical_price < typical_price.shift(1), 0)

    positive_mf = positive_flow.rolling(window=window).sum()
    negative_mf = negative_flow.rolling(window=window).sum()

    mfi = 100 - (100 / (1 + (positive_mf / negative_mf)))
    return mfi
def fetch_sentiment_score_alpha(ticker):
    """Fetch market sentiment score for a given stock ticker using Alpha Vantage API."""
    API_KEY = ALPHA_VANTAGE_API_KEY
    url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={API_KEY}"
    
    logging.info("!!! are tickers here: {ticker}: {e}")

    try:
        response = requests.get(url)
        data = response.json()

        # ✅ Extract sentiment score from Alpha Vantage response
        if "feed" in data and len(data["feed"]) > 0:
            sentiment_scores = [article["overall_sentiment_score"] for article in data["feed"]]
            return np.mean(sentiment_scores) if sentiment_scores else 0
        else:
            return 0  # Default neutral score if no data available
    except Exception as e:
        print(f"❌ ERROR fetching sentiment for {ticker}: {e}")
        return 0  # Default to 0 on failure


def analyze_sentiment(text):
    """
    Extract sentiment score from text (Financial News, Twitter, Reddit).
    """
    sentiment = analyzer.polarity_scores(text)
    return sentiment["compound"]


def detect_breakouts(data, window=20, threshold=1.02):
    """
    Identify breakout trading opportunities based on price action and volume.
    
    - Looks for price breaking above recent highs.
    - Uses volume surge to confirm breakouts.
    
    Params:
    - data (DataFrame): Stock data with OHLC & indicators.
    - window (int): Number of previous candles for resistance.
    - threshold (float): Percentage above resistance for breakout confirmation.

    Returns:
    - DataFrame with "breakout" signals (1 for breakout, 0 otherwise)
    """
    data["prev_high"] = data["high"].rolling(window=window).max().shift(1)
    data["breakout"] = np.where(
        (data["c"] > data["prev_high"] * threshold) & (data["volume"] > data["volume"].rolling(window=5).mean()),
        1, 0
    )

    return data

@app.route('/api/alpha-historical-data', methods=['GET'])
def alpha_historical_data():
    """
    Fetch historical data for a selected stock from Alpha Vantage.
    """
    ticker = request.args.get("ticker")
    interval = request.args.get("interval", "5min")  # Default to 5-minute intervals

    if not ticker:
        return jsonify({"error": "Ticker parameter is missing"}), 400

    print(f"📊 Fetching historical data from Alpha Vantage for: {ticker}")

    # Fetch intraday data from Alpha Vantage
    df = fetch_alpha_historical_data(ticker, interval=interval, output_size="full")

    if df.empty:
        return jsonify({"error": "No historical data found"}), 404

    # Debugging: Check before processing
    print(f"📊 Columns in DataFrame Before Processing: {df.columns.tolist()}")

    # Apply technical indicators
    df, _ = preprocess_data_with_indicators(df)  # Extract only the DataFrame


    # Debugging: Check after processing
    print(f"📊 Columns in DataFrame After Processing: {df.columns.tolist()}")

    # ✅ Fix: Use "volume" instead of "v"
    response_data = {
        "dates": df.index.strftime('%Y-%m-%d %H:%M:%S').tolist(),
        "open": df["o"].tolist(),
        "high": df["h"].tolist(),
        "low": df["l"].tolist(),
        "close": df["c"].tolist(),
        "volume": df["volume"].tolist()  # Fix applied here
    }

    return jsonify(response_data), 200

@app.route('/api/volatility-contraction-breakouts', methods=['GET'])
def volatility_contraction_breakouts():
    try:
        logging.info("Starting volatility contraction breakout scan...")

        universe_limit = int(request.args.get("universe_limit", 300))
        min_price = float(request.args.get("min_price", 0.5))
        max_price = float(request.args.get("max_price", 10.0))
        min_day_volume = float(request.args.get("min_day_volume", 5_000_000))
        min_day_change_pct = float(request.args.get("min_day_change_pct", 8.0))
        min_rvol = float(request.args.get("min_rvol", 2.0))

        candidates = generate_volatility_contraction_breakouts(
            universe_limit=universe_limit,
            min_price=min_price,
            max_price=max_price,
            min_day_volume=min_day_volume,
            min_day_change_pct=min_day_change_pct,
            min_rvol=min_rvol,
        )

        return jsonify({"candidates": candidates}), 200
    except Exception as e:
        logging.error(f"Error in volatility-contraction-breakouts: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# Function to predict the next day using LSTM
def predict_next_day(model, recent_data, scaler, features):
    """
    Predict the next day's value using the LSTM model.
    
    - Ensures correct feature selection
    - Scales the input before passing it to the LSTM
    - Handles missing feature errors gracefully
    """
    try:
        # ✅ Ensure enough data for LSTM
        if len(recent_data) < 50:
            print(f"⚠️ Warning: Only {len(recent_data)} rows available. LSTM requires at least 50.")
            return recent_data["c"].iloc[-1]  # Default to last close price

        # ✅ Ensure required features exist
        missing_features = [f for f in features if f not in recent_data.columns]
        if missing_features:
            print(f"⚠️ Warning: Missing features for LSTM: {missing_features}")
            for feature in missing_features:
                recent_data[feature] = 0  # Default missing features to 0

        # ✅ Extract last 50 rows for LSTM
        recent_data = recent_data[features].values[-50:]

        # ✅ Scale the data
        recent_scaled = scaler.transform(recent_data)

        # ✅ Reshape for LSTM (batch_size=1, time_steps=50, features=len(features))
        reshaped_data = recent_scaled.reshape(1, 50, len(features))

        # ✅ Make LSTM Prediction
        prediction = model.predict(reshaped_data)[0][0]

        return prediction

    except Exception as e:
        print(f"❌ ERROR in predict_next_day: {e}")
        return 0  # Default to 0 in case of failure

# Start legacy Polygon websocket only when explicitly enabled.
if config.ENABLE_LEGACY_POLYGON_WS:
    ensure_websocket_thread_running()

@app.route('/api/candlestick', methods=['GET'])
def candlestick_chart():
    try:
        # ✅ Expect a single ticker, just like before
        ticker = request.args.get('ticker')  
        if not ticker:
            return jsonify({"error": "Ticker parameter is missing"}), 400

        print(f"📌 Fetching candlestick data for ticker: {ticker}")

        # Define date range (last 180 days)
        end_date = datetime.today()
        start_date = end_date - timedelta(days=180)

        # Construct API request URL
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
            f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}?"
            f"adjusted=true&sort=asc&apiKey={POLYGON_API_KEY}"
        )

        # Fetch data from Polygon API
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # If no data available, return an empty response (previous behavior)
        if "results" not in data or not data["results"]:
            print(f"⚠️ Warning: No candlestick data found for ticker {ticker}. Returning empty response.")
            return jsonify({
                "dates": [], "open": [], "high": [], "low": [], "close": []
            }), 200  # Ensures frontend does not break

        # Convert results to DataFrame
        results = pd.DataFrame(data["results"])

        # Ensure required columns exist; if missing, default to empty lists
        return jsonify({
            "dates": results["t"].apply(lambda x: datetime.utcfromtimestamp(x / 1000).strftime('%Y-%m-%d')).tolist() if "t" in results else [],
            "open": results["o"].tolist() if "o" in results else [],
            "high": results["h"].tolist() if "h" in results else [],
            "low": results["l"].tolist() if "l" in results else [],
            "close": results["c"].tolist() if "c" in results else [],
        }), 200

    except requests.exceptions.Timeout:
        print(f"❌ Timeout while fetching data for {ticker}")
        return jsonify({"error": "External API request timed out"}), 504

    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching data for {ticker}: {e}")
        return jsonify({"error": "External API error"}), 500

    except Exception as e:
        print(f"❌ Unexpected error processing ticker {ticker}: {e}")
        return jsonify({"error": "Internal server error"}), 500
def fetch_polygon_candlestick_data(ticker):
    """
    Fetches candlestick data from Polygon API as a fallback.
    """
    try:
        # Define date range (last 180 days)
        end_date = datetime.today()
        start_date = end_date - timedelta(days=180)

        # Construct API request URL
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
            f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}?adjusted=true&sort=asc&apiKey={POLYGON_API_KEY}"
        )

        # Fetch data from Polygon API
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # If no data available, return an empty response
        if "results" not in data or not data["results"]:
            logging.warning(f"⚠️ No candlestick data found for {ticker}. Returning empty response.")
            return jsonify({
                "dates": [], "open": [], "high": [], "low": [], "close": [],
                "entry_point": None, "exit_point": None
            }), 200

        # Convert results to DataFrame
        results = pd.DataFrame(data["results"])

        # Convert timestamps to date strings
        results["date"] = results["t"].apply(lambda x: datetime.utcfromtimestamp(x / 1000).strftime('%Y-%m-%d'))

        # Ensure required columns exist
        required_columns = ["o", "h", "l", "c"]
        for col in required_columns:
            if col not in results:
                results[col] = None  # Handle missing values safely

        # ✅ Generate Buy/Sell Signals
        results = generate_trade_signals(results)

        # ✅ Identify first buy and sell signals
        entry_idx = results[results["buy_signal"] == 1].index.min()
        exit_idx = results[results["sell_signal"] == 1].index.min()

        # ✅ Assign Entry & Exit Price (or None if missing)
        entry_price = results.loc[entry_idx, "c"] if pd.notna(entry_idx) else None
        exit_price = results.loc[exit_idx, "c"] if pd.notna(exit_idx) else None

        # ✅ API Response
        response_data = {
            "dates": results["date"].tolist(),
            "open": results["o"].tolist(),
            "high": results["h"].tolist(),
            "low": results["l"].tolist(),
            "close": results["c"].tolist(),
            "entry_point": entry_price,
            "exit_point": exit_price
        }

        logging.info(f"✅ Polygon API Response for {ticker}: {json.dumps(response_data, indent=2)}")
        return jsonify(response_data), 200

    except Exception as e:
        logging.error(f"❌ Error fetching Polygon data for {ticker}: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch fallback stock data"}), 500
    
def ai_predict(model, filtered_data, scaler):
    """
    AI-powered stock prediction function.
    Uses XGBoost & LSTM for stock selection.
    """
    try:
        logging.debug("🔍 Entering ai_predict function.")

        if filtered_data is None or filtered_data.empty:
            logging.warning("⚠️ No data received for AI prediction!")
            return {"error": "No data received for prediction"}, 404

        logging.info(f"📌 AI Prediction started for {len(filtered_data)} stocks.")
        logging.debug(f"📝 First 5 rows of filtered_data:\n{filtered_data.head()}")

        # ✅ Ensure Model is Valid
        if isinstance(model, tuple):
            logging.error(f"❌ Unexpected tuple returned: {type(model)}")
            model = model[0]

        if not isinstance(model, (tf.keras.Model, tf.keras.Sequential, tf.keras.models.Model)):
            logging.error(f"❌ The model is not a valid Keras model. Type: {type(model)}")
            logging.warning("⚠️ No valid LSTM model available. Using XGBoost predictions only.")
            return {"candidates": filtered_data.to_dict(orient="records")}, 200

        logging.debug(f"✅ Model type before prediction: {type(model)}")

        # ✅ Extract Required Features for LSTM
        lstm_features = list(scaler.feature_names_in_)
        existing_features = [f for f in lstm_features if f in filtered_data.columns]
        missing_features = [f for f in lstm_features if f not in filtered_data.columns]

        logging.debug(f"📝 LSTM features extracted: {lstm_features}")
        logging.debug(f"✅ Existing features in dataset: {existing_features}")
        logging.debug(f"⚠️ Missing features: {missing_features}")

        # ✅ Handle Missing Features
        if missing_features:
            logging.warning(f"⚠️ Missing LSTM features: {missing_features}. Filling with 0.")
            for feature in missing_features:
                filtered_data[feature] = 0  

        # ✅ Normalize Data for LSTM
        logging.debug("🔄 Scaling features for LSTM model...")
        filtered_data[existing_features] = scaler.transform(filtered_data[existing_features])
        logging.debug(f"📝 First 5 rows after scaling:\n{filtered_data[existing_features].head()}")

        # ✅ Ensure Proper Shape for LSTM Input
        stock_seq = filtered_data[existing_features].values.reshape(1, 50, len(existing_features))
        logging.debug(f"📌 LSTM Input Shape: {stock_seq.shape}")

        try:
            prediction = model.predict(stock_seq)[0, 0]
            logging.info(f"✅ LSTM Prediction successful: {prediction}")
        except Exception as e:
            logging.error(f"❌ Error during LSTM prediction: {e}", exc_info=True)
            logging.warning("⚠️ Using XGBoost predictions due to LSTM failure.")
            return {"candidates": filtered_data.to_dict(orient="records")}, 200  

        # ✅ Add LSTM Prediction to DataFrame
        filtered_data["lstm_prediction"] = prediction
        logging.debug(f"📝 LSTM Predictions added to DataFrame:\n{filtered_data[['ticker', 'lstm_prediction']].head()}")

        # ✅ Compute AI Score
        xgb_weight, lstm_weight = 0.6, 0.4
        filtered_data["ai_score"] = (
            (xgb_weight * 1) +  
            (lstm_weight * (filtered_data["lstm_prediction"] / (filtered_data["close"] + 1e-6)))
        )

        logging.debug(f"📌 AI Score calculated. First 5 rows:\n{filtered_data[['ticker', 'ai_score']].head()}")

        # ✅ Select Top Candidates
        top_candidates = filtered_data.sort_values("ai_score", ascending=False).head(20)
        logging.info(f"📌 AI Predictions Completed. Top {len(top_candidates)} candidates selected.")
        logging.debug(f"📝 Top 5 candidates:\n{top_candidates.head()}")

        # ✅ Save the Final Selected Stocks for Charting
        os.makedirs(os.path.dirname(FINAL_AI_CSV_PATH), exist_ok=True)  # Ensure directory exists
        top_candidates.to_csv(FINAL_AI_CSV_PATH, index=False)

        if os.path.exists(FINAL_AI_CSV_PATH):
            logging.info(f"✅ File successfully saved: {FINAL_AI_CSV_PATH}")
        else:
            logging.error("❌ File save failed! The file does not exist after saving.")

        return {"candidates": top_candidates.to_dict(orient="records")}, 200

    except Exception as e:
        logging.error(f"❌ ERROR in ai_predict: {e}", exc_info=True)
        logging.warning("⚠️ AI Prediction failed, returning XGBoost stocks.")
        return {"candidates": filtered_data.to_dict(orient="records")}, 200


@app.route('/api/historical-data', methods=['GET'])
def historical_data():
    """
    Fetch detailed historical data for a selected stock ticker.
    """
    ticker = request.args.get("ticker")
    
    if not ticker:
        return jsonify({"error": "Ticker parameter is missing"}), 400

    print(f"📊 Fetching historical data for: {ticker}")

    # Fetch historical data for the given ticker
    df = fetch_historical_data()

    if df.empty:
        return jsonify({"error": "No historical data found"}), 404

    # Apply technical indicators
    df, _ = preprocess_data_with_indicators(df)  

    # Generate buy/sell signals
    df["buy_signal"] = (df["rsi"] < 30) & (df["macd_diff"] > 0)
    df["sell_signal"] = (df["rsi"] > 70) & (df["macd_diff"] < 0)

    # Prepare response data
    response_data = {
        "dates": df["timestamp"].dt.strftime('%Y-%m-%d').tolist(),
        "open": df["open"].tolist(),
        "high": df["high"].tolist(),
        "low": df["low"].tolist(),
        "close": df["close"].tolist(),
        "volume": df["volume"].tolist(),
        "buy_signals": df[df["buy_signal"]]["close"].tolist(),
        "sell_signals": df[df["sell_signal"]]["close"].tolist()
    }

    return jsonify(response_data), 200

# Caching (TTLCache)
historical_data_cache = TTLCache(maxsize=10, ttl=300)

def fetch_alpha_historical_data(ticker, interval="5min", output_size="full"):
    """
    Fetch historical stock data from Alpha Vantage and ensure data consistency.
    """
    api_key = ALPHA_VANTAGE_API_KEY

    url = (
        f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY"
        f"&symbol={ticker}&interval={interval}&outputsize={output_size}&apikey={api_key}"
    )

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        print(f"📊 Raw API Response Keys: {list(data.keys())}")  # Debugging

        time_series_key = f"Time Series ({interval})"
        if time_series_key not in data:
            print(f"⚠️ No historical data found for {ticker}. Response: {data}")
            return pd.DataFrame()

        records = data[time_series_key]

        # ✅ Convert JSON to DataFrame
        df = pd.DataFrame.from_dict(records, orient="index")
        df.index = pd.to_datetime(df.index)

        print(f"📊 Raw DataFrame Columns Before Renaming: {df.columns.tolist()}")  # Debugging

        # ✅ Rename columns correctly
        rename_mapping = {
            "1. open": "o",
            "2. high": "h",
            "3. low": "l",
            "4. close": "c",
            "5. volume": "volume"
        }

        df.rename(columns=rename_mapping, inplace=True)

        # ✅ Debugging: Check if volume column exists
        if "v" not in df.columns:
            print("❌ ERROR: Volume column ('5. volume') was not correctly renamed!")
            print(f"Current columns: {df.columns.tolist()}")  # Print column names for debugging

        print(f"📊 Sample Row After Renaming:\n{df.head(1)}")  # Print one row for validation

        # ✅ Convert data types to float
        try:
            df = df.astype(float)
        except ValueError as e:
            print(f"❌ Data type conversion error: {e}")
            print(f"📌 Current DataFrame:\n{df.head()}")  # Debugging output

        print(f"✅ {ticker} historical data fetched and formatted successfully.")
        return df

    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching Alpha Vantage data for {ticker}: {e}")
        return pd.DataFrame()
# Function to analyze sentiment
def analyze_sentiment(text):
    sentiment = analyzer.polarity_scores(text)
    return sentiment["compound"]
# Initialize sentiment analyzer
analyzer = SentimentIntensityAnalyzer()

def money_flow_index(high, low, close, volume, window=14):
    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    positive_flow = money_flow.where(typical_price > typical_price.shift(1), 0)
    negative_flow = money_flow.where(typical_price < typical_price.shift(1), 0)

    positive_mf = positive_flow.rolling(window=window).sum()
    negative_mf = negative_flow.rolling(window=window).sum()

    mfi = 100 - (100 / (1 + (positive_mf / negative_mf)))
    return mfi
def fetch_sentiment_score_alpha(ticker):
    """Fetch market sentiment score for a given stock ticker using Alpha Vantage API."""
    API_KEY = ALPHA_VANTAGE_API_KEY
    url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={API_KEY}"

    try:
        response = requests.get(url)
        data = response.json()

        # ✅ Extract sentiment score from Alpha Vantage response
        if "feed" in data and len(data["feed"]) > 0:
            sentiment_scores = [article["overall_sentiment_score"] for article in data["feed"]]
            return np.mean(sentiment_scores) if sentiment_scores else 0
        else:
            return 0  # Default neutral score if no data available
    except Exception as e:
        print(f"❌ ERROR fetching sentiment for {ticker}: {e}")
        return 0  # Default to 0 on failure


def analyze_sentiment(text):
    """
    Extract sentiment score from text (Financial News, Twitter, Reddit).
    """
    sentiment = analyzer.polarity_scores(text)
    return sentiment["compound"]
import numpy as np

def detect_breakouts(data, window=20, threshold=1.02):
    """
    Identify breakout trading opportunities based on price action and volume.
    
    - Looks for price breaking above recent highs.
    - Uses volume surge to confirm breakouts.
    
    Params:
    - data (DataFrame): Stock data with OHLC & indicators.
    - window (int): Number of previous candles for resistance.
    - threshold (float): Percentage above resistance for breakout confirmation.

    Returns:
    - DataFrame with "breakout" signals (1 for breakout, 0 otherwise)
    """
    data["prev_high"] = data["high"].rolling(window=window).max().shift(1)
    data["breakout"] = np.where(
        (data["c"] > data["prev_high"] * threshold) & (data["volume"] > data["volume"].rolling(window=5).mean()),
        1, 0
    )

    return data

def plot_candlestick_chart(data, ticker):
    """
    Plot candlestick chart with AI buy/sell signals.
    """
    try:
        logging.debug(f"📌 DEBUG: Plot function called for {ticker}")
        logging.debug(f"✅ First few rows of data:\n{data.head()}")

        buy_signals = data[data["buy_signal"] == 1]
        sell_signals = data[data["sell_signal"] == 1]

        # ✅ Explicitly create fig & ax
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # ✅ Use returnfig=True to get the figure from mpf.plot
        fig, axlist = mpf.plot(
            data,
            type="candle",
            volume=True,
            returnfig=True
        )

        # ✅ Scatter Buy Signals
        axlist[0].scatter(
            buy_signals.index, buy_signals["c"],
            color="green", label="BUY", marker="^", alpha=1, s=100
        )

        # ✅ Scatter Sell Signals
        axlist[0].scatter(
            sell_signals.index, sell_signals["c"],
            color="red", label="SELL", marker="v", alpha=1, s=100
        )

        # ✅ Ensure the title and legend are added to the correct axis
        axlist[0].set_title(f"{ticker} - AI Trading Signals")
        axlist[0].legend()

        # ✅ Show or Save the Figure
        plt.show()  # OR plt.savefig("chart.png")

    except Exception as e:
        logging.error(f"❌ ERROR in plot_candlestick_chart: {e}", exc_info=True)


def predict_next_day(model, recent_data, scaler, features):
    """
    Predict the next day's value using the LSTM model.
    """
    try:
        if len(recent_data) < 50:
            print(f"⚠️ Warning: Only {len(recent_data)} rows available. LSTM requires at least 50.")
            return recent_data["c"].iloc[-1]  # Default to last close price

        # Ensure required features exist
        missing_features = [f for f in features if f not in recent_data.columns]
        if missing_features:
            print(f"⚠️ Warning: Missing features for LSTM: {missing_features}")
            for feature in missing_features:
                recent_data[feature] = 0  # Default missing features to 0

        # Extract last 50 rows for LSTM
        recent_data = recent_data[features].values[-50:]

        # Scale the data
        recent_scaled = scaler.transform(recent_data)

        # Reshape for LSTM (batch_size=1, time_steps=50, features=len(features))
        reshaped_data = recent_scaled.reshape(1, 50, len(features))

        # Make LSTM Prediction
        prediction = model.predict(reshaped_data)[0][0]

        return prediction

    except Exception as e:
        print(f"❌ ERROR in predict_next_day: {e}")
        return 0  # Default to 0 in case of failure


@app.route('/api/scan-stocks', methods=['GET'])
def scan_stocks():
    try:
        logging.info("📌 Starting scan-stocks process...")

        model_artifacts_available = all(
            path.exists() for path in (TICKER_ENCODER_PATH, XGB_FEATURES_PATH, XGB_MODEL_PATH)
        )
        scanner_unavailable_msg = (
            "Scanner unavailable: live model-backed scan artifacts are missing. "
            "Scan results depend on live data and cannot be shown right now."
        )
        if not model_artifacts_available:
            logging.error(scanner_unavailable_msg)
            return jsonify({"error": scanner_unavailable_msg, "code": "SCAN_UNAVAILABLE"}), 503
        # ✅ Extract filtering parameters
        min_price = float(request.args.get("min_price", 0))
        max_price = float(request.args.get("max_price", float("inf")))
        volume_surge = float(request.args.get("volume_surge", 1.2))
        min_rsi = float(request.args.get("min_rsi", 0))
        max_rsi = float(request.args.get("max_rsi", 100))
        include_news = str(request.args.get("include_news", "false")).strip().lower() in {"1", "true", "yes", "on"}

        logging.info(f"📌 Scan Params: min_price={min_price}, max_price={max_price}, volume_surge={volume_surge}, min_rsi={min_rsi}, max_rsi={max_rsi}")

        # ✅ Fetch and preprocess historical data
        data = fetch_historical_data()
        if data is None or data.empty:
            logging.warning("⚠️ No stock data available!")
            return jsonify({"error": "No stock data available"}), 404

        # ✅ Ensure 'ticker' column exists before encoding
        if "ticker" not in data.columns:
            logging.error("❌ ERROR: 'ticker' column is missing!")
            return jsonify({"error": "'ticker' column missing from data"}), 500

        # ✅ Apply feature engineering
        data, _ = preprocess_data_with_indicators(data)

        # ✅ Sort and reduce to latest row per ticker
        if "timestamp" in data.columns:
            data = data.sort_values(["ticker", "timestamp"])
        else:
            data = data.sort_values(["ticker"])

        data["avg_volume_20"] = data.groupby("ticker")["volume"].transform(lambda x: x.rolling(window=20, min_periods=5).mean())
        data["atr_pct"] = (data.get("atr", 0) / data["close"]).replace([np.inf, -np.inf], 0) * 100
        latest_rows = data.groupby("ticker").tail(1).copy()

        # ✅ Encode tickers for model (handle unseen tickers gracefully)
        try:
            ticker_encoder = joblib.load(TICKER_ENCODER_PATH)
            try:
                latest_rows["ticker_encoded"] = ticker_encoder.transform(latest_rows["ticker"].astype(str))
            except ValueError:
                known = set(ticker_encoder.classes_.tolist())
                new_tickers = [t for t in latest_rows["ticker"].astype(str) if t not in known]
                if new_tickers:
                    updated_classes = np.concatenate([ticker_encoder.classes_, np.array(new_tickers)])
                    ticker_encoder.classes_ = updated_classes
                latest_rows["ticker_encoded"] = ticker_encoder.transform(latest_rows["ticker"].astype(str))
        except Exception as enc_err:
            logging.error(f"Scanner unavailable because ticker encoding failed: {enc_err}")
            return jsonify({"error": scanner_unavailable_msg, "code": "SCAN_UNAVAILABLE"}), 503
        trained_features = joblib.load(XGB_FEATURES_PATH)
        missing_features = [feature for feature in trained_features if feature not in latest_rows.columns]
        if missing_features:
            logging.error(f"Scanner unavailable because model features are missing: {missing_features}")
            return jsonify({"error": scanner_unavailable_msg, "code": "SCAN_UNAVAILABLE"}), 503
        else:
            logging.info(f"📌 Features in dataset before filtering: {latest_rows.columns.tolist()}")
        # ✅ Apply filtering conditions (liquidity, momentum, risk)
        def apply_filters(df, vol_min, atr_low, atr_high):
            return df[
                (df["close"] >= min_price) & 
                (df["close"] <= max_price) &
                (df["volume_surge"] > volume_surge) &
                (df["rsi"] >= min_rsi) & 
                (df["rsi"] <= max_rsi) &
                (df["avg_volume_20"] > vol_min) &
                (df["atr_pct"].between(atr_low, atr_high))
            ]

        filtered_data = apply_filters(latest_rows, vol_min=200000, atr_low=1, atr_high=15)

        if filtered_data.empty:
            logging.warning("⚠️ No stocks left after filtering! Relaxing liquidity/ATR filters.")
            filtered_data = apply_filters(latest_rows, vol_min=100000, atr_low=0.5, atr_high=25)

        if filtered_data.empty:
            logging.warning("⚠️ Still empty after relaxed filters! Returning top liquid tickers by volume/ATR bounds.")
            fallback = latest_rows[
                (latest_rows["close"] >= min_price) &
                (latest_rows["close"] <= max_price)
            ].sort_values("avg_volume_20", ascending=False).head(20)

            if fallback.empty:
                logging.warning("⚠️ Fallback also empty. Returning empty list.")
                return jsonify({"candidates": []}), 200
            filtered_data = fallback

        # ✅ Load XGBoost Model
        xgb_model = joblib.load(XGB_MODEL_PATH)

        # ✅ Ensure correct feature order for prediction
        try:
            xgb_input = filtered_data[trained_features]
        except KeyError as e:
            logging.error(f"Scanner unavailable because XGBoost input is invalid: {e}")
            return jsonify({"error": scanner_unavailable_msg, "code": "SCAN_UNAVAILABLE"}), 503

        # ✅ Predict using XGBoost
        if hasattr(xgb_model, "predict_proba"):
            proba = xgb_model.predict_proba(xgb_input)[:, 1]
        else:
            proba = None
        xgb_predictions = xgb_model.predict(xgb_input)

        # ✅ Filter selected stocks
        xgb_filtered_data = filtered_data.loc[xgb_predictions == 1].copy()
        if proba is not None:
            xgb_filtered_data["model_score"] = proba[xgb_predictions == 1]
        logging.info(f"📌 Stocks selected after XGBoost: {len(xgb_filtered_data)}")
        # ✅ Restore 'T' column before AI
        xgb_filtered_data["T"] = xgb_filtered_data["ticker"]

        # ✅ Ensure LSTM Gets Data
        if xgb_filtered_data.empty:
            logging.warning("⚠️ No stocks available for LSTM!")
            return jsonify({"candidates": []}), 200

        # ✅ Generate entry/stop/target (simple target)
        xgb_filtered_data["entry_point"] = xgb_filtered_data["open"].astype(float).round(4)
        xgb_filtered_data["stop_loss"] = (xgb_filtered_data["entry_point"] * 0.97).round(4)
        xgb_filtered_data["target_price"] = (xgb_filtered_data["entry_point"] * 1.05).round(4)

        # ✅ Rank candidates
        xgb_filtered_data["rank_score"] = (
            (xgb_filtered_data.get("model_score", 0.6)) * 0.4 +
            xgb_filtered_data["volume_surge"].clip(0, 5) * 0.2 +
            (1 / xgb_filtered_data["atr_pct"].clip(lower=0.5, upper=20)) * 0.2 +
            (xgb_filtered_data["price_change"].clip(-0.1, 0.1) + 0.1) * 0.2
        )

        final_df = xgb_filtered_data.sort_values("rank_score", ascending=False)
        if include_news:
            final_df["news"] = final_df["T"].apply(fetch_ticker_news)

        # ✅ Clean up for JSON serialization
        final_df = final_df.replace([np.inf, -np.inf], np.nan).fillna(0)
        if "timestamp" in final_df.columns:
            final_df["timestamp"] = final_df["timestamp"].astype(str)

        # ✅ Debug payload fields for N/A issues
        debug_cols = ["ticker", "close", "volume", "rsi", "volatility", "price_change"]
        missing_cols = [c for c in debug_cols if c not in final_df.columns]
        logging.info(f"📌 MISSING COLS (final_df): {missing_cols}")
        if not missing_cols and not final_df.empty:
            logging.info("📌 NaN counts (final_df): %s", final_df[debug_cols].isna().sum().to_dict())

        sample = final_df.iloc[0].to_dict() if not final_df.empty else None
        logging.info("📌 RESULT SAMPLE KEYS: %s", list(sample.keys()) if sample else "NO RESULTS")
        logging.info("📌 RESULT SAMPLE: %s", json.dumps(sample, indent=2) if sample else "NO RESULTS")

        cgc_row = None
        if not final_df.empty and "ticker" in final_df.columns:
            cgc_row = final_df.loc[final_df["ticker"] == "CGC"]
            if not cgc_row.empty:
                logging.info("📌 CGC PAYLOAD: %s", json.dumps(cgc_row.iloc[0].to_dict(), indent=2))
            else:
                logging.info("📌 CGC PAYLOAD: CGC NOT FOUND")

        logging.info(f"📌 Returning {len(final_df)} final stock candidates to frontend.")
        return jsonify({"candidates": final_df.to_dict(orient="records")}), 200

    except Exception as e:
        logging.error(f"❌ ERROR in scan-stocks: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/three-day-breakouts', methods=['GET'])
def three_day_breakouts():
    try:
        logging.info("📌 Starting three-day breakouts scan...")

        universe_limit = int(request.args.get("universe_limit", 150))
        min_price = float(request.args.get("min_price", 3.0))
        min_dollar_vol = float(request.args.get("min_dollar_vol", 10_000_000))

        candidates = generate_three_day_breakouts(
            universe_limit=universe_limit,
            min_price=min_price,
            min_dollar_vol=min_dollar_vol,
        )

        if not candidates:
            logging.info("📌 No candidates on strict pass; retrying with relaxed thresholds.")
            candidates = generate_three_day_breakouts(
                universe_limit=max(universe_limit, 300),
                min_price=max(1.0, min_price - 1.0),
                min_dollar_vol=max(5_000_000, min_dollar_vol // 2),
                relaxed=True,
            )

        if not candidates:
            return jsonify({"candidates": []}), 200

        logging.info(f"📌 Returning {len(candidates)} three-day breakout candidates.")
        return jsonify({"candidates": candidates}), 200
    except Exception as e:
        logging.error(f"❌ ERROR in three-day-breakouts: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
# Function to predict the next day using LSTM
def predict_next_day(model, recent_data, scaler, features):
    """
    Predict the next day's value using the LSTM model.
    
    - Ensures correct feature selection
    - Scales the input before passing it to the LSTM
    - Handles missing feature errors gracefully
    """
    try:
        # ✅ Ensure enough data for LSTM
        if len(recent_data) < 50:
            print(f"⚠️ Warning: Only {len(recent_data)} rows available. LSTM requires at least 50.")
            return recent_data["c"].iloc[-1]  # Default to last close price

        # ✅ Ensure required features exist
        missing_features = [f for f in features if f not in recent_data.columns]
        if missing_features:
            print(f"⚠️ Warning: Missing features for LSTM: {missing_features}")
            for feature in missing_features:
                recent_data[feature] = 0  # Default missing features to 0

        # ✅ Extract last 50 rows for LSTM
        recent_data = recent_data[features].values[-50:]

        # ✅ Scale the data
        recent_scaled = scaler.transform(recent_data)

        # ✅ Reshape for LSTM (batch_size=1, time_steps=50, features=len(features))
        reshaped_data = recent_scaled.reshape(1, 50, len(features))

        # ✅ Make LSTM Prediction
        prediction = model.predict(reshaped_data)[0][0]

        return prediction

    except Exception as e:
        print(f"❌ ERROR in predict_next_day: {e}")
        return 0  # Default to 0 in case of failure
    
@app.route('/api/number-one-picks', methods=['GET'])
def number_one_picks():
    try:
        logging.info("🚀 Running Number One Picks Strategy...")
        logging.info("📡 Backend hit: /api/number-one-picks")

        # Fetch base historical data
        df = fetch_historical_data()
        if df.empty:
            return jsonify({"error": "No data found"}), 404

        # Add indicators (includes atr, rsi, macd, etc.)
        df, _ = preprocess_data_with_indicators(df)

        # Ensure ATR exists
        if "atr" not in df.columns:
            try:
                df["atr"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14, fillna=True).average_true_range()
            except Exception as atr_err:
                logging.warning(f"⚠️ Unable to compute ATR: {atr_err}")
                df["atr"] = 0.0

        # Filter Step 1: price bounds (default: 1 to 200)
        min_price = float(request.args.get("min_price", 1))
        max_price = float(request.args.get("max_price", 200))
        df = df[(df["close"] >= min_price) & (df["close"] <= max_price)]

        # Liquidity: use volume directly (since historical depth may be limited)
        df = df.sort_values(["ticker", "timestamp"]) if "timestamp" in df.columns else df.sort_values("ticker")
        df["avg_volume_20"] = df.groupby("ticker")["volume"].transform(lambda x: x.rolling(window=20, min_periods=1).mean())
        df["avg_volume_20"] = df["avg_volume_20"].fillna(df["volume"])
        df = df[df["avg_volume_20"] > 100_000]

        # ATR%
        df["atr_pct"] = (df["atr"] / df["close"]).replace([np.inf, -np.inf], 0) * 100
        df = df[df["atr_pct"].between(0.5, 25)]

        # Float filter if available
        if "float" in df.columns:
            df = df[df["float"] < 150_000_000]  # relaxed float if present
        else:
            logging.warning("⚠️ 'float' column missing, skipping float filter!")

        if df.empty:
            return jsonify({"error": "No stocks meet float criteria"}), 200

        # Calculate MACD & Signal Lines
        df["macd"], df["signal"], df["macd_hist"] = compute_macd(df["close"])
        df["macd_valid"] = (df["macd"] > df["signal"]) & (df["macd"] > 0)

        # Volume surge vs 10 (fallback to 1 if insufficient history)
        df["volume_surge10"] = df["volume"] / df["volume"].rolling(window=10, min_periods=1).mean()
        df["volume_surge10"] = df["volume_surge10"].fillna(1)

        # MACD histogram rising (recent 2 bars if available)
        df["macd_hist_rising"] = df["macd_hist"].diff() > 0
        df["macd_hist_streak"] = df["macd_hist_rising"].rolling(window=2, min_periods=1).apply(lambda x: all(x), raw=True)

        # Candle pattern: last green
        df["is_green"] = df["close"] > df["open"]

        # Valid trade with relaxed requirements (designed for limited history)
        df["valid_trade"] = (
            df["macd_valid"] &
            (df["macd_hist_streak"] == 1.0) &
            df["is_green"] &
            (df["volume_surge10"] > 1.1) &
            df["atr_pct"].between(0.5, 25) &
            df["rsi"].between(40, 70)
        )

        selected = df[df["valid_trade"]].copy()

        if selected.empty:
            logging.info("⚠️ No valid trades found after all filters! Returning top liquid names.")
            fallback = df.sort_values("avg_volume_20", ascending=False).head(10).copy()
            fallback["entry_point"] = fallback["close"].astype(float).round(4)
            fallback["stop_loss"] = (fallback["close"] - fallback["atr"] * 1.0).round(4)
            fallback["target_price"] = (fallback["close"] + fallback["atr"] * 2.0).round(4)
            fallback["rank_score"] = 0.0
            fallback["T"] = fallback["ticker"]
            fallback = fallback.replace([np.inf, -np.inf], np.nan).fillna(0)
            if "timestamp" in fallback.columns:
                fallback["timestamp"] = fallback["timestamp"].astype(str)
            return jsonify({"candidates": fallback.to_dict(orient="records")}), 200

        # Refresh with live OHLC if available
        live_df = fetch_ohlcv_batch(selected["ticker"].unique().tolist(), days=5)
        if not live_df.empty:
            live_last = (
                live_df.sort_values("t")
                .groupby("ticker")
                .tail(1)
                .rename(columns={"close": "live_close", "high": "live_high", "low": "live_low"})
            )
            selected = selected.merge(live_last[["ticker", "live_close", "live_high", "live_low"]], on="ticker", how="left")

        # Entry/stop/target using ATR (prefer live close/high/low when present)
        price_for_entry = selected["live_close"].fillna(selected["close"]).astype(float)
        high_for_target = selected["live_high"].fillna(selected["high"]).astype(float)
        low_for_stop = selected["live_low"].fillna(selected["low"]).astype(float)

        selected["entry_point"] = price_for_entry.round(4)
        selected["stop_loss"] = (price_for_entry - selected["atr"] * 1.0).round(4)
        selected["target_price"] = (
            np.maximum(high_for_target, price_for_entry * (1 + np.maximum(0.02, (selected["atr_pct"] / 100) * 2.5)))
        ).round(4)

        # Rank by composite
        selected["rank_score"] = (
            selected["macd_hist"].clip(lower=-1, upper=1) * 0.3 +
            selected["volume_surge10"].clip(0, 5) * 0.2 +
            (1 / selected["atr_pct"].clip(lower=0.5, upper=20)) * 0.2 +
            selected["rsi"].clip(30, 70) / 100 * 0.1 +
            selected["price_change"].clip(-0.1, 0.1) * 0.2
        )

        selected = selected.sort_values("rank_score", ascending=False).head(10)

        # Restore Ticker column for frontend charting
        selected["T"] = selected["ticker"]

        selected = selected.replace([np.inf, -np.inf], np.nan).fillna(0)
        if "timestamp" in selected.columns:
            selected["timestamp"] = selected["timestamp"].astype(str)

        return jsonify({
            "candidates": selected.to_dict(orient="records")
        }), 200

    except Exception as e:
        logging.error(f"❌ Error in /api/number-one-picks: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# API to predict using LSTM
@app.route('/api/lstm-predict', methods=['GET'])
def lstm_predict():
    try:
        ticker = request.args.get('ticker')
        if not ticker:
            return jsonify({"error": "Ticker parameter is missing"}), 400

        # Get latest price from WebSocket updates
        price = latest_stock_prices.get(ticker.upper(), None)
        if price is None:
            return jsonify({"error": "No live data available yet for this ticker"}), 404

        # Ensure LSTM model and scaler are loaded
        if not lstm_cache["model"] or not lstm_cache["scaler"]:
            raise ValueError("LSTM model is not initialized. Please initialize the model via the scan-stocks route.")

        # Fetch historical data
        df = fetch_alpha_historical_data(ticker)

        if df.empty:
            return jsonify({"error": "No historical data available"}), 404

        # Preprocess data (Ensure alignment with Trading Charts)
        df, _ = preprocess_data_with_indicators(df)  # Extract only the DataFrame


        # Extract relevant features
        features = ["price_change", "volatility", "volume", "rsi", "macd_line", "macd_signal", "ema_12", "ema_26", "vwap"]
        X = df[features]

        # **LSTM Prediction: Using Last 50 Time Steps**
        recent_data = X.values[-50:].reshape(1, 50, len(features))
        prediction = lstm_cache["model"].predict(recent_data)[0][0]

        return jsonify({"ticker": ticker, "next_day_prediction": prediction}), 200
    except Exception as e:
        print(f"❌ Error in lstm-predict endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/ticker-news", methods=["GET"])
def ticker_news():
    tickers = request.args.get("ticker")  # Expect comma-separated tickers
    if not tickers:
        logging.warning("⚠️ No ticker provided in request.")
        return jsonify({"error": "Ticker is required"}), 400

    ticker_list = tickers.split(",")  # Split tickers into a list
    logging.info(f"📌 Fetching news for tickers: {ticker_list}")

    all_news = {}

    for ticker in ticker_list:
        url = f"https://api.polygon.io/v2/reference/news?ticker={ticker}&limit=5&apiKey={POLYGON_API_KEY}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            all_news[ticker] = response.json().get("results", [])
        except requests.exceptions.HTTPError as e:
            logging.error(f"❌ Error fetching news for {ticker}: {str(e)}")
            all_news[ticker] = {"error": f"Error fetching news for {ticker}: {str(e)}"}
        except Exception as e:
            logging.error(f"❌ Unexpected error fetching news for {ticker}: {str(e)}")
            all_news[ticker] = {"error": f"Unexpected error: {str(e)}"}

    #logging.info(f"📌 News response: {all_news}")  # ✅ Log full response
    return jsonify(all_news)  # Return news grouped by ticker

@app.route('/api/sentiment-plot', methods=['GET'])
def sentiment_plot():
    """
    API endpoint to fetch sentiment trends and reasoning for a ticker within a date range.
    """
    try:
        ticker = request.args.get("ticker")
        start_date = request.args.get("start_date", (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d"))
        end_date = request.args.get("end_date", datetime.today().strftime("%Y-%m-%d"))

        if not ticker:
            return jsonify({"error": "Ticker parameter is missing"}), 400

        # Fetch sentiment data
        sentiment_data = fetch_sentiment_trend(ticker, start_date, end_date)

        if sentiment_data.empty:
            return jsonify({"error": "No sentiment data available for this ticker"}), 404

        # Optional: Extract reasoning from insights
        sentiment_reasons = []
        for day in sentiment_data.itertuples():
            daily_reason = {
                "date": day.date,
                "reasons": []
            }
            # Add sentiment reasoning if available
            for insight in getattr(day, 'insights', []):
                daily_reason["reasons"].append({
                    "sentiment": insight.sentiment,
                    "reasoning": insight.sentiment_reasoning,
                })
            sentiment_reasons.append(daily_reason)

        return jsonify({
            "dates": sentiment_data['date'].tolist(),
            "positive": sentiment_data['positive'].tolist(),
            "negative": sentiment_data['negative'].tolist(),
            "neutral": sentiment_data['neutral'].tolist(),
            "sentiment_reasons": sentiment_reasons,
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

# ✅ Define Correct Model Paths
MODELS_DIR = config.MODELS_DIR
XGB_MODEL_PATH = config.XGB_MODEL_PATH
XGB_FEATURES_PATH = config.XGB_FEATURES_PATH

def check_and_train_model():
    """
    Check if the model exists, if not, trigger training automatically.
    """
    if not os.path.exists(XGB_MODEL_PATH) or not os.path.exists(XGB_FEATURES_PATH):
        logging.info("⚠️ XGBoost Model or Feature List Not Found! Training Now...")
        train_xgboost_with_optuna()
    else:
        logging.info("✅ XGBoost Model Found. No Need to Retrain.")

# ✅ Define Paths
LSTM_SCALER_PATH = config.SCALER_PATH

def ai_predict(model, filtered_data, scaler):
    """
    AI-powered stock prediction function.
    Uses XGBoost & LSTM for stock selection.
    Falls back to XGBoost if LSTM fails.
    """
    try:
        if filtered_data is None or filtered_data.empty:
            logging.warning("⚠️ No data received for AI prediction!")
            return jsonify({"error": "No data received for prediction"}), 404

        logging.info(f"📌 AI Prediction started for {len(filtered_data)} stocks.")

        # ✅ Validate Model Before Using It
        if isinstance(model, tuple):
            logging.error(f"❌ Unexpected tuple returned: {type(model)}")
            model = model[0]

        logging.info(f"🔍 Model type before prediction: {type(model)}")

        if not isinstance(model, (tf.keras.Model, tf.keras.Sequential, tf.keras.models.Model)):
            logging.error(f"❌ The model is not a valid Keras model. Type: {type(model)}")
            logging.warning("⚠️ No valid LSTM model available. Using XGBoost predictions only.")
            return jsonify({"candidates": filtered_data.to_dict(orient="records")}), 200

        logging.info("✅ Model is valid. Proceeding with LSTM prediction.")

        # ✅ Extract Required Features for LSTM
        lstm_features = list(scaler.feature_names_in_)
        existing_features = [f for f in lstm_features if f in filtered_data.columns]
        missing_features = [f for f in lstm_features if f not in filtered_data.columns]

        # ✅ Handle Missing Features
        if missing_features:
            logging.warning(f"⚠️ Missing LSTM features: {missing_features}. Filling with 0.")
            for feature in missing_features:
                filtered_data[feature] = 0  

        # ✅ Normalize Data for LSTM
        logging.info(f"🔄 Scaling {len(existing_features)} features for LSTM model...")
        filtered_data[existing_features] = scaler.transform(filtered_data[existing_features])

        # ✅ Apply LSTM Predictions Per Stock
        predictions = []
        for ticker in filtered_data["ticker"].unique():
            stock_data = filtered_data[filtered_data["ticker"] == ticker]
            stock_seq = stock_data[existing_features].values

            # 🔍 Log Input Data for Each Stock
            logging.info(f"📊 Processing {ticker} | Close: {stock_data['close'].values[0]} | Input Shape: {stock_seq.shape}")

            # ✅ Ensure Correct Shape for LSTM Input
            time_steps = 50
            num_features = len(existing_features)

            if len(stock_seq) < time_steps:
                logging.warning(f"⚠️ {ticker} has only {len(stock_seq)} rows. Padding to 50.")
                padding = np.zeros((time_steps - len(stock_seq), num_features))
                stock_seq = np.vstack([padding, stock_seq])
            else:
                stock_seq = stock_seq[-time_steps:]

            # ✅ Reshape for LSTM Input
            stock_seq = stock_seq.reshape(1, time_steps, num_features)
            logging.info(f"✅ Reshaped input for {ticker}: {stock_seq.shape}")

            # ✅ Make LSTM Prediction
            try:
                prediction = model.predict(stock_seq)[0, 0]
                logging.info(f"✅ LSTM Prediction for {ticker}: {prediction}")
            except Exception as e:
                logging.error(f"❌ Error predicting {ticker}: {e}", exc_info=True)
                prediction = np.nan  

            predictions.append({"ticker": ticker, "lstm_prediction": prediction})

        # ✅ Store Predictions in DataFrame
        pred_df = pd.DataFrame(predictions)
        filtered_data = filtered_data.merge(pred_df, on="ticker", how="left")

        # ✅ Compute AI Score
        xgb_weight, lstm_weight = 0.6, 0.4
        filtered_data["ai_score"] = (
            (xgb_weight * 1) +  
            (lstm_weight * (filtered_data["lstm_prediction"] / (filtered_data["close"] + 1e-6)))
        )

        # ✅ Select Top Candidates
        top_candidates = filtered_data.sort_values("ai_score", ascending=False).head(20)

        logging.info(f"📌 AI Predictions Completed. Top {len(top_candidates)} candidates selected.")

        # ✅ Save the Final Selected Stocks for Charting
        try:
            os.makedirs(os.path.dirname(FINAL_AI_CSV_PATH), exist_ok=True)
            top_candidates.to_csv(FINAL_AI_CSV_PATH, index=False)
            
            # ✅ Confirm File Creation
            if os.path.exists(FINAL_AI_CSV_PATH):
                logging.info(f"✅ File successfully saved: {FINAL_AI_CSV_PATH}")
            else:
                logging.error(f"❌ File save operation completed, but file not found at {FINAL_AI_CSV_PATH}")

        except Exception as e:
            logging.error(f"❌ Error while saving AI predictions CSV: {e}", exc_info=True)

        # ✅ Fetch Candlestick Data with Exception Handling
        try:
            tickers_list = top_candidates["T"].tolist()
            logging.info(f"📌 Fetching candlestick data for AI-selected tickers: {tickers_list}")
            candlestick_response, status_code = fetch_candlestick_data(tickers_list)

            if status_code == 200 and isinstance(candlestick_response, dict):
                logging.info("✅ Successfully fetched candlestick data.")

                # ✅ Inject AI-based Entry/Exit Points
                for ticker in tickers_list:
                    if ticker in candlestick_response:
                        candlestick_response[ticker]["entry_point"] = (
                            top_candidates[top_candidates["T"] == ticker]["close"] * 0.95
                        ).values[0]
                        candlestick_response[ticker]["exit_point"] = (
                            top_candidates[top_candidates["T"] == ticker]["close"] * 1.1
                        ).values[0]

                logging.info(f"✅ Returning AI predictions with candlestick data.")
                return jsonify({"candidates": top_candidates.to_dict(orient="records"),
                                "candlestick_data": candlestick_response}), 200

            logging.warning(f"⚠️ Candlestick data fetch returned status: {status_code}")

        except Exception as e:
            logging.error(f"❌ ERROR while fetching candlestick data: {e}", exc_info=True)

        return jsonify({"candidates": top_candidates.to_dict(orient="records")}), 200

    except Exception as e:
        logging.error(f"❌ ERROR in ai_predict: {e}", exc_info=True)
        logging.warning("⚠️ AI Prediction failed, returning XGBoost stocks.")
        return jsonify({"candidates": filtered_data.to_dict(orient="records")}), 200

@app.route("/api/train-lstm", methods=["POST"])
def train_lstm():
    """
    API endpoint to train the LSTM model.
    """
    try:
        model, scaler = train_and_cache_lstm_model()

        if model and scaler:
            return jsonify({"message": "✅ LSTM model trained and saved successfully!"}), 200
        else:
            return jsonify({"error": "❌ LSTM training failed."}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/train-xgb-optuna', methods=['POST'])
def train_xgb_endpoint():
    """
    API endpoint to trigger XGBoost model training.
    """
    try:
        logging.info("📌 Starting XGBoost Training via API...")

        # ✅ Load training data
        X_train, y_train = load_training_data()  # Ensure function exists in the imported module

        if X_train is None or y_train is None:
            logging.error("❌ ERROR: Training data is missing or empty!")
            return jsonify({"error": "Training data could not be loaded"}), 500

        logging.info(f"✅ Loaded Training Data: {len(X_train)} samples")

        # ✅ Train the model using Optuna
        best_model, best_params = tune_xgboost_hyperparameters(X_train, y_train)

        if not best_model or not best_params:
            logging.error("❌ ERROR: XGBoost training failed!")
            return jsonify({"error": "XGBoost model training failed"}), 500

        # ✅ Save the trained model
        joblib.dump(best_model, XGB_MODEL_PATH)
        joblib.dump(list(X_train.columns), XGB_FEATURES_PATH)
        logging.info(f"✅ XGBoost Model saved at: {XGB_MODEL_PATH}")

        return jsonify({
            "message": "✅ XGBoost model trained successfully!",
            "best_params": best_params
        }), 200

    except Exception as e:
        logging.error(f"❌ ERROR in train-xgb API: {e}")
        return jsonify({"error": str(e)}), 500
@app.route('/api/stock-data', methods=['GET'])
def get_stock_data():
    """
    Fetch stock data for a given ticker.
    """
    try:
        # ✅ Validate ticker input
        ticker = request.args.get('ticker')
        if not ticker:
            return jsonify({"error": "Ticker parameter is missing"}), 400

        print(f"📌 Fetching stock data for ticker: {ticker}")

        # ✅ Define date range (last 180 days)
        end_date = datetime.today()
        start_date = end_date - timedelta(days=180)

        # ✅ Construct API request URL
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
            f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}?"
            f"adjusted=true&sort=asc&apiKey={POLYGON_API_KEY}"
        )

        # ✅ Fetch data from Polygon API
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # ✅ Handle missing data
        if "results" not in data or not data["results"]:
            print(f"⚠️ Warning: No stock data found for {ticker}. Returning empty response.")
            return jsonify({
                "dates": [], "open": [], "high": [], "low": [], "close": [], "volume": []
            }), 200  # Ensure frontend doesn't break

        # ✅ Convert results to DataFrame
        results = pd.DataFrame(data["results"])

        # ✅ Ensure required columns exist; if missing, default to empty lists
        return jsonify({
            "dates": results["t"].apply(lambda x: datetime.utcfromtimestamp(x / 1000).strftime('%Y-%m-%d')).tolist() if "t" in results else [],
            "open": results["o"].tolist() if "o" in results else [],
            "high": results["h"].tolist() if "h" in results else [],
            "low": results["l"].tolist() if "l" in results else [],
            "close": results["c"].tolist() if "c" in results else [],
            "volume": results["v"].tolist() if "v" in results else [],
        }), 200

    except requests.exceptions.Timeout:
        print(f"❌ Timeout while fetching data for {ticker}")
        return jsonify({"error": "External API request timed out"}), 504

    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching data for {ticker}: {e}")
        return jsonify({"error": "External API error"}), 500

    except Exception as e:
        print(f"❌ Unexpected error processing ticker {ticker}: {e}")
        return jsonify({"error": "Internal server error"}), 500
    
@app.route('/api/anomalies', methods=['GET'])
def find_anomalies():
    try:
        import pickle
        from datetime import datetime

        logging.info("🚀 Running Anomaly Detection...")

        # Load the lookup table
        if not os.path.exists('lookup_table.pkl'):
            logging.error("❌ lookup_table.pkl not found.")
            return jsonify({"candidates": [], "error": "lookup_table missing"}), 200
        with open('lookup_table.pkl', 'rb') as f:
            lookup_table = pickle.load(f)

        # Read parameters
        target_date = request.args.get('date', datetime.today().strftime('%Y-%m-%d'))
        threshold_multiplier = float(request.args.get('threshold_multiplier', 3))
        max_results = int(request.args.get('limit', 20))
        min_price = float(request.args.get("min_price", 1))
        max_price = float(request.args.get("max_price", 200))
        min_volume = float(request.args.get("min_volume", 100000))

        anomalies = []

        # Validate structure: expect ticker -> {date: {...}}
        structure_valid = True
        for k, v in lookup_table.items():
            if not isinstance(v, dict):
                structure_valid = False
                break
        if not structure_valid:
            logging.error("❌ lookup_table format invalid. Expected dict of dicts (ticker -> date -> data).")
            return jsonify({"candidates": [], "error": "lookup_table format invalid"}), 200

        available_dates = set()
        for _, date_data in lookup_table.items():
            available_dates.update(date_data.keys())

        if target_date not in available_dates:
            if available_dates:
                target_date = sorted(available_dates)[-1]
                logging.info(f"⚠️ Requested date missing. Falling back to latest date: {target_date}")
            else:
                return jsonify({"candidates": [], "error": "No anomaly data available"}), 200

        for ticker, date_data in lookup_table.items():
            if target_date in date_data and isinstance(date_data, dict):
                data = date_data[target_date]
                trades = data.get('trades')
                avg_trades = data.get('avg_trades')
                std_trades = data.get('std_trades')
                close_price = data.get('close_price')
                volume = data.get('volume') or data.get('trades')

                if close_price is not None and (close_price < min_price or close_price > max_price):
                    continue
                if volume is not None and volume < min_volume:
                    continue

                if avg_trades is not None and std_trades is not None and std_trades > 0:
                    z_score = (trades - avg_trades) / std_trades
                    if z_score > threshold_multiplier:
                        vol_surge = trades / avg_trades if avg_trades else None
                        anomalies.append({
                            "ticker": ticker,
                            "date": target_date,
                            "trades": trades,
                            "avg_trades": avg_trades,
                            "std_trades": std_trades,
                            "z_score": round(z_score, 2),
                            "close_price": close_price,
                            "price_diff": data.get('price_diff'),
                            "volume_surge": round(vol_surge, 2) if vol_surge is not None else None
                        })

        anomalies.sort(key=lambda x: (x.get('z_score', 0), x.get('volume_surge') or 0), reverse=True)
        anomalies = anomalies[:max_results]

        logging.info(f"✅ Found {len(anomalies)} anomalies for {target_date} with threshold {threshold_multiplier}")

        return jsonify({"candidates": anomalies, "date_used": target_date, "available_dates": sorted(list(available_dates))}), 200

    except Exception as e:
        logging.error(f"❌ Error in /api/anomalies: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# Massively aggregated options data using Custom Bars (OHLC)
@app.route("/api/options-strategies", methods=["GET"])
def options_strategies():
    ticker = request.args.get("ticker", "AAPL").upper()
    underlying = float(request.args.get("underlying", 180))
    limit = min(int(request.args.get("limit", 25)), 50)

    fallback_strategies = [
        {
            "ticker": ticker,
            "type": "covered_call",
            "strike": round(underlying * 1.05, 2),
            "expiry": "2025-01-17",
            "premium": round(underlying * 0.01, 2),
            "roi": round(1.0, 2),
            "breakeven": round(underlying - underlying * 0.01, 2),
        },
        {
            "ticker": ticker,
            "type": "cash_secured_put",
            "strike": round(underlying * 0.9, 2),
            "expiry": "2025-01-17",
            "premium": round(underlying * 0.008, 2),
            "roi": round(0.8, 2),
            "breakeven": round(underlying * 0.9 - underlying * 0.008, 2),
        },
        {
            "ticker": ticker,
            "type": "debit_call_spread",
            "lower_strike": round(underlying * 0.98, 2),
            "upper_strike": round(underlying * 1.02, 2),
            "expiry": "2025-01-17",
            "cost": round(underlying * 0.01, 2),
            "max_profit": round((underlying * 1.02 - underlying * 0.98) - underlying * 0.01, 2),
            "rr": round(((underlying * 1.02 - underlying * 0.98) - underlying * 0.01) / (underlying * 0.01), 2),
        },
    ]

    try:
        rows = fetch_option_chain_for_ticker(ticker, limit=max(limit * 5, 60), max_pages=2)
        if not rows:
            logging.warning("No option chain rows returned for %s; falling back to sample strategies.", ticker)
            return jsonify({"strategies": fallback_strategies, "underlying": underlying}), 200

        def _row_sort_key(row):
            open_interest = float(row.get("open_interest") or row.get("oi") or 0)
            volume = float(row.get("volume") or 0)
            bid = float(row.get("bid") or 0)
            ask = float(row.get("ask") or 0)
            return (open_interest + (volume * 2.0), bid + ask)

        strategies = [
            {
                "ticker": ticker,
                "option_ticker": row.get("option_ticker") or "",
                "type": row.get("type", "call"),
                "strike": round(float(row.get("strike") or 0), 2),
                "expiry": row.get("expiry"),
                "bid": round(float(row.get("bid") or 0), 2),
                "ask": round(float(row.get("ask") or 0), 2),
                "delta": round(float(row.get("delta") or 0), 4),
                "iv": round(float(row.get("implied_volatility") or row.get("iv") or 0), 4),
                "oi": int(float(row.get("open_interest") or row.get("oi") or 0)),
                "volume": int(float(row.get("volume") or 0)),
                "source": row.get("source") or "unknown",
            }
            for row in sorted(rows, key=_row_sort_key, reverse=True)[:limit]
        ]

        return jsonify({"strategies": strategies, "underlying": underlying}), 200
    except Exception as req_err:
        logging.error(f"❌ Option chain request failed: {req_err}", exc_info=True)
        return jsonify({"strategies": fallback_strategies, "underlying": underlying}), 200


# Simple stub: Crypto signals (placeholder until live scoring is added)
@app.route("/api/crypto-signals", methods=["GET"])
def crypto_signals():
    try:
        ticker = request.args.get("ticker", "BTC").upper()
        price = float(request.args.get("price", 30000))
        signals = {
            "ticker": ticker,
            "score": 0.6,
            "entry": price,
            "stop": round(price * 0.95, 2),
            "target": round(price * 1.08, 2),
            "momentum": "up",
            "comment": "Placeholder signal; integrate live scoring for production.",
        }
        _dispatch_crypto_signal_alert(signals)
        return jsonify({"signals": signals}), 200
    except Exception as e:
        logging.error(f"❌ Error in /api/crypto-signals: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# Simple stub: Short ideas (placeholder until live data is added)
@app.route("/api/short-ideas", methods=["GET"])
def short_ideas():
    try:
        import pickle
        tickers_param = request.args.get("tickers", "")
        min_price = float(request.args.get("min_price", 1))
        max_price = float(request.args.get("max_price", 500))
        min_z = float(request.args.get("min_z", 0.5))
        limit = int(request.args.get("limit", 10))

        lookup_path = os.path.join(BASE_DIR, "lookup_table.pkl") if 'BASE_DIR' in globals() else "lookup_table.pkl"
        if not os.path.exists(lookup_path):
            logging.error("❌ lookup_table.pkl not found for short ideas.")
            return jsonify({"candidates": [], "error": "lookup_table missing"}), 200

        with open(lookup_path, 'rb') as f:
            table = pickle.load(f)

        candidates = []
        selected = [t.strip().upper() for t in tickers_param.split(",") if t.strip()] if tickers_param else None

        for ticker, date_map in table.items():
            if selected and ticker not in selected:
                continue
            if not isinstance(date_map, dict) or not date_map:
                continue
            latest_date = sorted(date_map.keys())[-1]
            data = date_map[latest_date]
            trades = data.get("trades")
            avg_trades = data.get("avg_trades")
            std_trades = data.get("std_trades")
            close_price = data.get("close_price")

            if close_price is None or close_price < min_price or close_price > max_price:
                continue
            if avg_trades is None or std_trades is None or std_trades <= 0:
                continue
            z_score = (trades - avg_trades) / std_trades if std_trades else 0
            if z_score < min_z:
                continue
            vol_surge = trades / avg_trades if avg_trades else None
            score = z_score * 0.6 + (vol_surge or 0) * 0.4
            entry = close_price
            stop = close_price * 0.97
            target = close_price * 1.05

            candidates.append({
                "ticker": ticker,
                "date": latest_date,
                "trades": trades,
                "avg_trades": avg_trades,
                "std_trades": std_trades,
                "z_score": round(z_score, 2),
                "volume_surge": round(vol_surge, 2) if vol_surge else None,
                "close_price": close_price,
                "score": round(score, 2),
                "entry_point": round(entry, 2),
                "stop_loss": round(stop, 2),
                "target_price": round(target, 2),
            })

        candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
        candidates = candidates[:limit]
        return jsonify({"candidates": candidates}), 200
    except Exception as e:
        logging.error(f"❌ Error in /api/short-ideas: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


market_signal_engine = SignalEngine(
    big_print_threshold=config.MARKET_SIGNALS_BIG_PRINT_THRESHOLD
)
market_signal_stream = None
market_signal_started = False
market_signal_lock = threading.Lock()


def emit_market_signal(signal):
    if signal.get("type") != "BIG_PRINT":
        market_signal_engine.recent_signals.append(signal)
    socketio.emit("market_signal", signal)


def start_market_signal_pipeline():
    global market_signal_stream, market_signal_started

    if not config.ENABLE_MARKET_SIGNALS:
        logging.info("Market signal pipeline is disabled by ENABLE_MARKET_SIGNALS.")
        return
    if not config.MARKET_SIGNALS_SUBSCRIBE:
        logging.info(
            "Market signal pipeline is disabled because MARKET_SIGNALS_SUBSCRIBE is empty. "
            "Skipping idle Polygon websocket startup."
        )
        return

    with market_signal_lock:
        if market_signal_started:
            return

        market_signal_stream = PolygonMarketStream(
            ws_url=POLYGON_WS_URL,
            api_key=POLYGON_API_KEY,
            engine=market_signal_engine,
            emit_signal=emit_market_signal,
            subscribe_params=config.MARKET_SIGNALS_SUBSCRIBE,
        )
        market_signal_stream.start()
        market_signal_started = True
        logging.info(
            "Market signal pipeline started (threshold=%s, subscribe=%s).",
            config.MARKET_SIGNALS_BIG_PRINT_THRESHOLD,
            config.MARKET_SIGNALS_SUBSCRIBE,
        )


@app.route("/api/market-signals/recent", methods=["GET"])
def recent_market_signals():
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 500))
    signals = list(market_signal_engine.recent_signals)[-limit:]
    return jsonify({"signals": signals}), 200


@app.route("/api/market-signals/top-stocks", methods=["GET"])
def market_signals_top_stocks():
    try:
        limit = int(request.args.get("limit", 25))
    except (TypeError, ValueError):
        limit = 25
    limit = max(1, min(limit, 100))

    try:
        min_notional = float(request.args.get("min_notional", 50_000_000))
    except (TypeError, ValueError):
        min_notional = 50_000_000

    url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
    params = {"apiKey": POLYGON_API_KEY}
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("tickers", [])

    top = []
    for row in rows:
        day = row.get("day") or {}
        prev_day = row.get("prevDay") or {}
        symbol = row.get("ticker")
        volume = _safe_float(day.get("v"), 0.0) or _safe_float(prev_day.get("v"), 0.0)
        vwap = _safe_float(day.get("vw"), 0.0)
        close = _safe_float(day.get("c"), 0.0) or _safe_float(prev_day.get("c"), 0.0) or _safe_float((row.get("lastTrade") or {}).get("p"), 0.0)
        if vwap <= 0 and close > 0:
            vwap = close
        if not symbol or volume <= 0 or vwap <= 0:
            continue
        try:
            notional = float(volume) * float(vwap)
        except (TypeError, ValueError):
            continue
        if notional < min_notional:
            continue
        top.append(
            {
                "symbol": symbol,
                "day_notional": notional,
                "day_volume": volume,
                "price": close,
            }
        )

    top.sort(key=lambda item: item["day_notional"], reverse=True)
    return jsonify({"stocks": top[:limit]}), 200


_high20_cache = {}
_high20_cache_lock = threading.Lock()
_intraday_metrics_cache = {}
_intraday_metrics_cache_lock = threading.Lock()
_daily_cache = {}
_daily_cache_lock = threading.Lock()
_scan_route_cache = TTLCache(maxsize=64, ttl=45)


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, value))


def _clip_unit(value):
    return max(0.0, min(1.0, value))


def _first_positive(*values, default=0.0):
    for value in values:
        parsed = _safe_float(value, 0.0)
        if parsed > 0:
            return parsed
    return default


def _build_request_cache_key(route_name):
    return route_name, tuple(sorted((str(key), str(value)) for key, value in request.args.items()))


def _parse_snapshot_candidate(row):
    minute = row.get("min") or {}
    day = row.get("day") or {}
    prev_day = row.get("prevDay") or {}
    last_trade = row.get("lastTrade") or {}
    symbol = str(row.get("ticker") or "").upper().strip()
    if not symbol:
        return None

    prev_close = _first_positive(prev_day.get("c"), day.get("o"), default=0.0)
    price = _first_positive(
        minute.get("c"),
        minute.get("vw"),
        minute.get("o"),
        minute.get("h"),
        minute.get("l"),
        day.get("c"),
        last_trade.get("p"),
        prev_close,
        default=0.0,
    )
    if price <= 0:
        return None

    minute_volume = _first_positive(minute.get("av"), minute.get("v"), minute.get("dv"), default=0.0)
    day_volume = _first_positive(day.get("v"), default=0.0)
    prev_volume = _first_positive(prev_day.get("v"), default=0.0)

    if minute_volume > 0:
        volume = minute_volume
        used_prev_volume = False
    elif day_volume > 0:
        volume = day_volume
        used_prev_volume = False
    else:
        volume = prev_volume
        used_prev_volume = prev_volume > 0

    vwap = _first_positive(minute.get("vw"), day.get("vw"), price, default=price)
    pct_change = _safe_float(row.get("todaysChangePerc"), 0.0)
    if pct_change == 0.0 and price > 0 and prev_close > 0:
        pct_change = ((price - prev_close) / prev_close) * 100.0

    rvol = 1.0 if used_prev_volume and prev_volume > 0 else (volume / prev_volume) if prev_volume > 0 else 0.0
    vwap_distance_pct = abs((price - vwap) / vwap) * 100.0 if vwap > 0 else 0.0

    return {
        "symbol": symbol,
        "price": price,
        "vwap": vwap,
        "day_volume": volume,
        "day_notional": volume * vwap,
        "pct_change": pct_change,
        "rvol": rvol,
        "vwap_distance_pct": vwap_distance_pct,
    }


def _snapshot_seed_score(item):
    day_notional = _safe_float(item.get("day_notional"), 0.0)
    pct_change = abs(_safe_float(item.get("pct_change"), 0.0))
    rvol = _safe_float(item.get("rvol"), 0.0)
    price = _safe_float(item.get("price"), 0.0)
    liquidity_component = min(day_notional / 500_000_000.0, 6.0) * 10.0
    move_component = min(pct_change, 25.0) * 2.0
    rvol_component = min(rvol, 6.0) * 12.0
    price_component = 6.0 if 1.0 <= price <= 25.0 else 2.0 if price > 0 else 0.0
    return liquidity_component + move_component + rvol_component + price_component


def _select_snapshot_seeds(
    rows,
    *,
    limit,
    min_price=0.0,
    max_price=float("inf"),
    min_day_notional=0.0,
    min_day_volume=0.0,
):
    candidates = []
    for row in rows:
        parsed = _parse_snapshot_candidate(row)
        if not parsed:
            continue
        if parsed["price"] < min_price:
            continue
        if math.isfinite(max_price) and parsed["price"] > max_price:
            continue
        if parsed["day_notional"] < min_day_notional:
            continue
        if parsed["day_volume"] < min_day_volume:
            continue
        parsed["_seedScore"] = round(_snapshot_seed_score(parsed), 4)
        candidates.append(parsed)

    candidates.sort(
        key=lambda item: (
            _safe_float(item.get("_seedScore")),
            _safe_float(item.get("day_notional")),
            abs(_safe_float(item.get("pct_change"))),
            _safe_float(item.get("rvol")),
        ),
        reverse=True,
    )
    return candidates[:limit]


def _fetch_polygon_snapshot_rows():
    snapshot_url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
    try:
        response = requests.get(snapshot_url, params={"apiKey": POLYGON_API_KEY}, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.RequestException as exc:
        detail = str(exc)
        if "WinError 10013" in detail:
            raise RuntimeError(
                "Polygon snapshot request failed because the local backend is blocked from opening outbound connections "
                "to api.polygon.io:443 (WinError 10013). Check Windows Firewall, antivirus, VPN, or corporate network rules."
            ) from exc
        raise RuntimeError(f"Polygon snapshot request failed: {exc}") from exc
    return payload.get("tickers", []) or []


def _compute_pressure_summary(daily, price, spy_daily=None):
    """Compute pre-breakout pressure score/bucket from daily metrics."""
    if not daily.get("has_data"):
        return {"score": 0.0, "bucket": "Low Priority", "notes": [], "components": {}}

    atr5 = _safe_float(daily.get("atr5"), 0.0)
    atr20 = _safe_float(daily.get("atr20"), 0.0)
    range5 = _safe_float(daily.get("range5"), 0.0)
    range20 = _safe_float(daily.get("range20"), 0.0)
    vol3 = _safe_float(daily.get("vol3"), 0.0)
    vol10 = _safe_float(daily.get("vol10"), 0.0)
    high20 = _safe_float(daily.get("high_20"), 0.0)
    close = _safe_float(price, 0.0)
    ret5 = _safe_float(daily.get("return_5d"), 0.0)
    ret20 = _safe_float(daily.get("return_20d"), 0.0)
    spy_ret5 = _safe_float(spy_daily.get("return_5d"), 0.0) if spy_daily else 0.0
    spy_ret20 = _safe_float(spy_daily.get("return_20d"), 0.0) if spy_daily else 0.0
    ema8 = _safe_float(daily.get("ema8"), 0.0)
    ema21 = _safe_float(daily.get("ema21"), 0.0)
    higher_lows = bool(daily.get("higher_lows"))
    higher_closes = bool(daily.get("higher_closes"))
    ema_stack = ema8 > 0 and ema21 > 0 and (close > ema8 > ema21)

    atr_ratio = (atr5 / atr20) if atr20 > 0 else 9.9
    range_ratio = (range5 / range20) if range20 > 0 else 9.9
    dist_to_high20 = ((high20 - close) / high20) if high20 > 0 else 1.0
    rvol_build = (vol3 / vol10) if vol10 > 0 else 0.0

    atr_score = _clip_unit((0.90 - atr_ratio) / 0.40)
    range_score = _clip_unit((0.95 - range_ratio) / 0.35)
    compression_score = (0.6 * atr_score + 0.4 * range_score) * 30

    near_high_score = _clip_unit((0.08 - dist_to_high20) / 0.08) * 25

    vol_score = _clip_unit(1 - (abs(rvol_build - 1.05) / 0.55)) * 15

    structure_score = (0.4 * int(higher_lows) + 0.3 * int(higher_closes) + 0.3 * int(ema_stack)) * 15

    rs5_score = _clip_unit((ret5 - spy_ret5) / 0.05)
    rs20_score = _clip_unit((ret20 - spy_ret20) / 0.10)
    rs_score = (0.5 * rs5_score + 0.5 * rs20_score) * 15

    exhaust_penalty = 0.0
    if ema8 > 0:
        exhaust_penalty = _clip_unit(((close / ema8) - 1) / 0.08) * 10

    total = compression_score + near_high_score + vol_score + structure_score + rs_score - exhaust_penalty
    total = max(total, 0.0)

    bucket = "Low Priority"
    if total >= 75:
        bucket = "A Setup"
    elif total >= 60:
        bucket = "B Setup"
    elif total >= 45:
        bucket = "Watch"

    notes = []
    if dist_to_high20 <= 0.02:
        notes.append("Near 20d high")
    if 0.9 <= rvol_build <= 1.4:
        notes.append("Rising but not explosive volume")
    if higher_lows:
        notes.append("Higher lows")
    if ema_stack:
        notes.append("8 > 21 & price above 8")
    if (ret5 - spy_ret5) > 0 or (ret20 - spy_ret20) > 0:
        notes.append("Outperforming market")

    components = {
        "compression_score": round(compression_score, 2),
        "near_high_score": round(near_high_score, 2),
        "volume_score": round(vol_score, 2),
        "structure_score": round(structure_score, 2),
        "rs_score": round(rs_score, 2),
        "exhaust_penalty": round(exhaust_penalty, 2),
        "atr_ratio": round(atr_ratio, 3),
        "range_ratio": round(range_ratio, 3),
        "rvol_build": round(rvol_build, 3),
        "dist_to_high20": round(dist_to_high20, 4),
    }

    return {
        "score": round(total, 2),
        "bucket": bucket,
        "notes": notes,
        "components": components,
        "dist_to_high20": dist_to_high20,
        "rvol_build": rvol_build,
    }


def _compute_pre_breakout_engine(item, intra, daily, spy_daily=None):
    """
    Pre-breakout "pressure" algorithm: focuses on compression + proximity + quiet accumulation + structure + relative strength.
    Returns a 0-100 score with buckets A/B/watch.
    """
    reasons = []
    if not daily.get("has_data"):
        return {"score": 0.0, "state": "No Data", "triggerLevel": None, "confidence": 0.0, "reasons": ["No daily data"]}

    price = _safe_float(item.get("price"), 0.0)
    high_20 = _safe_float(daily.get("high_20"), 0.0)
    dist_to_high = _safe_float(daily.get("dist_to_high_20"), 1.0)

    atr_pct = _safe_float(daily.get("atr_pct"), 0.0)
    atr_pct_avg = _safe_float(daily.get("atr_pct_10d_avg"), atr_pct or 1.0)
    range_pct_5 = _safe_float(daily.get("range_pct_5d_avg"), 0.0)
    range_pct_20 = _safe_float(daily.get("range_pct_20d_avg"), range_pct_5 or 1.0)

    rvol_build = _safe_float(daily.get("rvol_build"), 0.0)
    higher_lows = bool(daily.get("higher_lows"))
    higher_closes = bool(daily.get("higher_closes"))
    ema8 = _safe_float(daily.get("ema8"), 0.0)
    ema21 = _safe_float(daily.get("ema21"), 0.0)
    ema_stack = ema8 > 0 and ema21 > 0 and ema8 > ema21 and price > ema8

    ret_20 = _safe_float(daily.get("return_20d"), 0.0)
    ret_5 = _safe_float(daily.get("return_5d"), 0.0)
    spy_ret_20 = _safe_float(spy_daily.get("return_20d"), 0.0) if spy_daily else 0.0
    spy_ret_5 = _safe_float(spy_daily.get("return_5d"), 0.0) if spy_daily else 0.0

    # Compression
    atr_contract = 1 - (atr_pct / atr_pct_avg) if atr_pct_avg > 0 else 0.0
    range_contract = 1 - (range_pct_5 / range_pct_20) if range_pct_20 > 0 else 0.0
    compression_score = 0.5 * _clip_unit(atr_contract) + 0.5 * _clip_unit(range_contract)
    if compression_score >= 0.35:
        reasons.append("Volatility compressing")

    # Near resistance without breakout
    near_high_score = 1 - min(dist_to_high / 0.05, 1.0) if dist_to_high >= 0 else 0.0
    already_broken = price > high_20 * 1.02 if high_20 > 0 else False
    if near_high_score >= 0.4:
        reasons.append("Near 20d high")

    # Quiet accumulation (not a big RVOL spike)
    rvol_score = 1 - min(abs(rvol_build - 1.1) / 0.4, 1.0) if rvol_build > 0 else 0.0
    if 0.9 <= rvol_build <= 1.3:
        reasons.append("Rising but not explosive volume")

    # Structure
    structure_score = 0.4 * int(higher_lows) + 0.3 * int(higher_closes) + 0.3 * int(ema_stack)
    if higher_lows:
        reasons.append("Higher lows")
    if ema_stack:
        reasons.append("8 > 21 & price above 8")

    # Relative strength
    rs_20 = ret_20 - spy_ret_20
    rs_5 = ret_5 - spy_ret_5
    rs_score = 0.6 * _clip_unit(rs_20 / 0.10) + 0.4 * _clip_unit(rs_5 / 0.05)
    if rs_score >= 0.4:
        reasons.append("Outperforming market")

    # Exhaustion penalty (too extended above ema8)
    exhaustion = 0.0
    if ema8 > 0:
        exhaustion = _clip_unit(((price / ema8) - 1) / 0.08)
        if exhaustion > 0.6:
            reasons.append("Getting extended")

    score = (
        0.30 * compression_score
        + 0.25 * near_high_score
        + 0.15 * rvol_score
        + 0.15 * structure_score
        + 0.15 * rs_score
    ) - 0.15 * exhaustion

    score = _clip_unit(score)
    score_pct = round(_clamp(score * 100), 2)

    # Binary Pre-Breakout Pressure flag (strict version, similar to TTM Squeeze)
    atr5 = _safe_float(daily.get("atr5"), 0.0)
    atr20 = _safe_float(daily.get("atr20"), 0.0)
    range5 = _safe_float(daily.get("range5"), 0.0)
    range20 = _safe_float(daily.get("range20"), 0.0)
    vol3 = _safe_float(daily.get("vol3"), 0.0)
    vol10 = _safe_float(daily.get("vol10"), 0.0)
    dist_high = dist_to_high

    compression_ratio = (atr5 / atr20) if atr20 > 0 else 9.9
    range_compression = (range5 / range20) if range20 > 0 else 9.9
    volume_ratio = (vol3 / vol10) if vol10 > 0 else 0.0
    pressure_flag = (
        compression_ratio < 0.6
        and range_compression < 0.7
        and dist_high < 0.05
        and 0.9 < volume_ratio < 1.4
    )
    if pressure_flag:
        reasons.append("Pre-Breakout Pressure (squeeze)")

    state = "Watch"
    if score >= 0.75:
        state = "A setup"
    elif score >= 0.60:
        state = "B setup"

    trigger = round(high_20, 4) if high_20 > 0 else None
    confidence = round(_clamp(score_pct - 5), 2)

    return {
        "score": score_pct,
        "state": state if not already_broken else "Already Broke",
        "triggerLevel": trigger,
        "confidence": confidence,
        "reasons": reasons[:6],
        "features": {
            "compression": round(compression_score, 3),
            "near_high": round(near_high_score, 3),
            "rvol_build": round(rvol_build, 3),
            "structure": round(structure_score, 3),
            "rs_score": round(rs_score, 3),
            "exhaustion": round(exhaustion, 3),
            "atr5_over_20": round(compression_ratio, 3),
            "range5_over_20": round(range_compression, 3),
            "volume3_over_10": round(volume_ratio, 3),
            "pressure": bool(pressure_flag),
        },
        "alreadyBroken": already_broken,
    }


def _compute_continuation_engine(item):
    score = 30.0
    reasons = []
    price = _safe_float(item.get("price"), 0.0)
    vwap = _safe_float(item.get("vwap"), 0.0)
    rvol = _safe_float(item.get("rvol"), 0.0)
    pct_move = _safe_float(item.get("pct_change"), 0.0)
    dist_vwap = abs((price - vwap) / vwap) if vwap > 0 else 0.0

    if price > vwap > 0:
        score += 18
        reasons.append("Above VWAP")
    if rvol >= 1.5:
        score += 16
        reasons.append("High RVOL")
    if pct_move >= 1.0:
        score += 12
        reasons.append("Positive move")
    if dist_vwap <= 0.06:
        score += 10
        reasons.append("Not overextended")
    if dist_vwap > 0.09:
        score -= 10

    state = "Neutral"
    if score >= 68:
        state = "Trend Intact"
    elif score >= 55:
        state = "Trend Emerging"
    confidence = _clamp(score - 8)
    return {
        "score": round(_clamp(score), 2),
        "state": state,
        "triggerLevel": round(vwap, 4) if vwap > 0 else None,
        "confidence": round(confidence, 2),
        "reasons": reasons,
    }


def _compute_squeeze_engine(item, print_stats):
    score = 22.0
    reasons = []
    rvol = _safe_float(item.get("rvol"), 0.0)
    day_notional = _safe_float(item.get("day_notional"), 0.0)
    pct_move = _safe_float(item.get("pct_change"), 0.0)

    count_over = int(print_stats.get("count_over_threshold", 0))
    max_print = _safe_float(print_stats.get("max_notional"), 0.0)
    buy_count = int(print_stats.get("buy_count", 0))
    sell_count = int(print_stats.get("sell_count", 0))

    if rvol >= 2.0:
        score += 20
        reasons.append("RVOL >= 2")
    if day_notional >= 2_000_000_000:
        score += 12
        reasons.append("High liquidity")
    if count_over >= 2:
        score += 20
        reasons.append("Repeated big prints")
    if max_print >= 25_000_000:
        score += 14
        reasons.append("Large single print")
    if pct_move >= 2.0:
        score += 8
    if buy_count > sell_count:
        score += 8
        reasons.append("Buy pressure")

    state = "Neutral"
    if score >= 78:
        state = "Liquidity Expansion"
    elif score >= 60:
        state = "Imbalance Building"
    confidence = _clamp(score - 10)
    return {
        "score": round(_clamp(score), 2),
        "state": state,
        "triggerLevel": None,
        "confidence": round(confidence, 2),
        "reasons": reasons,
    }


def _compute_exhaustion_engine(item, intra):
    score = 12.0
    reasons = []
    price = _safe_float(item.get("price"), 0.0)
    vwap = _safe_float(item.get("vwap"), 0.0)
    rsi14 = _safe_float(intra.get("rsi14"), 50.0)
    upper_wick_ratio_last = _safe_float(intra.get("upper_wick_ratio_last"), 0.0)
    rvol5 = _safe_float(intra.get("rvol5"), 0.0)
    consecutive_wide_3 = bool(intra.get("consecutive_wide_3"))

    dist_from_vwap = ((price - vwap) / vwap) if vwap > 0 else 0.0
    exhaustion_flags = {
        "Distance > 5% above VWAP": dist_from_vwap > 0.05,
        "RSI > 78": rsi14 > 78,
        "Large upper wick": upper_wick_ratio_last > 1.2,
        "Volume climax": rvol5 >= 2.0,
        "3 consecutive wide candles": consecutive_wide_3,
    }
    true_count = 0
    for label, flag in exhaustion_flags.items():
        if flag:
            true_count += 1
            reasons.append(label)

    score += true_count * 16
    if true_count >= 3:
        score += 10

    state = "LOW"
    if true_count >= 3:
        state = "HIGH"
    elif true_count == 2:
        state = "MODERATE"

    trigger = round(vwap, 4) if vwap > 0 else None
    return {
        "score": round(_clamp(score), 2),
        "state": state,
        "triggerLevel": trigger,
        "confidence": round(_clamp(score - 8), 2),
        "reasons": reasons,
        "flagsTrue": true_count,
    }


def _determine_overall_bias(pre, cont, squeeze, exhaustion):
    high_count = sum(1 for v in [pre["score"], cont["score"], squeeze["score"]] if v >= 65)
    very_high_count = sum(1 for v in [pre["score"], cont["score"], squeeze["score"]] if v >= 70)
    if very_high_count == 3:
        return "High-Volatility Expansion Event"
    if high_count >= 2:
        if exhaustion["score"] >= 70:
            return "Strong Momentum but Exhaustion Risk"
        if pre["score"] >= cont["score"] and pre["score"] >= squeeze["score"]:
            return "Early Expansion Setup"
        if cont["score"] >= pre["score"] and cont["score"] >= squeeze["score"]:
            return "Momentum + Follow-Through"
        return "Momentum + Imbalance"
    if cont["score"] >= 65:
        return "Trend Continuation Bias"
    if pre["score"] >= 65:
        return "Pre-Breakout Bias"
    if squeeze["score"] >= 65:
        return "Squeeze Risk Bias"
    return "Neutral/Chop"


def _determine_phase_and_entry(item, pre, cont, squeeze, exhaustion):
    pct_move = _safe_float(item.get("pct_change"), 0.0)

    if exhaustion["score"] >= 75 and cont["score"] >= 70:
        phase = "Blowoff"
    elif pre["score"] >= 65 and pct_move < 4:
        phase = "Compression"
    elif cont["score"] >= 65 and exhaustion["score"] < 65:
        phase = "Expansion"
    elif exhaustion["score"] >= 65 and cont["score"] < 65:
        phase = "Distribution"
    else:
        phase = "Mixed"

    if pre["score"] >= 65 and pct_move < 4:
        ideal_entry = "Break of range high"
    elif cont["score"] >= 70 and 3 <= pct_move <= 12:
        ideal_entry = "Pullback to EMA/VWAP hold"
    elif squeeze["score"] >= 75:
        ideal_entry = "Break of multi-day high (tight trail)"
    elif cont["score"] >= 70 and pct_move > 40:
        ideal_entry = "Wait for pullback"
    elif exhaustion["score"] >= 70:
        ideal_entry = "No chase; wait reset"
    else:
        ideal_entry = "No clean entry"

    too_late = bool((cont["score"] >= 70 and pct_move > 40) or exhaustion["score"] >= 78)
    return phase, ideal_entry, too_late


def _fetch_20d_high(symbol):
    now = datetime.utcnow()
    cache_key = symbol.upper()
    with _high20_cache_lock:
        cached = _high20_cache.get(cache_key)
        if cached and (now - cached["at"]).total_seconds() < 300:
            return cached["value"]

    start = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    url = f"https://api.polygon.io/v2/aggs/ticker/{cache_key}/range/1/day/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 60, "apiKey": POLYGON_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        highs = [_safe_float(item.get("h"), 0.0) for item in results][-20:]
        value = max(highs) if highs else 0.0
    except Exception:
        value = 0.0

    with _high20_cache_lock:
        _high20_cache[cache_key] = {"value": value, "at": now}
    return value


def _fetch_intraday_1m_metrics(symbol, price, minutes=30):
    now = datetime.utcnow()
    key = f"{symbol.upper()}:{minutes}"
    with _intraday_metrics_cache_lock:
        cached = _intraday_metrics_cache.get(key)
        if cached and (now - cached["at"]).total_seconds() < 45:
            return cached["value"]

    start = (now - timedelta(minutes=max(35, minutes + 10))).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol.upper()}/range/1/minute/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 200, "apiKey": POLYGON_API_KEY}
    metrics = {
        "has_data": False,
        "range_high_20": 0.0,
        "range_low_20": 0.0,
        "range_ratio_20": 999.0,
        "near_breakout": False,
        "rvol5": 0.0,
        "higher_lows": False,
        "rsi14": 50.0,
        "upper_wick_ratio_last": 0.0,
        "consecutive_wide_3": False,
    }
    try:
        response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
        data = response.json()
        rows = data.get("results", [])
        if len(rows) < 22:
            with _intraday_metrics_cache_lock:
                _intraday_metrics_cache[key] = {"value": metrics, "at": now}
            return metrics

        highs = [_safe_float(r.get("h"), 0.0) for r in rows]
        lows = [_safe_float(r.get("l"), 0.0) for r in rows]
        opens = [_safe_float(r.get("o"), 0.0) for r in rows]
        closes = [_safe_float(r.get("c"), 0.0) for r in rows]
        vols = [_safe_float(r.get("v"), 0.0) for r in rows]

        hi20 = max(highs[-20:])
        lo20 = min(lows[-20:])
        recent5 = vols[-5:]
        prev20 = vols[-25:-5] if len(vols) >= 25 else vols[:-5]
        recent5_avg = (sum(recent5) / len(recent5)) if recent5 else 0.0
        prev20_avg = (sum(prev20) / len(prev20)) if prev20 else 0.0
        rvol5 = (recent5_avg / prev20_avg) if prev20_avg > 0 else 0.0
        higher_lows = min(lows[-5:]) > min(lows[-10:-5]) if len(lows) >= 10 else False
        near_breakout = price >= hi20 * 0.99 if hi20 > 0 else False
        range_ratio = ((hi20 - lo20) / price) if price > 0 else 999.0

        # RSI14 from closes
        gains = 0.0
        losses = 0.0
        if len(closes) >= 15:
            for i in range(len(closes) - 14, len(closes)):
                diff = closes[i] - closes[i - 1]
                if diff >= 0:
                    gains += diff
                else:
                    losses -= diff
        rs = (gains / losses) if losses > 0 else 999
        rsi14 = 100 - 100 / (1 + rs)

        last_o = opens[-1] if opens else price
        last_c = closes[-1] if closes else price
        last_h = highs[-1] if highs else price
        body = abs(last_c - last_o)
        upper_wick = last_h - max(last_o, last_c)
        upper_wick_ratio_last = (upper_wick / body) if body > 0 else 0.0

        ranges = [max(0.0, highs[i] - lows[i]) for i in range(len(highs))]
        atr20 = (sum(ranges[-20:]) / 20.0) if len(ranges) >= 20 else (sum(ranges) / max(len(ranges), 1))
        wide_flags = [(rng > atr20 * 1.8) for rng in ranges[-3:]] if atr20 > 0 else [False, False, False]
        consecutive_wide_3 = bool(len(wide_flags) == 3 and all(wide_flags))

        metrics = {
            "has_data": True,
            "range_high_20": hi20,
            "range_low_20": lo20,
            "range_ratio_20": range_ratio,
            "near_breakout": near_breakout,
            "rvol5": rvol5,
            "higher_lows": higher_lows,
            "rsi14": rsi14,
            "upper_wick_ratio_last": upper_wick_ratio_last,
            "consecutive_wide_3": consecutive_wide_3,
        }
    except Exception:
        pass

    with _intraday_metrics_cache_lock:
        _intraday_metrics_cache[key] = {"value": metrics, "at": now}
    return metrics


def _fetch_daily_metrics(symbol):
    """
    Fetch recent daily bars to derive compression/structure metrics for pre-breakout logic.
    Cached for 5 minutes per symbol.
    """
    now = datetime.utcnow()
    cache_key = symbol.upper()
    with _daily_cache_lock:
        cached = _daily_cache.get(cache_key)
        if cached and (now - cached["at"]).total_seconds() < 300:
            return cached["value"]

    start = (now - timedelta(days=120)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    url = f"https://api.polygon.io/v2/aggs/ticker/{cache_key}/range/1/day/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 180, "apiKey": POLYGON_API_KEY}
    metrics = {"has_data": False}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        rows = data.get("results", [])
        closes = [_safe_float(r.get("c"), 0.0) for r in rows if _safe_float(r.get("c"), 0.0) > 0]
        highs = [_safe_float(r.get("h"), 0.0) for r in rows]
        lows = [_safe_float(r.get("l"), 0.0) for r in rows]
        volumes = [_safe_float(r.get("v"), 0.0) for r in rows]
        if len(closes) < 40:
            with _daily_cache_lock:
                _daily_cache[cache_key] = {"value": metrics, "at": now}
            return metrics

        def ema(values, period):
            if not values:
                return 0.0
            k = 2 / (period + 1)
            ema_val = values[0]
            for v in values[1:]:
                ema_val = v * k + ema_val * (1 - k)
            return ema_val

        tr = []
        for i in range(len(highs)):
            if i == 0:
                tr.append(highs[i] - lows[i])
            else:
                prev_close = closes[i - 1]
                tr.append(max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close)))
        atr14 = sum(tr[-14:]) / 14.0 if len(tr) >= 14 else sum(tr) / max(len(tr), 1)

        # percentage ranges
        range_pct = []
        for h, l, c in zip(highs, lows, closes):
            if c > 0:
                range_pct.append((h - l) / c)
        range_pct_5d_avg = sum(range_pct[-5:]) / 5.0 if len(range_pct) >= 5 else sum(range_pct) / max(len(range_pct), 1)
        range_pct_20d_avg = sum(range_pct[-20:]) / 20.0 if len(range_pct) >= 20 else range_pct_5d_avg

        close = closes[-1]
        high_20 = max(highs[-20:]) if len(highs) >= 20 else max(highs)
        low_3d_ago = lows[-4] if len(lows) >= 4 else lows[-1]
        close_3d_ago = closes[-4] if len(closes) >= 4 else closes[-1]

        atr_pct = (atr14 / close) if close > 0 else 0.0
        atr_pct_hist = []
        for i in range(-25, 0):
            idx = len(range_pct) + i
            if idx >= 0 and idx < len(tr) and closes[idx] > 0:
                atr_pct_hist.append((tr[idx] / closes[idx]))
        atr_pct_10d_avg = sum(atr_pct_hist[-10:]) / 10.0 if len(atr_pct_hist) >= 10 else (sum(atr_pct_hist) / max(len(atr_pct_hist), 1))

        vol_3d_avg = sum(volumes[-3:]) / 3.0 if len(volumes) >= 3 else sum(volumes) / max(len(volumes), 1)
        vol_10d_avg = sum(volumes[-10:]) / 10.0 if len(volumes) >= 10 else vol_3d_avg
        rvol_build = (vol_3d_avg / vol_10d_avg) if vol_10d_avg > 0 else 0.0

        ema8 = ema(closes[-30:], 8)
        ema21 = ema(closes[-60:], 21)

        # Additional compression metrics
        atr5 = sum(tr[-5:]) / 5.0 if len(tr) >= 5 else atr14
        atr20_full = sum(tr[-20:]) / 20.0 if len(tr) >= 20 else atr14
        range5 = sum(range_pct[-5:]) / 5.0 if len(range_pct) >= 5 else range_pct_5d_avg
        range20 = sum(range_pct[-20:]) / 20.0 if len(range_pct) >= 20 else range_pct_20d_avg

        def ret(days):
            if len(closes) <= days:
                return 0.0
            past = closes[-(days + 1)]
            return (close - past) / past if past > 0 else 0.0

        metrics = {
            "has_data": True,
            "close": close,
            "high_20": high_20,
            "atr_pct": atr_pct,
            "atr_pct_10d_avg": atr_pct_10d_avg,
            "range_pct_5d_avg": range_pct_5d_avg,
            "range_pct_20d_avg": range_pct_20d_avg,
            "dist_to_high_20": ((high_20 - close) / high_20) if high_20 > 0 else 1.0,
            "vol_3d_avg": vol_3d_avg,
            "vol_10d_avg": vol_10d_avg,
            "rvol_build": rvol_build,
            "higher_lows": lows[-1] > low_3d_ago if lows else False,
            "higher_closes": close > close_3d_ago if closes else False,
            "ema8": ema8,
            "ema21": ema21,
            "return_20d": ret(20),
            "return_5d": ret(5),
            "bars": len(closes),
            # Compression inputs
            "atr5": atr5,
            "atr20": atr20_full,
            "range5": range5,
            "range20": range20,
            "vol3": vol_3d_avg,
            "vol10": vol_10d_avg,
        }
    except Exception:
        pass

    with _daily_cache_lock:
        _daily_cache[cache_key] = {"value": metrics, "at": now}
    return metrics


def _big_print_stats_by_symbol(window_minutes=30, min_print_notional=10_000_000):
    cutoff_ms = int((datetime.utcnow() - timedelta(minutes=window_minutes)).timestamp() * 1000)
    stats = {}
    for signal in list(market_signal_engine.recent_signals):
        if signal.get("type") != "BIG_PRINT":
            continue
        ts = int(signal.get("ts") or 0)
        if ts < cutoff_ms:
            continue
        symbol = str(signal.get("symbol") or "").upper()
        if not symbol:
            continue
        entry = stats.setdefault(
            symbol,
            {
                "count": 0,
                "count_over_threshold": 0,
                "max_notional": 0.0,
                "buy_count": 0,
                "sell_count": 0,
                "total_notional": 0.0,
            },
        )
        notional = _safe_float(signal.get("notional"), 0.0)
        side = str(signal.get("side") or "unknown").lower()
        entry["count"] += 1
        entry["total_notional"] += notional
        entry["max_notional"] = max(entry["max_notional"], notional)
        if notional >= min_print_notional:
            entry["count_over_threshold"] += 1
        if side == "buy":
            entry["buy_count"] += 1
        elif side == "sell":
            entry["sell_count"] += 1
    return stats


@app.route("/api/ai-picks", methods=["GET"])
def ai_picks():
    try:
        cache_key = _build_request_cache_key("ai_picks")
        cached_payload = _scan_route_cache.get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload), 200

        try:
            limit = max(1, min(int(request.args.get("limit", 8)), 20))
        except (TypeError, ValueError):
            limit = 8
        try:
            pool_limit = max(max(limit * 3, 18), min(int(request.args.get("pool_limit", 48)), 96))
        except (TypeError, ValueError):
            pool_limit = max(limit * 3, 48)

        min_day_notional = _safe_float(request.args.get("min_day_notional", 800_000_000), 800_000_000)
        min_price = _safe_float(request.args.get("min_price", 5.0), 5.0)
        news_limit = max(limit, min(int(_safe_float(request.args.get("news_limit", 8), 8)), 12))
        alert_config = {
            "live_min_score": _safe_float(request.args.get("live_min_score", 85.0), 85.0),
            "near_min_score": _safe_float(request.args.get("near_min_score", 75.0), 75.0),
            "near_distance_pct": _safe_float(request.args.get("near_distance_pct", 1.0), 1.0),
        }

        rows = _fetch_polygon_snapshot_rows()

        fallback_used = False
        candidate_rows = _select_snapshot_seeds(
            rows,
            limit=pool_limit,
            min_price=min_price,
            min_day_notional=min_day_notional,
        )
        if not candidate_rows:
            fallback_used = True
            candidate_rows = _select_snapshot_seeds(
                rows,
                limit=max(limit * 2, 12),
                min_price=min_price,
            )
        if not candidate_rows:
            return jsonify({"generated_at": datetime.utcnow().isoformat() + "Z", "picks": []}), 200

        flow_stats = _big_print_stats_by_symbol(window_minutes=30, min_print_notional=10_000_000)
        def build_preliminary_entry(item):
            daily_metrics = _fetch_daily_metrics(item["symbol"])
            intra_metrics = _fetch_intraday_1m_metrics(item["symbol"], item["price"], minutes=30)
            scored = calculate_ai_pick_score(
                item,
                daily_metrics,
                intra_metrics,
                news_items=[],
                flow_stats=flow_stats.get(item["symbol"], {}),
                analyzer=analyzer,
                alert_config=alert_config,
            )
            return {
                "item": item,
                "daily": daily_metrics,
                "intra": intra_metrics,
                "score": scored["score"],
            }

        with ThreadPoolExecutor(max_workers=min(12, max(4, len(candidate_rows)))) as executor:
            preliminary = list(executor.map(build_preliminary_entry, candidate_rows))

        if not preliminary:
            return jsonify({"generated_at": datetime.utcnow().isoformat() + "Z", "picks": []}), 200

        preliminary.sort(key=lambda entry: entry["score"], reverse=True)
        finalists = preliminary[:news_limit]
        def build_pick(entry):
            symbol = entry["item"]["symbol"]
            news_items = fetch_ticker_news(symbol, limit=3)
            return calculate_ai_pick_score(
                entry["item"],
                entry["daily"],
                entry["intra"],
                news_items=news_items,
                flow_stats=flow_stats.get(symbol, {}),
                analyzer=analyzer,
                alert_config=alert_config,
            )

        with ThreadPoolExecutor(max_workers=min(8, max(2, len(finalists)))) as executor:
            picks = list(executor.map(build_pick, finalists))

        picks.sort(
            key=lambda item: (
                alert_priority((item.get("alert") or {}).get("label")),
                float(item.get("score", 0.0) or 0.0),
            ),
            reverse=True,
        )
        response_payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "picks": picks[:limit],
            "debug": {
                "universe_count": len(rows),
                "candidate_count": len(candidate_rows),
                "scored_count": len(preliminary),
                "fallback_used": fallback_used,
                "alert_config": alert_config,
            },
        }
        _dispatch_ai_pick_alerts(response_payload["picks"])
        _scan_route_cache[cache_key] = response_payload
        return jsonify(response_payload), 200
    except RuntimeError as e:
        logging.error(f"AI picks route failed: {e}", exc_info=True)
        return jsonify({"generated_at": datetime.utcnow().isoformat() + "Z", "picks": [], "error": str(e)}), 503
        logging.error(f"AI picks route failed: {e}", exc_info=True)
        return jsonify({"generated_at": datetime.utcnow().isoformat() + "Z", "picks": [], "error": str(e)}), 500


@app.route("/api/market-signals/qualified-targets", methods=["GET"])
def market_signals_qualified_targets():
    cache_key = _build_request_cache_key("market_signals_qualified_targets")
    cached_payload = _scan_route_cache.get(cache_key)
    if cached_payload is not None:
        return jsonify(cached_payload), 200

    mode = str(request.args.get("mode", "breakout")).strip().lower()
    if mode not in {"breakout", "reversal", "big_prints", "pre_breakout"}:
        mode = "breakout"

    try:
        limit = int(request.args.get("limit", 25))
    except (TypeError, ValueError):
        limit = 25
    limit = max(1, min(limit, 100))

    min_notional_default = 800_000_000 if mode == "breakout" else 500_000_000
    if mode == "pre_breakout":
        min_notional_default = 400_000_000
    try:
        min_day_notional = float(request.args.get("min_day_notional", request.args.get("min_notional", min_notional_default)))
    except (TypeError, ValueError):
        min_day_notional = float(min_notional_default)
    min_price = _safe_float(request.args.get("min_price", 3.0), 3.0)
    max_price = _safe_float(request.args.get("max_price", float("inf")), float("inf"))
    min_day_volume = _safe_float(request.args.get("min_day_volume", 0), 0.0)
    min_move_pct = _safe_float(request.args.get("min_move_pct", 2.0), 2.0)
    max_move_pct = _safe_float(request.args.get("max_move_pct", 3.0), 3.0)
    min_rvol = _safe_float(request.args.get("min_rvol", 1.8), 1.8)
    max_range_ratio = _safe_float(request.args.get("max_range_ratio", 0.015), 0.015)
    min_near_break_ratio = _safe_float(request.args.get("min_near_break_ratio", 0.99), 0.99)
    require_higher_lows = str(request.args.get("require_higher_lows", "true")).strip().lower() in {"1", "true", "yes", "on"}
    min_vwap_distance_pct = _safe_float(request.args.get("min_vwap_distance_pct", 1.5), 1.5)
    require_vwap = str(request.args.get("require_vwap", "true")).strip().lower() in {"1", "true", "yes", "on"}
    show_qualified_only = str(request.args.get("qualified_only", "true")).strip().lower() in {"1", "true", "yes", "on"}
    min_print_notional = _safe_float(request.args.get("min_print_notional", 10_000_000), 10_000_000)
    print_window_minutes = int(_safe_float(request.args.get("print_window_minutes", 30), 30))
    min_print_count = int(_safe_float(request.args.get("min_print_count", 2), 2))
    single_print_override = _safe_float(request.args.get("single_print_override", 25_000_000), 25_000_000)
    pool_limit = int(_safe_float(request.args.get("pool_limit", max(limit * 3, 60)), max(limit * 3, 60)))
    pool_limit = max(max(limit * 2, 24), min(pool_limit, 120))

    try:
        rows = _fetch_polygon_snapshot_rows()
    except RuntimeError as exc:
        logging.error(f"Qualified targets route failed: {exc}", exc_info=True)
        return jsonify(
            {
                "mode": mode,
                "count": 0,
                "evaluated": 0,
                "targets": [],
                "error": str(exc),
                "debug": {"failure_counts": []},
            }
        ), 503

    seed_min_notional = min_day_notional * 0.25 if min_day_notional > 0 else 0.0
    candidate_rows = _select_snapshot_seeds(
        rows,
        limit=pool_limit,
        min_price=min_price,
        max_price=max_price,
        min_day_notional=seed_min_notional,
        min_day_volume=min_day_volume * 0.25 if min_day_volume > 0 else 0.0,
    )
    if not candidate_rows:
        candidate_rows = _select_snapshot_seeds(
            rows,
            limit=max(limit * 2, 16),
            min_price=min_price,
            max_price=max_price,
        )
    print_stats = _big_print_stats_by_symbol(window_minutes=print_window_minutes, min_print_notional=min_print_notional)

    results = []
    failure_counts = {}
    evaluated_count = 0
    spy_daily = _fetch_daily_metrics("SPY")

    def tally_failures(failed_rules):
        for label in failed_rules:
            failure_counts[label] = failure_counts.get(label, 0) + 1

    def evaluate_candidate(item):
        item = dict(item)
        symbol = item["symbol"]
        intra_for_engines = _fetch_intraday_1m_metrics(symbol=symbol, price=item["price"], minutes=30)
        stats_for_engines = print_stats.get(
            symbol,
            {"count": 0, "count_over_threshold": 0, "max_notional": 0.0, "buy_count": 0, "sell_count": 0, "total_notional": 0.0},
        )
        reasons = []
        failed = []
        score = 0.0

        def check_rule(ok, label):
            if ok:
                reasons.append(label)
            else:
                failed.append(label)
            return ok

        daily_metrics = _fetch_daily_metrics(symbol)

        if mode == "breakout":
            c1 = check_rule(item["day_notional"] >= min_day_notional, f"Day notional >= {min_day_notional:,.0f}")
            c2 = check_rule(item["price"] >= min_price, f"Price >= {min_price:g}")
            c2b = check_rule(item["price"] <= max_price, f"Price <= {max_price:g}") if math.isfinite(max_price) else True
            c2c = check_rule(item["day_volume"] >= min_day_volume, f"Day volume >= {min_day_volume:,.0f}") if min_day_volume > 0 else True
            c3 = check_rule(item["pct_change"] >= min_move_pct, f"% change >= {min_move_pct:g}")
            c4 = check_rule(item["rvol"] >= min_rvol, f"RVOL >= {min_rvol:g}")
            c5 = check_rule((item["price"] > item["vwap"]) if require_vwap else True, "Above VWAP")
            near_breakout = False
            high_20d = _safe_float(daily_metrics.get("high_20"), 0.0) if (c1 and c2 and c2b and c2c and c3 and c4) else 0.0
            if high_20d > 0:
                near_breakout = item["price"] >= high_20d * 0.98
                c6 = check_rule(near_breakout, "Within 2% of 20d high")
            else:
                # Do not auto-fail when 20d lookup is unavailable.
                c6 = check_rule(True, "20d high unavailable (rule skipped)")
            qualified = all([c1, c2, c2b, c2c, c3, c4, c5, c6])
            score = (
                min(item["day_notional"] / max(min_day_notional, 1), 4.0) * 30
                + min(item["rvol"] / max(min_rvol, 0.1), 3.0) * 25
                + min(max(item["pct_change"], 0.0) / max(min_move_pct, 0.1), 3.0) * 25
                + (20 if near_breakout else 0)
            )
            item["high_20d"] = high_20d
        elif mode == "reversal":
            c1 = check_rule(item["day_notional"] >= min_day_notional, f"Day notional >= {min_day_notional:,.0f}")
            c2 = check_rule(item["price"] >= min_price, f"Price >= {min_price:g}")
            c2b = check_rule(item["price"] <= max_price, f"Price <= {max_price:g}") if math.isfinite(max_price) else True
            c2c = check_rule(item["day_volume"] >= min_day_volume, f"Day volume >= {min_day_volume:,.0f}") if min_day_volume > 0 else True
            c3 = check_rule(abs(item["pct_change"]) >= min_move_pct, f"|% change| >= {min_move_pct:g}")
            c4 = check_rule(item["vwap_distance_pct"] >= min_vwap_distance_pct, f"VWAP distance >= {min_vwap_distance_pct:g}%")
            reversal_hint = (item["pct_change"] < 0 and item["price"] >= item["vwap"] * 0.995) or (
                item["pct_change"] > 0 and item["price"] <= item["vwap"] * 1.005
            )
            c5 = check_rule(reversal_hint, "Reversal setup near VWAP")
            qualified = all([c1, c2, c2b, c2c, c3, c4, c5])
            score = (
                min(item["day_notional"] / max(min_day_notional, 1), 4.0) * 30
                + min(abs(item["pct_change"]) / max(min_move_pct, 0.1), 4.0) * 35
                + min(item["vwap_distance_pct"] / max(min_vwap_distance_pct, 0.1), 4.0) * 35
            )
        elif mode == "big_prints":
            stats = print_stats.get(
                symbol,
                {"count": 0, "count_over_threshold": 0, "max_notional": 0.0, "buy_count": 0, "sell_count": 0, "total_notional": 0.0},
            )
            c1 = check_rule(item["day_notional"] >= min_day_notional, f"Day notional >= {min_day_notional:,.0f}")
            c2 = check_rule(item["price"] >= min_price, f"Price >= {min_price:g}")
            c2b = check_rule(item["price"] <= max_price, f"Price <= {max_price:g}") if math.isfinite(max_price) else True
            c2c = check_rule(item["day_volume"] >= min_day_volume, f"Day volume >= {min_day_volume:,.0f}") if min_day_volume > 0 else True
            c3 = check_rule(
                stats["count_over_threshold"] >= min_print_count or stats["max_notional"] >= single_print_override,
                f">= {min_print_count} prints >= {min_print_notional:,.0f} in {print_window_minutes}m OR single >= {single_print_override:,.0f}",
            )
            c4 = check_rule((item["price"] > item["vwap"]) if require_vwap else True, "Above VWAP")
            qualified = all([c1, c2, c2b, c2c, c3, c4])
            score = (
                min(item["day_notional"] / max(min_day_notional, 1), 4.0) * 25
                + min(stats["count_over_threshold"] / max(min_print_count, 1), 5.0) * 35
                + min(stats["max_notional"] / max(single_print_override, 1), 4.0) * 30
                + (10 if stats["buy_count"] >= stats["sell_count"] else 0)
            )
            item["big_print_count_30m"] = stats["count"]
            item["big_print_count_threshold_window"] = stats["count_over_threshold"]
            item["max_big_print_30m"] = stats["max_notional"]
            item["buy_prints_30m"] = stats["buy_count"]
            item["sell_prints_30m"] = stats["sell_count"]
        else:
            c1 = check_rule(item["day_notional"] >= min_day_notional, f"Day notional >= {min_day_notional:,.0f}")
            c2 = check_rule(item["price"] >= min_price, f"Price >= {min_price:g}")
            c2b = check_rule(item["price"] <= max_price, f"Price <= {max_price:g}") if math.isfinite(max_price) else True
            c2c = check_rule(item["day_volume"] >= min_day_volume, f"Day volume >= {min_day_volume:,.0f}") if min_day_volume > 0 else True
            c3 = check_rule(daily_metrics.get("has_data"), "Daily bars available")
            c4 = check_rule(daily_metrics.get("bars", 0) >= 60, ">= 60 bars")
            already_broken = bool(daily_metrics.get("has_data") and item["price"] > daily_metrics.get("high_20", 0) * 1.02)
            c5 = check_rule(not already_broken, "Not already broken out")
            qualified = all([c1, c2, c2b, c2c, c3, c4, c5])
            # Let the engine score drive ordering; keep base score comparable.
            score = 0.0
            item["range_high_20"] = daily_metrics.get("high_20", 0.0)
            item["range_low_20"] = intra_for_engines["range_low_20"]
            item["range_ratio_20"] = intra_for_engines["range_ratio_20"]
            item["rvol5"] = intra_for_engines["rvol5"]
            item["higher_lows"] = bool(daily_metrics.get("higher_lows"))

        engine_pre = _compute_pre_breakout_engine(item=item, intra=intra_for_engines, daily=daily_metrics, spy_daily=spy_daily)
        engine_cont = _compute_continuation_engine(item=item)
        engine_squeeze = _compute_squeeze_engine(item=item, print_stats=stats_for_engines)
        engine_exhaustion = _compute_exhaustion_engine(item=item, intra=intra_for_engines)
        pressure_summary = _compute_pressure_summary(daily_metrics, price=item["price"], spy_daily=spy_daily)
        if mode == "pre_breakout":
            score = pressure_summary.get("score", engine_pre.get("score", 0.0))

        overall_bias = _determine_overall_bias(engine_pre, engine_cont, engine_squeeze, engine_exhaustion)
        phase, ideal_entry, too_late = _determine_phase_and_entry(
            item=item,
            pre=engine_pre,
            cont=engine_cont,
            squeeze=engine_squeeze,
            exhaustion=engine_exhaustion,
        )

        row_out = {
            **item,
            "mode": mode,
            "qualified": qualified,
            "reasons": reasons,
            "failed_rules": failed,
            "score": round(score, 2),
            "engines": {
                "pre": engine_pre,
                "continuation": engine_cont,
                "squeeze": engine_squeeze,
                "exhaustion": engine_exhaustion,
            },
            "pressure": {
                "score": pressure_summary.get("score"),
                "bucket": pressure_summary.get("bucket"),
                "notes": pressure_summary.get("notes"),
                "dist_to_high20": pressure_summary.get("dist_to_high20"),
                "rvol_build": pressure_summary.get("rvol_build"),
                "components": pressure_summary.get("components"),
            },
            "overallBias": overall_bias,
            "phase": phase,
            "idealEntryType": ideal_entry,
            "tooLate": too_late,
        }

        return {
            "row": row_out,
            "failed": failed,
            "include": (not show_qualified_only) or qualified,
        }

    with ThreadPoolExecutor(max_workers=min(12, max(4, len(candidate_rows)))) as executor:
        evaluated = list(executor.map(evaluate_candidate, candidate_rows))

    evaluated_count = len(evaluated)
    for entry in evaluated:
        tally_failures(entry["failed"])
        if entry["include"]:
            results.append(entry["row"])

    results.sort(key=lambda x: x["score"], reverse=True)
    top_failures = sorted(failure_counts.items(), key=lambda kv: kv[1], reverse=True)[:6]
    response_payload = {
        "mode": mode,
        "count": len(results),
        "evaluated": evaluated_count,
        "targets": results[:limit],
        "debug": {
            "failure_counts": [{"rule": rule, "count": count} for rule, count in top_failures],
        },
    }
    _scan_route_cache[cache_key] = response_payload
    return jsonify(response_payload), 200


options_flow_poller = None
options_flow_started = False
options_flow_lock = threading.Lock()


def start_options_flow_pipeline():
    global options_flow_poller, options_flow_started

    if not config.ENABLE_OPTIONS_FLOW_SIGNALS:
        logging.info("Options flow pipeline is disabled by ENABLE_OPTIONS_FLOW_SIGNALS.")
        return
    if not config.INTRINIO_API_KEY:
        logging.warning("Options flow pipeline enabled but INTRINIO_API_KEY is missing.")
        return

    with options_flow_lock:
        if options_flow_started:
            return
        options_flow_poller = IntrinioOptionsFlowPoller(
            api_key=config.INTRINIO_API_KEY,
            endpoint_url=config.INTRINIO_UNUSUAL_ACTIVITY_URL,
            poll_seconds=config.OPTIONS_FLOW_POLL_SECONDS,
            min_premium=config.OPTIONS_FLOW_MIN_PREMIUM,
            max_items=config.OPTIONS_FLOW_MAX_ITEMS,
            emit_signal=emit_market_signal,
        )
        options_flow_poller.start()
        options_flow_started = True
        logging.info(
            "Options flow pipeline started (url=%s, min_premium=%s, poll=%ss).",
            config.INTRINIO_UNUSUAL_ACTIVITY_URL,
            config.OPTIONS_FLOW_MIN_PREMIUM,
            config.OPTIONS_FLOW_POLL_SECONDS,
        )


@app.route("/api/options-flow/recent", methods=["GET"])
def recent_options_flow_signals():
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 500))
    all_signals = list(market_signal_engine.recent_signals)
    filtered = [s for s in all_signals if s.get("type") == "BIG_OPTIONS_FLOW"]
    return jsonify({"signals": filtered[-limit:]}), 200


start_market_signal_pipeline()
start_options_flow_pipeline()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True
    )

