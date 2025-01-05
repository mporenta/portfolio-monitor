import json
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, Depends, Body
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import redis
import redis.asyncio as aioredis
from operator import is_
import pandas as pd
import asyncio
import math
from contextlib import asynccontextmanager
from fastapi.background import P
from fastapi.middleware.cors import CORSMiddleware
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
outputFolder = os.getenv('OUTPUT_FOLDER', 'output/')
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



from models import HaltedData  # Import the Pydantic models
# Instantiate Redis client (host defaults to the service name 'redis' in docker-compose)
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", 6381))


# Async Redis client (host "redis" from docker-compose, port 6381).
r = aioredis.Redis(host=redis_host, port=redis_port, db=0)

async def store_halted_tickers_in_redis(key: str, data: HaltedData):
    """
    Asynchronously writes the given HaltedData (Pydantic model) as JSON string to Redis.
    """
    # Convert the Pydantic model to a dict, then dump to JSON
    json_str = data.json()
    await r.set(key, json_str)

async def read_halted_tickers_from_redis(key: str) -> HaltedData | None:
    """
    Asynchronously reads the JSON string from Redis, converts it to the HaltedData model (if found).
    Returns None if the key doesn't exist.
    """
    raw_data = await r.get(key)
    if raw_data is not None:
        # Parse the JSON string back into the Pydantic model
        return HaltedData.parse_raw(raw_data)
    else:
        return None

def pull_ticker_data_from_ib():
    """
    Placeholder function for pulling stock ticker data from IB Gateway using ib_async and TWS API.
    """
    pass
# Initialize FastAPI app with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan with proper task management"""
    global client
    background_tasks = set()
    
    try:
        logging.info("Starting FastAPI application lifespan...")
        load_dotenv()
        
        client = streamTickData()
        logging.info("streamTickData initialized")
        
        # Start streamTickData in background
        task = asyncio.create_task(client.run())
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        
        yield
        
    except Exception as e:
        logging.error(f"Error in lifespan startup: {str(e)}", exc_info=True)
        raise
    finally:
        logging.info("Starting graceful shutdown...")
        
        # Proper task cancellation
        try:
            # Convert set to list before iteration to avoid size change issues
            tasks = list(background_tasks)
            for task in tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                        
            # Clean disconnect
            if client:
                await client.graceful_disconnect()
                logging.info("streamTickData gracefully disconnected")
                
        except Exception as e:
            logging.error(f"Error during shutdown: {str(e)}", exc_info=True)
        finally:
            logging.info("FastAPI application shutdown complete")

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="PnL Monitor with Redis",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://portfolio.porenta.us", "https://tv.porenta.us"],  # List all trusted origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],  # Limit methods if possible
    allow_headers=["*"],  # Adjust headers as needed
)

@app.get("/")
async def root():
    """
    Simple root endpoint to verify the API is running.
    """
    return {"message": "Hello from the Halted Tickers API with Pydantic!"}

@app.post("/halted_tickers", response_model=HaltedData)
async def create_halted_tickers(halted_data: HaltedData = Body(...)):
    """
    POST route to store new halted ticker data into Redis.
    Returns the same data as confirmation.
    """
    await store_halted_tickers_in_redis("halted_tickers", halted_data)
    return halted_data

@app.get("/halted_tickers", response_model=HaltedData)
async def get_halted_tickers():
    """
    GET route to retrieve halted ticker data from Redis.
    Returns the Pydantic model if found, otherwise raises 404.
    """
    data_in_redis = await read_halted_tickers_from_redis("halted_tickers")
    if data_in_redis:
        return data_in_redis
    else:
        # If there's no data, you can return a 404 or a helpful message
        return HaltedData(channel={"title":"N/A","link":"N/A","copyright":"N/A","pubDate":"N/A","ttl":"0","numItems":"0"},
                          items=[])

@app.get("/price/{symbol}")
async def get_ib_data(symbol: str):
    """
    Get real-time market price data for a given symbol.
    Args:
        symbol (str): The stock symbol to fetch price data for
    Returns:
        JSONResponse with market price data or error message
    """
    try:
        # Validate symbol
        if not symbol or not isinstance(symbol, str):
            raise HTTPException(
                status_code=400,
                detail="Invalid symbol provided"
            )
            
        # Ensure client is connected before proceeding
        if not client.ib.isConnected():
            await client.connect_with_retry()
            if not client.ib.isConnected():
                raise HTTPException(
                    status_code=503,
                    detail="Unable to connect to IB Gateway"
                )

        # Get market price
        price = await client.get_market_price(symbol)
        
        if price is False:
            raise HTTPException(
                status_code=404,
                detail=f"Unable to fetch price data for symbol: {symbol}"
            )

        response = {
            "symbol": symbol,
            "price": price,
            "timestamp": datetime.now(pytz.UTC).isoformat()
        }
        
        logging.info(f"Successfully fetched price data for {symbol}: {price}")
        return JSONResponse(
            content=response,
            status_code=200
        )

    except HTTPException as he:
        # Re-raise HTTP exceptions as-is
        raise he
    except Exception as e:
        logging.error(f"Error in get_ib_data for {symbol}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to fetch IB data",
                "message": str(e),
                "timestamp": datetime.now(pytz.UTC).isoformat()
            }
        )



