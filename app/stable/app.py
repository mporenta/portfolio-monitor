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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import pytz
import aiohttp
import time
from dotenv import load_dotenv
from ib_async import *
from ib_async import PnL, Contract
import logging
import signal
import requests
import asyncio
import os
from models import Base, Positions, PnLData, Trades, Orders, PositionClose
from fastapi.middleware.cors import CORSMiddleware
import sys
load_dotenv()
loadDotEnv = load_dotenv()
tiingo_token = os.getenv('TIINGO_API_TOKEN')
unique_ts = str((time.time_ns() // 1000000) -  (4 * 60 * 60 * 1000))
short_stock_manager = ShortStockManager()

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

# Initialize FastAPI app with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading .env in lifespan...")
    
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

async def on_orderStatus(trade: Trade):
    logger.info(f"order has new status{trade}")

    return trade


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
        logger.info(f"Received PnL update for unrealizedPnL: {total_unrealized_pnl} with the full item as {item}")
    #if pnl and pnl.realizedPnL is not None and pnl.unrealizedPnL is not None:
    if pnl:

            
        total_pnl = total_realized_pnl + (total_unrealized_pnl) / 2
        logger.info(f"{total_pnl} is the total_pnl = total_realized_pnl {total_realized_pnl} + (total_unrealized_pnl) / 2: {total_unrealized_pnl} all pnl object is {pnl}")
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
                async with asyncio.timeout(2):  # Reduced timeout
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
                    logger.info(f"Successfully fetched {len(positions_data)} positions")
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

       
        # Fetch open orders with retry logic
        for attempt in range(max_retries):
            try:
                async with asyncio.timeout(5):
                    if not ib.isConnected():
                        await ensure_ib_connection()
                    
                    trades = ib.executions()
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
            "trades": trades_data,
        }
        
        logger.info(f"Successfully completed IB data fetch of positions {positions_data} and trades {trades_data}")
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
    pnl_threshold = float(os.getenv("WEBHOOK_PNL_THRESHOLD", "-300"))
    
    import uvicorn
    production = str2bool(os.getenv("TBOT_PRODUCTION", "False"))
    if production:
        uvicorn.run("app:app", host="0.0.0.0", port=PORT)  # Changed from "main:app"
    else:
        uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)  # Changed from "main:app"