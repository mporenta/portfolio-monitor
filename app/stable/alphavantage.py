# pnl_monitor.py

from operator import is_
import requests
import json
from ib_async import IB, MarketOrder, LimitOrder, PnL, PortfolioItem, AccountValue, Contract, Trade
from ib_async import util, Position
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
log_level = os.getenv('TBOT_LOGLEVEL', 'INFO')
api_key = 'LX4G4DLW7MKJ9N37'
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)




class IBClient:
    def __init__(self):
        self.ib = IB()
        self.account: Optional[str] = None
        self.daily_pnl = 0.0
        self.total_unrealized_pnl = 0.0
        self.total_realized_pnl = 0.0
        self.net_liquidation = 0.0
        self.positions: List = []
        self.portfolio_items = []
        self.pnl = PnL()
    
        self.risk_amount = 0.0
        self.closing_initiated = False
        self.closed_positions = set()  # Track which positions have been closed
               # Load environment variables first
        load_dotenv()
    
       # Then set connection parameters
        self.host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')  # Default to localhost if not set
        self.port = int(os.getenv('TBOT_IBKR_PORT', '4002'))
        self.client_id = 69
        self.risk_percent = float(os.getenv('RISK_PERCENT', 0.01))
        self.token = os.getenv('TVWB_UNIQUE_KEY')
        
        # Logger setup
        self.logger = None
        # Subscribe to account value updates
        print(f"risk_amount {self.risk_amount}")
        self.ib.accountValueEvent += self.on_account_value_update
        self.ib.pnlEvent += self.on_pnl_update
    
  
    
    def connect(self):
        """
        Establish connection to IB Gateway.
        Retries with localhost (127.0.0.1) if initial connection fails with getaddrinfo error.
        """
        try:
           
            self.logger = logging.getLogger(__name__)
        
            try:
                # First attempt with original host
                self.ib.connect(
                    host=self.host,
                    port=self.port,
                    clientId=self.client_id
                )
                self.logger.info(f"Connected to IB Gateway at {self.host}:{self.port} with client ID {self.client_id}")
                print(f"risk_amount {self.risk_amount}")
                return True
            
            except Exception as e:
                # Check if the error message contains the getaddrinfo failed message
                if 'getaddrinfo failed' in str(e):
                    self.logger.warning(f"Connection failed with {self.host}, retrying with localhost (127.0.0.1)")
                    self.host = '127.0.0.1'  # Update host to localhost
                    self.ib.connect(
                        host=self.host,
                        port=self.port,
                        clientId=self.client_id
                    )
                    self.logger.info(f"Connected to IB Gateway at {self.host}:{self.port} with client ID {self.client_id}")
                    return True
                else:
                    raise  # Re-raise if it's a different error
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to connect to IB Gateway: {e}")

            return False
 
     

    # Example usage
    # Replace with your actual API key
   
    
    def subscribe_events(self):
        """Subscribe to order and PnL events, and initialize account."""
        self.ib.pnlEvent += self.on_pnl_update
        self.ib.newOrderEvent += self.on_new_order
        print(f"risk_amount {self.risk_amount}")
        accounts = self.ib.managedAccounts()
        
        if not accounts:
            self.logger.error("No managed accounts available.")
            return

        self.account = accounts[0]
        if self.account:
            self.ib.reqPnL(self.account)
        else:
            self.logger.error("Account not found; cannot subscribe to PnL updates.")
            
    def on_account_value_update(self, account_value: AccountValue):
        """Update stored NetLiquidation whenever it changes."""
        if account_value.tag == "NetLiquidation":
            self.net_liquidation = float(account_value.value)
            self.logger.debug(f"NetLiquidation updated: ${self.net_liquidation:,.2f}")
        
    def on_new_order(self, trade: Trade):
        """Callback for new orders."""
        self.logger.info(f"New order placed: {trade}")
    
    def on_pnl_update(self, pnl: PnL):
        """Handle PnL updates and check conditions."""
        try:
            # Update PnL values
            self.daily_pnl = float(pnl.dailyPnL or 0.0)
            self.total_unrealized_pnl = float(pnl.unrealizedPnL or 0.0)
            self.total_realized_pnl = float(pnl.realizedPnL or 0.0)
            
            self.logger.debug(f"Daily PnL: ${self.daily_pnl:,.2f}, Net Liquidation: ${self.net_liquidation:,.2f}")

            # Update portfolio items
            self.portfolio_items = self.ib.portfolio(self.account)
            
            # Process trades and orders
            trades = self.ib.trades()
            orders = self.ib.openOrders()
            
            # Insert trade data
            
            
       
            # Check positions and conditions
            for item in self.portfolio_items:
                if item.position != 0:
                    if self.check_pnl_conditions(pnl):
                        self.logger.info(f"PnL conditions met for {item.contract.symbol}")
                        
        except Exception as e:
            self.logger.error(f"Error in PnL update handler: {str(e)}")
        
    def check_pnl_conditions(self, pnl: PnL) -> bool:
       """Check if PnL conditions warrant closing positions."""
       try:
           

    
           if self.closing_initiated:
               return False

           if self.net_liquidation <= 0:
               self.logger.warning(f"Invalid net liquidation value: ${self.net_liquidation:,.2f}")
               return False
            
           #self.risk_amount = self.net_liquidation  * self.risk_percent
           self.risk_amount = 30000  * self.risk_percent
           is_threshold_exceeded = self.daily_pnl < 300
            
           if is_threshold_exceeded:
               self.logger.info(f"Risk threshold reached: Daily PnL ${self.daily_pnl:,.2f} >= ${self.risk_amount:,.2f}")
               self.closing_initiated = True
                
               positions_closed = False
               for item in self.portfolio_items:
                   position_key = f"{item.contract.symbol}_{item.position}"
                   if item.position != 0 and position_key not in self.closed_positions:
                       self.logger.info(f"Initiating close for {item.contract.symbol} (Position: {item.position})")
               self.portfolio_items =  self.ib.portfolio(self.account)
               for item in self.portfolio_items:
                   symbol = item.contract.symbol
                   pos = item.position
                   #self.logger.info("No positions to close.")
                   #return

               ny_tz = pytz.timezone('America/New_York')
               ny_time = datetime.now(ny_tz)
               is_after_hours = True  # or any logic to set trading hours based on `ny_time`

               for item in self.portfolio_items:
                   if item.position == 0:
                       continue
                    symbol = item.contract.symbol
                    pos = item.position
                    action = 'BUY' if item.position < 0 else 'SELL'
                    quantity = abs(item.position)
                    contract = Contract(symbol=symbol, exchange='SMART', secType='STK', currency='USD')
                    url = f'https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={api_key}'
                    response = requests.get(url)
                    data = response.json()
                    limit_price = data["Global Quote"]["05. price"]  # Ensure limit_price is correctly fetched here

                    # Use limit_price in your order creation
                    order = LimitOrder(
                        action=action, totalQuantity=quantity, lmtPrice=round(float(limit_price), 2),
                        tif='GTC', outsideRth=True
                    )
                    self.logger.debug(f"Placing LimitOrder for {symbol} at {limit_price}")
                    trade = self.ib.placeOrder(contract, order)
                    self.logger.info(f"Order placed and recorded for {trade}")

            except Exception as e:
                self.logger.error(f"Error creating order for {symbol}: {str(e)}")
                    
                
        
                   
                  
        if pos != 0:
                    self.logger.debug(f"No Positions for {symbol}")
                                


       except Exception as e:
           self.logger.error(f"Error creating order for {symbol}: {str(e)}")
           self.closed_positions.add(position_key)
           positions_closed = True
            
           return positions_closed
        
       return False

    
    
    def run(self):
        """Main run loop with improved error handling."""
        try:
            load_dotenv()
            logging.info("Starting Database fucker from run...")
           
            if not self.connect():
                return
                
            sleep(2)  # Allow connection to stabilize
         
            self.subscribe_events()
            print("jengo calling on_pnl_update initial run...")
            self.on_pnl_update(self.pnl)  # Initial update
            print("jengo called on_pnl_update from run")
            print(f"risk_amount {self.risk_amount}")
            no_update_counter = 0
            while True:
                try:
                    if self.ib.waitOnUpdate(timeout=1):
                        no_update_counter = 0
                    else:
                        no_update_counter += 1
                        if no_update_counter >= 60:
                            logging.debug("No updates for 60 seconds")
                            no_update_counter = 0
                except Exception as e:
                    logging.error(f"Error in main loop: {str(e)}")
                    sleep(1)  # Prevent tight error loop
                    
        except KeyboardInterrupt:
            logging.info("Shutting down by user request...")
        except Exception as e:
            logging.error(f"Critical error in run loop: {str(e)}")
        finally:
            self.ib.disconnect()


# Usage
if __name__ == '__main__':
    #IBClient.setup_logging()
    load_dotenv()
    client = IBClient()
    client.run()