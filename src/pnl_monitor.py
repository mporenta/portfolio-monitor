# pnl_monitor.py

from operator import is_
import flask
import requests
import json
from ib_async import IB, MarketOrder, LimitOrder, PnL, PortfolioItem, AccountValue, Contract, Trade
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
from db import DataHandler, init_db, is_symbol_eligible_for_close, insert_positions_data, insert_pnl_data, insert_order, insert_trades_data, update_order_fill, fetch_latest_positions_data
log_file_path = os.path.join(os.path.dirname(__file__), 'pnl.log')





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
        self.data_handler = DataHandler()
        self.pnl = PnL()
        self.risk_percent = 0.0013
        self.risk_amount = 0.0
        self.closing_initiated = False
        self.closed_positions = set()  # Track which positions have been closed
        load_dotenv()
        
        # Logger setup
        self.logger = None
        # Subscribe to account value updates
        self.ib.accountValueEvent += self.on_account_value_update
        self.ib.pnlEvent += self.on_pnl_update
    
  
    
    def connect(self):
        """Establish connection to IB Gateway."""
        try:
            logging.basicConfig(
                level=logging.DEBUG,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(log_file_path),
                    logging.StreamHandler()
                ]
            )
            self.logger = logging.getLogger(__name__)
            self.ib.connect('127.0.0.1', 4002, clientId=7)
            self.logger.info("Connected to IB Gateway")
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to connect to IB Gateway: {e}")
            return False

    
    def subscribe_events(self):
        """Subscribe to order and PnL events, and initialize account."""
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
            
            # Process trades and orders
            trades = self.ib.trades()
            orders = self.ib.openOrders()
            
            # Insert trade data
            insert_trades_data(trades)
            
            # Update database
            self.data_handler.insert_all_data(
                self.daily_pnl, 
                self.total_unrealized_pnl, 
                self.total_realized_pnl,
                self.net_liquidation,
                self.portfolio_items,
                trades,
                orders
            )

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
            
            self.risk_amount = self.net_liquidation  * self.risk_percent
            is_threshold_exceeded = self.daily_pnl >= self.risk_amount
            
            if is_threshold_exceeded:
                self.logger.info(f"Risk threshold reached: Daily PnL ${self.daily_pnl:,.2f} >= ${self.risk_amount:,.2f}")
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

    def send_webhook_request(self, portfolio_item: PortfolioItem):
        """Send webhook request to close position."""
        try:
            url = "https://tv.porenta.us/webhook"
            timenow = int(datetime.now().timestamp() * 1000)

            payload = {
                "timestamp": timenow,
                "ticker": portfolio_item.contract.symbol,
                "currency": "USD",
                "timeframe": "S",
                "clientId": 1,
                "key": "WebhookReceived:fcbd3d",
                "contract": "stock",
                "orderRef": f"close-all-{portfolio_item.contract.symbol}-{timenow}",
                "direction": "strategy.close_all",
                "metrics": [
                    {"name": "entry.limit", "value": 0},
                    {"name": "entry.stop", "value": 0},
                    {"name": "exit.limit", "value": 0},
                    {"name": "exit.stop", "value": 0},
                    {"name": "qty", "value": -10000000000},  # Large number to ensure full position close
                    {"name": "price", "value": portfolio_item.marketPrice or 0}
                ]
            }

            headers = {'Content-Type': 'application/json'}
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            
            if response.status_code == 200:
                self.logger.info(f"Successfully sent close request for {portfolio_item.contract.symbol}")
                self.logger.debug(f"Webhook response: {response.text}")
            else:
                self.logger.error(f"Failed to send webhook for {portfolio_item.contract.symbol}. Status: {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"Error sending webhook for {portfolio_item.contract.symbol}: {str(e)}")
            
  
    def close_all_positions(self):
        """Close all positions based on the data in the database."""
        # Fetch positions data from the database instead of using `self.ib.portfolio()`
        #portfolio_items = fetch_latest_positions_data()
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
                update_order_fill(trade)
                self.logger.info(f"Order placed and recorded for {symbol}")

            except Exception as e:
                self.logger.error(f"Error creating order for {symbol}: {str(e)}")
    
    def run(self):
        """Main run loop with improved error handling."""
        try:
            load_dotenv()
            init_db()
            if not self.connect():
                return
                
            sleep(2)  # Allow connection to stabilize
            self.subscribe_events()
            self.on_pnl_update(self.pnl)  # Initial update
            
            no_update_counter = 0
            while True:
                try:
                    if self.ib.waitOnUpdate(timeout=1):
                        no_update_counter = 0
                    else:
                        no_update_counter += 1
                        if no_update_counter >= 60:
                            self.logger.debug("No updates for 60 seconds")
                            no_update_counter = 0
                except Exception as e:
                    self.logger.error(f"Error in main loop: {str(e)}")
                    sleep(1)  # Prevent tight error loop
                    
        except KeyboardInterrupt:
            self.logger.info("Shutting down by user request...")
        except Exception as e:
            self.logger.error(f"Critical error in run loop: {str(e)}")
        finally:
            self.ib.disconnect()


# Usage
if __name__ == '__main__':
    #IBClient.setup_logging()
    client = IBClient()
    client.run()