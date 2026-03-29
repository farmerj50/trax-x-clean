import requests
import pandas as pd
import logging
from datetime import datetime, timedelta
import time
import config

API_KEY = config.POLYGON_API_KEY

def get_polygon_ohlcv(symbol: str, days: int = 90, retries: int = 2, timeout: int = 5) -> pd.DataFrame:
    """
    Fetch OHLCV data from Polygon API with retry and timeout handling.
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/"
        f"{start_date}/{end_date}?adjusted=true&sort=asc&limit={days}&apiKey={API_KEY}"
    )

    for attempt in range(retries + 1):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            data = response.json().get("results", [])

            if not data:
                raise ValueError(f"No OHLCV data found for {symbol}")

            df = pd.DataFrame(data)
            df['t'] = pd.to_datetime(df['t'], unit='ms')
            df.rename(columns={'c': 'close'}, inplace=True)

            return df[['t', 'close']]

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logging.warning(f"⏱️ Timeout for {symbol} (attempt {attempt + 1}/{retries + 1}): {e}")
            time.sleep(1)
        except Exception as e:
            logging.error(f"❌ Failed fetching OHLCV for {symbol}: {e}")
            break

    raise ValueError(f"❌ Exhausted retries for {symbol}")

def detect_market_regime() -> str:
    """
    Analyze SPY & VIX data from Polygon to determine current market regime.
    """
    logging.info("📈 Detecting market regime using Polygon.io...")

    try:
        spy = get_polygon_ohlcv("SPY")
        vix = get_polygon_ohlcv("VIX")  # Adjust if your plan uses a different symbol

        if len(spy) < 50:
            raise ValueError("Not enough SPY data to compute 50-day MA")

        spy_ma50 = spy['close'].rolling(50).mean()
        spy_latest = spy['close'].iloc[-1]
        spy_ma50_latest = spy_ma50.iloc[-1]
        vix_latest = vix['close'].iloc[-1]

        logging.info(f"SPY: {spy_latest:.2f}, MA50: {spy_ma50_latest:.2f}, VIX: {vix_latest:.2f}")

        bullish_spy = spy_latest > spy_ma50_latest
        low_vix = vix_latest < 20

        if bullish_spy and low_vix:
            return "bullish"
        elif not bullish_spy and vix_latest > 25:
            return "bearish"
        else:
            return "neutral"

    except Exception as e:
        logging.error(f"❌ Market regime detection failed: {e}")
        return "neutral"
