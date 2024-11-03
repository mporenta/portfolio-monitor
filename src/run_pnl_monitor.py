import logging
import sys
from pathlib import Path
import threading
import time
from datetime import datetime

from pnl_monitor import IBPortfolioTracker
from pnl_database_observer import PnLDatabaseObserver

# Create necessary directories
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS_DIR / 'pnl_monitor.log')
    ]
)

logger = logging.getLogger(__name__)

def record_updates(tracker: IBPortfolioTracker, observer: PnLDatabaseObserver):
    """Record updates to database periodically"""
    while True:
        try:
            if tracker.ib.isConnected():
                observer.record_pnl_update(tracker)
            time.sleep(5)  # Record every 5 seconds
        except Exception as e:
            logger.error(f"Error recording update: {e}")
            time.sleep(5)

def main():
    try:
        # Initialize database observer
        db_path = str(DATA_DIR / "pnl_monitor.db")
        observer = PnLDatabaseObserver(db_path=db_path)
        logger.info("Database observer initialized")

        # Initialize portfolio tracker
        tracker = IBPortfolioTracker()
        logger.info("Portfolio tracker initialized")

        # Start database recording thread
        record_thread = threading.Thread(
            target=record_updates,
            args=(tracker, observer),
            daemon=True
        )
        record_thread.start()
        logger.info("Database recording thread started")

        # Run the portfolio tracker
        tracker.run()

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()