import asyncio
from ib_async import IB, Stock, MarketOrder
import logging
import os
import time

log_file_path = os.path.join(os.path.dirname(__file__), 'flask_close.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()  # Optional: to also output logs to the console
    ]
)

logger = logging.getLogger(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'pnl_data_jengo.db')

async def close_positions(data):
    """
    Close active positions using the IB API.
    """
    ib = IB()
    try:
        retries = 3
        timeout = 10  # seconds
        for attempt in range(retries):
            try:
                # Attempt to connect asynchronously
                logger.info(f"Connecting to {data.get('host', '127.0.0.1')}:{data.get('port', 4002)} "
                            f"with clientId {data.get('clientId', 23)} (Attempt {attempt + 1})")
                await ib.connectAsync(data.get('host', '127.0.0.1'), data.get('port', 4002), clientId=data.get('clientId', 23))
                logger.info("Connected to TWS")
                break
            except asyncio.TimeoutError:
                logger.warning(f"Connection attempt {attempt + 1} timed out. Retrying...")
                await asyncio.sleep(2)
        else:
            raise TimeoutError("Failed to connect to TWS after multiple attempts.")

        tasks = []
        for pos in data['active_positions']:
            symbol, position_size = pos['symbol'], pos['position']

            if position_size == 0:
                logger.info(f"No position to close for {symbol}")
                continue

            action = 'SELL' if position_size > 0 else 'BUY'
            quantity = abs(position_size)

            # Asynchronous contract qualification
            contract = Stock(symbol, 'SMART', 'USD')
            qualified_contracts = await ib.qualifyContractsAsync(contract)
            if not qualified_contracts:
                logger.error(f"Failed to qualify contract for {symbol}")
                continue

            contract = qualified_contracts[0]
            logger.info(f"Qualified contract for {symbol}: {contract}")

            # Create and place the order
            order = MarketOrder(action, quantity)
            trade = ib.placeOrder(contract, order)

            # Monitor trade asynchronously
            tasks.append(_monitor_trade(trade, symbol))

        # Wait for all trades to complete
        await asyncio.gather(*tasks)
        logger.info("All positions closed")

    except Exception as e:
        logger.error(f"Error in close_positions: {e}", exc_info=True)
    finally:
        if ib.isConnected():
            ib.disconnect()  # Ensure clean disconnection
            logger.info("Disconnected from TWS")

async def _monitor_trade(trade, symbol, timeout=30):
    """
    Monitor the trade until it's done or timeout occurs.
    """
    start_time = time.time()
    while not trade.isDone():
        if time.time() - start_time > timeout:
            logger.warning(f"Monitoring trade for {symbol} timed out after {timeout} seconds.")
            break
        await asyncio.sleep(1)
    logger.info(f"Trade for {symbol} completed: {trade.orderStatus.status}")
