import requests
import pandas as pd
import logging
from datetime import datetime, timedelta
from cachetools import TTLCache
import os
import config

# ✅ Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ✅ Caching Mechanism (5-minute TTL)
historical_data_cache = TTLCache(maxsize=10, ttl=300)

# ✅ API Key for Polygon.io
POLYGON_API_KEY = config.POLYGON_API_KEY

def get_valid_date():
    """
    Get the most recent valid stock market date (no weekends or future dates).
    """
    today = datetime.utcnow()
    for i in range(7):  # ✅ Check last 7 days
        check_date = today - timedelta(days=i)
        if check_date.weekday() < 5:  # ✅ Monday-Friday (0-4)
            return check_date.strftime("%Y-%m-%d")
    return today.strftime("%Y-%m-%d")  # ✅ Fallback

def fetch_historical_data():
    """
    Fetch historical stock data from Polygon.io.
    Ensures it does not request today’s data, weekends, or future dates.
    """
    for i in range(720):  # ✅ Try fetching data for the last 360 days
        most_recent_date = datetime.utcnow() - timedelta(days=i)
        most_recent_date_str = most_recent_date.strftime("%Y-%m-%d")

        # ✅ Skip today's data (Polygon.io restricts same-day access)
        if most_recent_date.date() == datetime.utcnow().date():
            logging.info(f"🚫 Skipping today's data: {most_recent_date_str}")
            continue  # ✅ Skip today's date
        
        # ✅ Skip weekends (Saturday=5, Sunday=6)
        if most_recent_date.weekday() >= 5:
            logging.info(f"🚫 Skipping weekend: {most_recent_date_str}")
            continue  # ✅ Skip weekends
        
        logging.info(f"🔍 Attempting to fetch stock data for: {most_recent_date_str}")

        # ✅ Check cache first
        if most_recent_date_str in historical_data_cache:
            logging.info(f"✅ Returning cached data for {most_recent_date_str}")
            return historical_data_cache[most_recent_date_str]

        url = (
            f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/"
            f"{most_recent_date_str}?adjusted=true&apiKey={POLYGON_API_KEY}"
        )

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            # ✅ Ensure 'results' exists and contains data
            if "results" in data and data["results"]:
                df = pd.DataFrame(data["results"])  # ✅ Convert JSON to DataFrame

                # ✅ Rename columns for consistency
                rename_mapping = {
                    "T": "ticker",
                    "v": "volume",
                    "vw": "vwap",
                    "o": "open",
                    "c": "close",
                    "h": "high",
                    "l": "low",
                    "t": "timestamp",
                    "n": "trade_count",
                }
                df.rename(columns=rename_mapping, inplace=True)

                # ✅ Explicitly check `ticker` column BEFORE processing
                if "ticker" not in df.columns:
                    logging.error("❌ ERROR: 'ticker' column is missing in raw data!")
                    return pd.DataFrame(columns=["ticker", "volume", "vwap", "open", "close", "high", "low", "timestamp", "trade_count"])

                # ✅ Ensure `ticker` is a string & not missing values
                df["ticker"] = df["ticker"].astype(str)
                df = df[df["ticker"].notna()]  # Remove any missing ticker rows
                
                # ✅ Log fetched tickers for debugging
                unique_tickers = df["ticker"].unique()
                logging.info(f"📌 Tickers Fetched: {unique_tickers[:10]}")  # Show first 10 tickers

                # ✅ Cache and return the data
                historical_data_cache[most_recent_date_str] = df
                return df

            logging.warning(f"⚠️ No stock data found for {most_recent_date_str}")

        except requests.exceptions.Timeout:
            logging.error(f"❌ Timeout error while fetching data for {most_recent_date_str}")

        except requests.exceptions.HTTPError as http_err:
            logging.error(f"❌ HTTP error: {http_err}")

        except requests.exceptions.RequestException as req_err:
            logging.error(f"❌ Request error: {req_err}")

        except Exception as e:
            logging.error(f"❌ Unexpected error: {e}")

    logging.warning("❌ Unable to fetch stock data. Returning empty DataFrame.")
    return pd.DataFrame(columns=["ticker", "volume", "vwap", "open", "close", "high", "low", "timestamp", "trade_count"])
