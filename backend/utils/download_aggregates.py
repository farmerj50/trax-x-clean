import os
import shutil
import subprocess
from datetime import datetime

# === CONFIGURATION ===
MC_PATH = r"C:\mc\mc.exe"
GZIP_EXE = r"C:\mc\gzip-1.3.12-1-bin\bin\gzip.exe"
SOURCE_BUCKET = "s3polygon/flatfiles/us_stocks_sip/day_aggs_v1/2024/04/"
TEMP_FOLDER = r"C:\aggregates_day_temp"
FINAL_FOLDER = r"C:\Users\gabby\trax-x\backend\data\aggregates_day"
START_DAY = 1
END_DAY = 30

# === PREPARE DIRECTORIES ===
os.makedirs(TEMP_FOLDER, exist_ok=True)
os.makedirs(FINAL_FOLDER, exist_ok=True)

# === FUNCTION TO DOWNLOAD FILE ===
def download_file(day):
    file_name = f"2024-04-{day:02d}.csv.gz"
    src_path = os.path.join(SOURCE_BUCKET, file_name)
    dst_path = os.path.join(TEMP_FOLDER, file_name)
    print(f"\n=== Downloading {file_name} ===")

    result = subprocess.run(
        [MC_PATH, "cp", src_path, TEMP_FOLDER],
        capture_output=True, text=True
    )
    if "ERROR" in result.stderr:
        print(f"⚠️  {file_name} not found, skipping...")
        return False
    print(f"✅ {file_name} downloaded.")
    return True

# === FUNCTION TO DECOMPRESS FILE ===
def decompress_file(day):
    gz_path = os.path.join(TEMP_FOLDER, f"2024-04-{day:02d}.csv.gz")
    if os.path.exists(gz_path):
        print(f"Decompressing {gz_path}...")
        subprocess.run([GZIP_EXE, "-d", gz_path])
    else:
        print(f"⚠️  {gz_path} does not exist, skipping decompression.")

# === FUNCTION TO MOVE FILE ===
def move_file(day):
    csv_file = f"2024-04-{day:02d}.csv"
    src_csv_path = os.path.join(TEMP_FOLDER, csv_file)
    dst_csv_path = os.path.join(FINAL_FOLDER, csv_file)

    if os.path.exists(src_csv_path):
        shutil.move(src_csv_path, dst_csv_path)
        print(f"✅ {csv_file} moved to data folder.")
    else:
        print(f"⚠️  {csv_file} not found after decompression.")

# === MAIN PROCESS ===
def main():
    print("🚀 Starting Cody Python Automation...\n")
    
    for day in range(START_DAY, END_DAY + 1):
        if download_file(day):
            decompress_file(day)
            move_file(day)

    # Optional clean up
    if os.path.exists(TEMP_FOLDER):
        shutil.rmtree(TEMP_FOLDER)
    
    print("\n===================================")
    print("✅ All downloads, decompress and moves complete!")
    print(f"Files saved into: {FINAL_FOLDER}")
    print("===================================")

if __name__ == "__main__":
    main()
