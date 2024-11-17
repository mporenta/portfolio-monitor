# db.py
import sqlite3
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Table, MetaData
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dataclasses import asdict
from datetime import datetime
from typing import List, Dict, Optional
from ib_async import PortfolioItem, Trade, IB, Order

# Set the specific paths
load_dotenv()
DATABASE_PATH = os.getenv('DATABASE_PATH', '/app/data/pnl_data_jengo.db')
DATABASE_URL = f"sqlite:///{os.getenv('DATABASE_PATH', '/data/pnl_data_jengo.db')}"

# Set up logging to file
log_file_path = os.getenv('DATABASE_LOG_PATH', '/app/logs/db.log')
# Setup the database connection
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
# Ensure the log directory exists
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()  # Optional: to also output logs to the console
    ]
)

logger = logging.getLogger(__name__)
class PnLData(Base):
    __tablename__ = 'pnl_data'
    
    id = Column(Integer, primary_key=True)
    daily_pnl = Column(Float)
    total_unrealized_pnl = Column(Float)
    total_realized_pnl = Column(Float)
    net_liquidation = Column(Float)
    timestamp = Column(DateTime, default=lambda: datetime.now(datetime.timezone.utc))

class Position(Base):
    __tablename__ = 'positions'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, unique=True)
    position = Column(Float)
    market_price = Column(Float)
    market_value = Column(Float)
    average_cost = Column(Float)
    unrealized_pnl = Column(Float)
    realized_pnl = Column(Float)
    account = Column(String)
    timestamp = Column(DateTime, default=lambda: datetime.now(datetime.timezone.utc))

class Trade(Base):
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    trade_time = Column(DateTime, nullable=False)
    symbol = Column(String, unique=True)
    action = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    fill_price = Column(Float, nullable=False)
    commission = Column(Float)
    realized_pnl = Column(Float)
    order_ref = Column(String)
    exchange = Column(String)
    order_type = Column(String)
    status = Column(String)
    order_id = Column(Integer)
    perm_id = Column(Integer)
    account = Column(String)
    timestamp = Column(DateTime, default=lambda: datetime.now(datetime.timezone.utc))

class Order(Base):
    __tablename__ = 'orders'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    order_id = Column(Integer)
    perm_id = Column(Integer)
    action = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    total_quantity = Column(Float, nullable=False)
    limit_price = Column(Float)
    status = Column(String, nullable=False)
    filled_quantity = Column(Float, default=0)
    average_fill_price = Column(Float)
    last_fill_time = Column(DateTime)
    commission = Column(Float)
    realized_pnl = Column(Float)
    created_at = Column(DateTime, default=lambda: datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.now(datetime.timezone.utc))

def init_db():
    """Initialize the SQLite database and create the necessary tables."""
    logger.debug("Starting database initialization...")
    
    try:
        # Create database directory if it doesn't exist
        db_dir = os.path.dirname(os.getenv('DATABASE_PATH', '/app/data/pnl_data_jengo'))
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.debug(f"Created database directory at {db_dir}")
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        
        # Clear orders table
        with SessionLocal() as session:
            session.query(Order).delete()
            session.commit()
            logger.debug("Cleared orders table")
        
        logger.debug("Database initialization completed successfully")
        
    except Exception as e:
        logger.error(f"Critical error during database initialization: {str(e)}")
        raise


