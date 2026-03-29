import os
import joblib
import logging
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from tensorflow.keras.models import save_model, load_model  # type: ignore # ✅ Import both save & load model
from tensorflow.keras.layers import (  # type: ignore
    Input, Conv1D, BatchNormalization, Dropout, Dense, LSTM, 
    GlobalAveragePooling1D, LeakyReLU, LayerNormalization, MultiHeadAttention, 
    Bidirectional
)
from tensorflow.keras.models import Model  # type: ignore
from tensorflow.keras.optimizers import Adam  # type: ignore
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau  # type: ignore

# ✅ Import utilities
from utils.fetch_historical_performance import fetch_historical_data
from utils.indicators import preprocess_data_with_indicators
from utils.train_xgboost import train_xgboost_with_optuna
from sklearn.preprocessing import LabelEncoder

# ✅ Define paths for saving models
MODELS_DIR = "C:/Users/gabby/trax-x/backend/models"
XGB_MODEL_PATH = os.path.join(MODELS_DIR, "optimized_xgb_model.joblib")
XGB_FEATURES_PATH = os.path.join(MODELS_DIR, "xgb_features.pkl")
LSTM_MODEL_PATH_KERAS = os.path.join(MODELS_DIR, "cnn_lstm_attention_model.keras")  # ✅ Keras Format
LSTM_MODEL_PATH_H5 = os.path.join(MODELS_DIR, "cnn_lstm_attention_model.h5")  # ✅ H5 Format
LSTM_SCALER_PATH = os.path.join(MODELS_DIR, "cnn_lstm_attention_scaler.pkl")
TICKER_ENCODER_PATH = os.path.join(MODELS_DIR, "xgb_ticker_encoder.pkl")

# ✅ Ensure directory exists
os.makedirs(MODELS_DIR, exist_ok=True)

# ✅ Logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ✅ Cache for LSTM Model
lstm_cache = {"model": None, "scaler": None}



def preprocess_for_lstm(data, features, target, time_steps=50):
    """
    Prepares data for LSTM training.
    
    - Scales feature columns
    - Reshapes into (batch_size, time_steps, features)

    Returns:
    - X (numpy array): Scaled input sequences
    - y (numpy array): Target values
    - scaler (StandardScaler object): Used for feature scaling
    """
    try:
        if len(data) < time_steps:
            logger.warning(f"⚠️ Not enough data for LSTM: {len(data)} rows. Required: {time_steps}.")
            return None, None, None

        # ✅ Scale features
        scaler = StandardScaler()
        scaled_data = scaler.fit_transform(data[features])

        X, y = [], []
        for i in range(time_steps, len(scaled_data)):
            X.append(scaled_data[i - time_steps:i])
            y.append(data[target].iloc[i])

        return np.array(X), np.array(y), scaler

    except Exception as e:
        logger.error(f"❌ Error in preprocess_for_lstm: {e}")
        return None, None, None


