# 📂 utils/polygon_data.py

import requests
import pandas as pd
from datetime import datetime, timedelta
import config

POLYGON_API_KEY = config.POLYGON_API_KEY

def fetch_ohlcv_batch(tickers: list, days: int = 30) -> pd.DataFrame:
    """
    Fetch OHLCV data for a list of tickers from Polygon.io.
    Returns a combined DataFrame with a 'ticker' column.
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)

    all_data = []

    for ticker in tickers:
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
            f"{start_date}/{end_date}?adjusted=true&sort=asc&limit={days}&apiKey={POLYGON_API_KEY}"
        )
        try:
            resp = requests.get(url)
            resp.raise_for_status()
            results = resp.json().get("results", [])

            if not results:
                continue

            df = pd.DataFrame(results)
            df['t'] = pd.to_datetime(df['t'], unit='ms')
            df['ticker'] = ticker
            df.rename(columns={
                'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'
            }, inplace=True)
            all_data.append(df)

        except Exception as e:
            print(f"❌ Failed for {ticker}: {e}")

    if not all_data:
        return pd.DataFrame()

    return pd.concat(all_data, ignore_index=True)
