from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Union, Any
from dotenv import load_dotenv
from ib_async import Contract, PortfolioItem, IB
import logging
import signal
import requests
import asyncio
import os
from db import RedisDB, DataHandler  # Updated import for Redis
from pnl_monitor import IBClient
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
PORT = int(os.getenv("PNL_HTTPS_PORT", "5001"))

# Initialize Redis connection
redis_host = os.getenv('TBOT_PNL_REDIS_HOST', 'redis-pnl')
redis_port = int(os.getenv('TBOT_PNL_REDIS_PORT', '6379'))
redis_password = os.getenv('TBOT_PNL_REDIS_PASSWORD', '')

# Initialize Redis DB
redis_db = RedisDB(
    host=redis_host,
    port=redis_port,
    password=redis_password
)
redis_db.init_db()

# Set up logging
log_file_path = '/app/logs/app.log'
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Pydantic models
class Position(BaseModel):
    symbol: str
    action: str
    quantity: int

class PositionsRequest(BaseModel):
    positions: List[Position]

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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up templates
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    try:
        logger.info("Home route accessed, rendering dashboard.")
        return templates.TemplateResponse("tbot_dashboard.html", {"request": request})
    except Exception as e:
        logger.error(f"Error in home route: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to render the dashboard")

@app.get("/api/positions")
async def get_positions():
    try:
        logger.info("API call to /api/positions")
        positions = redis_db.fetch_latest_positions_data()
        logger.info("Successfully fetched positions data from Redis")
        return {"status": "success", "data": {"active_positions": positions}}
    except Exception as e:
        logger.error(f"Error fetching positions from Redis: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch positions data")

@app.get("/api/current-pnl")
async def get_current_pnl():
    try:
        logger.info("API call to /api/current-pnl")
        data = redis_db.fetch_latest_pnl_data()
        logger.info("Successfully fetched current PnL data from Redis")
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error(f"Error fetching current PnL from Redis: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch current PnL data")

@app.get("/api/trades")
async def get_trades():
    try:
        logger.info("API call to /api/trades")
        trades = redis_db.fetch_latest_trades_data()
        logger.info("Successfully fetched trades data from Redis")
        return {"status": "success", "data": {"trades": trades}}
    except Exception as e:
        logger.error(f"Error fetching trades from Redis: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch trades data")

@app.post("/close_positions")
async def close_positions_route():
    try:
        ib_client = IBClient()  # Initialize IBClient with Redis already configured
        
        # Get positions from Redis
        positions = redis_db.fetch_latest_positions_data()
        if not positions:
            logger.info("No positions to close")
            return {'status': 'success', 'message': 'No positions to close'}

        # Close positions
        await ib_client.close_all_positions()
        
        logger.info("Positions closed successfully")
        return {'status': 'success', 'message': 'Positions closed successfully'}
        
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

@app.on_event("startup")
async def startup_event():
    """Initialize Redis connection on startup"""
    try:
        redis_db.init_db()
        logger.info("Redis connection initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Redis connection: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up Redis connection on shutdown"""
    try:
        # Add any cleanup needed for Redis connection
        logger.info("Cleaning up Redis connection")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

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
        uvicorn.run("app:app", host="0.0.0.0", port=PORT)
    else:
        uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)
