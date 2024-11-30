from contextlib import asynccontextmanager
from json import load
from math import log
import time
from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, HTMLResponse
import uvicorn
import sqlite3
import logging
import datetime
import asyncio
from ib_insync import IB, MarketOrder, LimitOrder, PnL, PortfolioItem, AccountValue, Contract, Trade
from pydantic import BaseModel
from components.actions.base.action import am
from components.events.base.event import em
from components.schemas.trading import Order, Position, Schema
from utils.log import get_logger
from utils.register import register_action, register_event, register_link
from settings import REGISTERED_ACTIONS, REGISTERED_EVENTS, REGISTERED_LINKS, strtobool
import tbot as t


from dotenv import load_dotenv
import os
from commons import VERSION_NUMBER, LOG_LOCATION
from components.logs.log_event import LogEvent
from typing import Optional, List, AsyncGenerator
load_dotenv()
WEBHOOK_IB_PORT = int(os.getenv('WEBHOOK_IB_PORT', '4002'))
TBOT_IBKR_IPADDR = os.getenv('TBOT_IBKR_IPADDR', '127.0.0.1')  
WEBHOOK_IB_CLIENT_ID = int(os.getenv('WEBHOOK_IB_CLIENT_ID', '1111'))
IB_TIMEOUT = int(os.getenv('IB_TIMEOUT', '5'))
account_value = []

pnl= PnL()
ib = IB()

portfolio_items = ib.portfolio()
# Configure logging first
logging.basicConfig(
    level=logging.DEBUG if not strtobool(os.getenv("TBOT_PRODUCTION", "False")) else logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
DOT_ENV_TEST = os.getenv('DOT_ENV_TEST')
logger.info(f"Gobal DOT_ENV_TEST: {DOT_ENV_TEST}") 
accounts = ib.managedAccounts()
daily_pnl = float(0.0)
# Initialize FastAPI app with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    DOT_ENV_TEST = os.getenv('DOT_ENV_TEST')
    logger.info(f"DOT_ENV_TEST: {DOT_ENV_TEST}") 

    logger.info("Loading .env in lifespan...")
    WEBHOOK_IB_PORT = int(os.getenv('WEBHOOK_IB_PORT', '4002'))
    TBOT_IBKR_IPADDR = os.getenv('TBOT_IBKR_IPADDR', '127.0.0.1')  
    WEBHOOK_IB_CLIENT_ID = int(os.getenv('WEBHOOK_IB_CLIENT_ID', '1111'))
    IB_TIMEOUT = int(os.getenv('IB_TIMEOUT', '5'))
    daily_pnl = float(0.0)
    
    
 
    # Startup
    try:
        logger.info("Connecting to IB Gateway...")
        await ib.connectAsync(host=TBOT_IBKR_IPADDR, port=WEBHOOK_IB_PORT, clientId=WEBHOOK_IB_CLIENT_ID, timeout=IB_TIMEOUT)
        logger.info("Connected to IB Gateway.")
       
        
    except Exception as e:
        logger.error(f"Failed to connect to IB Gateway: {e}")
        raise RuntimeError("IB Gateway connection failed.")
    
    yield
    
    # Shutdown
    if ib.isConnected():
        ib.accountValueEvent += on_account_value_update
        ib.pnlEvent += get_ib_data
        logger.info(f"Subscribed to account value and PnL events: {ib.accountValueEvent}, {ib.pnlEvent}")
        subscribe_events()
       
        logger.info("subscribe_events ")

# Initialize FastAPI app with lifespan
app = FastAPI(
    title="PnL Monitor",
    lifespan=lifespan
)
# Initialize global variables
net_liquidation = float(0.0)
risk_percent = float(os.getenv('RISK_PERCENT', 0.01))
pnl_threshold_calc = 0.0
pnl_threshold = float(os.getenv("WEBHOOK_PNL_THRESHOLD", "-300"))

pnl_threshold_reached = False


# Register components
registered_actions = [register_action(action) for action in REGISTERED_ACTIONS]
registered_events = [register_event(event) for event in REGISTERED_EVENTS]
registered_links = [register_link(link, em, am) for link in REGISTERED_LINKS]




# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



# Set up templates
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

class WebhookPayload(BaseModel):
    key: str
    data: dict

  
class Metric(BaseModel):
    name: str
    value: float

class TradingWebhook(BaseModel):
    timestamp: int
    ticker: str
    key: str
    currency: str
    timeframe: str
    clientId: int
    contract: str
    orderRef: str
    direction: str
    metrics: List[Metric]

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return await t.get_main(request)

@app.get("/dashboard")
async def dashboard(request: Request):
    try:
        with open('.gui_key', 'r') as key_file:
            gui_key = key_file.read().strip()
            if gui_key != request.query_params.get("guiKey", None):
                raise HTTPException(status_code=401, detail="Access Denied")
    except FileNotFoundError:
        logger.warning("GUI key file not found. Open GUI mode detected.")

    action_list = am.get_all()
    # Using the new Pydantic models
    schema_list = {
        "order": Order().model_dump_json(),
        "position": Position().model_dump_json()
    }
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "schema_list": schema_list,
            "action_list": action_list,
            "event_list": registered_events,
            "version": os.getenv("VERSION_NUMBER", "1.0.0"),
        },
    )
