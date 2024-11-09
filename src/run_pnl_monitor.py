import threading
import logging
from datetime import datetime
import IBPortfolioTracker
import app
import os
logging.basicConfig(
                level=logging.debug,
                format='%(asctime)s - %(levelname)s - %(message)s'
            )

def main():
    # Create threads for IBPortfolioTracker.run() and app.run()
    thread1 = threading.Thread(target=IBPortfolioTracker.run)
    thread2 = threading.Thread(target=app.run)

    # Start the threads
    thread1.start()
    thread2.start()

    # Wait for both threads to finish
    thread1.join()
    thread2.join()

if __name__ == "__main__":
    main()
