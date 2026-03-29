import requests
def fetch_stock_performance(ticker, api_key):
    try:
        # Use the v3/reference/tickers/{ticker} endpoint
        reference_url = f"https://api.polygon.io/v3/reference/tickers/{ticker}?apiKey={api_key}"
        snapshot_url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}?apiKey={api_key}"

        # Fetch data from APIs
        reference_response = requests.get(reference_url, timeout=10)
        snapshot_response = requests.get(snapshot_url, timeout=10)

        # Validate responses
        reference_response.raise_for_status()
        snapshot_response.raise_for_status()

        # Extract data from responses
        reference_data = reference_response.json().get("results", {})
        snapshot_data = snapshot_response.json().get("ticker", {})

        # Prepare stock performance data
        stock_data = {
            "name": reference_data.get("name", "N/A"),
            "market_cap": reference_data.get("market_cap", "N/A"),
            "current_price": snapshot_data.get("lastTrade", {}).get("p", "N/A"),
            "change": snapshot_data.get("todaysChangePerc", "N/A"),
            "pe_ratio": reference_data.get("weighted_shares_outstanding", "N/A"),
            "week_52_high": snapshot_data.get("52wHigh", "N/A"),
            "week_52_low": snapshot_data.get("52wLow", "N/A"),
        }

        return stock_data
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error fetching stock performance for {ticker}: {e}")
