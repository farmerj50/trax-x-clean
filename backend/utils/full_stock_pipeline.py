import pandas as pd
import logging
import joblib

# Absolute imports from your app structure
from utils.pre_scan_filter import pre_scan_filter
from utils.market_regime import detect_market_regime
from utils.feature_engineering import engineer_features
from utils.feature_contract import validate_features
from utils.model_anomaly_detector import detect_anomalies
from utils.model_next_day_predictor import predict_next_day
from utils.technical_confirmation import confirm_technicals
from utils.ranking_system import rank_candidates
from utils.cashflow_quality import annotate_cashflow_quality

# Load anomaly model
ANOMALY_MODEL_PATH = r"C:\Users\gabby\trax-x\backend\models\anomaly_model.pkl"
anomaly_model = joblib.load(ANOMALY_MODEL_PATH)


def full_stock_pipeline(raw_data: pd.DataFrame) -> pd.DataFrame:
    logging.info("ðŸš€ Starting Full Stock Picking Pipeline...")

    # 1. Pre-Scan Filter (volume, price, etc.)
    clean_data = pre_scan_filter(raw_data)
    if clean_data.empty:
        logging.warning("âš ï¸ No stocks passed pre-scan filters.")
        return pd.DataFrame()

    # 2. Market Regime Detection
    regime = detect_market_regime()
    logging.info(f"ðŸ“Š Detected Market Regime: {regime}")

    # 3. Feature Engineering
    features = engineer_features(clean_data)
    features = validate_features(features, "full_pipeline")
    logging.info(f"ðŸ§  Engineered features shape: {features.shape}")

    # 4. Anomaly Detection using Isolation Forest
    try:
        anomalies = detect_anomalies(features, anomaly_model)
    except ValueError as ve:
        logging.error(f"âŒ Feature mismatch during anomaly detection: {ve}")
        return pd.DataFrame()

    if anomalies.empty:
        logging.warning("âš ï¸ No anomalies detected.")
        return pd.DataFrame()

    # 5. Next-Day Prediction (model loads internally)
    predictions = predict_next_day(anomalies)
    if predictions.empty:
        logging.warning("âš ï¸ No bullish next-day predictions.")
        return pd.DataFrame()

    # 6. Technical Confirmation tag (do not filter)
    predictions["tech_confirmed"] = confirm_technicals(predictions)

    # 7. Final Ranking
    ranked = rank_candidates(predictions, regime)
    if ranked.empty:
        logging.warning("âš ï¸ No candidates passed ranking filter.")
        return pd.DataFrame()

    ranked["rank_score"] = ranked["rank_score"] + ranked["tech_confirmed"].astype(int) * 0.1

    if regime == "bearish":
        ranked["rank_score"] *= 0.8
    elif regime == "bullish":
        ranked["rank_score"] *= 1.1

    ranked = annotate_cashflow_quality(ranked)
    ranked.loc[ranked["quality_tag"] == "cashflow_strong", "rank_score"] *= 1.10
    ranked.loc[ranked["quality_tag"] == "cashflow_positive", "rank_score"] *= 1.06
    ranked.loc[ranked["quality_tag"] == "ocf_only", "rank_score"] *= 1.02

    ranked = ranked.sort_values("rank_score", ascending=False)

    # 8. Select Top Picks
    final_picks = ranked.head(5)
    logging.info(f"âœ… Pipeline Completed. Final picks: {final_picks['ticker'].tolist()}")

    return final_picks


# Example test run
if __name__ == "__main__":
    try:
        raw_df = pd.read_csv("aggregates_day/sample_market_data.csv")
        final_watchlist = full_stock_pipeline(raw_df)
        print(final_watchlist)
    except Exception as e:
        logging.error(f"âŒ Pipeline crashed: {e}", exc_info=True)
