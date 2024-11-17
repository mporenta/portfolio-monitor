import redis
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import asdict

# Set up logging
log_file_path = '/app/logs/db.log'
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class RedisDB:
    def __init__(self, host='localhost', port=6379, db=0):
        self.redis_client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.logger = logger

    def init_db(self):
        """Initialize Redis database connection."""
        try:
            self.redis_client.ping()
            logger.debug("Successfully connected to Redis database")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _serialize_datetime(self, obj):
        """Helper method to serialize datetime objects."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    def insert_trades_data(self, trades):
        """Insert or update trades data."""
        try:
            for trade in trades:
                if trade.fills:
                    for fill in trade.fills:
                        trade_data = {
                            'symbol': trade.contract.symbol,
                            'trade_time': self._serialize_datetime(fill.time),
                            'action': trade.order.action,
                            'quantity': fill.execution.shares,
                            'fill_price': fill.execution.price,
                            'commission': fill.commissionReport.commission if fill.commissionReport else None,
                            'realized_pnl': fill.commissionReport.realizedPNL if fill.commissionReport else None,
                            'order_ref': trade.order.orderRef,
                            'exchange': fill.execution.exchange,
                            'order_type': trade.order.orderType,
                            'status': trade.orderStatus.status,
                            'order_id': trade.order.orderId,
                            'perm_id': trade.order.permId,
                            'account': trade.order.account,
                            'timestamp': self._serialize_datetime(datetime.now())
                        }
                        
                        # Store trade with timestamp as score for ordering
                        trade_key = f"trade:{trade.contract.symbol}:{trade.order.orderId}"
                        self.redis_client.zadd('trades', {json.dumps(trade_data): datetime.now().timestamp()})
                        
            logger.debug("Trade data inserted successfully.")
        except Exception as e:
            logger.error(f"Error inserting trade data: {e}")

    def insert_pnl_data(self, daily_pnl: float, total_unrealized_pnl: float, 
                       total_realized_pnl: float, net_liquidation: float):
        """Insert PnL data."""
        try:
            pnl_data = {
                'daily_pnl': daily_pnl,
                'total_unrealized_pnl': total_unrealized_pnl,
                'total_realized_pnl': total_realized_pnl,
                'net_liquidation': net_liquidation,
                'timestamp': self._serialize_datetime(datetime.now())
            }
            
            # Store PnL data with timestamp as score
            self.redis_client.zadd('pnl_data', {json.dumps(pnl_data): datetime.now().timestamp()})
            logger.debug("PnL data inserted successfully.")
        except Exception as e:
            logger.error(f"Error inserting PnL data: {e}")

    def insert_positions_data(self, portfolio_items: List[Dict]):
        """Insert or update positions data."""
        try:
            # Get current timestamp for batch operation
            current_time = datetime.now().timestamp()
            
            # Create set of current symbols
            current_symbols = {item.contract.symbol for item in portfolio_items}
            
            # Remove old positions
            existing_positions = self.redis_client.smembers('active_positions')
            for symbol in existing_positions - current_symbols:
                self.redis_client.delete(f"position:{symbol}")
            
            # Update active positions set
            self.redis_client.delete('active_positions')
            self.redis_client.sadd('active_positions', *current_symbols)
            
            # Insert new positions
            for item in portfolio_items:
                position_data = {
                    'symbol': item.contract.symbol,
                    'position': item.position,
                    'market_price': item.marketPrice,
                    'market_value': item.marketValue,
                    'average_cost': item.averageCost,
                    'unrealized_pnl': item.unrealizedPNL,
                    'realized_pnl': item.realizedPNL,
                    'account': item.account,
                    'timestamp': self._serialize_datetime(datetime.now())
                }
                
                position_key = f"position:{item.contract.symbol}"
                self.redis_client.set(position_key, json.dumps(position_data))
                
            logger.debug(f"Portfolio data updated in database")
        except Exception as e:
            logger.error(f"Error updating positions data: {e}")

    def insert_order(self, trade):
        """Insert a new order."""
        try:
            order_data = {
                'symbol': trade.contract.symbol,
                'order_id': trade.order.orderId,
                'perm_id': trade.order.permId,
                'action': trade.order.action,
                'order_type': trade.order.orderType,
                'total_quantity': trade.order.totalQuantity,
                'limit_price': trade.order.lmtPrice if hasattr(trade.order, 'lmtPrice') else None,
                'status': trade.orderStatus.status,
                'created_at': self._serialize_datetime(datetime.now()),
                'updated_at': self._serialize_datetime(datetime.now())
            }
            
            order_key = f"order:{trade.contract.symbol}:{trade.order.orderId}"
            self.redis_client.set(order_key, json.dumps(order_data))
            logger.debug(f"Order inserted/updated for {trade.contract.symbol}")
        except Exception as e:
            logger.error(f"Error inserting order: {e}")

    def fetch_latest_trades_data(self):
        """Fetch the latest trades data."""
        try:
            # Get the latest 100 trades, ordered by timestamp
            trades = self.redis_client.zrevrange('trades', 0, 99)
            return [json.loads(trade) for trade in trades]
        except Exception as e:
            logger.error(f"Error fetching latest trades data: {e}")
            return []

    def fetch_latest_pnl_data(self) -> Dict:
        """Fetch the latest PnL data."""
        try:
            latest_pnl = self.redis_client.zrevrange('pnl_data', 0, 0)
            if latest_pnl:
                return json.loads(latest_pnl[0])
            return {}
        except Exception as e:
            logger.error(f"Error fetching latest PnL data: {e}")
            return {}

    def fetch_latest_positions_data(self) -> List[Dict]:
        """Fetch the latest positions data."""
        try:
            positions = []
            symbols = self.redis_client.smembers('active_positions')
            for symbol in symbols:
                position_data = self.redis_client.get(f"position:{symbol}")
                if position_data:
                    positions.append(json.loads(position_data))
            return positions
        except Exception as e:
            logger.error(f"Error fetching latest positions data: {e}")
            return []

class DataHandler:
    def __init__(self, redis_client):
        self.db = redis_client
        self.logger = logger

    def insert_all_data(self, daily_pnl: float, total_unrealized_pnl: float, 
                       total_realized_pnl: float, net_liquidation: float, 
                       portfolio_items: List, trades: List, orders: List):
        """Insert all data types in one transaction."""
        try:
            # Insert PnL data
            self.db.insert_pnl_data(daily_pnl, total_unrealized_pnl, total_realized_pnl, net_liquidation)
            
            # Insert positions data
            self.db.insert_positions_data(portfolio_items)
            
            # Insert trades data
            self.db.insert_trades_data(trades)
            
            # Insert/update orders
            for trade in orders:
                self.db.insert_order(trade)
                
        except Exception as e:
            logger.error(f"Error in insert_all_data: {e}")
