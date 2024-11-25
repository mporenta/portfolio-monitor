from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from typing import List, Dict, Optional, Union, Any
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import pytz
import time
from datetime import datetime
from dotenv import load_dotenv
from ib_async import *
import logging
import signal
import requests
import asyncio
import os
from models import Base, Positions, PnLData, Trades, Orders, PositionClose
from fastapi.middleware.cors import CORSMiddleware

ib = IB()
portfolio_items = ib.portfolio()
load_dotenv()
tbotKey = os.getenv("TVWB_UNIQUE_KEY", "WebhookReceived:ac1a2d")
PORT = int(os.getenv("PNL_HTTPS_PORT", "5001"))
IB_CLIENT_ID = 40
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
    # Startup
    try:
        logger.info("Connecting to IB Gateway...")
        await ib.connectAsync(IB_HOST, IB_PORT, IB_CLIENT_ID)
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

from fastapi import FastAPI, HTTPException
from ib_async import IB, Contract, LimitOrder, MarketOrder
from datetime import datetime
import pytz
import logging

logger = logging.getLogger(__name__)
ib = IB()

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
                        totalQuantity=position.quantity,
                        tif='GTC'
                    )
                else:
                    logger.info(f"Creating limit order for {position.symbol}")
                    # Get current market price from IB
                    
                     # Wait for price data
                    limit_price = position.price
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
        logger.info("Received webhook request")
        logger.debug(f"Incoming webhook data: {webhook_data.dict()}")
        
        webhook_url = "https://tv.porenta.us/webhook"
        logger.info(f"Forwarding to webhook URL: {webhook_url}")
        
        # Convert webhook data to dictionary and add the key
        webhook_dict = webhook_data.dict()
        webhook_dict["key"] = tbotKey
        logger.info(f"Added key to webhook data, ticker: {webhook_dict.get('ticker')}")
        logger.debug(f"Modified webhook data: {webhook_dict}")
        
        # Forward the request to the webhook with proper headers
        logger.info("Sending POST request to webhook")
        response = requests.post(
            webhook_url,
            headers={'Content-Type': 'application/json'},
            json=webhook_dict
        )
        
        logger.info(f"Webhook response status code: {response.status_code}")
        logger.debug(f"Webhook response content: {response.content}")
        
        # Return the forwarded response with CORS headers
        cors_response = Response(
            content=response.content,
            status_code=response.status_code,
            headers={
                "Access-Control-Allow-Origin": "https://portfolio.porenta.us",
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )
        logger.info("Returning response to client")
        return cors_response
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error in proxy webhook: {str(e)}")
        raise HTTPException(status_code=503, detail="Error connecting to webhook service")
    except Exception as e:
        logger.error(f"Unexpected error in proxy webhook: {str(e)}")
        logger.exception("Full exception details:")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import FastAPI, HTTPException
from ib_async import IB
import logging

logger = logging.getLogger(__name__)
ib = IB()

async def ensure_ib_connection():
    """Ensure IB connection is active, reconnect if needed"""
    try:
        if not ib.isConnected():
            logger.info("IB not connected, attempting to reconnect...")
            await ib.connectAsync(IB_HOST, IB_PORT, IB_CLIENT_ID)
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
    import uvicorn
    production = str2bool(os.getenv("TBOT_PRODUCTION", "False"))
    if production:
        uvicorn.run("main:app", host="0.0.0.0", port=PORT)  # Changed from "main:app"
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)  # Changed from "main:app"
