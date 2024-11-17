import asyncio
from ib_async import IB, Stock, MarketOrder
import logging

logger = logging.getLogger(__name__)

async def close_positions(data):
    ib = IB()
    await ib.connectAsync('127.0.0.1', 4002, clientId=1)
    logger.info("Connected to TWS")

    positions = data['active_positions']

    for pos in positions:
        symbol = pos['symbol']
        position_size = pos['position']
        if position_size == 0:
            logger.info(f"No position to close for {symbol}")
            continue  # No position to close

        if position_size > 0:
            action = 'SELL'  # To close long positions, we sell
        else:
            action = 'BUY'   # To close short positions, we buy

        quantity = abs(position_size)
        logger.info(f"Closing position for {symbol}: Action={action}, Quantity={quantity}")

        # Create contract
        contract = Stock(symbol, 'SMART', 'USD')

        # Ensure the contract details are fetched
        await ib.qualifyContractsAsync(contract)
        logger.info(f"Contract qualified for {symbol}")

        # Create order
        order = MarketOrder(action, quantity)

        # Submit order
        trade = ib.placeOrder(contract, order)
        logger.info(f"Order placed for {symbol}")

        # Wait until the order is filled
        while not trade.isDone():
            await asyncio.sleep(1)
        logger.info(f"Order filled for {symbol}")

    ib.disconnect()
    logger.info("Disconnected from TWS")
