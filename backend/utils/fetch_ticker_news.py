import requests
import config

# Polygon.io API Key
POLYGON_API_KEY = config.POLYGON_API_KEY

def fetch_ticker_news(ticker, limit=5):
    """
    Fetch the latest news articles for a specific stock ticker.

    Args:
        ticker (str): The stock ticker symbol.
        limit (int): Number of articles to fetch (default is 5).

    Returns:
        list: A list of news articles or an empty list if an error occurs.
    """
    if not ticker:
        raise ValueError("Ticker is required")

    url = f"https://api.polygon.io/v2/reference/news?ticker={ticker}&limit={limit}&apiKey={POLYGON_API_KEY}"
    
    try:
        headers = {"Accept": "application/json"}  # Ensure JSON response
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Raise an error for bad responses (4xx, 5xx)
        
        # ✅ Debug: Print raw response
        #print("📌 Raw API Response:", response.text[:200])  # Print first 200 chars

        data = response.json()  # Convert response to JSON

        # ✅ Debug: Print parsed JSON
       # print("📌 Parsed JSON:", data)

        # Ensure response contains the expected "results" key
        if not isinstance(data, dict) or "results" not in data:
            print(f"⚠️ Unexpected response format: {data}")
            return []

        return data["results"]

    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching news for {ticker}: {e}")
        return []