def train_cnn_lstm_model():
    """
    Train a CNN-LSTM model with attention for stock price prediction.
    """
    try:
        logging.info("📌 Fetching historical stock data...")
        df = fetch_historical_data()
        if df is None or df.empty:
            raise ValueError("❌ ERROR: No historical stock data available for training.")

        # ✅ Preprocess Data
        df, _ = preprocess_data_with_indicators(df)

        # ✅ Ensure 'close' column exists (LSTM target variable)
        if "close" not in df.columns:
            logging.error("❌ 'close' column is missing after preprocessing! Cannot train LSTM.")
            raise KeyError("❌ Missing 'close' column in DataFrame.")

        # ✅ Load XGBoost-Trained Features (Ensures Consistency)
        try:
            trained_features = joblib.load(XGB_FEATURES_PATH)
            logging.info("✅ Loaded previously trained feature set from XGB.")
        except FileNotFoundError:
            trained_features = [
                "price_change", "volatility", "volume", "rsi",
                "macd_diff", "adx", "atr", "mfi", "macd_line", "macd_signal", "ticker_encoded"
            ]
            logging.info("⚠️ No saved feature list found. Using default feature set.")

        # ✅ Encode `ticker` and Include It as a Feature
        if "ticker" in df.columns:
            ticker_encoder = LabelEncoder()
            df["ticker_encoded"] = ticker_encoder.fit_transform(df["ticker"])
            joblib.dump(ticker_encoder, TICKER_ENCODER_PATH)  # Save for consistency
            logging.info(f"✅ Ticker encoding completed and saved at {TICKER_ENCODER_PATH}")
        else:
            logging.error("❌ ERROR: 'ticker' column missing from data. Training aborted.")
            return None

        # ✅ Add `ticker_encoded` to the list of training features
        trained_features.append("ticker_encoded")

        # ✅ Ensure all required features exist
        for f in trained_features:
            if f not in df.columns:
                df[f] = 0  # Fill missing features with zero

        # ✅ Save feature list for consistency
        joblib.dump(trained_features, XGB_FEATURES_PATH)
        logging.info(f"✅ Saved trained CNN-LSTM features: {trained_features}")

        # ✅ Extract Features and Target
        df = df[trained_features + ["close"]]  # Ensure 'close' column is included
        X = df[trained_features].values
        y = df["close"].shift(-1).fillna(df["close"])  # Predict next day's close price

        # ✅ Scale Data
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # ✅ Save Scaler
        joblib.dump(scaler, LSTM_SCALER_PATH)
        logging.info(f"✅ Saved CNN-LSTM Scaler.")

        # ✅ Reshape Data for LSTM (samples, time_steps, features)
        time_steps = 50  # Lookback period
        X_cnn_lstm, y_cnn_lstm = [], []
        for i in range(time_steps, len(X_scaled)):
            X_cnn_lstm.append(X_scaled[i - time_steps:i])
            y_cnn_lstm.append(y.iloc[i])

        X_cnn_lstm, y_cnn_lstm = np.array(X_cnn_lstm), np.array(y_cnn_lstm)

        logging.info(f"✅ Training CNN-LSTM with {X_cnn_lstm.shape[0]} samples and {X_cnn_lstm.shape[2]} features.")

        # ✅ Define Input Layer
        input_layer = Input(shape=(time_steps, X_cnn_lstm.shape[2]))

        # ✅ CNN Feature Extraction
        cnn_layer = Conv1D(filters=128, kernel_size=3, activation="relu")(input_layer)
        cnn_layer = BatchNormalization()(cnn_layer)
        cnn_layer = Dropout(0.3)(cnn_layer)

        # ✅ Attention Mechanism
        attention_layer = MultiHeadAttention(num_heads=4, key_dim=64)(cnn_layer, cnn_layer)
        attention_layer = LayerNormalization()(attention_layer)

        # ✅ LSTM Layers
        lstm_layer = Bidirectional(LSTM(128, return_sequences=True))(attention_layer)
        lstm_layer = BatchNormalization()(lstm_layer)
        lstm_layer = Dropout(0.3)(lstm_layer)

        lstm_layer = LSTM(64, return_sequences=True)(lstm_layer)
        lstm_layer = GlobalAveragePooling1D()(lstm_layer)

        # ✅ Fully Connected Dense Layers
        dense_layer = Dense(64, activation="relu")(lstm_layer)
        dense_layer = Dropout(0.2)(dense_layer)
        dense_layer = Dense(32, activation="swish")(dense_layer)
        output_layer = Dense(1)(dense_layer)

        # ✅ Compile Model
        model = Model(inputs=input_layer, outputs=output_layer)
        model.compile(optimizer=Adam(learning_rate=0.0001), loss="mean_squared_error")

        # ✅ Train Model
        early_stopping = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
        reduce_lr = ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=5)

        model.fit(X_cnn_lstm, y_cnn_lstm, epochs=300, batch_size=128, validation_split=0.2, verbose=1,
                  callbacks=[early_stopping, reduce_lr])

        # ✅ Save Model in Both Formats
        model.save(LSTM_MODEL_PATH_KERAS)
        model.save(LSTM_MODEL_PATH_H5, save_format="h5")  # ✅ H5 Format

        joblib.dump(scaler, LSTM_SCALER_PATH)

        logging.info(f"✅ Model saved at: {LSTM_MODEL_PATH_KERAS} and {LSTM_MODEL_PATH_H5}")
        logging.info(f"✅ Scaler saved at: {LSTM_SCALER_PATH}")

        return model, scaler

    except Exception as e:
        logging.error(f"❌ Error in train_cnn_lstm_model: {e}")
        raise
