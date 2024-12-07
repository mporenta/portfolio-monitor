# pnl_monitor.py

from operator import is_
import asyncio
from contextlib import asynccontextmanager
import requests
import json
from ib_async import IB, MarketOrder, LimitOrder, PnL, PortfolioItem, AccountValue, Contract, Trade
from typing import *
from datetime import datetime, timedelta
import pytz
import os
from dotenv import load_dotenv
import time
from time import sleep
import logging
from typing import Optional, List
load_dotenv()
print(f"Global load of Dotenv {load_dotenv()}")
log_file_path = os.path.join(os.path.dirname(__file__), 'pnl.log')
log_level = os.getenv('TBOT_LOGLEVEL', 'INFO')
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
        self.client_id = int(os.getenv('IB_GATEWAY_CLIENT_ID', '8'))
        self.risk_percent = float(os.getenv('RISK_PERCENT', 0.01))
        self.token = os.getenv('TVWB_UNIQUE_KEY')
        self.tiingo_token = os.getenv('TIINGO_API_TOKEN')   
        
        # Logger setup
        self.logger = None
        # Subscribe to account value updates
        self.ib.accountValueEvent += self.on_account_value_update
        self.ib.pnlEvent += self.on_pnl_update
    
  
    
    async def connect(self):
       """
       Establish async connection to IB Gateway.
       Retries with localhost (127.0.0.1) if initial connection fails with getaddrinfo error.
       """
       try:
           self.logger = logging.getLogger(__name__)
           start_time = datetime.now()
           timeout = timedelta(seconds=120)
            
           while datetime.now() - start_time < timeout:
               try:
                   # First attempt with original host
                   await self.ib.connectAsync(
                       host=self.host,
                       port=self.port,
                       clientId=self.client_id
                   )
                   self.logger.info(f"Connected to IB Gateway at {self.host}:{self.port} with client ID {self.client_id}")
                   self.portfolio_items = self.ib.portfolio(self.account)
                   print(f"jengo asnyc connect portfolio_items = {self.portfolio_items}")

                   return True
                
               except Exception as e:
                   if 'getaddrinfo failed' in str(e):
                       self.logger.warning(f"Connection failed with {self.host}, retrying with localhost (127.0.0.1)")
                       original_host = self.host
                       self.host = '127.0.0.1'
                        
                       try:
                           await self.ib.connectAsync(
                               host=self.host,
                               port=self.port,
                               clientId=self.client_id
                           )
                           self.logger.info(f"Connected to IB Gateway at {self.host}:{self.port} with client ID {self.client_id}")
                           return True
                       except Exception as inner_e:
                           self.host = original_host
                           self.logger.warning(f"Connection attempt failed: {inner_e}")
                   else:
                       self.logger.warning(f"Connection attempt failed: {e}")
                    
                   elapsed = datetime.now() - start_time
                   remaining = timeout - elapsed
                    
                   if remaining.total_seconds() > 0:
                       self.logger.info(f"Retrying in 3 seconds... (Timeout in {remaining.total_seconds():.1f} seconds)")
                       await asyncio.sleep(3)
                   else:
                       self.logger.error("Connection attempts timed out after 120 seconds")
                       break
            
           return False
                    
       except Exception as e:
           if self.logger:
               self.logger.error(f"Failed to connect to IB Gateway: {e}")
           return False
    
    def subscribe_events(self):
        """Subscribe to order and PnL events, and initialize account."""
        self.ib.pnlEvent += self.on_pnl_update
        self.ib.newOrderEvent += self.on_new_order
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
            load_dotenv()
            self.risk_amount =  float(os.getenv('WEBHOOK_PNL_THRESHOLD', -300.0))  # Risk set WEBHOOK_PNL_THRESHOLD=-300.0 float(os.getenv('WEBHOOK_PNL_THRESHOLD', -300.0))
            self.logger.debug(f"dotenv - Risk amount set to: ${self.risk_amount:,.2f}")


            if self.closing_initiated:
                return False

            if self.net_liquidation <= 0:
                self.logger.warning(f"Invalid net liquidation value: ${self.net_liquidation:,.2f}")
                return False
            
            
            is_threshold_exceeded = self.daily_pnl <= self.risk_amount #This is the real one
            #is_threshold_exceeded = self.daily_pnl > self.risk_amount # This is a test when my pnl is positive and the market is closed
            #print(f" jengo pnl is_threshold_exceeded, jk its a test {is_threshold_exceeded} = {self.daily_pnl} > {self.risk_amount}" )  #THE TEST ONE

            print(f" jengo pnl is_threshold_exceeded {is_threshold_exceeded} = {self.daily_pnl} <= {self.risk_amount}" )  #THE REAL ONE
            if is_threshold_exceeded:
                self.logger.debug(f"is_threshold_exceeded {is_threshold_exceeded} = {self.daily_pnl:,.2f}, <= risk_amount ${self.risk_amount:,.2f}")

                self.logger.info(f"Risk threshold reached: Daily PnL ${self.daily_pnl:,.2f} <= ${self.risk_amount:,.2f}")
                self.closing_initiated = True
                
                positions_closed = False
                for item in self.portfolio_items:
                    position_key = f"{item.contract.symbol}_{item.position}"
                    if item.position != 0 and position_key not in self.closed_positions:
                        self.logger.info(f"Initiating close for {item.contract.symbol} (Position: {item.position})")
                        self.send_webhook_request(item)
                        self.closed_positions.add(position_key)
                        positions_closed = True
                
                return positions_closed
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error in PnL conditions check: {str(e)}")
            return False

    def send_webhook_request(self, portfolio_items: PortfolioItem):
        """Send webhook request to close position with different logic for market/after hours."""
       
        try:
            # Get current NY time
            ny_tz = pytz.timezone('America/New_York')
            current_time = datetime.now(ny_tz)
            market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        
            timenow = int(current_time.timestamp() * 1000)
            position_size = abs(portfolio_items.position)
            is_long_position = portfolio_items.position > 0
        
            url = "https://tv.porenta.us/webhook"
        
            if market_open <= current_time <= market_close:
                # During market hours - use close_all strategy
                self.logger.info(f"Market hours close for {portfolio_items.contract.symbol}")
                payload = {
                    "timestamp": timenow,
                    "ticker": portfolio_items.contract.symbol,
                    "currency": "USD",
                    "timeframe": "S",
                    "clientId": 1,
                    "key": self.token,
                    "contract": "stock",
                    "orderRef": f"close-all-{portfolio_items.contract.symbol}-{timenow}",
                    "direction": "strategy.close_all",
                    "metrics": [
                        {"name": "entry.limit", "value": 0},
                        {"name": "entry.stop", "value": 0},
                        {"name": "exit.limit", "value": 0},
                        {"name": "exit.stop", "value": 0},
                        {"name": "qty", "value": -10000000000},
                        {"name": "price", "value": portfolio_items.marketPrice or 0}
                    ]
                }
            else:
                # After hours - get Tiingo price for entry.limit
                self.logger.info(f"After hours close for {portfolio_items.contract.symbol} ({'LONG' if is_long_position else 'SHORT'} position)")
                
                # Fetch current price from Tiingo
                tiingo_token = self.tiingo_token
                self.logger.info(f"Tiingo token: {tiingo_token}")
                tiingo_url = f"https://api.tiingo.com/iex/?tickers={portfolio_items.contract.symbol}&token={tiingo_token}"
                headers = {'Content-Type': 'application/json'}
                market_price = portfolio_items.marketPrice  # default value
                
                try:
                    tiingo_response = requests.get(tiingo_url, headers=headers)
                    tiingo_data = tiingo_response.json()
                    if tiingo_data and len(tiingo_data) > 0:
                        market_price = tiingo_data[0]['tngoLast']
                        self.logger.debug(f"Using Tiingo price for {portfolio_items.contract.symbol}: {market_price}")
                except Exception as te:
                    self.logger.error(f"Error fetching Tiingo data: {str(te)}, using portfolio market price")
                
                payload = {
                    "timestamp": timenow,
                    "ticker": portfolio_items.contract.symbol,
                    "currency": "USD",
                    "timeframe": "S",
                    "clientId": 1,
                    "key": self.token,
                    "contract": "stock",
                    "orderRef": f"close-all-{portfolio_items.contract.symbol}-{timenow}",
                    "direction": "strategy.entryshort" if is_long_position else "strategy.entrylong",
                    "metrics": [
                        {"name": "entry.limit", "value": market_price},
                        {"name": "entry.stop", "value": 0},
                        {"name": "exit.limit", "value": 0},
                        {"name": "exit.stop", "value": 0},
                        {"name": "qty", "value": position_size},
                        {"name": "price", "value": portfolio_items.marketPrice}
                    ]
                }

            headers = {'Content-Type': 'application/json'}
            self.logger.debug(f"Sending webhook for {portfolio_items.contract.symbol} - Payload: {payload}")
        
            response = requests.post(url, headers=headers, data=json.dumps(payload))
        
            if response.status_code == 200:
                self.logger.info(f"Successfully sent close request for {portfolio_items.contract.symbol}")
                self.logger.debug(f"Webhook response: {response.text}")
            else:
                self.logger.error(f"Failed to send webhook for {portfolio_items.contract.symbol}. Status: {response.status_code}")
            
        except Exception as e:
            self.logger.error(f"Error sending webhook for {portfolio_items.contract.symbol}: {str(e)}")
            
  
    def close_all_positions(self):
        """Close all positions based on the data in the database."""
        
        portfolio_items =  self.ib.portfolio(self.account)
        for item in portfolio_items:
            symbol = item.contract.symbol
            pos = item.position
            #self.logger.info("No positions to close.")
            #return

        ny_tz = pytz.timezone('America/New_York')
        ny_time = datetime.now(ny_tz)
        is_after_hours = True  # or any logic to set trading hours based on `ny_time`

        for item in portfolio_items:
            if item['position'] == 0:
                continue
           
            

            action = 'BUY' if item['position'] < 0 else 'SELL'
            quantity = abs(item['position'])

            # Example contract setup - modify as needed
            contract = Contract(symbol=symbol, exchange='SMART', secType='STK', currency='USD')
            
            try:
                if pos != 0:
                    self.logger.debug(f"Placing MarketOrder for {symbol}")
                    order = MarketOrder(action=action, totalQuantity=quantity, tif='GTC')
                    
                else:
                    limit_price = self.get_market_data(contract)  # Placeholder for a method to fetch market data
                    order = LimitOrder(
                        action=action, totalQuantity=quantity, lmtPrice=round(limit_price, 2), 
                        tif='GTC', outsideRth=True
                    )
                    self.logger.debug(f"Placing LimitOrder for {symbol} at {limit_price}")

                # Place the order and update the order fill in the database
                trade = self.ib.placeOrder(contract, order)
                #self.ib.sleep(30)
                self.logger.info(f"Order placed and recorded for {symbol}")

            except Exception as e:
                self.logger.error(f"Error creating order for {symbol}: {str(e)}")
    
    async def run(self):
        """Async main run loop with improved error handling."""
        try:
            load_dotenv()
            if not await self.connect():
                return
                
            await asyncio.sleep(2)  # Allow connection to stabilize
            self.risk_amount = 30000 * self.risk_percent

            print(f"jengo risk_amount ={self.risk_amount}")
            is_threshold_exceeded = self.daily_pnl <= self.risk_amount
            print(f" jengo run is_threshold_exceeded {is_threshold_exceeded} = {self.daily_pnl} <= {self.risk_amount}" )
        
            self.subscribe_events()
            print("jengo calling on_pnl_update initial run...")
            self.on_pnl_update(self.pnl)  # Initial update
            print("jengo called on_pnl_update from run")
            
            no_update_counter = 0
            while True:
                try:
                    # Wait for the update event with a timeout
                    try:
                        await asyncio.wait_for(self.ib.updateEvent, timeout=1)
                        no_update_counter = 0
                    except asyncio.TimeoutError:
                        no_update_counter += 1
                        if no_update_counter >= 60:
                            logging.debug("No updates for 60 seconds")
                            no_update_counter = 0
                            
                except Exception as e:
                    logging.error(f"Error in main loop: {str(e)}")
                    await asyncio.sleep(1)  # Prevent tight error loop
                        
        except KeyboardInterrupt:
            logging.info("Shutting down by user request...")
        except Exception as e:
            logging.error(f"Critical error in run loop: {str(e)}")
        finally:
            await self.ib.disconnect()

# Modified main section
if __name__ == '__main__':
    load_dotenv()
    client = IBClient()
    asyncio.run(client.run())