
from operator import is_
import requests
import json
from ib_async import *
from ib_async import util
from typing import *
from datetime import datetime
import pytz 
import os
from dotenv import load_dotenv
import time
from time import sleep
import logging
from typing import Optional, List
log_file_path = os.path.join(os.path.dirname(__file__), 'pnl.log')
logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file_path),
                logging.StreamHandler()
            ]
        )
logger = logging.getLogger(__name__)

ib = IB()
load_dotenv()
    
       # Then set connection parameters
host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')  # Default to localhost if not set
port = int(os.getenv('TBOT_IBKR_PORT', '4002'))
client_id = 33







def close_all_positions(portfolio_items):
    try:
        # First attempt with original host
        ib.connect(
            host=host,
            port=port,
            clientId=client_id
        )
        logger.info(f"Connected to IB Gateway at {host}:{port} with client ID {client_id}")
       
            
    
        
        """Close all positions based on the data in the database."""
        # Fetch positions data from the database instead of using `ib.portfolio()`
        #portfolio_items = fetch_latest_positions_data()
        portfolio_items
        for item in portfolio_items:
            symbol = item.contract.symbol
            pos = item.position
        if pos == 0:
         
            #logger.info("No positions to close.")
            #return
            
       
            logger.info(f" No Positions for {symbol}")

            action = 'BUY' if pos < 0 else 'SELL'
            quantity = abs(pos)

            # Example contract setup - modify as needed
            contract = Contract(symbol=symbol, exchange='SMART', secType='STK', currency='USD')
                
            logger.debug(f"Placing MarketOrder for {symbol}")
            order = MarketOrder(action=action, totalQuantity=quantity, tif='GTC', outsideRth = True)
                    
            # Place the order and update the order fill in the database
            trade = ib.placeOrder(contract, order)
            #ib.sleep(30)
                
            logger.info(f"Order placed and recorded for {trade}")
        
        ib.sleep(3)
        logger.info("Positions closed successfully")
        logger.info("Disconnecting from IB Gateway")
        return ib.disconnect()
   
       

    except Exception as e:
            logger.error(f"Error creating order for {symbol}: {str(e)}")

            

    
    






ib.run()