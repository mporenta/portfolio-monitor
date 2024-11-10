# ib_base.py
import logging
from ib_async import *
from typing import *

class IBBase:
    def __init__(self, client_id: int):
        self.ib = IB()
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        util.logToConsole(level=30)
        
        try:
            self.ib.connect("127.0.0.1", 4002, clientId=client_id)
            self.logger.info("Connected successfully to IB Gateway")
            
            self.ib.waitOnUpdate(timeout=2)
            accounts = self.ib.managedAccounts()
            
            if not accounts:
                raise Exception("No managed accounts available")
                
            self.account = accounts[0]
            self.logger.info(f"Using account {self.account}")
            
        except Exception as e:
            self.logger.error(f"Initialization failed: {str(e)}")
            raise
