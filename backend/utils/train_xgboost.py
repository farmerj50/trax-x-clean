import os
import joblib
import logging
import optuna
import pandas as pd
import matplotlib.pyplot as plt
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.utils.class_weight import compute_sample_weight
from utils.fetch_historical_performance import fetch_historical_data
from utils.indicators import preprocess_data_with_indicators
import xgboost as xgb
from sklearn.metrics import accuracy_score, classification_report
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import LabelEncoder


# ✅ Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ✅ Define Correct Model Paths
MODELS_DIR = r"C:\Users\gabby\trax-x\backend\models"
XGB_MODEL_PATH = os.path.join(MODELS_DIR, "optimized_xgb_model.joblib")
XGB_FEATURES_PATH = os.path.join(MODELS_DIR, "xgb_features.pkl")
LSTM_SCALER_PATH = os.path.join(MODELS_DIR, "cnn_lstm_attention_scaler.pkl")
TICKER_ENCODER_PATH = os.path.join(MODELS_DIR, "xgb_ticker_encoder.pkl")

# ✅ Ensure models directory exists
os.makedirs(MODELS_DIR, exist_ok=True)
def objective(trial, X, y):
    try:
        # ✅ Validate scale_pos_weight calculation
        pos_weight = (y == 0).sum() / max((y == 1).sum(), 1)  # Avoid division by zero
        logging.info(f"📌 Calculated scale_pos_weight: {pos_weight}")

        params = {
            "scale_pos_weight": pos_weight,
            "max_depth": trial.suggest_int("max_depth", 3, 12),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1),
            "n_estimators": trial.suggest_int("n_estimators", 300, 800),
        }

        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.15, random_state=42)
        model = XGBClassifier(**params, random_state=42, use_label_encoder=False, eval_metric="logloss")
        model.fit(X_train, y_train)

        return cross_val_score(model, X_val, y_val, cv=3, scoring="accuracy").mean()

    except Exception as e:
        logging.error(f"❌ ERROR in Optuna objective function: {e}")
        return 0

def load_training_data():
    """
    Loads and preprocesses training data for XGBoost.
    Returns:
        - X (features)
        - y (target labels)
    """
    try:
        # ✅ Fetch historical stock data
        df = fetch_historical_data()  

        # ✅ Apply feature engineering
        df, _ = preprocess_data_with_indicators(df)  

        # ✅ Define Features and Target
        features = [
            "ticker_encoded", "price_change", "volatility", "volume", "rsi", 
            "macd_diff", "adx", "atr", "mfi", "macd_line", "macd_signal"
        ]
        target = "buy_signal"  

        # ✅ Check if required features exist
        missing_features = [col for col in features if col not in df.columns]
        if missing_features:
            logging.warning(f"⚠️ Missing features detected: {missing_features}. Adding them with default value 0.")
            for feature in missing_features:
                df[feature] = 0  # Fill missing features with zero

        # ✅ Extract Features and Target
        X = df[features].fillna(0)  
        y = df[target]

        logging.info(f"✅ Training Data Loaded Successfully with shape: {X.shape}")

        # ✅ Load the scaler and check if it matches `X`
        if os.path.exists(LSTM_SCALER_PATH):
            scaler = joblib.load(LSTM_SCALER_PATH)
            logging.info(f"✅ StandardScaler loaded successfully.")

            # ✅ Check if the scaler was trained with the same number of features
            expected_features = scaler.n_features_in_
            actual_features = X.shape[1]

            if expected_features != actual_features:
                logging.error(f"❌ Feature mismatch: StandardScaler expects {expected_features} features, but got {actual_features}.")

            logging.info(f"📌 Features used for training: {list(X.columns)}")

        return X, y

    except Exception as e:
        logging.error(f"❌ ERROR loading training data: {e}")
        raise


def tune_xgboost_hyperparameters(X_train, y_train, n_trials=50):
    """Uses Optuna to find the best hyperparameters for XGBoost."""
    try:
        logging.info("📌 Starting XGBoost hyperparameter tuning with Optuna...")
        study = optuna.create_study(direction="maximize")
        study.optimize(lambda trial: objective(trial, X_train, y_train), n_trials=n_trials)

        if len(study.trials) == 0:
            logging.error("❌ ERROR: No trials were completed in Optuna.")
            return None, {}

        best_params = study.best_params
        logging.info(f"✅ Best XGBoost Parameters: {best_params}")

        sample_weights = compute_sample_weight(class_weight="balanced", y=y_train)
        best_model = XGBClassifier(**best_params, random_state=42, use_label_encoder=False)
        best_model.fit(X_train, y_train, sample_weight=sample_weights)
        return best_model, best_params

    except Exception as e:
        logging.error(f"❌ ERROR in tune_xgboost_hyperparameters: {e}")
        return None, {}

