# backend/utils/move_aggregates.py (you can create this file)

import shutil
import os

# Paths
source_folder = r'C:\aggregates_day'
destination_folder = r'C:\Users\gabby\trax-x\backend\data\aggregates_day'

# Make destination if not exists
os.makedirs(destination_folder, exist_ok=True)

# Copy each CSV file
for filename in os.listdir(source_folder):
    if filename.endswith('.csv'):
        src_path = os.path.join(source_folder, filename)
        dst_path = os.path.join(destination_folder, filename)
        shutil.copy(src_path, dst_path)
        print(f"Copied {filename} to data folder.")

print("✅ All files moved successfully!")