def on_account_value_update(account_value: AccountValue):
   """Update stored NetLiquidation whenever it changes."""
   if account_value.tag == "NetLiquidation":
       global net_liquidation
       net_liquidation = float(account_value.value)
       logger.debug(f"on_account_value_update NetLiquidation updated: ${net_liquidation}")

def subscribe_events():
        """Subscribe to order and PnL events, and initialize account."""
        ib.pnlEvent += get_ib_data
        
        accounts = ib.managedAccounts()
        
        if not accounts:
            logger.error("No managed accounts available.")
            return

        account = accounts[0]
        if account:
            ib.reqPnL(account)
        else:
            logger.error("Account not found; cannot subscribe to PnL updates.")
       
        
async def ensure_ib_connection():
    """Ensure IB connection is active, reconnect if needed"""
    try:
        if not ib.isConnected():
            logger.info("IB not connected, attempting to reconnect...")
            await ib.connectAsync(host=TBOT_IBKR_IPADDR, port=WEBHOOK_IB_PORT, clientId=WEBHOOK_IB_CLIENT_ID, timeout=IB_TIMEOUT)

                 

            # Wait a brief moment for connection to stabilize
            await asyncio.sleep(1)
            
            if not ib.isConnected():
                raise ConnectionError("Failed to establish IB connection")
            logger.info("Successfully reconnected to IB")
        return True
    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
        raise HTTPException(status_code=503, detail="IB Gateway connection failed")

def get_ib_data(pnl: PnL):
   
   daily_pnl = float(pnl.dailyPnL or 0.0)
   logger.debug(f"get_ib_data DailyPnL updated: ${daily_pnl:,.2f}")

@app.post("/webhook")
async def webhook(request: Request, payload: TradingWebhook):
   if not ensure_ib_connection():
        logger.error("IB Manager not initialized")
        raise HTTPException(status_code=503, detail="IB Manager unavailable")
  

   pnl_threshold_calc = net_liquidation * risk_percent
   logger.debug(f"Calculated PnL threshold: ${pnl_threshold_calc:,.2f}")
   pnl_threshold_reached = daily_pnl <= pnl_threshold
   logger.debug(f"Received webhook payload: {payload.model_dump()}")
   logger.debug(f"NetLiquidation: ${net_liquidation} DailyPnL: ${daily_pnl:,.2f} RiskPercent: {risk_percent}") 
   if pnl_threshold_reached:
       pnl_threshold_reached = True
       raise HTTPException(status_code=400, detail=f"Webhook condition: Daily PnL below limits{daily_pnl}")

   triggered_events = []
   for event in em.get_all():
       if event.webhook:
           if event.key == payload.key:
               event.trigger(data=payload.model_dump())
               triggered_events.append(event.name)

   if not triggered_events:
       logger.warning(f"No events triggered for webhook request {payload.model_dump()}")
   else:
       logger.info(f"Triggered events: {triggered_events}")
       logger.info(f"Client IP: {request.client.host}")

   return {"message": "Request processed", "triggered_events": triggered_events}