def load_lstm_model():
    """
    Load the LSTM model and scaler from disk if available.
    Tries loading from `.keras` first, then `.h5` if necessary.
    """
    try:
        if os.path.exists(LSTM_SCALER_PATH):
            scaler = joblib.load(LSTM_SCALER_PATH)
        else:
            print("⚠️ LSTM scaler not found.")
            return None, None

        # ✅ Try Loading `.keras` Model First
        if os.path.exists(LSTM_MODEL_PATH_KERAS):
            print(f"✅ Loading LSTM model from: {LSTM_MODEL_PATH_KERAS}")
            model = load_model(LSTM_MODEL_PATH_KERAS)
            return model, scaler

        # ✅ If `.keras` fails, Try Loading `.h5`
        elif os.path.exists(LSTM_MODEL_PATH_H5):
            print(f"✅ Loading LSTM model from: {LSTM_MODEL_PATH_H5}")
            model = load_model(LSTM_MODEL_PATH_H5)
            return model, scaler

        else:
            print("⚠️ No LSTM model found. Retrain needed.")
            return None, None

    except Exception as e:
        print(f"❌ Error in load_lstm_model: {e}")
        return None, None


def train_and_cache_lstm_model():
    """
    Train the LSTM model and cache it for future use.
    Ensures the model is only trained if it doesn't already exist.
    """
    try:
        logger.info("🚀 Checking for existing LSTM model before training...")

        # ✅ First, try to load an existing model
        model, scaler = load_lstm_model()
        if model is not None and scaler is not None:
            logger.info("✅ Pre-trained LSTM model detected. Skipping retraining.")
            lstm_cache["model"], lstm_cache["scaler"] = model, scaler  # Cache loaded model
            return model, scaler

        # 🚨 LOGGING ADDED: If model is missing, log the issue
        if model is None:
            logger.warning("⚠️ No LSTM model found! Expected at:")
            logger.warning(f"🔍 {LSTM_MODEL_PATH_KERAS}")
            logger.warning(f"🔍 {LSTM_MODEL_PATH_H5}")

        if scaler is None:
            logger.warning("⚠️ No LSTM scaler found! Expected at:")
            logger.warning(f"🔍 {LSTM_SCALER_PATH}")

        # ✅ If no model is found, proceed to training
        logger.warning("⚠️ No LSTM model found. Training a new model...")

        logger.info("📌 Fetching historical stock data...")
        data = fetch_historical_data()
        if data is None or data.empty:
            raise ValueError("❌ No historical data available for training.")

        # ✅ Preprocess Data (Ensure features are present)
        data, _ = preprocess_data_with_indicators(data)

        # ✅ Load trained XGBoost feature set to maintain consistency
        try:
            trained_features = joblib.load(XGB_FEATURES_PATH)
            logger.info(f"✅ Loaded trained feature set: {trained_features}")
        except FileNotFoundError:
            trained_features = [
                "price_change", "volatility", "volume", "rsi",
                "macd_diff", "adx", "atr", "mfi", "macd_line", "macd_signal"
            ]
            logger.warning("⚠️ No saved feature list found. Using default feature set.")

        # ✅ Ensure all required features exist in `data`
        for feature in trained_features:
            if feature not in data.columns:
                data[feature] = 0  # Fill missing features with zero

        # ✅ Save feature list for consistency
        joblib.dump(trained_features, XGB_FEATURES_PATH)
        logger.info(f"✅ Saved trained CNN-LSTM features: {trained_features}")

        # ✅ Extract only required features
        data = data[trained_features]

        # ✅ Train Model
        model, scaler = train_cnn_lstm_model()

        if model is None or scaler is None:
            logger.error("❌ Training failed! Model or scaler is None.")
            return None, None  # Prevents caching a broken model

        # ✅ Save Model & Scaler
        model.save(LSTM_MODEL_PATH_KERAS)
        joblib.dump(scaler, LSTM_SCALER_PATH)

        logger.info(f"✅ Model saved at: {LSTM_MODEL_PATH_KERAS}")
        logger.info(f"✅ Scaler saved at: {LSTM_SCALER_PATH}")

        # ✅ Cache the newly trained model
        lstm_cache["model"], lstm_cache["scaler"] = model, scaler
        return model, scaler

    except Exception as e:
        logger.error(f"❌ Error training and saving LSTM model: {e}", exc_info=True)
        return None, None  # Prevent app crash

