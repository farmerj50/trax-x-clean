import pandas as pd
import numpy as np
import logging
from ta.momentum import RSIIndicator, WilliamsRIndicator
from ta.trend import MACD, EMAIndicator, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator, money_flow_index  # ✅ Keep money_flow_index!
from sklearn.preprocessing import StandardScaler
import time
import os

LOG_DIR = r"C:\Users\gabby\trax-x\backend\log_dir"
FINAL_AI_CSV_PATH = os.path.join(LOG_DIR, "final_ai_predictions.csv")

# ✅ Configure Logger
logger = logging.getLogger(__name__)
def compute_rsi(close_prices, window=14):
    """
    Compute RSI for a given series of closing prices.
    """
    return RSIIndicator(close=close_prices, window=window, fillna=True).rsi()

def compute_macd(close_prices):
    """
    Compute MACD (Moving Average Convergence Divergence).
    Returns: MACD line, Signal line, Histogram
    """
    macd = MACD(close=close_prices, window_slow=26, window_fast=12, window_sign=9, fillna=True)
    return macd.macd(), macd.macd_signal(), macd.macd_diff()

def preprocess_data_with_indicators(df):
    """
    Add advanced technical indicators and sentiment analysis.
    Returns:
        - Processed DataFrame (df)
        - Scaler (for LSTM feature standardization)
        - List of buy signals
    """
    try:
        df = df.copy()

        # ✅ Ensure timestamp is in datetime format
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

        # ✅ Ensure `ticker` column exists before processing
        if "ticker" not in df.columns:
            logger.warning("⚠️ 'ticker' column is missing in preprocess_data_with_indicators!")
        else:
            df["ticker"] = df["ticker"].astype(str)

        # ✅ Ensure required columns exist
        required_cols = ["open", "close", "high", "low", "volume"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"❌ Missing required columns: {missing_cols}")

        # ✅ Feature Engineering - Technical Indicators
        df["price_change"] = (df["close"] - df["open"]) / df["open"]
        df["volatility"] = (df["high"] - df["low"]) / df["low"]
        df["volume_surge"] = df["volume"] / df["volume"].rolling(window=5, min_periods=1).mean()

        df["rsi"] = RSIIndicator(close=df["close"], window=14, fillna=True).rsi()
        df["macd_line"] = MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9, fillna=True).macd()
        df["macd_signal"] = MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9, fillna=True).macd_signal()
        df["macd_diff"] = df["macd_line"] - df["macd_signal"]

        df["adx"] = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14, fillna=True).adx()
        df["atr"] = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14, fillna=True).average_true_range()
        df["mfi"] = money_flow_index(high=df["high"], low=df["low"], close=df["close"], volume=df["volume"], window=14, fillna=True)

        # ✅ Compute Buy Signal
        df["buy_signal"] = (
            ((df["rsi"] < 50) & (df["macd_diff"] > 0)) |
            ((df["adx"] > 15) & (df["macd_diff"] > 0)) |
            ((df["close"] < df["open"]) & (df["volume_surge"] > 1.1))
        ).astype(int)

        # ✅ Extract Buy Signals List
        buy_signals = df["buy_signal"].tolist()

        # ✅ Log Buy Signal Counts
        logger.info(f"📌 Total Buy Signals Detected: {df['buy_signal'].sum()}")

        return df, buy_signals

    except Exception as e:
        logger.error(f"❌ Error in preprocess_data_with_indicators: {e}")
        return pd.DataFrame(), []

def generate_trade_signals(data, sell_threshold=1.1):
    """
    ✅ Assigns entry & exit points based on real stock data before saving.
    ✅ Ensures values are passed correctly to candlestick API.
    """

    try:
        # ✅ Ensure required columns exist
        required_columns = ["open", "close", "high", "low", "volume", "ticker"]
        missing_cols = [col for col in required_columns if col not in data.columns]
        if missing_cols:
            raise ValueError(f"❌ Missing required columns in generate_trade_signals: {missing_cols}")

        # ✅ Use Open Price as Entry Point
        data["entry_point"] = data["open"]

        # ✅ Define Sell Price Thresholds (Example: 10% target gain)
        data["exit_point"] = data["entry_point"] * sell_threshold

        # ✅ Fill missing values safely
        data.fillna({"entry_point": 0, "exit_point": 0}, inplace=True)

        # 🔹 FIX: Save the modified DataFrame before returning
        data.to_csv(FINAL_AI_CSV_PATH, index=False)
        logging.info("✅ Entry/Exit points saved before returning data.")

        # ✅ Log generated trade signals
        logging.info(f"📌 Trade Signals Generated - Entry Points: {data['entry_point'].count()}, Exit Points: {data['exit_point'].count()}")

        return data

    except Exception as e:
        logging.error(f"❌ Error in generate_trade_signals: {e}", exc_info=True)
        return pd.DataFrame()
    
def preprocess_number_one_strategy(df: pd.DataFrame, float_limit: float = 50_000_000):
    try:
        df = df.copy()

        logger.info("🚀 Running Number One Picks strategy (updated)...")

        # 1. Filter by Float
        if "float" in df.columns:
            df = df[df["float"] < float_limit]
        else:
            logger.warning("⚠️ 'float' column missing!")
        if df.empty:
            return pd.DataFrame()

        # 2. MACD Calculation
        df["macd"], df["signal"], df["macd_hist"] = compute_macd(df["close"])
        df["macd_valid"] = df["macd"] > df["signal"]

        # 3. Candle Pattern
        df["is_green"] = df["close"] > df["open"]

        # Look for streaks of green candles, with no red interruption
        df["green_streak"] = df["is_green"].rolling(window=3, min_periods=1).apply(lambda x: (x.sum() == len(x)))

        # 4. Final Selection
        df["valid_trade"] = df["macd_valid"] & df["green_streak"].fillna(False)

        selected = df[df["valid_trade"]]

        logger.info(f"✅ Strategy matched {len(selected)} valid entries.")
        return selected

    except Exception as e:
        logger.error(f"❌ Error in preprocess_number_one_strategy: {e}", exc_info=True)
        return pd.DataFrame()












