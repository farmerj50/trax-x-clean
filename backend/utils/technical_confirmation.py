import pandas as pd
import logging


def confirm_technicals(df: pd.DataFrame) -> pd.Series:
    """
    Returns a boolean Series indicating which rows pass technical confirmation.
    Rules:
    - Today's close > yesterday's high (breakout)
    - Volume > 1.5x 10-day average
    - RSI between 50 and 70
    """
    logging.info("ðŸ§ª Running technical confirmation checks...")

    results = []
    index = []

    for i, row in df.iterrows():
        try:
            price_breakout = row["close"] > row["prev_high"]
            volume_surge = row["volume"] > 1.5 * row["avg_volume_10d"]
            rsi_check = 50 <= row["rsi"] <= 70

            passed = sum([price_breakout, volume_surge, rsi_check])
            results.append(passed >= 2)
        except Exception as e:
            logging.warning(f"âš ï¸ Failed confirmation check for {row.get('ticker', '?')}: {e}")
            results.append(False)
        index.append(i)

    confirmed = pd.Series(results, index=index)
    logging.info(f"âœ… {int(confirmed.sum())} stocks passed technical confirmation.")
    return confirmed