@app.post("/webhook_local")
async def webhook_local(request: Request, payload: TradingWebhook):
   
    if not ensure_ib_connection():
        logger.error("IB Manager not initialized")
        raise HTTPException(status_code=503, detail="IB Manager unavailable")
    logger.debug(f"Received webhook payload: {payload.model_dump()}")
    account_value= await ib.accountSummaryAsync(account="")
    for item in account_value:
        if item.tag == "NetLiquidation":
            net_liquidation = float(item.value)
            logger.debug(f"NetLiquidation: ${net_liquidation}")

    logger.debug(f" jengo NetLiquidation: ${net_liquidation}")
    account= ""
   
    pnl = ib.reqPnL(account)
    daily_pnl = float(pnl.dailyPnL)
    logger.debug(f"jengo DailyPnL updated: ${daily_pnl:,.2f}")
    pnl_threshold_reached = daily_pnl <= pnl_threshold
    logger.debug(f"pnl_threshold_reached: {pnl_threshold_reached}")
    pnl_threshold_calc = net_liquidation * risk_percent
    logger.debug(f"jengo Calculated PnL threshold: ${pnl_threshold_calc:,.2f}")


    pnl_threshold_reached = daily_pnl <= pnl_threshold
    logger.debug(f"Received webhook payload: {payload.model_dump()}")
    logger.debug(f"NetLiquidation: ${net_liquidation} DailyPnL: ${daily_pnl:,.2f} RiskPercent: {risk_percent}") 
    if pnl_threshold_reached:
        raise HTTPException(status_code=400, detail=f"Webhook condition: Daily PnL below limits{daily_pnl}")

    triggered_events = []
    for event in em.get_all():
        if event.webhook:
            event.trigger(data=payload.model_dump())    
            triggered_events.append(event.name)

    if not triggered_events:
        logger.warning(f"No events triggered for webhook request {payload.model_dump()}")
    else:
        logger.info(f"Triggered events: {triggered_events}")
        logger.info(f"Client IP: {request.client.host}")

    return {"message": "Request processed", "triggered_events": triggered_events}

@app.get("/events")

@app.get("/logs")
async def get_logs():
    with open(LOG_LOCATION, "r") as log_file:
        logs = [LogEvent().from_line(log) for log in log_file.readlines()]
    return JSONResponse(content=[log.as_json() for log in logs])

@app.post("/event/active")
async def activate_event(event_name: str = None, active: bool = True):
    if not event_name:
        raise HTTPException(status_code=404, detail="Event name cannot be empty.")
    try:
        event = em.get(event_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Cannot find event with name: {event_name}")

    event.active = active
    logger.info(f"Event {event.name} active set to: {event.active}, via POST request")
    return {"active": event.active}




@app.get("/orders", response_class=HTMLResponse)
async def orders(request: Request):
    return await t.get_orders(request)

@app.get("/orders/data")
async def orders_data():
    return await t.get_orders_data()

@app.get("/alerts", response_class=HTMLResponse)
async def alerts(request: Request):
    return await t.get_alerts(request)

@app.get("/alerts/data")
async def alerts_data():
    return await t.get_alerts_data()

@app.get("/errors", response_class=HTMLResponse)
async def errors(request: Request):
    return await t.get_errors(request)

@app.get("/errors/data")
async def errors_data():
    return await t.get_errors_data()

@app.get("/tbot", response_class=HTMLResponse)
async def tbot_view(request: Request):
    return await t.get_tbot(request)

@app.get("/tbot/data")
async def tbot_data():
    return await t.get_tbot_data()

@app.get("/ngrok")
async def ngrok():
    return await t.get_ngrok()

if __name__ == "__main__":
    try:
        load_dotenv()
        DOT_ENV_TEST = os.getenv('DOT_ENV_TEST')
        WEBHOOK_IB_PORT = int(os.getenv('WEBHOOK_IB_PORT', '4002'))
        TBOT_IBKR_IPADDR = os.getenv('TBOT_IBKR_IPADDR', '127.0.0.1')  
        WEBHOOK_IB_CLIENT_ID = int(os.getenv('WEBHOOK_IB_CLIENT_ID', '1111'))
        IB_TIMEOUT = int(os.getenv('IB_TIMEOUT', '5'))
        logger.info(f"if __name__  DOT_ENV_TEST: {DOT_ENV_TEST}") 
       
        port = int(os.getenv("TVWB_HTTPS_PORT", "5000"))
        is_production = strtobool(os.getenv("TBOT_PRODUCTION", "False"))
        
        if is_production:
            logger.info("Starting in production mode.")
            uvicorn.run(
                "main:app", 
                host="0.0.0.0", 
                port=port, 
                log_level="info",
                reload=False
            )
        else:
            logger.info("Starting in development mode with debug.")
            uvicorn.run(
                "main:app", 
                host="0.0.0.0", 
                port=port, 
                log_level="debug",
                reload=True
            )
            
    except Exception as e:
        logger.exception("An error occurred while running the FastAPI app.")