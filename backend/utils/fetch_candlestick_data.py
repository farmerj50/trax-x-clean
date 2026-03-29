import time
import logging
import pandas as pd
from utils.fetch_historical_performance import fetch_historical_data
from utils.indicators import generate_trade_signals, compute_rsi, compute_macd
from utils.indicators import preprocess_data_with_indicators
import os

LOG_DIR = r"C:\Users\gabby\trax-x\backend\log_dir"
FILTERED_CSV_PATH = os.path.join(LOG_DIR, "filtered_before_xgboost.csv")
XGB_CSV_PATH = os.path.join(LOG_DIR, "filtered_after_xgboost.csv")
FINAL_AI_CSV_PATH = os.path.join(LOG_DIR, "final_ai_predictions.csv")

MAX_RETRIES = 3  # 🔄 Maximum retry attempts
WAIT_TIME = 2  # ⏳ Wait time between retries (in seconds)

def get_signal_price(stock_data, signal_column):
    """
    Retrieve the price for the first occurrence of a given signal.
    Retries up to MAX_RETRIES times with a WAIT_TIME delay.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        signal_idx = stock_data[stock_data[signal_column] == 1].index.min()

        if pd.notna(signal_idx) and signal_idx in stock_data.index:
            price = float(stock_data.loc[signal_idx, "close"])
            logging.info(f"✅ {signal_column} found on attempt {attempt}: {price}")
            return price
        
        logging.warning(f"⚠️ Attempt {attempt}: {signal_column} not found, retrying...")
        time.sleep(WAIT_TIME)  # ⏳ Wait before retrying
    
    logging.error(f"❌ Failed to find {signal_column} after {MAX_RETRIES} attempts.")
    return "N/A"  # 🚨 If all retries fail, return "N/A"

import time
import logging
import pandas as pd

MAX_RETRIES = 3  # 🔄 Maximum retry attempts
WAIT_TIME = 2  # ⏳ Wait time between retries (in seconds)

def fetch_candlestick_data(tickers):
    """
    Fetch candlestick data for the final AI-selected stocks.
    Ensures entry & exit points are properly assigned and saved, with retry logic.
    """
    try:
        logging.info(f"📌 Fetching candlestick data for batch: {tickers}")

        # ✅ Load Final AI Predictions with retries
        for attempt in range(1, MAX_RETRIES + 1):
            final_ai_predictions = pd.read_csv(FINAL_AI_CSV_PATH)

            # ✅ Check if entry/exit points exist
            if "entry_point" in final_ai_predictions and "exit_point" in final_ai_predictions:
                if final_ai_predictions["entry_point"].notna().all() and final_ai_predictions["exit_point"].notna().all():
                    logging.info("✅ Entry & Exit points detected in CSV. Proceeding...")
                    break  # Exit retry loop if values are present

            logging.warning(f"⚠️ Attempt {attempt}: 'entry_point' or 'exit_point' missing. Recalculating...")

            # 🔄 Compute Entry & Exit Points
            final_ai_predictions["entry_point"] = final_ai_predictions["open"]
            final_ai_predictions["exit_point"] = final_ai_predictions["entry_point"] * 1.05  # Sell at 5% profit target

            # ✅ Save updated CSV with entry/exit points
            final_ai_predictions.to_csv(FINAL_AI_CSV_PATH, index=False)
            logging.info("✅ Entry & Exit points successfully computed and saved.")

            # ⏳ Wait before retrying (if needed)
            if attempt < MAX_RETRIES:
                logging.info(f"🔄 Waiting {WAIT_TIME} seconds before retrying...")
                time.sleep(WAIT_TIME)

        response_data = {}

        for ticker in tickers:
            stock_data = final_ai_predictions[final_ai_predictions["ticker"] == ticker].copy()

            if stock_data.empty:
                logging.warning(f"⚠️ No valid data found for {ticker}, skipping.")
                response_data[ticker] = {
                    "dates": [], "open": [], "high": [], "low": [], "close": [],
                    "entry_point": "N/A", "exit_point": "N/A"
                }
                continue

            # ✅ Convert timestamp to datetime format
            stock_data["timestamp"] = pd.to_datetime(stock_data["timestamp"], errors="coerce")
            stock_data.dropna(subset=["timestamp"], inplace=True)

            # ✅ Assign Entry & Exit Prices from Updated CSV
            entry_price = stock_data["entry_point"].values[0] if "entry_point" in stock_data else "N/A"
            exit_price = stock_data["exit_point"].values[0] if "exit_point" in stock_data else "N/A"

            # ✅ Log values to confirm correctness
            logging.info(f"🔍 {ticker} - Entry: {entry_price}, Exit: {exit_price}")

            response_data[ticker] = {
                "dates": stock_data["timestamp"].dt.strftime('%Y-%m-%d').tolist(),
                "open": stock_data["open"].tolist(),
                "high": stock_data["high"].tolist(),
                "low": stock_data["low"].tolist(),
                "close": stock_data["close"].tolist(),
                "entry_point": entry_price,
                "exit_point": exit_price,
            }

        logging.info(f"✅ Successfully processed tickers: {tickers}")
        return response_data, 200

    except Exception as e:
        logging.error(f"❌ Error in fetch_candlestick_data: {e}", exc_info=True)
        return {"error": "Failed to fetch stock data"}, 500