def insert_trades_data(trades):
    """Insert or update trades data."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        for trade in trades:
            if trade.fills:  # Only process trades with fills
                for fill in trade.fills:
                    cursor.execute('''
                        INSERT OR REPLACE INTO trades 
                        (symbol, trade_time, action, quantity, fill_price, commission,
                         realized_pnl, order_ref, exchange, order_type, status, 
                         order_id, perm_id, account)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        trade.contract.symbol,
                        fill.time,
                        trade.order.action,
                        fill.execution.shares,
                        fill.execution.price,
                        fill.commissionReport.commission if fill.commissionReport else None,
                        fill.commissionReport.realizedPNL if fill.commissionReport else None,
                        trade.order.orderRef,
                        fill.execution.exchange,
                        trade.order.orderType,
                        trade.orderStatus.status,
                        trade.order.orderId,
                        trade.order.permId,
                        trade.order.account
                    ))
        
        conn.commit()
        conn.close()
        logger.debug("insert_trades_data_jengo Trade data inserted successfully.")
    except Exception as e:
        logger.error(f"Error inserting trade data: {e}")

def fetch_latest_trades_data():
    """Fetch the latest trades data to match DataTables columns."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                trade_time,
                symbol,
                action,
                quantity,
                fill_price,
                commission,
                realized_pnl,
                exchange,
                order_ref,
                status
            FROM trades 
            ORDER BY trade_time DESC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
           
                        {
                            'trade_time': row[0],
                            'symbol': row[1],
                            'action': row[2],
                            'quantity': row[3],
                            'fill_price': row[4],
                            'commission': row[5],
                            'realized_pnl': row[6],
                            'exchange': row[7],
                            'order_ref': row[8],
                            'status': row[9]
                        }
                        for row in rows
                    ]
                    
    except Exception as e:
        logger.error(f"Error fetching latest trades data from the database: {e}")
        return {"data": {"trades": {"data": [], "status": "error"}}, "status": "error", "message": str(e)}


def insert_pnl_data(daily_pnl: float, total_unrealized_pnl: float, total_realized_pnl: float, net_liquidation: float):
    """Insert PnL data into the pnl_data table."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO pnl_data (daily_pnl, total_unrealized_pnl, total_realized_pnl, net_liquidation)
            VALUES (?, ?, ?, ?)
        ''', (daily_pnl, total_unrealized_pnl, total_realized_pnl, net_liquidation))
        conn.commit()
        conn.close()
        logger.debug("jengo PnL data inserted into the database.")
    except Exception as e:
        logger.error(f"Error inserting PnL data into the database: {e}")

def insert_positions_data(portfolio_items: List[PortfolioItem]):
    """Insert or update positions data and remove stale records."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        # Get current symbols from portfolio
        current_symbols = {item.contract.symbol for item in portfolio_items}
        #print(f"insert_positions_data print Jengo Current symbols: {current_symbols}")

        # Delete records for symbols not in current portfolio
        cursor.execute('''
            DELETE FROM positions 
            WHERE symbol NOT IN ({})
        '''.format(','.join('?' * len(current_symbols))), 
        tuple(current_symbols))

        # Insert or update current positions
        for item in portfolio_items:
            cursor.execute('''
                INSERT OR REPLACE INTO positions 
                (symbol, position, market_price, market_value, average_cost, unrealized_pnl, realized_pnl, account)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item.contract.symbol,
                item.position,
                item.marketPrice,
                item.marketValue,
                item.averageCost,
                item.unrealizedPNL,
                item.realizedPNL,
                item.account
            ))

        conn.commit()
        conn.close()
        logger.debug(f"Portfolio data updated in database: {portfolio_items}")
    except Exception as e:
        logger.error(f"Error updating positions data in database: {e}")
        if 'conn' in locals():
            conn.close()


def fetch_latest_pnl_data() -> Dict[str, float]:
    """Fetch the latest PnL data from the pnl_data table."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT daily_pnl, total_unrealized_pnl, total_realized_pnl, net_liquidation FROM pnl_data ORDER BY timestamp DESC LIMIT 1')
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                'daily_pnl': row[0],
                'total_unrealized_pnl': row[1],
                'total_realized_pnl': row[2],
                'net_liquidation': row[3]
            }
        logger.debug("jengo Fetching PnL data from the database.")
        return {}
    except Exception as e:
        logger.error(f"Error fetching latest PnL data from the database: {e}")
        return {}
def fetch_latest_net_liquidation() -> float:
    """Fetch only the latest net liquidation value from the database."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT net_liquidation FROM pnl_data ORDER BY timestamp DESC LIMIT 1')
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0.0
    except Exception as e:
        logger.error(f"Error fetching net liquidation from database: {e}")
        return 0.0

def fetch_latest_positions_data() -> List[Dict[str, float]]:
    """Fetch the latest positions data from the positions table."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT symbol, position, market_price, market_value, average_cost, unrealized_pnl, realized_pnl, account FROM positions ORDER BY timestamp DESC')
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                'symbol': row[0],
                'position': row[1],
                'market_price': row[2],
                'market_value': row[3],
                'average_cost': row[4],
                'unrealized_pnl': row[5],
                'realized_pnl': row[6],
                'exchange': row[7]  # Ensure 'exchange' is included
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching latest positions data from the database: {e}")
        return []


def insert_order(trade):
    """Insert a new order into the orders table."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT or REPLACE INTO orders (
                symbol,
                order_id,
                perm_id,
                action,
                order_type,
                total_quantity,
                limit_price,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, order_id) DO UPDATE SET
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
        ''', (
            trade.contract.symbol,
            trade.order.orderId,
            trade.order.permId,
            trade.order.action,
            trade.order.orderType,
            trade.order.totalQuantity,
            trade.order.lmtPrice if hasattr(trade.order, 'lmtPrice') else None,
            trade.orderStatus.status
        ))
        
        conn.commit()
        conn.close()
        logger.debug(f"Order inserted/updated for {trade.contract.symbol} order type: {trade.order.orderType}")
    except Exception as e:
        logger.error(f"Error inserting order: {e}")

