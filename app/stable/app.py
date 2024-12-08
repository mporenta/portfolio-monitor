from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import httpx
from datetime import datetime
from typing import List, Dict, Optional, Union, Any
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import pytz
import time
from dotenv import load_dotenv
from ib_async import *
import logging
import signal
import requests
import asyncio
import os
from models import Base, Positions, PnLData, Trades, Orders, PositionClose
from fastapi.middleware.cors import CORSMiddleware
import sys
load_dotenv()
tiingo_token = os.getenv('TIINGO_API_TOKEN')
unique_ts = str((time.time_ns() // 1000000) -  (4 * 60 * 60 * 1000))

def get_timestamp(unique_ts: str) -> str:
    """Get timestamp for database"""
    dtime = datetime.fromtimestamp(int(unique_ts) / 1000.0)
    dtime_str = dtime.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return dtime_str


timestamp = get_timestamp(unique_ts)

ib = IB()
portfolio_items = ib.portfolio()

tbotKey = os.getenv("TVWB_UNIQUE_KEY", "WebhookReceived:ac1a2d")
PORT = int(os.getenv("PNL_HTTPS_PORT", "5001"))
FASTAPI_IB_CLIENT_ID = int(os.getenv('FASTAPI_IB_CLIENT_ID', '1111'))
IB_HOST = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')  
IB_PORT = int(os.getenv('TBOT_IBKR_PORT', '4002'))

# Get the src directory path
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (project root)
ROOT_DIR = os.path.dirname(SRC_DIR)
DATA_DIR = "/app/data"

DATABASE_PATH = os.getenv('DATABASE_PATH', '/app/data/pnl_data_jengo.db')
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Set up logging
log_file_path = '/app/logs/app.log'
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

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

# Initialize FastAPI app with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading .env in lifespan...")
    load_dotenv()
    # Startup
    try:
        logger.info("Connecting to IB Gateway...")
        await ib.connectAsync(IB_HOST, IB_PORT, FASTAPI_IB_CLIENT_ID)
        logger.info("Connected to IB Gateway.")
    except Exception as e:
        logger.error(f"Failed to connect to IB Gateway: {e}")
        raise RuntimeError("IB Gateway connection failed.")
    
    yield
    
    # Shutdown
    if ib.isConnected():
        await ib.disconnect()
        logger.info("Disconnected from IB Gateway.")

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="PnL Monitor",
    lifespan=lifespan
)
load_dotenv()
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
print(f"global Connecting to database at {DATABASE_PATH}")

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

@app.get("/api/positions")
async def get_positions(db: Session = Depends(get_db)):
   
    try:
        logger.info("API call to /api/positions")
        positions = db.query(Positions).all()
        positions_data = [
            {
                'symbol': pos.symbol,
                'position': pos.position,
                'market_price': pos.market_price,
                'market_value': pos.market_value,
                'average_cost': pos.average_cost,
                'unrealized_pnl': pos.unrealized_pnl,
                'realized_pnl': pos.realized_pnl,
                'account': pos.account,
                'exchange': pos.exchange,  # Already correctly named in database
                'timestamp': pos.timestamp
            }
            for pos in positions
        ]
        logger.info(f"Successfully fetched positions data.{positions_data}")
        return {"status": "success", "data": {"active_positions": positions_data}}
    except Exception as e:
        logger.error(f"Error fetching positions: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch positions data")

@app.get("/api/current-pnl")
async def get_current_pnl(db: Session = Depends(get_db)):
    try:
        logger.info("API call to /api/current-pnl")
        pnl = db.query(PnLData).order_by(PnLData.timestamp.desc()).first()
        if pnl:
            data = {
                'daily_pnl': pnl.daily_pnl,
                'total_unrealized_pnl': pnl.total_unrealized_pnl,
                'total_realized_pnl': pnl.total_realized_pnl,
                'net_liquidation': pnl.net_liquidation
            }
        else:
            data = {}
        logger.info("Successfully fetched current PnL data.")
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error(f"Error fetching current PnL: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch current PnL data")

@app.get("/api/trades")
async def get_trades(db: Session = Depends(get_db)):
    try:
        logger.info("API call to /api/trades")
        trades = db.query(Trades).order_by(Trades.trade_time.desc()).all()
        trades_data = [
            {
                'trade_time': trade.trade_time,
                'symbol': trade.symbol,
                'action': trade.action,
                'quantity': trade.quantity,
                'fill_price': trade.fill_price,
                'commission': trade.commission,
                'realized_pnl': trade.realized_pnl,
                'exchange': trade.exchange,
                'order_ref': trade.order_ref,
                'status': trade.status
            }
            for trade in trades
        ]
        logger.info("Successfully fetched trades data.")
        return {"status": "success", "data": {"trades": trades_data}}
    except Exception as e:
        logger.error(f"Error fetching trades: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch trades data")





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
        is_market_hours = market_open <= current_time <= market_close

        for position in positions_request.positions:
            try:
                logger.info(f"Processing order for {position.symbol}")
                
                # Create contract
                contract = Contract(
                    symbol=position.symbol,
                    exchange='SMART',
                    secType='STK',
                    currency='USD'
                )

                

                # Create order based on market hours
                if is_market_hours:
                    logger.info(f"Creating market order for {position.symbol}")
                    order = MarketOrder(
                        action=position.action,
                        totalQuantity=-10000000000,
                        tif='GTC'
                    )
                else:
                    logger.info(f"Creating limit order for {position.symbol}")
                    # Fetch current price from Tiingo
                    logger.info(f"Tiingo token: {tiingo_token}")
                    tiingo_url = f"https://api.tiingo.com/iex/?tickers={position.symbol}&token={tiingo_token}"
                    headers = {'Content-Type': 'application/json'}
                    
                
                    try:
                        tiingo_response = requests.get(tiingo_url, headers=headers)
                        tiingo_data = tiingo_response.json()
                        if tiingo_data and len(tiingo_data) > 0:
                            limit_price = tiingo_data[0]['tngoLast']
                            logger.info(f"Tiingo response: {tiingo_data} - Using Tiingo 'tngoLast' price for {position.symbol}: {limit_price}")
                    except Exception as te:
                        logger.error(f"Error fetching Tiingo data: {str(te)}")
                    
                     # Wait for price data
                    
                    if not limit_price:
                        raise ValueError(f"Could not get market price for {position.symbol}")
                        
                    order = LimitOrder(
                        action=position.action,
                        totalQuantity=position.quantity,
                        lmtPrice=round(limit_price, 2),
                        tif='GTC',
                        outsideRth=True
                    )

                # Place the order
                trade = ib.placeOrder(contract, order)
                logger.info(f"Order placed for {position.symbol}: {trade}")

                # Create PositionResponse
                position_response = PositionResponse(
                    symbol=position.symbol,
                    position=float(position.quantity),
                    market_price=trade.orderStatus.lastFillPrice or 0.0,
                    market_value=(trade.orderStatus.lastFillPrice or 0.0) * position.quantity,
                    average_cost=trade.orderStatus.avgFillPrice or 0.0,
                    unrealized_pnl=0.0,  # Will be updated when filled
                    realized_pnl=0.0,    # Will be updated when filled
                    account=trade.order.account or "",
                    exchange=contract.exchange,
                    timestamp=current_time,
                    
                )
                
                response_data.append(position_response)

            except Exception as e:
                logger.error(f"Error processing order for {position.symbol}: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500, 
                    detail=f"Error processing order for {position.symbol}: {str(e)}"
                )

        logger.info("All orders processed successfully")
        return response_data

    except Exception as e:
        logger.error(f"Error processing positions request: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Error processing positions request: {str(e)}"
        )

@app.post("/proxy/webhook")
async def proxy_webhook(webhook_data: WebhookRequest):
    try:
        load_dotenv()
        logger.info(f"load_dotenv{load_dotenv()}")
        logger.info("Received webhook request")
        logger.debug(f"Incoming webhook data: {webhook_data.dict()}")
        
        # Check if direction contains "close" or "cancel" - bypass PNL check if true
        if "close" in webhook_data.direction.lower() or "cancel" in webhook_data.direction.lower():
            logger.info(f"Direction '{webhook_data.direction}' contains close/cancel - bypassing PNL check")
        else:
            # Get PNL threshold from environment
            pnl_threshold = float(os.getenv("WEBHOOK_PNL_THRESHOLD", "-300"))
            logger.info(f"PNL threshold set to: {pnl_threshold}")
            
            # Fetch current positions and PNL data
            try:
                # Create async client for internal request
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "http://localhost:5001/api/orders-data",  # Internal call to our own endpoint
                        timeout=10.0
                    )
                    response.raise_for_status()
                    positions_data = response.json()
                    
                    # Calculate total PNL for active positions
                    total_pnl = 0.0
                    for position in positions_data.get('data', []):
                        # Only consider positions that are not zero
                        if position:
                            realized_pnl = float(position.get('realizedpnl', 0))
                            unrealized_pnl = float(position.get('unrealizedpnl', 0))
                            total_pnl += realized_pnl + unrealized_pnl
                    
                    logger.info(f"Calculated total PNL: {total_pnl}")
                    
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
        webhook_dict = webhook_data.dict()
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


