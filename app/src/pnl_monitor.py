# pnl_monitor.py

from operator import is_
import pandas as pd
import asyncio
from contextlib import asynccontextmanager
from fastapi.background import P
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
from real_time_bars import RealtimePriceService
risk_amount = float(os.getenv('WEBHOOK_PNL_THRESHOLD', -300.0))  # Risk set 
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
        load_dotenv()
        self.ib = IB()
        self.unrealized_pnl = 0.0
        self.daily_pnl = 0.0
        self.total_unrealized_pnl = 0.0
        self.total_realized_pnl = 0.0
        self.net_liquidation = 0.0
        self.combined_unrealized_pnl = 0.0
        self.total_realizedPnl = 0.0
        self.total_pnl = 0.0
        self.is_threshold_exceeded = False

        self.positions: List = []
        self.trade: List = []
        self.portfolio_items = []
        self.pnl = PnL()
        self.account = os.getenv('IB_PAPER_ACCOUNT', '')
        


        self.risk_amount = risk_amount
        self.closing_initiated = False
        self.closed_positions = set()  # Track which positions have been closed
               # Load environment variables first
        
    
       # Then set connection parameters
        self.host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')  # Default to localhost if not set
        self.port = int(os.getenv('TBOT_IBKR_PORT', '4002'))
        self.client_id = int(os.getenv('IB_GATEWAY_CLIENT_ID', '9'))
        self.risk_percent = float(os.getenv('RISK_PERCENT', 0.01))
        self.token = os.getenv('TVWB_UNIQUE_KEY')
        self.tiingo_token = os.getenv('TIINGO_API_TOKEN')
 

        
        # Logger setup
        self.logger = None
        # Subscribe to account value updates
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 300
        self.reconnect_delay = 1  # seconds
    
  
 
    
                    
 
        
    async def try_connect(self) -> bool:
        """Single connection attempt with error handling"""
        
        self.logger = logging.getLogger(__name__)

        try:
            await self.ib.connectAsync(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=20  # Increased timeout for stability
            )
            self.subscribe_events()
            self.logger.info(f"In try_connect: jengo subscribe_events Connection established with {self.host} for account: {self.account}")
            return True
        except Exception as e:
            if 'getaddrinfo failed' in str(e):
                self.logger.warning(f"Connection failed with {self.host}, trying localhost")
                try:
                    await self.ib.connectAsync(
                        host='127.0.0.1',
                        port=self.port,
                        clientId=self.client_id,
                        timeout=20
                    )
                    self.subscribe_events()
                    self.logger.info(f"In try_connect: jengo subscribe_events Connection established with {self.host}")
                    return True
                except Exception as inner_e:
                    self.logger.error(f"Localhost connection failed: {inner_e}")
            else:
                self.logger.error(f"Connection error: {e}")
            return False
    def on_connected(self):
        """Handle successful connection"""
        self.connected = True
        self.reconnect_attempts = 0
        self.logger.info("on_connected Successfully connected to IB Gateway")
        self.subscribe_events()
        
    def on_disconnected(self):
        """Handle disconnection"""
        self.connected = False
        self.logger.warning("Disconnected from IB Gateway")
            
    async def connect_with_retry(self) -> bool:
        """Attempt connection with retries"""
        while self.reconnect_attempts < self.max_reconnect_attempts:
            if await self.try_connect():
                return True
                
            self.reconnect_attempts += 1
            if self.reconnect_attempts < self.max_reconnect_attempts:
                wait_time = self.reconnect_delay * (2 ** self.reconnect_attempts)
                self.logger.info(f"Retrying connection in {wait_time} seconds... "
                               f"(Attempt {self.reconnect_attempts + 1}/{self.max_reconnect_attempts})")
                await asyncio.sleep(wait_time)
                
        self.logger.error("Max reconnection attempts reached")
        return False
        
    async def ensure_connected(self):
        """Ensure connection is maintained"""
        if not self.ib.isConnected():
            self.logger.warning("Connection lost, attempting to reconnect...")
            if await self.connect_with_retry():
                self.logger.info("Reconnection successful")
            else:
                self.logger.error("Failed to reconnect")
                raise ConnectionError("Unable to maintain connection to IB Gateway")
    def subscribe_events(self):
        """Subscribe to order and PnL events, and initialize account."""
        self.logger.info("subscribe_events Subscribing to events")
        self.ib.pnlEvent += self.on_pnl_update
        self.ib.newOrderEvent += self.on_new_order
          # Subscribe to portfolio updates
        # Keep account value subscription for net liquidation updates
        self.ib.accountValueEvent += self.on_account_value_update

    
      
        
        self.ib.reqPnL(self.account)
            

        self.logger.info(f"subscribe_events jengo Subscribed to events for account {self.account}")
        
    def on_account_value_update(self, account_value: AccountValue):
        """Update stored NetLiquidation whenever it changes."""
        if account_value.tag == "NetLiquidation":
            self.net_liquidation = float(account_value.value)
            self.logger.debug(f"NetLiquidation updated: ${self.net_liquidation:,.2f}")
        
    def on_new_order(self, trade: Trade):
        """Callback for new orders."""
        self.logger.debug(f"New order placed: {trade}")
    
    

    async def on_pnl_update(self, pnl: PnL):
        """Handle PnL updates and check conditions."""
        try:
            # Update PnL values
            self.daily_pnl = float(pnl.dailyPnL or 0.0)
            self.total_unrealized_pnl = float(pnl.unrealizedPnL or 0.0)
            self.total_realized_pnl = float(pnl.realizedPnL or 0.0)
            
            
            self.logger.debug(f"Daily PnL: ${self.daily_pnl:,.2f}, Net Liquidation: ${self.net_liquidation:,.2f}")

            # Update portfolio items
            self.trade = self.ib.portfolio(self.account)
            
            
            
            

            # Check positions and conditions
            for item in self.trade:
                if item.position != 0:
                    self.logger.info(f"PnL conditions met for {item.contract.symbol}")
                    await self.async_orders()
            
                        
        except Exception as e:
            self.logger.error(f"Error in PnL update handler: {str(e)}")

    async def async_orders(self) -> bool:
        try:
            # Portfolio analysis for positions
            self.portfolio_items = self.ib.portfolio(self.account)
            await self.process_portfolio_positions()
        
            # Trade analysis
            trade = await asyncio.to_thread(self.ib.trades)
            orders = {}
            for trade in trade:
                perm_id = trade.order.permId
                symbol = trade.contract.symbol
            
                if perm_id not in orders:
                    orders[perm_id] = {
                        'symbol': symbol,
                        'qty': trade.order.filledQuantity,
                        'commission': sum(fill.commissionReport.commission for fill in trade.fills),
                        'realizedPNL': sum(fill.commissionReport.realizedPNL or 0 for fill in trade.fills)
                    }
    
            # Aggregate trade summary
            symbol_summary = {}
            for order in orders.values():
                symbol = order['symbol']
                if symbol not in symbol_summary:
                    symbol_summary[symbol] = {'qty': 0, 'commission': 0, 'realizedPNL': 0}
            
                symbol_summary[symbol]['qty'] = max(symbol_summary[symbol]['qty'], order['qty'])
                symbol_summary[symbol]['commission'] += order['commission']
                symbol_summary[symbol]['realizedPNL'] += order['realizedPNL']

            rows = [{
                'Symbol': symbol,
                'TotalQty': data['qty'],
                'TotalCommission': round(data['commission'], 6),
                'TotalRealizedPNL': round(data['realizedPNL'], 6)
            } for symbol, data in symbol_summary.items()]
    
            self.total_realizedPnl = sum(data['realizedPNL'] for data in symbol_summary.values())
            rows.append({
                'Symbol': 'TOTAL',
                'TotalQty': '',
                'TotalCommission': '',
                'TotalRealizedPNL': round(self.total_realizedPnl, 6)
            })
    
            df = pd.DataFrame(rows)
            self.logger.debug("Trade Summary by Symbol:\n{}".format(df.to_string(index=False)))
        
            return True
        except Exception as e:
            self.logger.error(f"Error in async_orders: {str(e)}")
            return False

    async def process_portfolio_positions(self):
        try:
            self.total_unrealized_pnl = sum(float(item.unrealizedPNL or 0.0) for item in self.portfolio_items)
            self.combined_unrealized_pnl = self.total_unrealized_pnl
            self.total_pnl = self.total_realizedPnl + self.combined_unrealized_pnl
        
            self.logger.debug(f"Total PnL: ${self.total_pnl:,.2f} = Total Realized PnL: ${self.total_realizedPnl:,.2f} + Combined Unrealized PnL: ${self.combined_unrealized_pnl:,.2f}")
        
            self.is_threshold_exceeded = self.total_pnl <= self.risk_amount or self.total_realizedPnl <= self.risk_amount
        
            if self.is_threshold_exceeded:
                self.logger.info(f"Risk threshold reached: Combined PnL ${self.total_pnl:,.2f} <= ${self.risk_amount:,.2f} or {self.total_realizedPnl} <= {self.risk_amount}")
                self.closing_initiated = True
            
                # Process all non-zero positions
                positions_to_close = [pos for pos in self.portfolio_items if pos.position != 0]
                for pos in positions_to_close:
                    position_key = f"{pos.contract.symbol}_{pos.position}_{pos.contract.conId}"
                    if position_key not in self.closed_positions:
                        self.logger.info(f"Initiating close for {pos.contract.symbol} (Position: {pos.position})")
                        await self.place_order(pos)
                        self.closed_positions.add(position_key)
            
                return True
        except Exception as e:
            self.logger.error(f"Error processing positions: {str(e)}")
            return False


    def check_portfolio_conditions(self, portfolio_items: PortfolioItem) -> bool:
        """Check if portfolio conditions warrant closing positions."""
        try:
            portfolio_items =  self.ib.trades()
            #load_dotenv()
            #self.portfolio_items = portfolio_items
            self.risk_amount = 0
            #self.logger.info(f"dotenv - Risk amount set to: ${self.risk_amount:,.2f}")

            if not portfolio_items:
                self.logger.warning("No portfolio items found, gettings trades")
                portfolio_items = self.ib.trades()
                self.logger.info(f"Trades: {portfolio_items}")
                

            # Log portfolio items
            for item in portfolio_items:
                self.logger.info(f"check_portfolio_conditions jengo Portfolio item: {item.contract.symbol} - Position: {item.position}")

          

           
   
        except Exception as e:
            self.logger.error(f"Error in portfolio conditions check: {str(e)}")
            return False

  
    


    
  
   
    async def place_order(self, portfolio_item: PortfolioItem):
        """
        Place an order with Interactive Brokers based on the position request.
        """
        
        self.logger.info(f"place_order jengo Received position request: {portfolio_item}")

        response_data = []
        try:
            

            self.tiingo_token = os.getenv('TIINGO_API_TOKEN')   
            ny_tz = pytz.timezone('America/New_York')
            current_time = datetime.now(ny_tz)
            market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
            is_market_hours = market_open <= current_time <= market_close

            is_long_position = portfolio_item.position > 0
            symbol = portfolio_item.contract.symbol
            pos = abs(portfolio_item.position)

            try:
                self.logger.info(f"Processing order for place_order jengo  {symbol}")

                # Create contract
                contract = Contract(
                    symbol=symbol,
                    exchange='SMART',
                    secType='STK',
                    currency='USD'
                )

                # Determine action based on position
                action = 'SELL' if is_long_position else 'BUY'

                # Create order based on market hours
                if is_market_hours:
                    self.logger.info(f"Creating market order for {symbol}")
                    order = MarketOrder(
                        action=action,
                        totalQuantity=pos,
                        tif='GTC'
                    )
                else:
                    self.logger.info(f"Creating limit order for place_order jengo {symbol}")
                    # Fetch current price from Tiingo
                    self.logger.info(f"Tiingo token: {self.tiingo_token}")
                    tiingo_url = f"https://api.tiingo.com/iex/?tickers={symbol}&token={self.tiingo_token}"
                    headers = {'Content-Type': 'application/json'}

                    try:
                        tiingo_response = requests.get(tiingo_url, headers=headers)
                        tiingo_data = tiingo_response.json()
                        if tiingo_data and len(tiingo_data) > 0:
                            limit_price = tiingo_data[0]['tngoLast']
                            self.logger.info(f"Tiingo response: {tiingo_data} - Using Tiingo 'tngoLast' price for {symbol}: {limit_price}")
                    except Exception as te:
                        self.logger.error(f"Error fetching Tiingo data: {str(te)}")

                    if not limit_price:
                        raise ValueError(f"Could not get market price for {symbol}")

                    order = LimitOrder(
                        action=action,
                        totalQuantity=pos,
                        lmtPrice=round(limit_price, 2),
                        tif='GTC',
                        outsideRth=False
                    )

                # Place the order
                trade = self.ib.placeOrder(contract, order)
                self.logger.info(f"Order placed for {symbol}: {trade}")

            except Exception as e:
                self.logger.error(f"Error processing order for {symbol}: {str(e)}", exc_info=True)

            self.logger.info("Order processed successfully")
            return response_data

        except Exception as e:
            self.logger.error(f"Error processing position request: {str(e)}", exc_info=True)
      
    async def run(self):
        """Main run loop with connection management and graceful shutdown."""
        try:
            if not await self.connect_with_retry():
                self.logger.error("Initial connection failed")
                return

            while True:
                try:
                    await self.ensure_connected()
                    await asyncio.wait_for(self.ib.updateEvent, timeout=1)
                    

                    # Perform portfolio checks
                    

                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    self.logger.info("Run loop cancelled, shutting down...")
                    break
                except Exception as e:
                    self.logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt detected, shutting down...")

        finally:
            await self.graceful_disconnect()

    async def graceful_disconnect(self):
        """Gracefully disconnect from IB Gateway and unsubscribe from updates."""
        try:
            if self.ib.isConnected():
                self.logger.info("Unsubscribing from events...")
                self.ib.pnlEvent.clear()
                self.ib.newOrderEvent.clear()
                self.ib.accountValueEvent.clear()

                # Cancel PnL and portfolio updates
                if self.account:
                    try:
                        self.ib.cancelPnL(self.account)
                    except Exception as e:
                        self.logger.error(f"Error cancelling PnL updates: {e}")

                self.ib.wrapper.portfolio.clear()
                self.ib.wrapper.positions.clear()

                self.logger.info("Disconnecting from IB Gateway...")
                self.ib.disconnect()
        except Exception as e:
            self.logger.error(f"Error during graceful disconnect: {e}")


# Modified main section
if __name__ == '__main__':
    load_dotenv()
    
    client = IBClient()
    asyncio.run(client.run())