def update_order_fill(trade):
    """Update order fill information when a fill occurs."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        total_filled = sum(fill.execution.shares for fill in trade.fills)
        avg_fill_price = (
            sum(fill.execution.shares * fill.execution.price for fill in trade.fills) / 
            total_filled if total_filled > 0 else None
        )
        last_fill_time = max(fill.execution.time for fill in trade.fills) if trade.fills else None
        total_commission = sum(
            fill.commissionReport.commission 
            for fill in trade.fills 
            if fill.commissionReport
        )
        total_realized_pnl = sum(
            fill.commissionReport.realizedPNL 
            for fill in trade.fills 
            if fill.commissionReport and fill.commissionReport.realizedPNL
        )

        cursor.execute('''
            UPDATE orders SET 
                filled_quantity = ?,
                average_fill_price = ?,
                last_fill_time = ?,
                commission = ?,
                realized_pnl = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE symbol = ? AND order_id = ?
        ''', (
            total_filled,
            avg_fill_price,
            last_fill_time,
            total_commission,
            total_realized_pnl,
            trade.orderStatus.status,
            trade.contract.symbol,
            trade.order.orderId
        ))
        
        conn.commit()
        conn.close()
        logger.debug(f"Order fill updated for {trade.contract.symbol}")
    except Exception as e:
        logger.error(f"Error updating order fill: {e}")

def get_order_status(symbol: str) -> Optional[dict]:
    """Get the current status of an order by symbol."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                symbol,
                order_id,
                status,
                filled_quantity,
                total_quantity,
                average_fill_price,
                realized_pnl,
                updated_at
            FROM orders 
            WHERE symbol = ?
            ORDER BY updated_at DESC 
            LIMIT 1
        ''', (symbol,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'symbol': row[0],
                'order_id': row[1],
                'status': row[2],
                'filled_quantity': row[3],
                'total_quantity': row[4],
                'average_fill_price': row[5],
                'realized_pnl': row[6],
                'last_update': row[7]
            }
        return None
    except Exception as e:
        logger.error(f"Error fetching order status: {e}")
        return None
    
def is_symbol_eligible_for_close(symbol: str) -> bool:
    """
    Check if a symbol is eligible for closing based on database conditions:
    - Must be in positions table
    - No recent orders (within 60 seconds)
    - No recent trades (within 60 seconds)
    """
    try:
        current_time = datetime.now()
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        # Add debug logging
        cursor.execute('SELECT * FROM positions WHERE symbol = ?', (symbol,))
        position_record = cursor.fetchone()
        logger.debug(f" is_symbol_eligible_for_closePosition record for {symbol}: {position_record}")

        # Check if symbol exists in positions table
        cursor.execute('''
            SELECT COUNT(*) FROM positions 
            WHERE symbol = ?
        ''', (symbol,))
        position_exists = cursor.fetchone()[0] > 0

        if not position_exists:
            logger.debug(f"{symbol} not found in positions table is_symbol_eligible_for_close")
            return False

        # Check for recent orders (within last 60 seconds)
        cursor.execute('''
            SELECT COUNT(*) FROM orders 
            WHERE symbol = ? 
            AND datetime(created_at) >= datetime(?, 'unixepoch')
        ''', (symbol, current_time.timestamp() - 60))
        recent_orders = cursor.fetchone()[0] > 0

        if recent_orders:
            logger.debug(f"{symbol} has recent orders is_symbol_eligible_for_close")
            return False

        # Check for recent trades (within last 60 seconds)
        cursor.execute('''
            SELECT COUNT(*) FROM trades 
            WHERE symbol = ? 
            AND datetime(trade_time) >= datetime(?, 'unixepoch')
        ''', (symbol, current_time.timestamp() - 60))
        recent_trades = cursor.fetchone()[0] > 0

        if recent_trades:
            logger.debug(f"{symbol} has recent trades is_symbol_eligible_for_close")
            return False

        conn.close()
        logger.debug(f"{symbol} is eligible for closing")
        return True

    except Exception as e:
        logger.error(f"Error checking symbol eligibility: {e}")
        return False
    
    

class DataHandler:
    def __init__(self):
        self.logger = logger  # Use the logger configured above
        

    def insert_all_data(
        self, daily_pnl: float, total_unrealized_pnl: float, total_realized_pnl: float, 
        net_liquidation: float, portfolio_items: List[PortfolioItem], trades: List[Trade], orders: List[Trade]
    ):
        """Insert PnL, positions, trades, and orders data."""
        # Insert PnL data
        insert_pnl_data(daily_pnl, total_unrealized_pnl, total_realized_pnl, net_liquidation)
        
        # Insert positions data
        #print(f"Jengo Portfolio data inserted successfully {portfolio_items}")
        insert_positions_data(portfolio_items)
        
        # Insert trades data
       
        #print(f"Jengo Trades data inserted successfully {trades}")
        insert_trades_data(trades)

        logger.debug(f"Jengo insert_all_data  inserted successfully {daily_pnl, total_unrealized_pnl, total_realized_pnl, trades, orders,portfolio_items}")


        return daily_pnl, total_unrealized_pnl, total_realized_pnl, trades, orders,portfolio_items
        
        # Insert/update each order
        #for trade in orders:
            #insert_order(trade)
            #update_order_fill(trade)

        # Log consolidated data after all insertions
        #self.log_pnl_and_positions()
        
    
'''
    def log_pnl_and_positions(self):
        """Fetch and log the latest PnL, positions, and trades data."""
        try:
            # Fetch and log PnL data
            pnl_data = fetch_latest_pnl_data()
            if pnl_data:
                self.logger.debug(f"""
    PnL Update:
    - Daily P&L: ${pnl_data.get('daily_pnl', 0.0):,.2f}
    - Unrealized P&L: ${pnl_data.get('total_unrealized_pnl', 0.0):,.2f}
    - Realized P&L: ${pnl_data.get('total_realized_pnl', 0.0):,.2f}
    - Net Liquidation: ${pnl_data.get('net_liquidation', 0.0):,.2f}
                """)

            # Fetch and log positions data
            positions_data = fetch_latest_positions_data()
            self.logger.debug("Positions:")
            for position in positions_data:
                self.logger.debug(
                    f"Symbol: {position['symbol']}, Position: {position['position']}, "
                    f"Market Price: ${position.get('market_price', 0.0):,.2f}, "
                    f"Market Value: ${position.get('market_value', 0.0):,.2f}, "
                    f"Unrealized PnL: ${position.get('unrealized_pnl', 0.0):,.2f}"
                )

            # Fetch and log trades data
            trades_data = fetch_latest_trades_data()
            self.logger.debug("Jengo db Trades:")
            for trade in trades_data:
                self.logger.debug(
                    f"Trade Time: {trade['trade_time']}, Symbol: {trade['symbol']}, "
                    f"Action: {trade['action']}, Quantity: {trade['quantity']}, "
                    f"Fill Price: ${trade.get('fill_price', 0.0):,.2f}, "
                    f"Commission: ${trade.get('commission', 0.0):,.2f if trade['commission'] is not None else 'N/A'}, "
                    f"Realized PnL: ${trade.get('realized_pnl', 0.0):,.2f if trade['realized_pnl'] is not None else 'N/A'}, "
                    f"Status: {trade['status']}"
                )

        except Exception as e:
            self.logger.error(f"Error fetching data for logging: {e}")
'''
