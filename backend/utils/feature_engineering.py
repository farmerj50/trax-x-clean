# 📂 File: utils/feature_engineering.py
import pandas as pd

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    # 🔥 Basic Feature Engineering
    df['pct_change_1d'] = df['close'].pct_change(1)
    df['pct_change_5d'] = df['close'].pct_change(5)
    df['pct_change_10d'] = df['close'].pct_change(10)
    df['relative_volume'] = df['volume'] / df['volume'].rolling(10).mean()
    df['atr%'] = (df['high'] - df['low']) / df['close']
    df['distance_50ema'] = df['close'] / df['close'].ewm(span=50).mean()
    df['distance_200ema'] = df['close'] / df['close'].ewm(span=200).mean()
    df['days_since_20d_high'] = (
    df['close']
    .rolling(window=20)
    .apply(lambda x: int(x.iloc[-1] < x.max()), raw=False)
).fillna(0).cumsum()

    
    return df

# 📂 File: utils/market_regime.py
import yfinance as yf

def detect_market_regime():
    spy = yf.Ticker("SPY").history(period="3mo")["Close"]
    vix = yf.Ticker("^VIX").history(period="3mo")["Close"]

    bullish_spy = spy.iloc[-1] > spy.rolling(50).mean().iloc[-1]
    low_vix = vix.iloc[-1] < 20

    if bullish_spy and low_vix:
        return "bullish"
    elif not bullish_spy and vix.iloc[-1] > 25:
        return "bearish"
    else:
        return "neutral"

# 📂 File: utils/technical_confirmation.py
import pandas as pd

def technical_confirm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    conditions = (
        (df['close'] > df['high'].shift(1)) &
        (df['volume'] > 2 * df['volume'].rolling(10).mean())
    )
    
    confirmed = df[conditions]
    return confirmed

# 📂 File: models/model_utils.py
import numpy as np

def score_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    candidates = candidates.copy()

    # ⚡ Ranking formula
    candidates['rank_score'] = (
        candidates['next_day_signal'] * 0.4 +
        candidates['relative_volume'] * 0.2 +
        candidates['atr%'] * 0.2 +
        candidates['distance_50ema'] * 0.1 +
        candidates['distance_200ema'] * 0.1
    )

    return candidates.sort_values("rank_score", ascending=False)

# 🛠️ Integration Plan:
# 1. Pre-filter (price range, volume, volatility)
# 2. Add features
# 3. Market regime adjustment
# 4. Technical confirmation
# 5. Rank candidates and pick Top 3-5

# 👉 Next: I will build the orchestrator file that combines all these into a clean endpoint. Type `continue` 🚀
