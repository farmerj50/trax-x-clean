import os
import pandas as pd
from collections import defaultdict
import pickle
import json

# Directory containing the daily CSV files (under backend/data/aggregates_day)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(BASE_DIR, 'data', 'aggregates_day')

# Initialize a dictionary to hold trades data
trades_data = defaultdict(list)

# List all CSV files in the directory
files = sorted([f for f in os.listdir(data_dir) if f.endswith('.csv')])

print("Starting to process files...")

# Process each file (assuming files are named in order)
for file in files:
    print(f"Processing {file}")
    file_path = os.path.join(data_dir, file)
    df = pd.read_csv(file_path)
    # For each stock, store the date and relevant data
    for _, row in df.iterrows():
        ticker = row['ticker']
        date = pd.to_datetime(row['window_start'], unit='ns').date()
        trades = row['transactions']
        close_price = row['close']  # Make sure 'close' column exists
        trades_data[ticker].append({
            'date': date,
            'trades': trades,
            'close_price': close_price
        })

print("Finished processing files.")
print("Building lookup table...")

# Now, build the lookup table
lookup_table = defaultdict(dict)

for ticker, records in trades_data.items():
    df_ticker = pd.DataFrame(records)
    df_ticker.sort_values('date', inplace=True)
    df_ticker.set_index('date', inplace=True)

    df_ticker['price_diff'] = df_ticker['close_price'].pct_change() * 100

    # Shift trades to exclude the current day from rolling stats
    df_ticker['trades_shifted'] = df_ticker['trades'].shift(1)
    df_ticker['avg_trades'] = df_ticker['trades_shifted'].rolling(window=5).mean()
    df_ticker['std_trades'] = df_ticker['trades_shifted'].rolling(window=5).std()

    for date, row in df_ticker.iterrows():
        date_str = date.strftime('%Y-%m-%d')
        if pd.notnull(row['avg_trades']) and pd.notnull(row['std_trades']):
            lookup_table[ticker][date_str] = {
                'trades': row['trades'],
                'close_price': row['close_price'],
                'price_diff': row['price_diff'],
                'avg_trades': row['avg_trades'],
                'std_trades': row['std_trades']
            }
        else:
            lookup_table[ticker][date_str] = {
                'trades': row['trades'],
                'close_price': row['close_price'],
                'price_diff': row['price_diff'],
                'avg_trades': None,
                'std_trades': None
            }

print("Lookup table built successfully.")

# Save as JSON
with open('lookup_table.json', 'w') as f:
    json.dump(lookup_table, f, indent=4)

print("Lookup table saved to 'lookup_table.json'.")

# Save as Pickle (for fast loading later)
with open('lookup_table.pkl', 'wb') as f:
    pickle.dump(lookup_table, f)

print("Lookup table saved to 'lookup_table.pkl'.")
