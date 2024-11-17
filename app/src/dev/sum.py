# pnl.py
import logging
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
from db import *
from db import is_symbol_eligible_for_close, insert_positions_data, insert_pnl_data, insert_order, insert_trades_data, update_order_fill
from app import app as flask_app

load_dotenv()
PORT = int(os.getenv("PNL_HTTPS_PORT", "5002"))
class IBPortfolioTracker():
    def __init__(self):
     
            
            self.trade = Trade()
            self.ib = IB()
            self.host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')  # Use container name as default
            self.port = int(os.getenv('TBOT_IBKR_PORT', '4002'))   # Use existing env var
            self.client_id = int(os.getenv('IB_GATEWAY_CLIENT_ID', '8'))
          
            self.risk_percent = float(os.getenv('RISK_PERCENT', 0.01))
            self.total_realized_pnl = 0.0
            self.total_unrealized_pnl = 0.0
            self.daily_pnl = 0.0  
            self.net_liquidation = 0.0
            self.positions = []
            self.last_log_time = 0
            self.log_interval = 10
            self.closing_initiated = False
            self.portfolio_items = []
            self.trade = None
    
             # Set up logging
            logging.basicConfig(
                level=logging.debug,
                format='%(asctime)s - %(levelname)s - %(message)s'
            )
            self.logger = logging.getLogger(__name__)
            util.logToConsole(level=30)
            try:
                self.logger.info(f"Connecting to IB Gateway at {self.host}:{self.port} with client ID {self.client_id}")
                self.ib.connect(
                    host=self.host,
                    port=self.port,
                    clientId=self.client_id
            )
                self.logger.info("Connected successfully to IB Gateway")
            
                self.ib.waitOnUpdate(timeout=2)
                accounts = self.ib.managedAccounts()
                
                if not accounts:
                    raise Exception("No managed accounts available")
                    
                self.account = accounts[0]
                self.logger.info(f"Using account {self.account}")
                

                # Set up callbacks
                self.ib.accountSummaryEvent += self.on_account_summary
                self.ib.connectedEvent += self.onConnected
                self.ib.newOrderEvent += self.get_trades
                self.ib.updatePortfolioEvent += self.on_portfolio_update
                #self.ib.updatePortfolioEvent += self.on_pnl_update

                # Request initial account summary
                self.request_account_summary()
                
                
                # Subscribe to PnL updates
                self.pnl = self.ib.reqPnL(self.account)
                if not self.pnl:
                    raise RuntimeError("Failed to subscribe to PnL updates")
                self.ib.pnlEvent += self.on_pnl_update
                self.logger.info(f"Subscribed to PnL updates for Jengo {self.pnl}")
                self.portfolio_items = self.ib.portfolio(self.account)
                
        
        
            except Exception as e:
                self.logger.error(f"Initialization failed: {str(e)}")
                raise

    def should_log(self) -> bool:
        """Check if enough time has passed since last logging"""
        current_time = time.time()
        if current_time - self.last_log_time >= self.log_interval:
            self.last_log_time = current_time
            return True
        return False
 

    def request_account_summary(self):
        """Request account summary update"""
        try:
            # Request account summary
            self.ib.reqAccountSummary()
            self.logger.debug("Requested account summary update")
        except Exception as e:
            self.logger.error(f"Error requesting account summary: {str(e)}")

    def on_account_summary(self, value: AccountValue):
        """Handle account summary updates"""
        try:
            if value.tag == 'NetLiquidation':
                try:
                    new_value = float(value.value)
                    if new_value > 0:
                        if new_value != self.net_liquidation:
                            self.logger.debug(f"Net liquidation changed: ${self.net_liquidation:,.2f} -> ${new_value:,.2f}")
                        self.net_liquidation = new_value
                    else:
                        self.logger.warning(f"Received non-positive net liquidation value: {new_value}")
                except ValueError:
                    self.logger.error(f"Invalid net liquidation value received: {value.value}")
        except Exception as e:
            self.logger.error(f"Error processing account summary: {str(e)}")

    def get_net_liquidation(self) -> float:
        """Get the current net liquidation value"""
        if self.net_liquidation <= 0:
            # Request a fresh update if the value is invalid
            self.request_account_summary()
            self.ib.sleep(1)
            #self.ib.sleep(1)  # Give time for update to arrive
        return self.net_liquidation
    def get_trades(self, trade: Trade):
        try:
            #print(f"Trade received: {trade}")
            existing_trades = self.ib.trades()
            insert_trades_data(existing_trades)  # Add this line
            #self.logger.info(f"db Trades inserted: {existing_trades}")
            return trade
        except Exception as e:
            self.logger.error(f"Error processing trade: {str(e)}")
            return None
    def get_market_data(self, contract) -> float:
       
        market_contract = Contract(contract)
        market_contract.symbol = contract.symbol
        market_contract.secType = contract.secType
        market_contract.currency = contract.currency
        market_contract.exchange = 'SMART'
        market_contract.primaryExchange = contract.primaryExchange
        self.logger.debug(f"Closing {contract.symbol} after hours")  

        bars =  self.ib.reqHistoricalData(
            contract=market_contract,
            endDateTime='',
            durationStr='60 S',
            barSizeSetting='1 min',
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )
        self.logger.debug(f"Got {len(bars)} bars for {contract.symbol}")
        return bars[-1].close if bars else contract.marketPrice
