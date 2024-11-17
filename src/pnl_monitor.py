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

# Import the new Redis database implementation
from db import RedisDB, DataHandler

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
        self.pnl = PnL()
        self.risk_amount = 0.0
        self.closing_initiated = False
        self.closed_positions = set()  # Track which positions have been closed
        
        # Load environment variables
        load_dotenv()
        
        # Initialize Redis connection
        redis_host = os.getenv('TBOT_PNL_REDIS_HOST', 'redis-pnl')
        redis_port = int(os.getenv('TBOT_PNL_REDIS_PORT', '6379'))
        redis_password = os.getenv('TBOT_PNL_REDIS_PASSWORD', '')
        
        # Initialize Redis DB and DataHandler
        self.redis_db = RedisDB(
            host=redis_host,
            port=redis_port,
            password=redis_password
        )
        self.data_handler = DataHandler(self.redis_db)
    
        # Set IB connection parameters
        self.host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')
        self.port = int(os.getenv('TBOT_IBKR_PORT', '4002'))
        self.client_id = int(os.getenv('IB_GATEWAY_CLIENT_ID', '8'))
        self.risk_percent = float(os.getenv('RISK_PERCENT', 0.01))
        
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
            
            # Initialize Redis database
            self.redis_db.init_db()
            
            # Connect to IB Gateway
            self.ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id
            )
            
            self.logger.info(f"Connected to IB Gateway at {self.host}:{self.port} with client ID {self.client_id}")
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

    def is_symbol_eligible_for_close(self, symbol: str) -> bool:
        """Check if a symbol is eligible for closing."""
        try:
            positions = self.redis_db.fetch_latest_positions_data()
            position_exists = any(p['symbol'] == symbol for p in positions)
            
            if not position_exists:
                self.logger.debug(f"{symbol} not found in positions")
                return False

            return True
        except Exception as e:
            self.logger.error(f"Error checking symbol eligibility: {e}")
            return False

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
            
            # Update Redis database
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

    def close_all_positions(self):
        """Close all positions based on the data in Redis."""
        try:
            positions = self.redis_db.fetch_latest_positions_data()
            
            if not positions:
                self.logger.info("No positions to close.")
                return

            ny_tz = pytz.timezone('America/New_York')
            ny_time = datetime.now(ny_tz)

            for position in positions:
                if position['position'] == 0:
                    continue

                symbol = position['symbol']
                quantity = abs(position['position'])
                action = 'BUY' if position['position'] < 0 else 'SELL'

                contract = Contract(symbol=symbol, exchange='SMART', secType='STK', currency='USD')
                
                try:
                    if self.is_market_hours(ny_time):
                        order = MarketOrder(action=action, totalQuantity=quantity, tif='GTC')
                    else:
                        market_price = position.get('market_price', 0)
                        order = LimitOrder(
                            action=action, 
                            totalQuantity=quantity, 
                            lmtPrice=round(market_price, 2), 
                            tif='GTC', 
                            outsideRth=True
                        )

                    trade = self.ib.placeOrder(contract, order)
                    self.redis_db.insert_order(trade)
                    self.logger.info(f"Order placed and recorded for {symbol}")

                except Exception as e:
                    self.logger.error(f"Error creating order for {symbol}: {str(e)}")

        except Exception as e:
            self.logger.error(f"Error in close_all_positions: {str(e)}")
        


    def run(self):
        """Main run loop with improved error handling."""
        try:
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
                    sleep(1)
                    
        except KeyboardInterrupt:
            self.logger.info("Shutting down by user request...")
        except Exception as e:
            self.logger.error(f"Critical error in run loop: {str(e)}")
        finally:
            self.ib.disconnect()

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
        """Send webhook request to close position with different logic for market/after hours."""
        try:
            # Get current NY time
            ny_tz = pytz.timezone('America/New_York')
            current_time = datetime.now(ny_tz)
            market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        
            timenow = int(current_time.timestamp() * 1000)
            position_size = abs(portfolio_item.position)
            is_long_position = portfolio_item.position > 0
        
            url = "https://tv.porenta.us/webhook"
        
            if market_open <= current_time <= market_close:
                # During market hours - use close_all strategy
                self.logger.info(f"Market hours close for {portfolio_item.contract.symbol}")
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
                        {"name": "qty", "value": -10000000000},
                        {"name": "price", "value": portfolio_item.marketPrice or 0}
                    ]
                }
            else:
                # After hours - use position-specific payload
                self.logger.info(f"After hours close for {portfolio_item.contract.symbol} ({'LONG' if is_long_position else 'SHORT'} position)")
                payload = {
                    "timestamp": timenow,
                    "ticker": portfolio_item.contract.symbol,
                    "currency": "USD",
                    "timeframe": "S",
                    "clientId": 1,
                    "key": "WebhookReceived:fcbd3d",
                    "contract": "stock",
                    "orderRef": f"close-all-{portfolio_item.contract.symbol}-{timenow}",
                    "direction": "strategy.entryshort" if is_long_position else "strategy.entrylong",
                    "metrics": [
                        {"name": "entry.limit", "value": portfolio_item.marketPrice},
                        {"name": "entry.stop", "value": 0},
                        {"name": "exit.limit", "value": 0},
                        {"name": "exit.stop", "value": 0},
                        {"name": "qty", "value": position_size},
                        {"name": "price", "value": portfolio_item.marketPrice}
                    ]
                }

            headers = {'Content-Type': 'application/json'}
            self.logger.debug(f"Sending webhook for {portfolio_item.contract.symbol} - Payload: {payload}")
        
            response = requests.post(url, headers=headers, data=json.dumps(payload))
        
            if response.status_code == 200:
                self.logger.info(f"Successfully sent close request for {portfolio_item.contract.symbol}")
                self.logger.debug(f"Webhook response: {response.text}")
            else:
                self.logger.error(f"Failed to send webhook for {portfolio_item.contract.symbol}. Status: {response.status_code}")
            
        except Exception as e:
            self.logger.error(f"Error sending webhook for {portfolio_item.contract.symbol}: {str(e)}")

    @staticmethod
    def is_market_hours(ny_time: datetime) -> bool:
        """Check if it's during market hours."""
        market_open = ny_time.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = ny_time.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= ny_time <= market_close



if __name__ == '__main__':
    client = IBClient()
    client.run()
