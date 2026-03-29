import pandas as pd
import logging
from utils.model_loader import load_xgb_model


def predict_next_day(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    model, feature_list = load_xgb_model()
    if model is None or not feature_list:
        logging.error("âŒ XGBoost model or feature list unavailable for next-day prediction.")
        return pd.DataFrame()

    X = df.reindex(columns=feature_list).fillna(0)

    probas = model.predict_proba(X)
    df["next_day_up_prob"] = probas[:, 1]

    return df
