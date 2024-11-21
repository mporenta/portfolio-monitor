from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Union, Any
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from datetime import datetime
# Import SQLAlchemy models with different names to avoid conflicts


from dotenv import load_dotenv
from ib_async import Contract, PortfolioItem, IB
import logging
import signal
import requests
import asyncio
import os
from models import Base, Positions, PnLData, Trades, Orders, PositionClose
from closeall import close_positions
from fastapi.middleware.cors import CORSMiddleware
ib = IB()
portfolio_items = ib.portfolio()
load_dotenv()
PORT = int(os.getenv("PNL_HTTPS_PORT", "5001"))
# Initialize the database


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

class PositionCloseRequest(BaseModel, PortfolioItem):
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

class WebhookMetric(BaseModel):
    name: str
    value: Union[int, float]

class WebhookRequest(BaseModel):
    timestamp: int
    ticker: str
    currency: str
    timeframe: str
    clientId: int
    key: str
    contract: str
    orderRef: str
    direction: str
    metrics: List[WebhookMetric]

# Initialize FastAPI app
app = FastAPI(title="PnL Monitor")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up templates
templates = Jinja2Templates(directory=os.path.join(ROOT_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(ROOT_DIR, "static")), name="static")
print(f"global Connecting to database at {DATABASE_PATH}")




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
        print(f"Connecting to database at {DATABASE_PATH}")
        print(f"Database URL: {DATABASE_URL}")
        print(f"Database engine: {engine}")
        print(f"Database session: {SessionLocal}")
        print(f"def Database session: {db}")
        print(f"Depends(get_db)): {get_db}")
        print(f"Database query: {db.query(Positions).all()}")
        
        

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







@app.post("/close_positions")
async def close_positions_route(sybmol, request: Request, db: Session = Depends(get_db)):
    """
    FastAPI route to handle position closing requests.
    """
    try:

        result = await close_positions(portfolio_items)
        return result
    except ValueError as e:
        logger.error(f"ValueError in close_positions_route: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in close_positions_route: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/proxy/webhook")
async def proxy_webhook(webhook_data: WebhookRequest):
    try:
        logger.info("Proxying webhook request")
        webhook_url = "https://tv.porenta.us/webhook"
        
        # Forward the request to the webhook
        response = requests.post(
            webhook_url,
            json=webhook_data.dict(),
            headers={'Content-Type': 'application/json'}
        )
        
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers)
        )
    except Exception as e:
        logger.error(f"Error in proxy webhook: {str(e)}")
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
    import uvicorn
    production = str2bool(os.getenv("TBOT_PRODUCTION", "False"))
    if production:
        uvicorn.run("main:app", host="0.0.0.0", port=PORT)  # Changed from "main:app"
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)  # Changed from "main:app"
