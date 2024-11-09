import threading
import logging
import asyncio
from datetime import datetime
from pnl_monitor import IBPortfolioTracker
from app import run_flask_app
import os
import signal
import sys

log_file_path = os.path.join(os.path.dirname(__file__), 'main.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Global flag for shutdown
shutdown_flag = threading.Event()

def signal_handler(signum, frame):
    logger.info("Shutdown signal received")
    shutdown_flag.set()

def run_portfolio_tracker():
    """Wrapper function to create and run portfolio tracker instance"""
    # Set up a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        portfolio_tracker = IBPortfolioTracker()
        while not shutdown_flag.is_set():
            try:
                portfolio_tracker.run()
            except Exception as e:
                logger.error(f"Portfolio tracker error: {str(e)}")
                if not shutdown_flag.is_set():
                    logger.info("Attempting to restart portfolio tracker...")
                    continue
                break
    except Exception as e:
        logger.error(f"Portfolio tracker failed: {str(e)}")
    finally:
        loop.close()

def run_flask():
    """Wrapper function to run Flask app"""
    try:
        run_flask_app()
    except Exception as e:
        logger.error(f"Flask app failed: {str(e)}")

def main():
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create threads
    thread1 = threading.Thread(target=run_portfolio_tracker, name="IBThread")
    thread2 = threading.Thread(target=run_flask, name="FlaskThread", daemon=True)
    
    try:
        # Start the threads
        thread1.start()
        thread2.start()
        
        # Wait for shutdown signal
        while not shutdown_flag.is_set():
            thread1.join(timeout=1.0)
            if not thread1.is_alive():
                break
            
    except Exception as e:
        logger.error(f"Error in main thread: {str(e)}")
    finally:
        # Ensure clean shutdown
        shutdown_flag.set()
        logger.info("Shutting down threads...")
        
        # Give threads time to clean up
        thread1.join(timeout=5.0)
        if thread1.is_alive():
            logger.warning("IB thread did not shut down cleanly")
        
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"__main__ failed: {str(e)}")
    sys.exit(0)