class streamTickData:
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
        self.portfolio_item = []
        self.pnl = PnL()
        self.accounts = []
        self.account = []
        self.halted_open_positions = {}
        self.open_positions = {}  # Dictionary to store open positions index
        self.current_positions = {}  # Dictionary to store current positions index
        self.subscribed_tickers = {}
        self.symbols_to_remove = []
        


        self.risk_amount = risk_amount
        self.closing_initiated = False
        self.closed_positions = set()  # Track which positions have been closed
               # Load environment variables first
        
    
       # Then set connection parameters
        self.host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')  # Default to localhost if not set
        self.port = int(os.getenv('TBOT_IBKR_PORT', '4002'))
        self.client_id = 7878
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
            self.logger.info(f"jengo portfolio_item from try_connect: {self.portfolio_item}")
            await self.monitor_pnl_and_close_positions(self.portfolio_item)
            self.logger.info(f"Subscribing to PnL updates for account: {self.account}")

           
       
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
                self.logger.error(f"Connection error in try_connect: {e}")
            return False  
        

    async def monitor_pnl_and_close_positions(self, portfolio_item: PortfolioItem):
        """Monitor PnL and handle position closures with price service ready"""
        try:
            #

                        
            
            self.ib.updatePortfolioEvent += self.update_portfolio_event

            self.logger.info("Started monitoring PnL and positions.")
            await self.update_portfolio_event(portfolio_item)
            
        except Exception as e:
            self.logger.error(f"Error in PnL update handler: {str(e)}")
          
    async def get_portfolio_data(self):
        """
        Asynchronously retrieves portfolio data from Interactive Brokers.
        
        Args:
            outputFolder (str): Directory path where the CSV file will be saved. Defaults to 'output/'.
            
        Returns:
            tuple: (DataFrame with portfolio data, path to saved CSV file)
            
        Environment Variables:
            IB_GATEWAY_HOST: IB Gateway host (default: 'ib-gateway')
            TBOT_IBKR_PORT: Port number (default: 4002)
            IB_GATEWAY_CLIENT_ID: Client ID (default: 9)
        """
        
        
        myHoldings = []
        header = ['Account', 'Alias', 'secType', 'conId', 'Symbol', 'Exchange', 'Currency', 
                'localSymbol', 'Position', 'avgCost', 'Contract Month', 'Strike', 'Right', 
                'Multiplier', 'Market Price', 'Market Value', 'Unrealized PNL', 'Realized PNL']
        
        try:
            
            accounts = self.ib.managedAccounts()
            
            if not accounts:
                raise ValueError("No accounts found")
                
            for account in accounts:
                myPort = self.ib.portfolio(account)
                await asyncio.sleep(0.1)  # Allow time for portfolio data to arrive
                
                for s in myPort:
                    position = None
                    
                    if s.contract.secType == 'STK':
                        position = [
                            account, account, s.contract.secType, s.contract.conId,
                            s.contract.symbol, s.contract.primaryExchange, s.contract.currency,
                            s.contract.localSymbol, s.position, s.averageCost,
                            None, None, None, None,
                            s.marketPrice, s.marketValue, s.unrealizedPNL, s.realizedPNL
                        ]
                    
                    elif s.contract.secType == 'OPT':
                        position = [
                            account, account, s.contract.secType, s.contract.conId,
                            s.contract.symbol, s.contract.primaryExchange, s.contract.currency,
                            s.contract.localSymbol, s.position, s.averageCost,
                            s.contract.lastTradeDateOrContractMonth, s.contract.strike, 
                            s.contract.right, s.contract.multiplier,
                            s.marketPrice, s.marketValue, s.unrealizedPNL, s.realizedPNL
                        ]
                    
                    elif s.contract.secType == 'CASH':
                        position = [
                            account, account, s.contract.secType, s.contract.conId,
                            s.contract.symbol, None, None, s.contract.localSymbol,
                            s.position, s.averageCost, None, None, None, None,
                            s.marketPrice, s.marketValue, s.unrealizedPNL, s.realizedPNL
                        ]
                    
                    if position:
                        myHoldings.append(position)
                    else:
                        self.logger.warning(f'Warning: Unhandled security type: {s.contract.secType}')
            
            holdings = pd.DataFrame(myHoldings, columns=header)
            now_str = datetime.now().strftime('%Y-%m-%d_%H-%M')
            filepath = os.path.join(outputFolder, f"{now_str}_portfolio.csv")
            
            os.makedirs(outputFolder, exist_ok=True)
            holdings.to_csv(filepath, index=False)
            
            return holdings, filepath
            
        except Exception as e:
            self.logger.error(f"Error in get_portfolio_data: {str(e)}")
            raise
            
        

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
                    self.logger.debug(f"jengo 'position != 0' contract, symbol, position: {contract} - {symbol} - {position} primaryExchange: {item.contract.primaryExchange} - exchange= {contract.exchange}")
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
                            ticker.updateEvent += self.get_market_price
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
        """
        Stream market data for current portfolio positions.
    
        Args:
            duration (int): How long to stream in seconds (default: 30)
    
        Returns:
            pd.DataFrame: Final snapshot of market data
        """
        
    
        try:
            
            accounts = self.ib.managedAccounts()
        
            if not accounts:
                raise ValueError("No accounts found")
            
            positions = []
            for account in accounts:
                myPort = self.ib.portfolio(account)
                await asyncio.sleep(0.1)
                positions.extend([pos for pos in myPort if pos.contract.secType == 'STK'])
            
            for pos in positions:
                self.ib.reqMktData(pos.contract, '', False, False)
            
            df = pd.DataFrame(
                index=[pos.contract.symbol for pos in positions],
                columns=['bidSize', 'bid', 'ask', 'askSize', 'high', 'low', 'close']
            )
        
            def onPendingTickers(tickers: Ticker):
                for t in tickers:
                    if t.contract.symbol in df.index:
                        df.loc[t.contract.symbol] = (
                            t.bidSize, t.bid, t.ask, t.askSize, t.high, t.low, t.close)
                self.logger.debug(df)
            
            self.ib.pendingTickersEvent += onPendingTickers
            await asyncio.sleep(30)
            self.ib.pendingTickersEvent -= onPendingTickers
        
            for pos in positions:
                self.ib.cancelMktData(pos.contract)
            
            return df
        
        except Exception as e:
            self.logger.error(f"Error in update_portfolio_event: {str(e)}")
            raise

    async def get_market_price(self, symbol: str) -> Optional[float]:
        """Get  price using reqRealTimeBars"""
        try:
            self.positions = await self.ib.reqPositionsAsync()
            for item in self.positions:
                if item.contract.symbol != symbol:
                    continue

                
                
                contract = Contract(
                    symbol=symbol,
                    exchange= 'SMART',
                    secType='STK',
                    currency='USD',
                    conId=item.contract.conId,
                    primaryExchange= item.contract.primaryExchange
                )
                bars = self.ib.reqRealTimeBars(
                    contract=contract,
                    barSize=5,
                    barSizeSetting='5 secs', 
                    whatToShow='TRADES', 
                    useRTH=False
                )
                """
                Request realtime 5 second bars.

                https://interactivebrokers.github.io/tws-api/realtime_bars.html

                Args:
                    contract: Contract of interest.
                    barSize: Must be 5.
                    whatToShow: Specifies the source for constructing bars.
                        Can be 'TRADES', 'MIDPOINT', 'BID' or 'ASK'.
                    useRTH: If True then only show data from within Regular
                        Trading Hours, if False then show all data.
                    realTimeBarsOptions: Unknown.
                """
                        
                if not bars:
                    self.logger.warning(f"No price data available for {symbol}")
            
                last_price = bars[-1].close
                print(f"jengo last_price: {last_price}")
                return last_price
              
                
        except Exception as e:
            self.logger.error(f"Error getting market price for {symbol}: {str(e)}")
            return False
    async def redis_test(self):
        test_key = "test_key"
        test_value = "Hello from ib_portfolio!"
        r.set(test_key, test_value)
        retrieved_value = r.get(test_key)
        logging.info(f"Redis test - Set '{test_key}' to '{test_value}', retrieved '{retrieved_value.decode()}'")
        return retrieved_value.decode()
    async def run(self):
        """Main run loop with connection management and graceful shutdown."""
        try:
            self.logger.info("jengo Starting main run loop... and testing redis")
            await self.redis_test()
            

            # Your existing run logic continues below...
            if not self.ib.isConnected():
                await self.try_connect()
                self.logger.error("Initial connection failed")
                return

            while True:
                try:
                    
                    
                    
                                       
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
           
            if self.ib.isConnected():
                self.logger.info("Unsubscribing from events...")
                self.ib.pnlEvent.clear()
                self.ib.newOrderEvent.clear()
                self.ib.accountValueEvent.clear()
                
                



                self.ib.wrapper.portfolio.clear()
                self.ib.wrapper.positions.clear()

                self.logger.info("Disconnecting from IB Gateway...")
                self.ib.disconnect()
        except Exception as e:
            self.logger.error(f"Error during graceful disconnect: {e}")

if __name__ == '__main__':
    load_dotenv()
    
    client = streamTickData()
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