async def ensure_ib_connection():
    """Ensure IB connection is active, reconnect if needed"""
    try:
        if not ib.isConnected():
            logger.info("IB not connected, attempting to reconnect...")
            await ib.connectAsync(IB_HOST, IB_PORT, FASTAPI_IB_CLIENT_ID)
            # Wait a brief moment for connection to stabilize
            await asyncio.sleep(1)
            
            if not ib.isConnected():
                raise ConnectionError("Failed to establish IB connection")
            logger.info("Successfully reconnected to IB")
        return True
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
        raise HTTPException(status_code=503, detail="IB Gateway connection failed")

@app.get("/api/ib-data", response_model=Dict[str, List[dict]])
async def get_ib_data():
    """
    Fetch positions, PnL, and trades with robust connection handling.
    """
    logger.info("Starting IB data fetch")
    
    try:
        # Ensure connection is active
        await ensure_ib_connection()
        
        # Initialize response data
        positions_data = []
        pnl_data = []
        trades_data = []
        
        # Fetch positions with retry logic
        max_retries = 3
        retry_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                async with asyncio.timeout(5):  # Reduced timeout
                    if not ib.isConnected():
                        await ensure_ib_connection()
                    
                    # Request positions
                    positions = await ib.reqPositionsAsync()
                    await asyncio.sleep(0.5)  # Allow time for data to arrive
                    
                    positions_data = [
                        {
                            "account": pos.account,
                            "contract": pos.contract.symbol,
                            "position": pos.position,
                            "avgCost": pos.avgCost,
                            "marketPrice": getattr(pos, 'marketPrice', None),
                            "marketValue": getattr(pos, 'marketValue', None)
                        }
                        for pos in positions
                    ]
                    logger.debug(f"Successfully fetched {len(positions_data)} positions")
                    break  # Success, exit retry loop
                    
            except asyncio.TimeoutError:
                logger.warning(f"Timeout on attempt {attempt + 1} of {max_retries}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error("All position fetch attempts failed")
            except Exception as e:
                logger.error(f"Error fetching positions: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                break

        # Fetch PnL data with retry logic
        for attempt in range(max_retries):
            try:
                async with asyncio.timeout(5):
                    if not ib.isConnected():
                        await ensure_ib_connection()
                    
                    accounts = ib.managedAccounts()
                    if accounts:
                        account = accounts[0]
                        await ib.reqAccountUpdatesAsync(account)
                        await asyncio.sleep(0.5)  # Allow time for data to arrive
                        
                        pnl = await ib.reqPnLAsync(account)
                        if pnl:
                            pnl_data = [{
                                "account": account,
                                "dailyPnL": getattr(pnl, 'dailyPnL', 0.0),
                                "unrealizedPnL": getattr(pnl, 'unrealizedPnL', 0.0),
                                "realizedPnL": getattr(pnl, 'realizedPnL', 0.0),
                            }]
                            logger.debug("Successfully fetched PnL data")
                            break
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"PnL fetch attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue

        # Fetch open orders with retry logic
        for attempt in range(max_retries):
            try:
                async with asyncio.timeout(5):
                    if not ib.isConnected():
                        await ensure_ib_connection()
                    
                    trades = await ib.reqAllOpenOrdersAsync()
                    await asyncio.sleep(0.5)  # Allow time for data to arrive
                    
                    trades_data = [
                        {
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
                        }
                        for trade in trades
                    ]
                    logger.debug(f"Successfully fetched {len(trades_data)} open orders")
                    break
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"Orders fetch attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue

        response = {
            "positions": positions_data,
            "pnl": pnl_data,
            "trades": trades_data,
        }
        
        logger.info("Successfully completed IB data fetch")
        return JSONResponse(
            content=response,
            status_code=200
        )

    except Exception as e:
        logger.error(f"Error in get_ib_data: {str(e)}", exc_info=True)
        # If we get here, something really went wrong
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to fetch IB data",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }
        )
@app.get("/api/orders-data")
async def proxy_orders_data():
    try:
        logger.info("Received request for orders data")
        
        # Generate timestamp using your method
        
        # Use the container name as hostname since they're on the same network
        orders_url = f"http://tbot-on-tradingboat:5000/orders/data?_={unique_ts}"
        logger.info(f"Forwarding request to internal endpoint: {orders_url}")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                orders_url,
                timeout=10.0
            )
            
            logger.info(f"Orders data response status code: {response.status_code}")
            logger.debug(f"Orders data response content: {response.text}")
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers={
                    "Access-Control-Allow-Origin": "https://portfolio.porenta.us",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Content-Type": response.headers.get("Content-Type", "application/json")
                }
            )
            
    except httpx.TimeoutException:
        logger.error("Timeout while fetching orders data")
        raise HTTPException(status_code=504, detail="Request to orders service timed out")
    except httpx.RequestError as e:
        logger.error(f"Network error in orders proxy: {str(e)}")
        raise HTTPException(status_code=503, detail="Error connecting to orders service")
    except Exception as e:
        logger.error(f"Unexpected error in orders proxy: {str(e)}")
        logger.exception("Full exception details:")
        raise HTTPException(status_code=500, detail=str(e))
        

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
    import uvicorn
    production = str2bool(os.getenv("TBOT_PRODUCTION", "False"))
    if production:
        uvicorn.run("app:app", host="0.0.0.0", port=PORT)  # Changed from "main:app"
    else:
        uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)  # Changed from "main:app"
