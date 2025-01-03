# pnl_monitor.py

from operator import is_
import pandas as pd
import asyncio
import math
from contextlib import asynccontextmanager
from fastapi.background import P
import aiohttp
import requests
import json
from ib_async import IB, MarketOrder, LimitOrder, PnL, PortfolioItem, AccountValue, Contract, Trade, util, Ticker, Stock
from typing import *
from datetime import datetime, timedelta
import pytz
import os
from dotenv import load_dotenv
import time
import logging
from typing import Optional, List
load_dotenv()
from real_time_bars import RealtimePriceService
risk_amount = float(os.getenv('WEBHOOK_PNL_THRESHOLD', -300.0))  # Risk set 
log_file_path = os.path.join(os.path.dirname(__file__), 'pnl.log')
log_level = os.getenv('TBOT_LOGLEVEL', 'DEBUG')
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)


class PnLMonitor:
    def __init__(self):
        load_dotenv()
        self.ib = IB()
        self.limit_price = None
        self.unrealized_pnl = 0.0
        self.daily_pnl = 0.0
        self.total_unrealized_pnl = 0.0
        self.total_realized_pnl = 0.0
        self.net_liquidation = 0.0
        self.combined_unrealized_pnl = 0.0
        self.total_realizedPnl = 0.0
        self.total_pnl = 0.0
        self.is_threshold_exceeded = False
        self.price_service = None

        self.positions: List = []
        self.trade: List = []
        self.pnl = PnL()
        self.accounts = []
        self.account = None
        self.halted_open_positions = {}
        self.open_positions = []  
        # Position tracking
        self.current_positions = {}  # conId: conId
        self.subscribed_tickers = {}  # symbol: ticker
        self.symbols_to_remove = []
        self.portfolio_item = []
        self.pending_orders = set()
        
        


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
        self.openOrders = []
 

        
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
            self.accounts = self.ib.managedAccounts()

            self.account = self.accounts[0] if self.accounts else None

            self.logger = logging.getLogger(__name__)
            self.ib.reqPnL(self.account)
            self.logger.info(f"Subscribing to PnL updates for account: {self.account}")
            self.portfolio_item = self.ib.portfolio(self.account)
            await self.monitor_pnl_and_close_positions(self.portfolio_item)
            self.logger.info(f"In try_connect: jengo subscribe_events Connection established with {self.host} and clientId: {self.client_id} for account: {self.account}")
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
                    self.accounts = self.ib.managedAccounts()
                    self.account = self.accounts[0] if self.accounts else None
                    self.logger = logging.getLogger(__name__)
                    self.ib.reqPnL(self.account)
                    self.logger.info(f"Subscribing to PnL updates for account: {self.account}")
                    self.portfolio_item = self.ib.portfolio(self.account)
                    self.logger.info(f"jengo portfolio_item from try_connect: {self.portfolio_item}")
                    await self.monitor_pnl_and_close_positions(self.portfolio_item)
                    

                    self.logger.info(f"In try_connect: jengo subscribe_events Connection established with {self.host} and clientId: {self.client_id} for account: {self.account}")
                    return True
                except Exception as inner_e:
                    self.logger.error(f"Localhost connection failed: {inner_e}")
            else:
                self.logger.error(f"Connection error: {e}")
            return False
    async def init_price_service(self):
        """Initialize and connect price service if not already initialized"""
        self.logger = logging.getLogger(__name__)
        try:
            if self.price_service is None:
                self.price_service = RealtimePriceService()
                if not await self.price_service.start():
                    raise ConnectionError("Failed to start price service")
                self.logger.info("Price service initialized and connected")
            elif not self.price_service.client.isConnected():
                # Reconnect if connection was lost
                if not await self.price_service.start():
                    raise ConnectionError("Failed to reconnect price service")
                self.logger.info("Price service reconnected")
            return True
        except Exception as e:
            self.logger.error(f"Error initializing price service: {str(e)}")
            self.price_service = None
            return False
        
    

    async def _get_tiingo_price(self, symbol: str) -> Optional[float]:
        """Fallback method to get price from Tiingo API"""
        try:
            tiingo_token = self.tiingo_token
            tiingo_url = f"https://api.tiingo.com/iex/?tickers={symbol}&token={tiingo_token}"
            headers = {'Content-Type': 'application/json'}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(tiingo_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            price = data[0]['tngoLast']
                            self.logger.info(f"Got tngoLast price for {symbol} from Tiingo: {price}")
                            return price
            return None
        except Exception as e:
            self.logger.error(f"Error getting Tiingo price for {symbol}: {str(e)}")
            return None

    async def on_pnl_event(self, pnl: PnL):
        if not self.account:
            self.account = self.ib.managedAccounts()[0] if self.ib.managedAccounts() else None

        pnl = self.ib.pnl(self.account)
        for item in pnl:
            self.total_unrealized_pnl = float(item.unrealizedPnL or 0.0) / 2
            self.total_realized_pnl = float(item.realizedPnL or 0.0)
            self.logger.debug(f"Received PnL update - unrealizedPnL: {self.total_unrealized_pnl}, full item: {item}")
        
        if not pnl:
            self.logger.warning("PnL data is incomplete.")
            return
            
        self.total_pnl = self.total_realized_pnl + self.total_unrealized_pnl
        self.logger.debug(f"Total PnL: {self.total_pnl} (realized: {self.total_realized_pnl}, unrealized: {self.total_unrealized_pnl})")
        
        self.open_positions = [p for p in self.ib.positions() if p.position != 0]
        if self.open_positions and (self.total_pnl <= self.risk_amount or self.total_realized_pnl <= self.risk_amount):
            self.logger.info(f"Total PnL: {self.total_pnl} is below risk amount {self.risk_amount}, closing positions...")
            await asyncio.sleep(0.2)
            await self.close_all_positions()

    
    

    async def create_position_index(self):
        """Create an index of current open positions."""
        
        for position in self.ib.positions():
            if position.position != 0:  # Only index non-zero positions
                symbol = position.contract.symbol
                self.current_positions[symbol] = position.contract.conId
        return self.current_positions

    async def close_all_positions(self):
        """Close all open positions."""
        closed_positions = set()  # Track positions we've closed
    
        for position in self.ib.positions():
            if position.position != 0:
                symbol = position.contract.symbol
                if symbol not in closed_positions:
                    await self._place_closing_order(position)
                    closed_positions.add(symbol)

    
    async def monitor_pnl_and_close_positions(self, portfolio_item: PortfolioItem):
        """Monitor PnL and handle position closures with price service ready"""
        try:
            # Initialize price service first
            if not await self.init_price_service():
                self.logger.error("Failed to initialize price service, monitoring may have limited functionality")

                        
            
            self.ib.pnlEvent.clear()
            self.ib.pnlEvent += self.on_pnl_event
            self.ib.orderStatusEvent += self.order_status_event
            self.ib.newOrderEvent += self.new_order_event
            self.ib.updatePortfolioEvent += self.update_portfolio_event

            self.logger.info("Started monitoring PnL and positions.")
            await self.update_portfolio_event(portfolio_item)
            
        except Exception as e:
            self.logger.error(f"Error in PnL update handler: {str(e)}")
    
    async def update_portfolio_event(self, portfolio_item: PortfolioItem):
        try:
            self.symbols_to_remove = []
       
            # Process each position update
            for item in self.portfolio_item:
                symbol = item.contract.symbol
                position = item.position
                contract = Contract(
                    symbol=symbol,
                    exchange= 'SMART',
                    secType='STK',
                    currency='USD',
                    conId=item.contract.conId,
                    primaryExchange= item.contract.primaryExchange
                )
           
                if position != 0:
                    self.logger.info(f"jengo 'position != 0' contract, symbol, position: {contract} - {symbol} - {position} primaryExchange: {item.contract.primaryExchange} - exchange= {contract.exchange}")
                    # Subscribe to market data if not already subscribed
                    if symbol not in self.subscribed_tickers:
                        try:
                            ticker = self.ib.reqMktData(
                                contract,
                                genericTickList='',
                                snapshot=False,
                                regulatorySnapshot=False,
                                mktDataOptions=[]
                            )
                            ticker.updateEvent += self._on_ticker_update
                            self.subscribed_tickers[symbol] = ticker
                            self.logger.info(f"Subscribed to {symbol}, position={position}")
                        except Exception as e:
                            self.logger.error(f"Error subscribing to {symbol}: {str(e)}")
               
                    # Update position tracking
                    self.current_positions[contract.conId] = contract.conId
                else:
                    self.logger.info(f"jengo 'position == 0 contract', symbol, position: {contract} - {symbol} - {position}")
                    # Position closed - unsubscribe from market data
                    if symbol in self.subscribed_tickers:
                        self.ib.cancelMktData(contract)
                        self.symbols_to_remove.append(symbol)
                        self.logger.info(f"Unsubscribed from {symbol}")
       
            # Clean up removed subscriptions
            for symbol in self.symbols_to_remove:
                del self.subscribed_tickers[symbol]
           
        except Exception as e:
            self.logger.error(f"Error in update_portfolio_event: {str(e)}")

        

    async def _on_ticker_update(self, ticker: Ticker):
        """
        Enhanced ticker update handler with trading status and price updates
        """
        try:
            self.logger.info(f"new ticker update  - jengo ticker: {ticker}")
            symbol = ticker.contract.symbol
            await asyncio.sleep(0.2)
            self.logger.info(f"after sleep - jengo symbol: {symbol}")
            
            # Skip if we already have a pending order for this symbol
            if symbol in self.pending_orders:
                self.logger.info(f"Skipping ticker update for {symbol} - pending order exists")
                return
                
            self.logger.info(f"on ticker total_unrealized_pnl {self.total_unrealized_pnl}")
            self.halted_open_positions = {}
            positions = await self.ib.reqPositionsAsync()
            halted_conId = ticker.contract.conId
            
            # Filter for the specific conId
            specific_position = next((pos for pos in positions if pos.contract.conId == halted_conId), None)
            
            if not specific_position:
                return
                
            updates = []
            self.logger.info(f"Processing ticker update for {symbol}")
            
            self.current_positions = await self.create_position_index()
            
            # Check if we have a valid position
            if specific_position and specific_position.position != 0:
                conId = specific_position.contract.conId
                
                # Update index
                if symbol not in self.halted_open_positions:
                    self.halted_open_positions[symbol] = conId
                elif self.halted_open_positions[symbol] != conId:
                    self.halted_open_positions[symbol] = conId

                # Check halted status
                if ticker.halted == 1 or ticker.halted == 2:
                    self.logger.info(f"jengo ticker halt: [{ticker}] Trading HALTED")
                    
                    # Add to pending orders before placing the order
                    
                    trade = await self._place_market_order(specific_position)
                    
                    
                    if not trade:
                        # If order placement failed, remove from pending
                        self.pending_orders.remove(symbol)
                    
                    # Clean up closed positions from the index
                    self.halted_open_positions = {
                        sym: con_id for sym, con_id in self.halted_open_positions.items() 
                        if sym in self.current_positions
                    }
                    
                    updates.append("HALTED")
                elif ticker.halted == 0 or math.isnan(ticker.halted):
                    updates.append("TRADING")

            # Collect all available price information with NaN checks
            if ticker.last is not None and ticker.lastSize is not None:
                if not math.isnan(ticker.last) and not math.isnan(ticker.lastSize):
                    updates.append(f"Last: ${ticker.last:.2f} (size: {ticker.lastSize})")
        
            if ticker.bid is not None and ticker.ask is not None:
                if not math.isnan(ticker.bid) and not math.isnan(ticker.ask):
                    updates.append(f"Bid: ${ticker.bid:.2f}, Ask: ${ticker.ask:.2f}")
        
            if ticker.volume is not None and not math.isnan(ticker.volume):
                updates.append(f"Volume: {ticker.volume:,.0f}")
        
            if ticker.high is not None and not math.isnan(ticker.high):
                updates.append(f"High: ${ticker.high:.2f}")
        
            if ticker.low is not None and not math.isnan(ticker.low):
                updates.append(f"Low: ${ticker.low:.2f}")
        
            # Only log if we have updates to report
            if updates:
                self.logger.debug(f"[{symbol}] " + " | ".join(updates))
            
        except Exception as e:
            self.logger.error(f"Error in ticker update handler: {str(e)}", exc_info=True)
                
    async def order_status_event(self, trade: Trade):
        """Enhanced order status handler with pending order cleanup"""
        self.logger.debug(f"Received order status event: {trade}")
        
        symbol = trade.contract.symbol
        
        if trade.orderStatus.status == 'Filled':
            self.logger.info(f"Order filled for {symbol}")
            
            # Clean up tracking
            if symbol in self.pending_orders:
                self.pending_orders.remove(symbol)
            
            self.closed_positions.add(symbol)
            
            self.logger.info(f"Closed positions: {self.closed_positions}")
            self.logger.info(f"Open positions: {self.open_positions}")
            self.logger.info(f"Current positions: {self.current_positions}")
            
        elif trade.orderStatus.status in ['Cancelled', 'ApiCancelled']:
            # Clean up tracking for cancelled orders
            if symbol in self.pending_orders:
                self.pending_orders.remove(symbol)
                
        return trade

    async def new_order_event(self, trade: Trade):
        self.logger.info(f"jengo Received new order status event: {trade} and self.pending_orders is {self.pending_orders}")
        if trade.contract.symbol not in self.pending_orders:
            self.logger.info(f"jengo Adding new pending order for {trade.contract.symbol}")

            self.pending_orders.add(trade.contract.symbol)
            
        
        if trade:
            if trade.orderStatus == 'Filled':
                self.logger.info(f"Order filled for {trade.contract.symbol}")
                self.closed_positions.add(trade.contract.symbol)
                self.logger.info(f"Closed positions: {self.closed_positions}")
                self.logger.info(f"Open positions: {self.open_positions}")
                self.logger.info(f"Current positions: {self.current_positions}")
        return trade
    async def connect_with_retry(self) -> bool:
        """Attempt connection with retries"""
        while self.reconnect_attempts < self.max_reconnect_attempts:
            if await self.try_connect():
                return True
                
            self.reconnect_attempts += 1
            if self.reconnect_attempts < self.max_reconnect_attempts:
                wait_time = self.reconnect_delay * (1 ** self.reconnect_attempts)
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
            

    async def _place_closing_order(self, portfolio_item: PortfolioItem):
        """Place an order with Interactive Brokers based on the position request."""
        try:
            
            ny_tz = pytz.timezone('America/New_York')
            current_time = datetime.now(ny_tz)
            is_weekend = current_time.weekday() >= 5
            market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)

            symbol = portfolio_item.contract.symbol 
            pos = abs(portfolio_item.position)
            is_long_position = portfolio_item.position > 0
            
            contract = Contract(
                symbol=symbol,
                exchange='SMART',
                secType='STK',
                currency='USD'
            )

            action = 'SELL' if is_long_position else 'BUY'

            if market_open <= current_time <= market_close and not is_weekend:
                # Use market order during regular trading hours
                order = MarketOrder(
                    action=action,
                    totalQuantity=pos,
                    tif='GTC'
                )
            else:
                # Use limit order outside regular trading hours
                price = await self.get_market_price(symbol)
                if not price:
                    raise ValueError(f"Could not get market price for {symbol}")
                
                order = LimitOrder(
                    action=action,
                    totalQuantity=pos,
                    lmtPrice=round(price, 2),
                    tif='GTC',
                    transmit=True,
                    outsideRth=True
                )

            if symbol in self.pending_orders:
                self.logger.info(f"Skipping ticker update for {symbol} - pending order exists")
                return
            trade = self.ib.placeOrder(contract, order)
            self.logger.info(f"Order placed for {symbol}: {trade}")
            if trade:
                #await self.new_order_event(trade)
                #await self.order_status_event(trade)
                return trade

        except Exception as e:
            self.logger.error(f"Error processing order for {symbol}: {str(e)}", exc_info=True)
            return None

    async def _place_market_order(self, portfolio_item: PortfolioItem):
        """Place an order with Interactive Brokers based on the position request."""
        try:

            symbol = portfolio_item.contract.symbol
            pos = abs(portfolio_item.position)
            is_long_position = portfolio_item.position > 0
            
            contract = Contract(
                symbol=symbol,
                exchange='SMART',
                secType='STK',
                currency='USD'
            )

            action = 'SELL' if is_long_position else 'BUY'

            
            order = MarketOrder(
                action=action,
                totalQuantity=pos,
                tif='GTC'
            )

            trade = self.ib.placeOrder(contract, order)
            if trade:
                #await self.new_order_event(trade)
                #await self.order_status_event(trade)
                self.logger.info(f"jengo Order placed for {symbol}: {trade}")
                return trade
            else:
                return False

        except Exception as e:
            self.logger.error(f"Error processing order for {symbol}: {str(e)}", exc_info=True)
            return None
        

    async def run(self):
        """Main run loop with connection management and graceful shutdown."""
        try:
            print("Starting Price Service in run loop...")
            

            await self.init_price_service()
            if not await self.connect_with_retry():
                self.logger.error("Initial connection failed")
                return

            while True:
                try:
                    await self.ensure_connected()
                    
                    
                    # Ensure price service is connected
                    
                    if self.price_service and not self.price_service.client.isConnected():
                        self.logger.debug("Running price service connection in run loop...")
                        await self.init_price_service()
                    
                    await asyncio.wait_for(self.ib.updateEvent, timeout=1)

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
        """Gracefully disconnect all services."""
        try:
            # Disconnect price service
            if self.price_service:
                if self.price_service.client.isConnected():
                    self.price_service.client.disconnect()
                self.price_service = None
                self.logger.info("Price service disconnected")

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

    async def get_market_price(self, symbol: str) -> Optional[float]:
        """Get market price using RealtimePriceService with fallback to Tiingo"""
        try:
            if not self.price_service or not self.price_service.client.isConnected():
                self.logger.warning("Price service not connected, attempting to reconnect...")
                await self.init_price_service()
            
            if not self.price_service:
                self.logger.error("Price service unavailable")
                return await self._get_tiingo_price(symbol)
                
            price = await self.price_service.get_price(symbol)
            if price is not None:
                self.logger.info(f"Got price for {symbol} from RealtimePriceService: {price}")
                return price
            
            self.logger.warning(f"Could not get price from RealtimePriceService for {symbol}, falling back to Tiingo")
            return await self._get_tiingo_price(symbol)
            
        except Exception as e:
            self.logger.error(f"Error getting market price for {symbol}: {str(e)}")
            return await self._get_tiingo_price(symbol)


            
if __name__ == '__main__':
    load_dotenv()
    
    client = PnLMonitor()
    asyncio.run(client.run())