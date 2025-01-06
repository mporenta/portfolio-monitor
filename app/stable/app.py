from redis.asyncio import Redis
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from shorts import ShortStockManager
import httpx
from datetime import datetime
from typing import List, Dict, Optional, Union, Any
import pytz
import json
import aiohttp
import time
from dotenv import load_dotenv
from ib_async import *
import logging
import signal
import requests
import asyncio
import os
from fastapi.middleware.cors import CORSMiddleware
import sys
load_dotenv()
redis: Redis = None
loadDotEnv = load_dotenv()
tiingo_token = os.getenv('TIINGO_API_TOKEN')
unique_ts = str((time.time_ns() // 1000000) -  (4 * 60 * 60 * 1000))
short_stock_manager = ShortStockManager()
account_value= []
net_liquidation = 0.0
def get_timestamp(unique_ts: str) -> str:
    """Get timestamp for database"""
    dtime = datetime.fromtimestamp(int(unique_ts) / 1000.0)
    dtime_str = dtime.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return dtime_str


timestamp = get_timestamp(unique_ts)

ib = IB()
portfolio_items = ib.portfolio()
tbotKey = os.getenv("TVWB_UNIQUE_KEY", "WebhookReceived:1234")
PORT = int(os.getenv("PNL_HTTPS_PORT", "5001"))
client_id = int(os.getenv('FASTAPI_IB_CLIENT_ID', '1111'))
IB_HOST = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')  
ibPort = os.getenv('TBOT_IBKR_PORT')
max_attempts=300
initial_delay=1
# Get the src directory path
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (project root)
ROOT_DIR = os.path.dirname(SRC_DIR)
DATA_DIR = "/app/data"
# Set up logging
log_file_path = '/app/logs/app.log'
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
pnl_threshold = float(os.getenv("WEBHOOK_PNL_THRESHOLD", "-300"))
log_level = os.getenv('TBOT_LOGLEVEL', 'INFO')
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
class PositionCloseRequest(BaseModel):
    contract: Contract
    position: float
    marketPrice: float
    marketValue: float
    averageCost: float
    unrealizedPNL: float
    realizedPNL: float
    account: str
    symbol: str
    action: str
    quantity: int

class ClosePositionsRequestSchema(BaseModel):
    positions: List[PositionCloseRequest]

# Pydantic models for request/response validation
class PositionCreate(BaseModel):
    symbol: str
    action: str
    quantity: int
    price: float

class PositionResponse(BaseModel):
    symbol: str
    position: float
    market_price: float
    market_value: float
    average_cost: float
    unrealized_pnl: float
    realized_pnl: float
    account: str
    exchange: str
    timestamp: datetime
    

    class Config:
        from_attributes = True

class PositionsRequest(BaseModel):
    positions: List[PositionCreate]

class Metric(BaseModel):
    name: str
    value: float

class WebhookRequest(BaseModel):
    timestamp: int
    ticker: str
    currency: str
    timeframe: str
    clientId: int
    contract: str
    orderRef: str
    direction: str
    metrics: List[Metric]
class IBRedisSync:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.net_liquidation = net_liquidation

    async def initialize(self, ib: IB):
        self.ib = ib
        # Set up event handlers for real-time updates
        self.ib.pnlEvent += self._handle_pnl_update
        self.ib.orderStatusEvent += self._handle_order_update
        logger.info("IBRedisSync initialized")
    
        
    async def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info("IBRedisSync service started")

    async def stop(self):
        self.running = False
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _sync_loop(self):
        """Main sync loop for periodic data updates"""
        while self.running:
            try:
                if not self.ib.isConnected():
                    await asyncio.sleep(5)
                    continue

                await asyncio.gather(
                    self._sync_portfolio_data(),
                    self._sync_contract_data(),
                    self._sync_pnl_data(),
                    self._sync_trade_data(),
                    self._sync_ib_data(),
                    self.on_account_value_update()
                )
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                await asyncio.sleep(5)
    async def _handle_order_update(self, trade: Trade):
        """Real-time Trade updates"""
        try:
            open_orders = await self.ib.reqAllOpenOrdersAsync()
            contract_data = []
            for trade in open_orders:
                # Get the timestamp from the first log entry
                log_time = trade.log[0].time if trade.log else None
                
                trade_dict = {
                    "contract": {
                        "symbol": trade.contract.symbol,
                        "conId": trade.contract.conId,
                        "exchange": trade.contract.exchange,
                        "currency": trade.contract.currency
                    },
                    "order": {
                        "permId": trade.order.permId,
                        "action": trade.order.action,
                        "totalQuantity": trade.order.totalQuantity,
                        "orderType": trade.order.orderType,
                        "lmtPrice": trade.order.lmtPrice,
                        "auxPrice": trade.order.auxPrice,
                        "tif": trade.order.tif,
                        "orderRef": trade.order.orderRef or ""
                    },
                    "orderStatus": {
                        "status": trade.orderStatus.status,
                        "filled": trade.orderStatus.filled,
                        "remaining": trade.orderStatus.remaining,
                        "avgFillPrice": trade.orderStatus.avgFillPrice,
                        "permId": trade.orderStatus.permId,
                        "lastFillPrice": trade.orderStatus.lastFillPrice
                    },
                    "log": [{
                        "time": log_time.isoformat() if log_time else None,
                        "status": entry.status,
                        "message": entry.message,
                        "errorCode": entry.errorCode
                    } for entry in trade.log]
                }
                contract_data.append(trade_dict)
                
                # Store by symbol for quick lookup
                await self.redis.hset(
                    f"contract:{trade.contract.symbol}",
                    trade.order.permId,
                    json.dumps(trade_dict)
                )
            
            # Store full contract data
            await self.redis.set('contract:data', json.dumps(contract_data))
        except Exception as e:
            logger.error(f"Error syncing contract data: {e}")
    async def _handle_pnl_update(self, pnl: PnL):
        """Real-time PNL updates"""
        try:
            pnl_data = {
                'unrealized_pnl': float(pnl.unrealizedPnL or 0),
                'realized_pnl': float(pnl.realizedPnL or 0),
                'daily_pnl': float(pnl.dailyPnL or 0),
            }
            await self.redis.hset('current:pnl', mapping=pnl_data)
        except Exception as e:
            logger.error(f"Error handling PNL update: {e}")

    async def _sync_portfolio_data(self):
        """Sync portfolio items"""
        try:
            logger.info("jengo Syncing portfolio data in redis...")
            portfolio_items = self.ib.portfolio()
            portfolio_data = [
                {
                    "account": item.account,
                    "contract": item.contract.symbol,
                    "conId": item.contract.conId,
                    "position": item.position,
                    "unrealizedPNL": item.unrealizedPNL,
                    "realizedPNL": item.realizedPNL,
                    "marketPrice": item.marketPrice,
                    "marketValue": item.marketValue,
                }
                for item in portfolio_items
            ]
            await self.redis.set('portfolio:data', json.dumps(portfolio_data))
        except Exception as e:
            logger.error(f"Error syncing portfolio data: {e}")

    async def _sync_contract_data(self):
        """Sync open orders and contracts"""
        try:
            open_orders = await self.ib.reqAllOpenOrdersAsync()
            contract_data = []
            for trade in open_orders:
                # Get the timestamp from the first log entry
                log_time = trade.log[0].time if trade.log else None
                
                trade_dict = {
                    "contract": {
                        "symbol": trade.contract.symbol,
                        "conId": trade.contract.conId,
                        "exchange": trade.contract.exchange,
                        "currency": trade.contract.currency
                    },
                    "order": {
                        "permId": trade.order.permId,
                        "action": trade.order.action,
                        "totalQuantity": trade.order.totalQuantity,
                        "orderType": trade.order.orderType,
                        "lmtPrice": trade.order.lmtPrice,
                        "auxPrice": trade.order.auxPrice,
                        "tif": trade.order.tif,
                        "orderRef": trade.order.orderRef or ""
                    },
                    "orderStatus": {
                        "status": trade.orderStatus.status,
                        "filled": trade.orderStatus.filled,
                        "remaining": trade.orderStatus.remaining,
                        "avgFillPrice": trade.orderStatus.avgFillPrice,
                        "permId": trade.orderStatus.permId,
                        "lastFillPrice": trade.orderStatus.lastFillPrice
                    },
                    "log": [{
                        "time": log_time.isoformat() if log_time else None,
                        "status": entry.status,
                        "message": entry.message,
                        "errorCode": entry.errorCode
                    } for entry in trade.log]
                }
                contract_data.append(trade_dict)
                
                # Store by symbol for quick lookup
                await self.redis.hset(
                    f"contract:{trade.contract.symbol}",
                    trade.order.permId,
                    json.dumps(trade_dict)
                )
            
            # Store full contract data
            await self.redis.set('contract:data', json.dumps(contract_data))
        except Exception as e:
            logger.error(f"Error syncing contract data: {e}")

    async def _sync_pnl_data(self):
        """Sync PNL data"""
        try:
            accounts = self.ib.managedAccounts()
            account = accounts[0] if accounts else None
            if account:
                pnl_items = self.ib.pnl(account)
                pnl_data = [{
                    'daily_pnl': item.dailyPnL,
                    'total_unrealized_pnl': item.unrealizedPnL,
                    'total_realized_pnl': item.realizedPnL,
                    'net_liquidation': await self.on_account_value_update(),
                } for item in pnl_items]
                await self.redis.set('pnl:data', json.dumps(pnl_data))
        except Exception as e:
            logger.error(f"Error syncing PNL data: {e}")

    async def _sync_trade_data(self):
        """Sync trade data"""
        try:
            trades = await self.ib.reqAllOpenOrdersAsync()
            trades_data = [{
                "tradeId": trade.order.permId,
                "contract": trade.contract.symbol,
                "action": trade.order.action,
                "position": trade.order.totalQuantity,
                "status": trade.orderStatus.status,
                "orderType": trade.order.orderType,
                "limitPrice": trade.order.lmtPrice,
                "avgFillPrice": trade.orderStatus.avgFillPrice,
                "filled": trade.orderStatus.filled,
                "remaining": trade.orderStatus.remaining
            } for trade in trades]
            await self.redis.set('trade:data', json.dumps(trades_data))
        except Exception as e:
            logger.error(f"Error syncing trade data: {e}")

    async def on_account_value_update(self):
        """Update stored NetLiquidation whenever it changes."""
        try:
            account_value= await self.ib.accountSummaryAsync()
            for account_value in account_value:
                if account_value.tag == "NetLiquidation":
                    self.net_liquidation = float(account_value.value)
                    logger.info(f"NetLiquidation updated: ${self.net_liquidation:,.2f}")
                    print(f"jengo NetLiquidation updated: ${self.net_liquidation:,.2f}")
                    return self.net_liquidation
        except Exception as e:
            logger.error(f"Error getting account values  for {account_value}: {str(e)}")
        
    async def _sync_ib_data(self):
        """Sync combined IB data"""
        try:
            positions = await self.ib.reqPositionsAsync()
            await asyncio.sleep(0.5)
            
            positions_data = [{
                "account": pos.account,
                "contract": pos.contract.symbol,
                "position": pos.position,
                "avgCost": pos.avgCost,
                "marketPrice": getattr(pos, 'marketPrice', None),
                "marketValue": getattr(pos, 'marketValue', None)
            } for pos in positions]

            trades = self.ib.executions()
            trades_data = [{
                "tradeId": trade.order.orderId,
                "contract": trade.contract.symbol,
                "action": trade.order.action,
                "quantity": trade.order.totalQuantity,
                "status": trade.orderStatus.status,
                "orderType": trade.order.orderType,
                "limitPrice": getattr(trade.order, 'lmtPrice', None),
                "avgFillPrice": trade.orderStatus.avgFillPrice,
                "filled": trade.orderStatus.filled,
                "remaining": trade.orderStatus.remaining
            } for trade in trades]

            ib_data = {
                "positions": positions_data,
                "trades": trades_data,
            }
            
            await self.redis.set('ib:data', json.dumps(ib_data))
        except Exception as e:
            logger.error(f"Error syncing IB data: {e}")

redis_sync=IBRedisSync(Redis)
# Redis connection parameters from environment variables with defaults
# At the top with other globals
REDIS_HOST = os.getenv('FAST_REDIS_HOST', 'redis_fastapi')  # Use container name
REDIS_PORT = int(os.getenv('FAST_REDIS_PORT', 6380))
REDIS_DB = int(os.getenv('FAST_REDIS_DB', 0))
FAST_REDIS_PASSWORD = os.getenv("FAST_REDIS_PASSWORD", None)  # Optional password

async def init_redis() -> Redis:
    """Initialize Redis connection"""
    try:
       
        redis = Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True
        )
        # Test connection
        await redis.ping()
        logger.info(f"jengo init_redis() -> Redis: Successfully connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        return redis
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise

async def close_redis(redis: Redis):
    """Close Redis connection"""
    try:
        await redis.close()
        logger.info("Redis connection closed")
    except Exception as e:
        logger.error(f"Error closing Redis connection: {e}")
# Initialize FastAPI app with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis
    logger.info("Loading .env in lifespan...")
    
    # Initialize Redis
    try:
        redis = Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True
        )
        await redis.ping()  # Test connection
        logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        
        # Initialize Redis sync
        redis_sync = IBRedisSync(redis)
        await redis_sync.initialize(ib)
        await redis_sync.start()
        app.state.redis_sync = redis_sync  # Store in app state for cleanup
        
    except Exception as e:
        logger.error(f"Failed to initialize Redis: {e}")
        raise

    async def try_connect():
        logger.info(f"jengo try connect() Attempting to connect to IB Gateway at {IB_HOST}...")
        try:
            
            await ib.connectAsync(
                host=IB_HOST,
                port=ibPort,
                clientId=client_id,
                timeout=20
            )
            logger.info(f"jengo awaiting connectAsync()  at host: {IB_HOST}...")
            accounts = ib.managedAccounts()
            account = accounts[0] if accounts else None
            ib.reqPnL(account)
            ib.reqAccountSummaryAsync()
            # Initialize Redis sync
            await app.state.redis_sync.initialize(ib)
            await app.state.redis_sync.start()
            
            
            ib.disconnectedEvent += on_disconnected
            logger.info("Connected to IB Gateway and subscribed to disconnection event")
            return True
        except Exception as e:
            if 'getaddrinfo failed' in str(e):
                logger.warning(f"Connection failed with {IB_HOST}, trying localhost")
                try:
                    
                    await ib.connectAsync(
                        host='127.0.0.1',
                        port=ibPort,
                        clientId=client_id,
                        timeout=20
                    )
                    logger.info(f"jengo awaiting connectAsync()  at host: {IB_HOST}...")
                    accounts = ib.managedAccounts()
                    account = accounts[0] if accounts else None
                    
                    ib.reqPnL(account)
                    ib.positionEvent += on_pnl_event
                    ib.reqAccountSummaryAsync()
                    # Initialize Redis sync
                    await app.state.redis_sync.initialize(ib)
                    await app.state.redis_sync.start()
                    
                    ib.disconnectedEvent += on_disconnected
                    logger.info("Connected to IB Gateway and subscribed to disconnection event")
                    return True
                except Exception as inner_e:
                    logger.error(f"Localhost connection failed: {inner_e}")
            else:
                logger.error(f"Connection error: {e}")
            return False

    async def on_disconnected():
        """Handle disconnection"""
        logger.warning("Disconnected from IB Gateway")
        if not ib.isConnected():
            await connect_with_retry()   

    async def connect_with_retry():
        logger.info("Attempting to reconnect to IB Gateway...")
        attempt = 0
        while attempt < max_attempts:
            if await try_connect():
                logger.info("Successfully connected to IB Gateway")
                return True
                
            attempt += 1
            if attempt < max_attempts:
                delay = initial_delay * (1 ** attempt)
                logger.info(f"Retrying connection in {delay} seconds... "
                           f"(Attempt {attempt + 1}/{max_attempts})")
                await asyncio.sleep(delay)
                
        logger.error("Max reconnection attempts reached")
        return False

    try:
        logger.info("Connecting to IB Gateway...")
        if not await connect_with_retry():
            raise RuntimeError("Failed to connect to IB Gateway after multiple attempts")
            
        # Initialize short stock data
        logger.info("Initializing short stock data...")
        await short_stock_manager.fetch_and_parse_short_availability()
        short_stock_manager.start_scheduler()
        logger.info("Short stock manager initialized and scheduler started.")
        
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        if ib and ib.isConnected():
            ib.disconnect()  # Remove await here
        raise RuntimeError(f"Startup failed: {e}")
    
    yield  # Application runs here
    
    # Cleanup
    try:
        logger.info("Starting shutdown process...")
         # Stop Redis sync
        if redis:
            await redis.close()
            logger.info("Redis connection closed")
        
        # Disconnect from IB if connected
        if ib and ib.isConnected():
            logger.info("Disconnecting from IB Gateway...")
            ib.disconnect()  # Remove await here
            logger.info("Disconnected from IB Gateway.")
        
        # Stop the short stock scheduler
        logger.info("Stopping short stock scheduler...")
        short_stock_manager.stop_scheduler()
        logger.info("Short stock scheduler stopped.")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
        raise

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="PnL Monitor",
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

# Set up templates
templates = Jinja2Templates(directory=os.path.join(ROOT_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(ROOT_DIR, "static")), name="static")

@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str):
    return Response(
        headers={
            "Access-Control-Allow-Origin": "*",  # Change '*' to specific origins in production
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
        status_code=204,  # No content
    )
@app.post("/proxy/webhook")
async def proxy_webhook(webhook_data: WebhookRequest):
    pnl= PnL()
    try:
        # Get price from metrics
        price = next((metric.value for metric in webhook_data.metrics if metric.name == "price"), None)
        
        # Check if price is below threshold and fetch trade halts if needed
        if price is not None and price < 10.0:
            logger.info(f"Price {price} is below 10.0, checking trade halts for {webhook_data.ticker}")
            
            # Fetch current trade halts
            await short_stock_manager.fetch_and_parse_trade_halts()
            rss_data = short_stock_manager.parse_rss_to_json(short_stock_manager.fetch_rss_feed())
            
            # Check if ticker is in halts
            ticker_halt = next((item for item in rss_data.get("items", []) 
                              if item.get("IssueSymbol") == webhook_data.ticker), None)
            
            if ticker_halt:
                logger.info(f"Found halt data for {webhook_data.ticker}")
                
                # Check ResumptionDate and ResumptionTradeTime
                if not ticker_halt.get("ResumptionDate"):
                    logger.warning(f"No resumption date for {webhook_data.ticker}, blocking webhook")
                    return JSONResponse(
                        status_code=403,
                        content={
                            "status": "rejected",
                            "message": f"Trading halted for {webhook_data.ticker} with no resumption date"
                        }
                    )
                
                # Check if enough time has passed since resumption
                try:
                    ny_tz = pytz.timezone('America/New_York')
                    now = datetime.now(ny_tz)
                    
                    resumption_datetime = datetime.strptime(
                        f"{ticker_halt['ResumptionDate']} {ticker_halt['ResumptionTradeTime']}", 
                        "%m/%d/%Y %H:%M:%S"
                    )
                    resumption_datetime = ny_tz.localize(resumption_datetime)
                    
                    time_since_resumption = (now - resumption_datetime).total_seconds()
                    
                    if time_since_resumption < 300:  # Less than 5 minutes
                        logger.warning(f"Not enough time passed since resumption for {webhook_data.ticker}")
                        return JSONResponse(
                            status_code=403,
                            content={
                                "status": "rejected",
                                "message": f"Only {time_since_resumption} seconds have passed since trading resumed for {webhook_data.ticker}. Required: 300 seconds"
                            }
                        )
                except Exception as e:
                    logger.error(f"Error processing resumption time: {str(e)}")
                    # If we can't process the time properly, reject for safety
                    return JSONResponse(
                        status_code=403,
                        content={
                            "status": "rejected",
                            "message": f"Error processing halt data for {webhook_data.ticker}"
                        }
                    )
        try:
            loadDotEnv
            logger.info(f"loadDotEnv{loadDotEnv}")
            logger.info("Received webhook request")
            logger.debug(f"Incoming webhook data: {webhook_data.model_dump()}")
            # Check if it's a short entry order
            if "entryshort" in webhook_data.direction.lower():
                # Check if all entry values are 0 for Market Order
                entry_types = ["entry.limit", "entry.stop"]
                for entry_type in entry_types:
                    value = next((metric.value for metric in webhook_data.metrics if metric.name == entry_type), None)
                    if value is None or value != 0:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "status": "rejected",
                                "message": f"Invalid {entry_type} value. Expected 0, got {value}"
                            }
                        )

                # Get quantity from metrics
                quantity = next((metric.value for metric in webhook_data.metrics if metric.name == "qty"), None)
                if quantity is None:
                    raise HTTPException(status_code=400, detail="Quantity not found in metrics")
                
                # Check short availability
                shares = short_stock_manager.get_availability(webhook_data.ticker)
                if shares is None:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "status": "rejected",
                            "message": f"No short availability data found for {webhook_data.ticker}"
                        }
                    )
                
                required_shares = quantity * 5
                if shares < required_shares:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "status": "rejected",
                            "message": f"Insufficient shares available to short. Required: {required_shares}, Available: {shares}",
                            "symbol": webhook_data.ticker,
                            "available_shares": shares,
                            "required_shares": required_shares
                        }
                    )
                logger.info(f"Short availability check passed for {webhook_data.ticker}. Required: {required_shares}, Available: {shares}")

            # Rest of your existing webhook logic...
            
            # Check if direction contains "close" or "cancel" - bypass PNL check if true
            if "close" in webhook_data.direction.lower() or "cancel" in webhook_data.direction.lower():
                logger.info(f"Direction '{webhook_data.direction}' contains close/cancel - bypassing PNL check")
            else:
                # Get PNL threshold from environment
                
                logger.info(f"PNL threshold set to: {pnl_threshold}")
                total_pnl = None
                # Fetch current positions and PNL data
                try:

                    total_pnl = await on_pnl_event(pnl)
            
                    
                    logger.info(f"Calculated total PNL: {total_pnl} and pnl_threshold is: {pnl_threshold}")
                    
                    # Check if total PNL meets threshold
                    if total_pnl <= pnl_threshold:
                        logger.warning(f"Total PNL ({total_pnl}) below threshold ({pnl_threshold}). Webhook blocked.")
                        return JSONResponse(
                            status_code=403,
                            content={
                                "status": "rejected",
                                "message": f"Current PNL ({total_pnl}) is below threshold ({pnl_threshold})",
                                "total_pnl": total_pnl,
                                "threshold": pnl_threshold
                            }
                        )
                    
                    logger.info(f"PNL check passed. Proceeding with webhook forwarding.")
                        
                except Exception as e:
                    logger.error(f"Error fetching or processing PNL data: {str(e)}")
                    raise HTTPException(status_code=500, detail="Failed to verify PNL conditions")
            
            # If we get here, either PNL check passed or direction was close/cancel
            webhook_url = "http://tbot-on-tradingboat:5000/webhook"
            logger.info(f"Forwarding to webhook URL: {webhook_url}")
            
            # Convert webhook data to dictionary and add the key
            webhook_dict = webhook_data.model_dump()
            webhook_dict["key"] = tbotKey
            logger.info(f"Added key to webhook data, ticker: {webhook_dict.get('ticker')}")
            
            # Forward the request to the webhook
            response = requests.post(
                webhook_url,
                headers={'Content-Type': 'application/json'},
                json=webhook_dict
            )
            
            logger.info(f"Webhook response status code: {response.status_code}")
            logger.debug(f"Webhook response content: {response.content}")
            
            # Return the forwarded response with CORS headers
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Access-Control-Allow-Origin": "https://portfolio.porenta.us",
                    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error in proxy webhook: {str(e)}")
            raise HTTPException(status_code=503, detail="Error connecting to webhook service")
        except Exception as e:
            logger.error(f"Unexpected error in proxy webhook: {str(e)}")
            logger.exception("Full exception details:")
            raise HTTPException(status_code=500, detail=str(e))
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error in proxy webhook: {str(e)}")
        raise HTTPException(status_code=503, detail="Error connecting to webhook service")
    except Exception as e:
        logger.error(f"Unexpected error in proxy webhook: {str(e)}")
        logger.exception("Full exception details:")
        raise HTTPException(status_code=500, detail=str(e))
        
