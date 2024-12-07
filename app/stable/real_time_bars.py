import asyncio
from typing import Optional, Dict
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
        self.client_id = int(os.getenv('IB_REALTIME_CLIENT_ID', '9'))

    # Required wrapper methods
    def connectAck(self):
        self.logger.info("Connection acknowledged")
        
    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        if errorCode not in [2104, 2106, 2107, 2108, 2158]:  # Filter common notifications
            self.logger.error(f"Error {errorCode}: {errorString}")
            
    def connectionClosed(self):
        self.logger.warning("IB connection closed")
        
    def nextValidId(self, orderId):
        self.logger.info(f"First valid order ID: {orderId}")

    def setEventsDone(self):
        self.logger.info("Events processing completed")

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
        contract = Contract()
        contract.symbol = symbol
        contract.secType = 'STK'
        contract.exchange = 'SMART'
        contract.currency = 'USD'
        
        req_id = self.client.getReqId()
        self.price_callbacks[req_id] = asyncio.Event()
        
        try:
            self.client.reqRealTimeBars(
                reqId=req_id,
                contract=contract,
                barSize=5,
                whatToShow='TRADES',
                useRTH=True,
                realTimeBarsOptions=[]
            )
            
            await asyncio.wait_for(self.price_callbacks[req_id].wait(), timeout=5)
            return self.prices.get(req_id)
        except asyncio.TimeoutError:
            self.logger.error(f"Timeout waiting for {symbol} price")
            return None
        finally:
            self.client.cancelRealTimeBars(req_id)
            self.price_callbacks.pop(req_id, None)
            self.prices.pop(req_id, None)

    def realtimeBar(self, reqId, time: int, open_: float, high: float, 
                    low: float, close: float, volume: int, wap: float, 
                    count: int):
        if reqId in self.price_callbacks:
            self.prices[reqId] = close
            self.price_callbacks[reqId].set()

async def run_service():
    service = RealtimePriceService()
    if await service.start():
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            service.client.disconnect()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_service())