from time import sleep
from ib_async import IB, Trade, PnL
import logging
from typing import Optional, List
from db import DataHandler, init_db

class IBClient:
    def __init__(self):
        self.ib = IB()
        self.account: Optional[str] = None
        self.daily_pnl: float = 0.0
        self.total_unrealized_pnl: float = 0.0
        self.total_realized_pnl: float = 0.0
        self.positions: List = []
        self.data_handler = DataHandler()
        self.pnl = PnL()
        
        # Logger setup
        self.logger = logging.getLogger(__name__)
    
    @staticmethod
    def setup_logging():
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
    
    def connect(self):
        """Establish connection to IB Gateway."""
        try:
            self.ib.connect('127.0.0.1', 4002, clientId=1)
            self.logger.info("Connected to IB Gateway")
        except Exception as e:
            self.logger.error(f"Failed to connect to IB Gateway: {e}")
    
    def subscribe_events(self):
        """Subscribe to order and PnL events, and initialize account."""
        self.ib.newOrderEvent += self.on_new_order
        self.ib.pnlEvent += self.on_pnl_update
        accounts = self.ib.managedAccounts()
        
        if not accounts:
            self.logger.error("No managed accounts available.")
            return

        self.account = accounts[0]
        if self.account:
            self.ib.reqPnL(self.account)
        else:
            self.logger.error("Account not found; cannot subscribe to PnL updates.")
    
    def on_new_order(self, trade: Trade):
        """Callback for new orders."""
        self.logger.info(f"New order placed: {trade}")
    
    def on_pnl_update(self, pnl: PnL):
        """Handle PnL updates by inserting and logging data."""
        self.daily_pnl = float(pnl.dailyPnL or 0.0)
        self.total_unrealized_pnl = float(pnl.unrealizedPnL or 0.0)
        self.total_realized_pnl = float(pnl.realizedPnL or 0.0)
        net_liquidation = 10000.0  # Replace with the actual net liquidation value
    
        # Fetch positions, trades, and open orders
        portfolio_items = self.ib.portfolio(self.account)
        trades = self.ib.trades()
        orders = self.ib.openOrders()
    
        # Debugging step: log trades fetched
        if trades:
            self.logger.info(f"Fetched trades: {[trade.contract.symbol for trade in trades]}")
        else:
            self.logger.warning("No trades fetched; check connection or trade subscriptions.")

        # Use DataHandler to insert and log the data
        self.data_handler.insert_all_data(
            self.daily_pnl, self.total_unrealized_pnl, self.total_realized_pnl, 
            net_liquidation, portfolio_items, trades, orders
        )

    
    def run(self):
        """Run the client to listen for updates continuously."""
        init_db()
        self.connect()
        sleep(2)
        self.subscribe_events()
        self.on_pnl_update(self.pnl)
        no_update_counter = 0
        try:
            while True:
                if self.ib.waitOnUpdate(timeout=1):
                    no_update_counter = 0
                else:
                    no_update_counter += 1
                    if no_update_counter >= 60:
                        self.logger.info("No updates for the last 60 seconds.")
                        no_update_counter = 0
        except KeyboardInterrupt:
            print("Interrupted by user; shutting down...")
        finally:
            self.disconnect()

    def disconnect(self):
        """Disconnect from IB Gateway and clean up."""
        if self.account:
            self.ib.cancelPnL(self.account)  # Cancel PnL subscription if active

        # Unsubscribe from events
        self.ib.newOrderEvent -= self.on_new_order
        self.ib.pnlEvent -= self.on_pnl_update

        self.ib.disconnect()
        self.logger.info("Disconnected from IB Gateway")

    def send_webhook_request(self, ticker):
        url = "https://tv.porenta.us/webhook"
        timenow = int(datetime.now().timestamp() * 1000)  # Convert to Unix timestamp in milliseconds

        payload = {
            "timestamp": timenow,
            "ticker": ticker,
            "currency": "USD",
            "timeframe": "S",
            "clientId": 1,
            "key": "WebhookReceived:fcbd3d",
            "contract": "stock",
            "orderRef": f"close-all {timenow}",
            "direction": "strategy.close_all",
            "metrics": [
                {"name": "entry.limit", "value": 0},
                {"name": "entry.stop", "value": 0},
                {"name": "exit.limit", "value": 0},
                {"name": "exit.stop", "value": 0},
                {"name": "qty", "value": -10000000000},
                {"name": "price", "value": 116.00}
            ]
        }

        headers = {
            'Content-Type': 'application/json'
        }

        response = requests.post(url, headers=headers, data=json.dumps(payload))
        print(response.text)
  
    def close_all_positions(self):
        """Close all positions and monitor fills"""
        self.portfolio_items = self.ib.portfolio()
        openOrders = self.ib.openOrders()
        for trade in openOrders:
            #insert_order(trade)
            logger.debug(f"Order inserted/updated for {trade} order type: {trade.orderType}")
            self.ib.sleep(2)
            logger.debug(f"After sleep - Order inserted/updated for {trade} order type: {trade.orderType}")
            
    
        try:
            if not self.portfolio_items:
                self.logger.info("No positions to close")
                return

            ny_tz = pytz.timezone('America/New_York')
            ny_time = datetime.now(ny_tz)
            is_after_hours = True

            for item in self.portfolio_items:
                if item.position == 0:
                    continue
                
                # Get the contract from portfolio item
                contract = item.contract
            
                # Check if symbol is eligible for closing
                if not is_symbol_eligible_for_close(contract.symbol):
                    self.logger.info(f"Skipping {contract.symbol} - not eligible for closing")
                    self.on_pnl_update(PnL)
                
                self.insert_positions_db(self.portfolio_items)

                action = 'BUY' if item.position < 0 else 'SELL'
                quantity = abs(item.position)

                try:
                    # Set the exchange
                    contract.exchange = contract.primaryExchange

                    if is_after_hours:
                        self.logger.debug(f"Closing {contract.symbol} during market hours")
                        order = MarketOrder(
                            action=action,
                            totalQuantity=quantity,
                            tif='GTC'
                        )
                    else:
                        self.logger.debug(f"Getting market data for {contract.symbol}")
                        limit_price = self.get_market_data(contract)
                        self.logger.debug(f"Got market data for {contract.symbol}: {limit_price}")

                        self.logger.debug(f"Closing {contract.symbol} after hours")
                        order = LimitOrder(
                            action=action,
                            totalQuantity=quantity,
                            lmtPrice=round(limit_price, 2),
                            tif='GTC',
                            outsideRth=True
                        )
                        self.logger.debug(f"Limit order for {contract.symbol}: {order}")

                    trade = self.ib.placeOrder(contract, order)
                    update_order_fill(trade)
                    
                    
                    self.logger.info(f"jengo2orders inserted: {trade}")
                    self.on_pnl_update(PnL)

                except Exception as e:
                    self.logger.error(f"Error creating order for position: {str(e)}")

        except Exception as e:
            self.logger.error(f"Error in close_all_positions: {str(e)}")
# Usage
if __name__ == '__main__':
    IBClient.setup_logging()
    client = IBClient()
    client.run()


  
            
    
        
   