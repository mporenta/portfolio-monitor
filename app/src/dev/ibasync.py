# https://web.archive.org/web/20230322131733/https://ib-insync.readthedocs.io/recipes.html#async-streaming-ticks
# Not sure why this was removed from Ewalds Code Recipes.  
# Perhaps there were too many issues with using async that he didn't want to deal with all the questions

import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
import ib_async as ibi

class App:

    async def run(self):
        self.host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')  # Use container name as default
        self.port = int(os.getenv('TBOT_IBKR_PORT', '4002'))   # Use existing env var
        self.client_id = 12
        self.ib = ibi.IB()
        with await self.ib.connectAsync(host=self.host, port=self.port, clientId=self.client_id):

            contracts = [
                ibi.Stock(symbol, 'SMART', 'USD')
                for symbol in ['AAPL', 'TSLA', 'AMD', 'INTC']]
            for contract in contracts:
                self.ib.reqMktData(contract)

            async for tickers in self.ib.pendingTickersEvent:
                for ticker in tickers:
                    print(ticker)

    def stop(self):
        self.ib.disconnect()


app = App()
try:
    asyncio.run(app.run())
except (KeyboardInterrupt, SystemExit):
    app.stop()