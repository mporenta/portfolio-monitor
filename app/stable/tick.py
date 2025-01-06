from operator import is_
import pandas as pd
import asyncio
import math
from contextlib import asynccontextmanager
from fastapi.background import P
import aiohttp
import requests
import json
from ib_async import *
from typing import *
from datetime import datetime, timedelta
import pytz
import os
from dotenv import load_dotenv
import time
import logging
from typing import Optional, List
load_dotenv()
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
        self.collected_ticks = []
        self.collected_bars = []

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
        self.client_id = 199
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
            
            self.logger.info(f"In try_connect: jengo subscribe_events Connection established with {self.host} and clientId: {self.client_id} for account: {self.account}")
            await self.init_price_service()
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
                    
                    

                    self.logger.info(f"In try_connect: jengo subscribe_events Connection established with {self.host} and clientId: {self.client_id} for account: {self.account}")
                    await self.init_price_service()
                    return True
                except Exception as inner_e:
                    self.logger.error(f"Localhost connection failed: {inner_e}")
            else:
                self.logger.error(f"Connection error: {e}")
            return False
    
  
    

    async def create_position_index(self):
        """Create an index of current open positions."""
        
        for position in self.ib.positions():
            if position.position != 0:  # Only index non-zero positions
                symbol = position.contract.symbol
                self.current_positions[symbol] = position.contract.conId
        return self.current_positions

       

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
            

    

    async def init_price_service(self):
    
        # Local lists for record-keeping
        self.collected_ticks = []
        self.collected_bars = []
        try:
            current_positions = await self.ib.reqPositionsAsync()
            print(f"jengo Current positions: {current_positions}")
        
            # Process each position from the request
            for position in current_positions:
                symbol = position.contract.symbol
                conId = position.contract.conId
                primaryExchange = position.contract.primaryExchange
        
                # 2) Create and qualify a US stock contract
                contract = Contract()
                contract.symbol = symbol
                contract.secType = "STK"
                contract.exchange = "SMART"
                contract.currency = "USD"
                contract.conId = conId
                contract.primaryExchange = primaryExchange

                qualified = await self.ib.qualifyContractsAsync(contract)
                if qualified:
                    contract = qualified[0]
                    self.ib.reqMktData(contract, '', False, False)
                    print(f"Qualified contract: {contract}")
                else:
                    print("Failed to qualify contract. Check contract details.")
                    return

                # 3) Subscribe to TICK-BY-TICK data
                #    - 'AllLast' means all trades from all relevant exchanges
                
                ticker = self.ib.reqTickByTickData(contract, tickType="AllLast", numberOfTicks=0, ignoreSize=False)
                print(f"Subscribed to tick-by-tick data for {contract.symbol}...")

                # 4) Hook our tick callback to the pendingTickersEvent
                self.ib.pendingTickersEvent += self.onPendingTickers

                # 5) Subscribe to 5-second REAL-TIME BARS
                bars = self.ib.reqRealTimeBars(contract, barSize=5, whatToShow="MIDPOINT", useRTH=False)
                print("Subscribed to real-time bars (5-sec, MIDPOINT).")

                # 6) Hook the onBarUpdate callback to the bars
                bars.updateEvent += self.onBarUpdate

        except Exception as e:
            self.logger.error(f"Error in init_price_service: {str(e)}")

        

    # --- TICK-BY-TICK CALLBACK ---
    async def onPendingTickers(sef, tickers):
        """
        Called automatically whenever *any* ticker
        has fresh tickByTicks data.
        """
        for ticker in tickers:
            while ticker.tickByTicks:
                tick_data = ticker.tickByTicks.pop(0)
                self.collected_ticks.append(tick_data)
                print("TickByTick from pendingTickersEvent:", tick_data)
                print(f"Collected {len(self.collected_ticks)} total ticks.")
                return self.collected_ticks

    # --- REAL-TIME BARS CALLBACK ---
    async def onBarUpdate(self, bar_list, hasNewBar):
        """
        Called automatically every time a new 5-sec bar arrives
        or an existing bar changes. We'll store and print the latest bar.
        """
        last_bar = bar_list[-1]  # The most recent bar
        self.collected_bars.append(last_bar)
        print("RealTimeBar:", last_bar)
        return self.collected_bars
    
    


    
    
        print(f"Collected {len(self.collected_bars)} real-time bars.")   

    async def run(self):
        """Main run loop with connection management and graceful shutdown."""
        try:
            print("Starting Price Service in run loop...")
            

            
            if not await self.connect_with_retry():
                self.logger.error("Initial connection failed")
                return

            while True:
                try:
                    await self.ensure_connected()
                    
                    
                    # Ensure price service is connected
                    
                    
                    
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
            if self.no_price_service:
                if self.no_price_service.client.isConnected():
                    self.no_price_service.client.disconnect()
                self.no_price_service = None
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
            if not self.no_price_service or not self.no_price_service.client.isConnected():
                self.logger.warning("Price service not connected, attempting to reconnect...")
                await self.init_price_service_delete()
            
            if not self.no_price_service:
                self.logger.error("Price service unavailable")
                return await self._get_tiingo_price(symbol)
                
            price = await self.no_price_service.get_price(symbol)
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

