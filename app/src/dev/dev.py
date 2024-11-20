# closeall.py
from pydantic import BaseModel
import asyncio
import os
import logging
from ib_async import *
from ib_async.contract import Contract
from ib_async.objects import PortfolioItem
from dotenv import load_dotenv
from typing import List, Optional

# Load environment variables
load_dotenv()

# Configure logging
log_file_path = os.path.join(os.path.dirname(__file__), 'pnl.log')
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

# Define IB parameters
host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')
port = int(os.getenv('TBOT_IBKR_PORT', '4002'))
client_id = 33

# Request model for the API
class ClosePositionsRequestSchema(BaseModel):
    symbols: List[str]  # List of symbols to close

async def close_positions(symbols_to_close: List[str]) -> dict:
    """
    Closes specified positions based on the current portfolio.
    
    Args:
        symbols_to_close: List of symbols to close positions for
    """
    ib = IB()
    try:
        await ib.connectAsync(host=host, port=port, clientId=client_id)
        logger.info(f"Connected to IB Gateway at {host}:{port} with client ID {client_id}")

        # Get current portfolio
        portfolio_items = await ib.portfolio()
        
        # Filter portfolio items for requested symbols
        positions_to_close = [
            item for item in portfolio_items
            if item.contract.symbol in symbols_to_close
        ]

        for position_item in positions_to_close:
            if position_item.position == 0:
                logger.info(f"No position to close for {position_item.contract.symbol}")
                continue

            # Determine action based on current position
            action = 'BUY' if position_item.position < 0 else 'SELL'
            quantity = abs(position_item.position)
            price =  item.marketPrice

            # Ensure contract details are set
            contract = position_item.contract
            contract.exchange = 'SMART'
            if not contract.currency:
                contract.currency = 'USD'
            if not contract.secType:
                contract.secType = 'STK'
            

            # Create and place the order
            order = LimitOrder(
             action=action,
             totalQuantity=quantity,
             tif='GTC',
             outsideRth=True,
             lmtPrice=price,
         )

            trade = await ib.placeOrder(contract, order)
            logger.info(f"Order placed for {contract.symbol}: {action} {quantity} shares")
            
            # Wait for order processing
            await asyncio.sleep(3)

        logger.info("All requested positions processed")
        await ib.disconnect()
        
        return {
            'status': 'success',
            'message': 'Position closing orders placed successfully'
        }

    except Exception as e:
        logger.error(f"Error while processing positions: {str(e)}")
        await ib.disconnect()
        raise Exception(f"Error processing positions: {str(e)}")

async def close_all_positions() -> dict:
    """
    Closes all positions in the current portfolio.
    """
    ib = IB()
    try:
        await ib.connectAsync(host=host, port=port, clientId=client_id)
        logger.info(f"Connected to IB Gateway at {host}:{port} with client ID {client_id}")

        # Get all positions
        portfolio_items = await ib.portfolio()
        symbols_to_close = [item.contract.symbol for item in portfolio_items if item.position != 0]
        
        return await close_positions(symbols_to_close)

    except Exception as e:
        logger.error(f"Error in close_all_positions: {str(e)}")
        await ib.disconnectAsync()
        raise Exception(f"Error in close_all_positions: {str(e)}")