def predict_next_day(model, recent_data, scaler, features):
    """
    Predicts the next day's closing price using the trained LSTM model.

    Args:
        model: The trained LSTM model.
        recent_data: The most recent data available as a DataFrame.
        scaler: The StandardScaler used for preprocessing.
        features: List of feature columns used in training.

    Returns:
        float: Predicted next day's closing price.
    """
    try:
        # ✅ Ensure there are enough rows for LSTM (e.g., last 50 time steps)
        time_steps = 50
        if len(recent_data) < time_steps:
            print(f"⚠️ Not enough historical data. Required: {time_steps}, Found: {len(recent_data)}")
            return None

        # ✅ Check if all required features exist in `recent_data`
        missing_features = [f for f in features if f not in recent_data.columns]
        if missing_features:
            print(f"❌ ERROR: Missing features in `recent_data`: {missing_features}")
            print(f"📌 Available Columns: {list(recent_data.columns)}")
            return None

        # ✅ Confirm feature shape before transformation
        expected_features = scaler.n_features_in_
        actual_features = len(features)

        print(f"📌 Expected features: {expected_features}, Provided features: {actual_features}")
        print(f"📌 Features Passed to Scaler: {features}")

        if expected_features != actual_features:
            print(f"❌ ERROR: Mismatch in feature count! Expected {expected_features}, but got {actual_features}.")
            return None

        # ✅ Select required features and scale them
        recent_features = recent_data[features].iloc[-time_steps:].values
        recent_features_scaled = scaler.transform(recent_features)

        # ✅ Reshape to match LSTM input shape (1 sample, 50 time steps, num_features)
        recent_features_scaled = np.array(recent_features_scaled).reshape(1, time_steps, len(features))

        # ✅ Make prediction
        predicted_price = model.predict(recent_features_scaled)[0][0]

        print(f"📌 LSTM Prediction for Next Day: {predicted_price}")
        return predicted_price

    except Exception as e:
        print(f"❌ Error in predict_next_day: {e}")
        return None

def check_and_train_models():
    """
    Ensures both XGBoost & LSTM models exist, retraining them if missing.
    """
    try:
        logging.info("🚀 Checking if models exist...")

        # ✅ CHECK & TRAIN XGBOOST
        if not os.path.exists(XGB_MODEL_PATH) or not os.path.exists(XGB_FEATURES_PATH):
            logging.warning("⚠️ XGBoost Model or Feature List Not Found! Training Now...")

            # 🔹 ADD DEBUGGING: Confirm execution starts
            logging.info("🚀 Triggering XGBoost Training in App...")

            best_model = train_xgboost_with_optuna()

            if best_model is None:
                logging.error("❌ ERROR: XGBoost Training Failed! Model is None.")
            elif os.path.exists(XGB_MODEL_PATH):
                logging.info("✅ XGBoost Model Trained and Saved Successfully!")
            else:
                logging.error("❌ ERROR: XGBoost Model File Missing After Training!")
                return  # 🔴 STOP if training failed

        else:
            logging.info(f"✅ XGBoost Model Found at {XGB_MODEL_PATH}. Loading...")
            best_model = joblib.load(XGB_MODEL_PATH)

        # ✅ CHECK & TRAIN LSTM
        model, scaler = load_lstm_model()

        if model is not None and scaler is not None:
            logging.info("✅ LSTM model loaded successfully.")
        else:
            logging.warning("⚠️ LSTM model or scaler missing! Retraining now...")
            train_and_cache_lstm_model()
            logging.info("✅ LSTM Model Trained Successfully!")

        logging.info("✅ Model check complete. Both XGBoost & LSTM are ready.")

    except Exception as e:
        logging.error(f"❌ Error in check_and_train_models: {e}", exc_info=True)

if __name__ == "__main__":
    logging.info("🚀 Running Model Training Script...")
    check_and_train_models()
    logging.info("✅ Training Completed!")