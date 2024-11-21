# closeall.py

from pydantic import BaseModel
import asyncio
import os
import logging
from ib_async import *
from dotenv import load_dotenv
from typing import List, Optional
ib = IB()
   
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

# Define request models with unique names to avoid conflicts
def positions_to_close(portfolio_items: PortfolioItem):
    portfolio_items = ib.portfolio()
    for item in portfolio_items:
        if item.position != 0:
            positions_to_close.append({
                'symbol': item.contract.symbol,
                'action': 'SELL' if item.position > 0 else 'BUY',
                'quantity': abs(item.position)
            })

async def close_positions(positions_to_close) -> dict:
  
    """
    Closes specified positions based on the request.

   

    Args:
        positions_to_close: List of positions to close with their details
    
    Returns:
        dict: Status of the operation
    """
    
    try:
        await ib.connectAsync(host=host, port=port, clientId=client_id)
        logger.info(f"Connected to IB Gateway at {host}:{port} with client ID {client_id}")


        # Gracefully disconnect
        await ib.disconnect()
        logger.info("Disconnected from IB Gateway")
        
        return {
            'status': 'success',
            'message': 'Positions closed successfully'
        }

    except Exception as e:
        logger.error(f"Error while processing positions: {str(e)}")
        await ib.disconnect()
        raise Exception(f"Error processing positions: {str(e)}")

