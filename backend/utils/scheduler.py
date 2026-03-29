from apscheduler.schedulers.background import BackgroundScheduler
import requests
import atexit
import threading

# Shared cache to store results from periodic scans
scheduler_cache = {"stocks": []}
cache_lock = threading.Lock()

# Function for periodic stock scanning
def periodic_stock_scan():
    try:
        print("Running periodic stock scan...")
        response = requests.get("http://localhost:5000/api/scan-stocks?min_price=1&max_price=100", timeout=15)
        response.raise_for_status()
        candidates = response.json().get("candidates", [])

        # Cache the top 20 candidates
        with cache_lock:
            scheduler_cache["stocks"] = candidates[:20]
        
        print(f"Periodic stock scan completed. Found {len(candidates)} candidates.")
    except requests.exceptions.RequestException as e:
        print(f"HTTP error during periodic stock scan: {e}")
    except Exception as e:
        print(f"Error during periodic stock scan: {e}")

# Function to get cached stocks
def get_cached_stocks():
    with cache_lock:
        return scheduler_cache["stocks"]

# Initialize scheduler
def initialize_scheduler():
    scheduler = BackgroundScheduler()

    # Add the periodic stock scan job (every 5 minutes)
    scheduler.add_job(func=periodic_stock_scan, trigger="interval", minutes=5)

    # Start the scheduler
    scheduler.start()
    print("Scheduler started with periodic stock scan job.")

    # Ensure the scheduler shuts down gracefully on app exit
    atexit.register(lambda: scheduler.shutdown())
