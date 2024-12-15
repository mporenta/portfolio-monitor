import asyncio
from typing import Optional, Dict
import pytz
from datetime import datetime, timedelta
import logging
import os
from dotenv import load_dotenv
from ib_async import Client, Contract

class RealtimePriceService:
    def __init__(self):
        self.client = Client(self)
        self.price_callbacks: Dict[int, asyncio.Event] = {}
        self.prices: Dict[int, float] = {}
        self.logger = logging.getLogger(__name__)
        
        load_dotenv()
        self.host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')
        self.port = int(os.getenv('TBOT_IBKR_PORT', '4002'))
        self.client_id = int(os.getenv('IB_REALTIME_CLIENT_ID', '77'))

    # Required wrapper methods
    def connectAck(self):
        self.logger.info("Connection acknowledged")
        
    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        if errorCode not in [2104, 2106, 2107, 2108, 2158, 2174]:  # Added 2174 to filter warning
            self.logger.error(f"Error {errorCode}: {errorString}")
            if reqId in self.price_callbacks:
                self.price_callbacks[reqId].set()
            
    def connectionClosed(self):
        self.logger.warning("IB connection closed")
        
    def nextValidId(self, orderId):
        self.logger.debug(f"First valid order ID: {orderId}")

    def setEventsDone(self):
        self.logger.debug("Events processing completed")

    def realtimeBar(self, reqId, time, open_, high, low, close, volume, wap, count):
        """Callback for real-time bar data"""
        if reqId in self.price_callbacks:
            self.prices[reqId] = close
            self.price_callbacks[reqId].set()
            self.logger.debug(f"Got real-time price for reqId {reqId}: close={close}")

    def historicalData(self, reqId, bar):
        """Callback for historical data"""
        if reqId in self.price_callbacks and not self.price_callbacks[reqId].is_set():
            self.prices[reqId] = bar.close
            self.logger.debug(f"Got historical price for reqId {reqId}: close={bar.close}")

    def historicalDataEnd(self, reqId: int, start: str, end: str):
        """Required callback for historical data end notification"""
        if reqId in self.price_callbacks and not self.price_callbacks[reqId].is_set():
            self.logger.debug(f"Historical data complete for reqId {reqId}")
            self.price_callbacks[reqId].set()

    async def start(self):
        start_time = datetime.now()
        timeout = timedelta(seconds=120)
        
        while datetime.now() - start_time < timeout:
            try:
                await self.client.connectAsync(host=self.host, port=self.port, clientId=self.client_id, timeout=5)
                self.logger.info(f"Price service connected to IB Gateway at {self.host}:{self.port}")
                return True
            except Exception as e:
                if 'getaddrinfo failed' in str(e):
                    self.host = '127.0.0.1'
                    try:
                        await self.client.connectAsync(host=self.host, port=self.port, clientId=self.client_id, timeout=5)
                        self.logger.info(f"Price service connected to local IB Gateway at {self.host}:{self.port}")
                        return True
                    except Exception:
                        self.host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')
                
                remaining = timeout - (datetime.now() - start_time)
                if remaining.total_seconds() > 0:
                    await asyncio.sleep(3)
                else:
                    return False
        return False

    async def get_price(self, symbol: str) -> Optional[float]:
        """Get the current price for a symbol, using either real-time or historical data"""
        if not symbol:
            self.logger.error("Symbol cannot be empty")
            return None

        contract = Contract()
        contract.symbol = symbol
        contract.secType = 'STK'
        contract.exchange = 'SMART'
        contract.currency = 'USD'
        
        req_id = self.client.getReqId()
        self.price_callbacks[req_id] = asyncio.Event()

        try:
            price = await self._get_price_data(req_id, contract)
            if price is not None:
                self.logger.debug(f"class {self.__class__.__name__}: Got price for {symbol}: {price}")
            return price
        except Exception as e:
            self.logger.error(f"Error getting price for {symbol}: {str(e)}")
            return None
        finally:
            if req_id in self.price_callbacks:
                self.price_callbacks.pop(req_id, None)
            if req_id in self.prices:
                self.prices.pop(req_id, None)

    async def _get_price_data(self, req_id: int, contract: Contract) -> Optional[float]:
        """Internal method to get price data using either real-time or historical data"""
        ny_tz = pytz.timezone('America/New_York')
        current_time = datetime.now(ny_tz)
        
        is_weekend = current_time.weekday() >= 5
        market_open = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
        
        if is_weekend:
            # Use historical data for weekends
            end_datetime = current_time - timedelta(days=1)  # Get last trading day
            while end_datetime.weekday() >= 5:  # Adjust if last day was also weekend
                end_datetime -= timedelta(days=1)
            
            end_str = end_datetime.strftime('%Y%m%d %H:%M:%S') + ' US/Eastern'
            
            self.logger.debug(f"Requesting historical data for {contract.symbol} as of {end_str}")
            self.client.reqHistoricalData(
                reqId=req_id,
                contract=contract,
                endDateTime=end_str,
                durationStr='1 D',
                barSizeSetting='1 min',
                whatToShow='TRADES',
                useRTH=1,
                formatDate=1,
                keepUpToDate=False,
                chartOptions=[]
            )
        else:
            # Use real-time data during market hours
            use_rth = market_open <= current_time <= market_close
            
            self.client.reqRealTimeBars(
                reqId=req_id,
                contract=contract,
                barSize=5,
                whatToShow='TRADES',
                useRTH=use_rth,
                realTimeBarsOptions=[]
            )

        try:
            await asyncio.wait_for(self.price_callbacks[req_id].wait(), timeout=5)
            return self.prices.get(req_id)
        except asyncio.TimeoutError:
            self.logger.error(f"Timeout waiting for {contract.symbol} price")
            return None
        finally:
            if not is_weekend:
                self.client.cancelRealTimeBars(req_id)
            else:
                self.client.cancelHistoricalData(req_id)