import os
import joblib
from tensorflow.keras.models import load_model # type: ignore

# ✅ Utility function to delete existing models
def delete_existing_model(file_path):
    """Deletes the existing model file to prevent duplication issues."""
    if os.path.exists(file_path):
        os.remove(file_path)
        print(f"🗑️ Deleted old model file: {file_path}")
