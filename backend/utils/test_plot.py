import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import mplfinance as mpf

# Import the function from your main script
from app import plot_candlestick_chart  # Replace "your_script" with the actual filename

# ✅ Configure Logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# ✅ Generate Test Data (Simulating AI Predictions with Entry/Exit Points)
def generate_test_data():
    num_days = 30
    dates = [datetime.today() - timedelta(days=i) for i in range(num_days)]
    open_prices = np.random.uniform(90, 110, num_days)
    high_prices = open_prices + np.random.uniform(1, 5, num_days)
    low_prices = open_prices - np.random.uniform(1, 5, num_days)
    close_prices = np.random.uniform(low_prices, high_prices, num_days)

    data = pd.DataFrame({
        "date": dates,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "buy_signal": np.random.choice([0, 1], num_days),
        "sell_signal": np.random.choice([0, 1], num_days),
    })

    data.set_index("date", inplace=True)
    return data

# ✅ Generate Sample Data
test_data = generate_test_data()

# ✅ Test Function Call
logging.info("🚀 Testing Candlestick Chart Plotting...")
plot_candlestick_chart(test_data, "TEST")

# ✅ Show Plot
plt.show()
