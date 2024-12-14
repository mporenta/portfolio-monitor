import asyncio
import logging
from ib_async import IB, util
from ib_async.contract import Contract
from ib_async.order import MarketOrder

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PnLMonitor:
    def __init__(self, host='127.0.0.1', port=7497, clientId=1):
        self.ib = IB()
        self.host = host
        self.port = port
        self.clientId = clientId
        self.open_positions = {}  # Dictionary to store open positions index
        self.current_positions = {}  # Dictionary to store current positions index
        
    async def connect(self):
        await self.ib.connectAsync(self.host, self.port, self.clientId)

    def on_pnl_event(self, pnl):
        total_pnl = pnl.realizedPnL + pnl.unrealizedPnL
        logger.info(f"Total PnL: {total_pnl}")
        
        if self.has_open_positions():
            open_symbols = [position.contract.symbol for position in self.ib.positions() if position.position != 0]
            logger.info(f"These positions are open: {', '.join(open_symbols)}")
            
            if total_pnl <= -1.0:
                logger.info("Total PnL is less than or equal to -1.0, checking positions to close...")
                self.close_all_positions()

    def has_open_positions(self):
        positions = self.ib.positions()
        return any(position.position != 0 for position in positions)

    def create_position_index(self):
        """Create an index of current open positions."""
        self.current_positions = {}
        for position in self.ib.positions():
            if position.position != 0:  # Only index non-zero positions
                symbol = position.contract.symbol
                self.current_positions[symbol] = position.contract.conId
        return self.current_positions

    def close_all_positions(self):
        """
        Close all open positions using the index-based approach:
        1. Create index of open positions
        2. Iterate through positions
        3. Check and update index
        4. Place orders to close positions
        """
        # Step 1: Create index of open positions
        self.current_positions = self.create_position_index()
        
        # Step 2: Iterate through positions
        for position in self.ib.positions():
            if position.position != 0:
                symbol = position.contract.symbol
                conId = position.contract.conId
                
                # Step 3: Check and update index
                if symbol not in self.open_positions:
                    # New position to track
                    self.open_positions[symbol] = conId
                    self._place_closing_order(position)
                elif self.open_positions[symbol] != conId:
                    # Contract ID has changed, update index and place new order
                    self.open_positions[symbol] = conId
                    self._place_closing_order(position)
                
        # Clean up closed positions from the index
        self.open_positions = {symbol: conId for symbol, conId 
                             in self.open_positions.items() 
                             if symbol in self.current_positions}

    def _place_closing_order(self, position):
        """Helper method to place a closing order for a position."""
        contract = position.contract
        action = 'SELL' if position.position > 0 else 'BUY'
        order = MarketOrder(action, abs(position.position))
        self.ib.placeOrder(contract, order)
        logger.info(f"Placed {action} order for {abs(position.position)} {contract.symbol}")

    async def monitor_pnl_and_close_positions(self):
        # Subscribe to PnL updates
        account = ""  # Specify the account if needed
        pnl = self.ib.reqPnL(account)
        self.ib.pnlEvent += self.on_pnl_event
        # Wait indefinitely for events
        await asyncio.Event().wait()

    def run(self):
        util.run(self._run())

    async def _run(self):
        await self.connect()
        try:
            await self.monitor_pnl_and_close_positions()
        finally:
            self.ib.disconnect()

if __name__ == "__main__":
    PnLMonitor().run()