@app.get("/short/{symbol}")
async def get_short_availability(symbol: str):
    shares = short_stock_manager.get_availability(symbol)
    if shares is None:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    return {
        "symbol": symbol.upper(),
        "available_shares": shares,
        "last_updated": short_stock_manager.get_last_updated().isoformat()
    }

# Add bulk lookup endpoint if needed
@app.post("/short/bulk")
async def get_bulk_short_availability(symbols: List[str]):
    results = {}
    last_updated = short_stock_manager.get_last_updated()
    
    for symbol in symbols:
        shares = short_stock_manager.get_availability(symbol.upper())
        if shares is not None:
            results[symbol.upper()] = shares
    
    return {
        "data": results,
        "last_updated": last_updated.isoformat() if last_updated else None,
        "found": len(results),
        "not_found": len(symbols) - len(results)
    }

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    try:
        logger.info("Home route accessed, rendering dashboard.")
        logger.debug(f"Template directory: {os.path.join(ROOT_DIR, 'templates')}")
        return templates.TemplateResponse("tbot_dashboard.html", {"request": request})
    except Exception as e:
        logger.error(f"Error in home route: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to render the dashboard: {str(e)}")



            


@app.get("/api/pnl-data", response_model=Dict[str, List[dict]])
async def get_current_pnl():
    try:
        pnl_data = await redis.get('pnl:data')
        positions_data = await redis.get('positions:data')
        
        response = {
            "positions": json.loads(positions_data) if positions_data else [],
            "pnl": json.loads(pnl_data) if pnl_data else [],
        }
        
        return JSONResponse(content=response, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching PNL data from Redis: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch PNL data")

@app.get("/api/contract-data", response_model=Dict[str, List[dict]])
async def get_contracts():
    try:
        contract_data = await redis.get('contract:data')
        response = {
            "contract_data": json.loads(contract_data) if contract_data else []
        }
        return JSONResponse(content=response, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching contract data from Redis: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch contract data")

@app.get("/api/trade-data", response_model=Dict[str, List[dict]])
async def get_trades():
    try:
        trade_data = await redis.get('trade:data')
        response = {
            "trades": json.loads(trade_data) if trade_data else []
        }
        return JSONResponse(content=response, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching trade data from Redis: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch trade data")

@app.get("/api/ib-data", response_model=Dict[str, List[dict]])
async def get_ib_data():
    try:
        ib_data = await redis.get('ib:data')
        if not ib_data:
            raise HTTPException(status_code=404, detail="No IB data available")
        return JSONResponse(content=json.loads(ib_data), status_code=200)
    except Exception as e:
        logger.error(f"Error fetching IB data from Redis: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch IB data")

@app.get("/api/portfolio-data", response_model=Dict[str, List[dict]])
async def get_portfolio_data():
    try:
        portfolio_data = await redis.get('portfolio:data')
        response = {
            "portfolio_data": json.loads(portfolio_data) if portfolio_data else []
        }
        return JSONResponse(content=response, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching portfolio data from Redis: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch portfolio data")


@app.post("/close_positions", response_model=List[PositionResponse])
async def place_order(positions_request: PositionsRequest):
    """
    Place an order with Interactive Brokers based on the positions request.
    """
    logger.info(f"Received positions request: {positions_request}")
    
    if not ib.isConnected():
        logger.error("IB Gateway not connected")
        raise HTTPException(status_code=503, detail="IB Gateway not connected")

    response_data = []
    try:
        ny_tz = pytz.timezone('America/New_York')
        current_time = datetime.now(ny_tz)
        market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        is_market_hours = False  # Can be changed to market_open <= current_time <= market_close

        # Get current positions from IB
        current_positions = await ib.reqPositionsAsync()
        
        # Process each position from the request
        for pos_request in positions_request.positions:
            symbol = pos_request.symbol
            action = pos_request.action
            quantity = pos_request.quantity
            
            logger.info(f"Processing order for symbol {symbol}")
            
            # Find matching position in current positions
            matching_position = next(
                (pos for pos in current_positions if pos.contract.symbol == symbol),
                None
            )
            
            if not matching_position:
                logger.warning(f"No matching position found for {symbol}")
                continue
                
            try:
                # Create contract
                contract = Contract()
                contract.symbol = symbol
                contract.secType = "STK"
                contract.currency = "USD"
                contract.exchange = "SMART"
                contract.primaryExchange = "NASDAQ"
                
                if is_market_hours:
                    logger.info(f"Creating market order for {symbol}")
                    order = MarketOrder(
                        action=action,
                        totalQuantity=quantity,
                        tif='GTC'
                    )
                else:
                    # Fetch real-time price data
                    bars = await ib.reqHistoricalDataAsync(
                        contract, 
                        endDateTime='', 
                        durationStr='60 S',
                        barSizeSetting='5 secs', 
                        whatToShow='Midpoint', 
                        useRTH=False
                    )
                    
                    if not bars:
                        logger.warning(f"No price data available for {symbol}")
                        continue
                        
                    last_price = bars[-1].close
                    tick_offset = -0.01 if action == 'SELL' else 0.01
                    limit_price = round(last_price + tick_offset, 2)
                    
                    order = LimitOrder(
                        action=action,
                        totalQuantity=quantity,
                        lmtPrice=limit_price,
                        tif='GTC',
                        outsideRth=True
                    )
                
                # Place the order
                trade = ib.placeOrder(contract, order)
                trade.statusEvent += on_orderStatus
                logger.info(f"Order placed for {symbol}: {order} with limit price {limit_price}")
                
                # Create response
                position_response = PositionResponse(
                    symbol=symbol,
                    position=float(quantity),
                    market_price=float(last_price if 'last_price' in locals() else 0.0),
                    market_value=float(quantity * (last_price if 'last_price' in locals() else 0.0)),
                    average_cost=float(matching_position.avgCost),
                    unrealized_pnl=0.0,  # Will be updated when filled
                    realized_pnl=0.0,    # Will be updated when filled
                    account=matching_position.account,
                    exchange=contract.exchange,
                    timestamp=current_time
                )
                
                response_data.append(position_response)
                
            except Exception as e:
                logger.error(f"Error processing order for {symbol}: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Error processing order for {symbol}: {str(e)}"
                )

        logger.info("All orders processed successfully")
        return response_data

    except Exception as e:
        logger.error(f"Error processing positions request: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing positions request: {str(e)}"
        )



async def on_pnl_event(pnl: PnL):
    accounts = ib.managedAccounts()

    account = accounts[0] if accounts else None
    pnl = ib.pnl(account)
    for item in pnl:
        total_unrealized_pnl = float((item.unrealizedPnL /2) or 0.0)
        total_realized_pnl = float(item.realizedPnL or 0.0)
        logger.debug(f"Received PnL update for unrealizedPnL: {total_unrealized_pnl} with the full item as {item}")
    #if pnl and pnl.realizedPnL is not None and pnl.unrealizedPnL is not None:
    if pnl:

            
        total_pnl = total_realized_pnl + (total_unrealized_pnl) / 2
        logger.debug(f"{total_pnl} is the total_pnl = total_realized_pnl {total_realized_pnl} + (total_unrealized_pnl) / 2: {total_unrealized_pnl} all pnl object is {pnl}")
        return total_pnl
    else:
        logger.warning("PnL data is incomplete.")
            

            

async def ensure_ib_connection():
    try:
        if not ib.isConnected():
            logger.info("IB not connected, attempting to reconnect...")
            await ib.connectAsync(
                host=IB_HOST,
                port=ibPort,
                clientId=client_id,
                timeout=20
            )
            await asyncio.sleep(1)
            
            if not ib.isConnected():
                # Try localhost if main host fails
                try:
                    await ib.connectAsync(
                        host='127.0.0.1',
                        port=ibPort,
                        clientId=client_id,
                        timeout=20
                    )
                    await asyncio.sleep(1)
                except Exception:
                    raise ConnectionError("Failed to establish IB connection")
                    
            logger.info("Successfully reconnected to IB")
        return True
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
        raise HTTPException(status_code=503, detail="IB Gateway connection failed")


@app.get("/api/portfolio-data", response_model=Dict[str, List[dict]])
async def get_portfolio_data():
    try:
        logger.info("jengo Fetching portfolio data from Redis")
        portfolio_data = await redis.get('portfolio:data')
        response = {
            "portfolio_data": json.loads(portfolio_data) if portfolio_data else []
        }
        return JSONResponse(content=response, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching portfolio data from Redis: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch portfolio data")
    
async def on_orderStatus(trade: Trade):
    logger.info(f"order has new status{trade}")
    redis_sync._sync_contract_data()

    return trade
        

def str2bool(value: str) -> bool:
    """Convert string to boolean, accepting various common string representations"""
    value = value.lower()
    if value in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    elif value in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    else:
        raise ValueError(f'Invalid boolean value: {value}')

if __name__ == "__main__":
    load_dotenv()
    pnl_threshold = float(os.getenv("WEBHOOK_PNL_THRESHOLD", "-300"))
    
    import uvicorn
    production = str2bool(os.getenv("TBOT_PRODUCTION", "False"))
    if production:
        uvicorn.run("app:app", host="0.0.0.0", port=PORT)  # Changed from "main:app"
    else:
        uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)  # Changed from "main:app"