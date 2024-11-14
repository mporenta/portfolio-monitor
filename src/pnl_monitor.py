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
from db import DataHandler, init_db, is_symbol_eligible_for_close, insert_positions_data, insert_pnl_data, insert_order, insert_trades_data, update_order_fill, fetch_latest_positions_data

class IBClient:
    def __init__(self):
        self.ib = IB()
        self.account: Optional[str] = None
        self.daily_pnl: float = 0.0
        self.total_unrealized_pnl: float = 0.0
        self.total_realized_pnl: float = 0.0
        self.positions: List = []
        self.portfolio_items = []
        self.data_handler = DataHandler()
        self.pnl = PnL()
        self.risk_percent = 0.01
        
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
        #net_liquidation = 10000.0  # Replace with the actual net liquidation value
        
    
        # Fetch positions, trades, and open orders
        portfolio_items = self.ib.portfolio(self.account)
        trades = self.ib.trades()
        orders = self.ib.openOrders()
        insert_trades_data(trades)
    
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
        for item in self.portfolio_items:
            if item.position == 0:
                continue
            self.check_pnl_conditions(pnl)
        
    def send_webhook_request(self, symbol: str):
        """Send a webhook request with a specific payload for closing positions."""
        url = "https://tv.porenta.us/webhook"
        timenow = int(datetime.now().timestamp() * 1000)  # Unix timestamp in milliseconds

        payload = {
            "timestamp": timenow,
            "ticker": symbol,
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

        headers = {'Content-Type': 'application/json'}
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        self.logger.info(f"Webhook response: {response.text}")
        
    def check_pnl_conditions(self, pnl: PnL) -> bool:
        self.portfolio_items =  self.ib.portfolio(self.account)
        for item in self.portfolio_items:
            symbol = item.contract.symbol
            self.logger.info(f"jengo Symbol: {symbol}")
        
        try:
            # If we've already initiated closing, don't try again
            if self.closing_initiated:
                return False
            
            net_liq = self.get_net_liquidation()
            if net_liq <= 0:
                self.logger.warning(f"Invalid net liquidation value: ${net_liq:,.2f}")
                return False
        
            self.daily_pnl =  float(pnl.dailyPnL) if pnl.dailyPnL is not None else 0.0
            #self.risk_amount = net_liq * self.risk_percent
            self.risk_amount = 30000 * self.risk_percent
            
            is_threshold_exceeded = self.daily_pnl <= -self.risk_amount
            self.logger.info(f"Risk threshold is Daily PnL ${self.daily_pnl:,.2f} <= -${self.risk_amount:,.2f}")
        
            if is_threshold_exceeded:
                # Insert portfolio data into the database
                #self.insert_positions_db(self.portfolio_items)
                #self.logger.info(f"insert symbol to db Portfolio items: {self.portfolio_items.contract.symbol}")
                self.logger.info(f"insert symbol to db Portfolio items: {self.portfolio_items}")
                self.logger.info(f"Risk threshold reached: Daily PnL ${self.daily_pnl:,.2f} <= -${self.risk_amount:,.2f}")
                self.logger.info(f"Threshold is {self.risk_percent:.1%} of ${net_liq:,.2f}")
                self.closing_initiated = True
                if is_symbol_eligible_for_close(symbol):
                    
                    self.send_webhook_request(symbol)
                    self.close_all_positions()
                    self.logger.info(f"Closing this bitch {symbol}")
                    return True
                else:
                    self.logger.info(f"Symbol {symbol} is not eligible for closing")
                    return False
        except Exception as e:
            self.logger.error(f"Error checking PnL conditions: {str(e)}")
            return False
            
  
    def close_all_positions(self):
        """Close all positions based on the data in the database."""
        # Fetch positions data from the database instead of using `self.ib.portfolio()`
        portfolio_items = fetch_latest_positions_data()
        if not portfolio_items:
            self.logger.info("No positions to close.")
            return

        ny_tz = pytz.timezone('America/New_York')
        ny_time = datetime.now(ny_tz)
        is_after_hours = True  # or any logic to set trading hours based on `ny_time`

        for item in portfolio_items:
            if item['position'] == 0:
                continue

            symbol = item['symbol']
            if not is_symbol_eligible_for_close(symbol):
                self.logger.info(f"Skipping {symbol} - not eligible for closing")
                continue

            action = 'BUY' if item['position'] < 0 else 'SELL'
            quantity = abs(item['position'])

            # Example contract setup - modify as needed
            contract = Contract(symbol=symbol, exchange='SMART', secType='STK', currency='USD')
            
            try:
                if is_after_hours:
                    order = MarketOrder(action=action, totalQuantity=quantity, tif='GTC')
                    self.logger.debug(f"Placing MarketOrder for {symbol}")
                else:
                    limit_price = self.get_market_data(contract)  # Placeholder for a method to fetch market data
                    order = LimitOrder(
                        action=action, totalQuantity=quantity, lmtPrice=round(limit_price, 2), 
                        tif='GTC', outsideRth=True
                    )
                    self.logger.debug(f"Placing LimitOrder for {symbol} at {limit_price}")

                # Place the order and update the order fill in the database
                trade = self.ib.placeOrder(contract, order)
                update_order_fill(trade)
                self.logger.info(f"Order placed and recorded for {symbol}")

            except Exception as e:
                self.logger.error(f"Error creating order for {symbol}: {str(e)}")
    
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
