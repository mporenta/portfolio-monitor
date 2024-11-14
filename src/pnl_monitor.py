# pnl.py

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
from db import DataHandler, init_db, is_symbol_eligible_for_close, insert_positions_data, insert_pnl_data, insert_order, insert_trades_data, update_order_fill

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
            self.logger.debug(f"Order inserted/updated for {trade} order type: {trade.orderType}")
            self.ib.sleep(2)
            self.logger.debug(f"After sleep - Order inserted/updated for {trade} order type: {trade.orderType}")
            
    
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


# Usage
if __name__ == '__main__':
    IBClient.setup_logging()
    client = IBClient()
    client.run()