def plot_feature_importance(model, feature_names):
    """Plot the feature importance from the trained XGBoost model."""
    try:
        importance = model.get_booster().get_score(importance_type="weight")
        if not importance:
            logging.warning("⚠️ No feature importance found in model.")
            return

        importance_df = pd.DataFrame(importance.items(), columns=["Feature", "Importance"])
        importance_df = importance_df.sort_values(by="Importance", ascending=False)

        plt.figure(figsize=(10, 6))
        plt.barh(importance_df["Feature"], importance_df["Importance"], color="skyblue")
        plt.xlabel("Importance")
        plt.ylabel("Feature")
        plt.title("XGBoost Feature Importance")
        plt.gca().invert_yaxis()
        plt.show()

    except Exception as e:
        logging.error(f"❌ ERROR in plot_feature_importance: {e}")

def train_xgboost_with_optuna(force_retrain=False):
    try:
        logging.info("🚀 Starting XGBoost Training...")

        # ✅ Check if a trained model exists before retraining
        if not force_retrain and os.path.exists(XGB_MODEL_PATH):
            try:
                test_model = joblib.load(XGB_MODEL_PATH)
                logging.info(f"✅ XGBoost model already exists at {XGB_MODEL_PATH}. Skipping training.")
                return test_model
            except:
                logging.warning(f"⚠️ Corrupted or invalid model file found. Retraining XGBoost...")

        # ✅ Fetch & preprocess data
        df = fetch_historical_data()
        if df is None or df.empty:
            raise ValueError("❌ ERROR: No historical stock data available for training.")

        df, _ = preprocess_data_with_indicators(df)

        # ✅ Ensure 'ticker' exists before encoding
        if "ticker" not in df.columns:
            logging.error("❌ ERROR: 'ticker' column missing from dataset. Training aborted.")
            return None

        df["ticker"] = df["ticker"].astype(str)  # Ensure tickers are strings

        # ✅ Encode Ticker as a Feature
        if os.path.exists(TICKER_ENCODER_PATH):
            ticker_encoder = joblib.load(TICKER_ENCODER_PATH)
        else:
            ticker_encoder = LabelEncoder()
            ticker_encoder.fit(df["ticker"])
            joblib.dump(ticker_encoder, TICKER_ENCODER_PATH)  # Save encoder for later use
            logging.info(f"✅ Ticker encoder trained and saved at {TICKER_ENCODER_PATH}")

        df["ticker_encoded"] = ticker_encoder.transform(df["ticker"])

        # ✅ Define required features (INCLUDE ticker_encoded)
        required_features = [
            "price_change", "volatility", "volume", "rsi",
            "macd_diff", "adx", "atr", "mfi", "macd_line", "macd_signal", "ticker_encoded"
        ]

        # ✅ Ensure all required features exist
        missing_features = [feature for feature in required_features if feature not in df.columns]
        if missing_features:
            logging.warning(f"⚠️ Missing features detected: {missing_features}. Adding them with default value 0.")
            for feature in missing_features:
                df[feature] = 0  # Fill missing features with zero

        # ✅ Extract Features and Target
        X = df[required_features].fillna(0)  # Ensure no NaN values
        y = df["buy_signal"]

        # ✅ Store tickers separately before dropping from feature set
        tickers = df["ticker"].copy()

        logging.info(f"✅ Training XGBoost on {len(X)} samples with {len(required_features)} features.")

        # ✅ Train-Test Split (Keep tickers separate)
        try:
            X_train, X_test, y_train, y_test, tickers_train, tickers_test = train_test_split(
                X, y, tickers, test_size=0.2, random_state=42
            )
        except Exception as e:
            logging.error(f"❌ ERROR in train_test_split: {e}")
            return None

        # ✅ Save Feature Names (ENSURE ticker_encoded is included properly)
        joblib.dump(required_features, XGB_FEATURES_PATH)
        logging.info(f"✅ Saved trained feature order at {XGB_FEATURES_PATH}")

        # ✅ Compute sample weights for training
        sample_weights = compute_sample_weight(class_weight="balanced", y=y_train)

        # ✅ Perform Hyperparameter Tuning with Optuna
        best_model, best_params = tune_xgboost_hyperparameters(X_train, y_train)

        # ✅ Confirm Training Before Saving
        if best_model:
            joblib.dump(best_model, XGB_MODEL_PATH)
            logging.info(f"✅ XGBoost Model trained and saved at: {XGB_MODEL_PATH}")
            return best_model
        else:
            logging.error("❌ ERROR: Model training failed. Not saving.")
            return None

    except Exception as e:
        logging.error(f"❌ ERROR in train_xgboost_with_optuna: {e}", exc_info=True)
        return None

if __name__ == "__main__":
    train_xgboost_with_optuna()