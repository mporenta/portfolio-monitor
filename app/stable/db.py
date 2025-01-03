from operator import is_
from ib_async import *
from datetime import datetime, timezone
import os
from time import sleep
import logging
import sqlite3
import logging
from pathlib import Path
from dotenv import load_dotenv
from dataclasses import asdict
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Table, MetaData, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import List, Dict, Optional


# Set the specific paths
load_dotenv()
DATA_DIR = os.path.join('DATA_DIR', "/app/data")

os.makedirs(DATA_DIR, exist_ok=True)
# Define database path
DATABASE_PATH = os.path.join(DATA_DIR, "pnl_data_jengo.db")
DATABASE_URL = os.getenv(f'DATABASE_URL', 'sqlite:///{DATABASE_PATH}')

# Set up logging to file
log_file_path = os.getenv('DATABASE_LOG_PATH', '/app/logs/db.log')
# Setup the database connection
# Create engine with correct path
engine = create_engine(
    DATABASE_URL, 
    connect_args={
        "check_same_thread": False,
        "timeout": 30
    }
)
@event.listens_for(engine, 'connect')
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA timezone = 'UTC'")
    cursor.close()
    
# Create sessionmaker
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for declarative models
Base = declarative_base()

# Ensure the log directory exists
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

# Configure logging
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
class PnLData(Base):
    __tablename__ = 'pnl_data'
    
    id = Column(Integer, primary_key=True)
    daily_pnl = Column(Float)
    total_unrealized_pnl = Column(Float)
    total_realized_pnl = Column(Float)
    net_liquidation = Column(Float)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Positions(Base):
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
    exchange = Column(String)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Trades(Base):
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
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Orders(Base):
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



def migrate_database(DATABASE_PATH):
    """Create or update database schema"""
    
    # Ensure database directory exists
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
        # Create pnl_data table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pnl_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_pnl REAL,
                total_unrealized_pnl REAL,
                total_realized_pnl REAL,
                net_liquidation REAL,
                timestamp DATETIME DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
            )
        ''')

        # Create positions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                position REAL,
                market_price REAL,
                market_value REAL,
                average_cost REAL,
                unrealized_pnl REAL,
                realized_pnl REAL,
                account TEXT,
                exchange TEXT,
                timestamp DATETIME DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
                UNIQUE(symbol)
            )
        ''')

        # Create trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_time DATETIME NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity REAL NOT NULL,
                fill_price REAL NOT NULL,
                commission REAL,
                realized_pnl REAL,
                order_ref TEXT,
                exchange TEXT,
                order_type TEXT,
                status TEXT,
                order_id INTEGER,
                perm_id INTEGER,
                account TEXT,
                timestamp DATETIME DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
            )
        ''')

        # Create orders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                order_id INTEGER,
                perm_id INTEGER,
                action TEXT NOT NULL,
                order_type TEXT NOT NULL,
                total_quantity REAL NOT NULL,
                limit_price REAL,
                status TEXT NOT NULL,
                filled_quantity REAL DEFAULT 0,
                average_fill_price REAL,
                last_fill_time DATETIME,
                commission REAL,
                realized_pnl REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, order_id)
            )
        ''')

        # Create indexes for better query performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pnl_timestamp ON pnl_data(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)')

        conn.commit()
        logging.info("Database migration completed successfully")
        
    except Exception as e:
        logging.error(f"Error during database migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Initialize the database with proper schema"""
    try:
        DATABASE_PATH
        migrate_database(DATABASE_PATH)
        logging.info("Database initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")
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
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        current_symbols = {item.contract.symbol for item in portfolio_items}

        cursor.execute('''
            DELETE FROM positions 
            WHERE symbol NOT IN ({})
        '''.format(','.join('?' * len(current_symbols))), 
        tuple(current_symbols))

        for item in portfolio_items:
            cursor.execute('''
                INSERT OR REPLACE INTO positions 
                (symbol, position, market_price, market_value, average_cost, 
                unrealized_pnl, realized_pnl, account, exchange)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                item.contract.symbol,
                item.position,
                item.marketPrice,
                item.marketValue,
                item.averageCost,
                item.unrealizedPNL,
                item.realizedPNL,
                item.account,
                item.contract.primaryExchange  # Map primaryExchange to exchange column
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
        cursor.execute('SELECT symbol, position, market_price, market_value, average_cost, unrealized_pnl, realized_pnl, account, exchange, timestamp FROM positions ORDER BY timestamp DESC')
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
                'account': row[7],
                'exchange': row[8],
                'timestamp': row[9]
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
        current_time = datetime.now(timezone.utc)
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


load_dotenv()
init_db()
print(f"Global load of Dotenv {load_dotenv()}")



class IBClientDB:
    def __init__(self):
        self.ib = IB()
        
        self.account = None
        self.wrapper = self.ib.wrapper
        self.client = self.ib.client
        self.data_handler = DataHandler()
        init_db()
        self.no_update_counter = 0
        
        # Load environment variables
        load_dotenv()
        self.host = os.getenv('IB_GATEWAY_HOST', 'ib-gateway')
        self.port = int(os.getenv('TBOT_IBKR_PORT', '4002'))
        self.client_id = 44
        
        log_file_path = '/app/logs/pnl.log'
        log_level = os.getenv('TBOT_LOGLEVEL', 'INFO')
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file_path),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _createEvents(self):
        """Set up event subscriptions"""
        # Account & PnL
        self.ib.accountValueEvent += self.on_account_value_update
        self.ib.pnlEvent += self.on_pnl_update
        self.ib.updatePortfolioEvent += self.on_portfolio_update
        
        # Orders & Executions  
        self.ib.orderStatusEvent += self.on_order_status
        self.ib.execDetailsEvent += self.on_execution_details
        self.ib.commissionReportEvent += self.on_commission_report

    def on_account_value_update(self, account_value: AccountValue):
        """Handle NetLiquidation updates"""
        try:
            if account_value.tag == "NetLiquidation":
                with SessionLocal() as session:
                    net_liq = PnLData(
                        daily_pnl=None,
                        total_unrealized_pnl=None,
                        total_realized_pnl=None,
                        net_liquidation=float(account_value.value),
                        timestamp=datetime.now(timezone.utc)
                    )
                    session.merge(net_liq)
                    session.commit()
                    self.logger.debug(f"NetLiquidation updated: ${float(account_value.value):,.2f}")
        except Exception as e:
            self.logger.error(f"Error updating net liquidation: {e}")

    def on_pnl_update(self, pnl: PnL):
        """Handle PnL updates"""
        try:
            with SessionLocal() as session:
                pnl_data = PnLData(
                    daily_pnl=float(pnl.dailyPnL or 0.0),
                    total_unrealized_pnl=float(pnl.unrealizedPnL or 0.0),
                    total_realized_pnl=float(pnl.realizedPNL or 0.0),
                    net_liquidation=None,  # Don't update net_liquidation here
                    timestamp=datetime.now(timezone.utc)
                )
                session.merge(pnl_data)
                session.commit()
                self.logger.debug("PnL data updated")
        except Exception as e:
            self.logger.error(f"Error updating PnL data: {e}")
        
    def on_portfolio_update(self, item: PortfolioItem):
        """Handle portfolio updates"""
        try:
            with SessionLocal() as session:
                position = Positions(
                    symbol=item.contract.symbol,
                    position=item.position,
                    market_price=item.marketPrice,
                    market_value=item.marketValue,
                    average_cost=item.averageCost,
                    unrealized_pnl=item.unrealizedPNL,
                    realized_pnl=item.realizedPNL,
                    account=item.account,
                    exchange=item.contract.primaryExchange,
                    timestamp=datetime.now(timezone.utc)
                )
                session.merge(position)
                session.commit()
        except Exception as e:
            self.logger.error(f"Error updating portfolio: {e}")

    def on_execution_details(self, trade: Trade, fill: Fill):
        """Handle execution details"""
        try:
            with SessionLocal() as session:
                trade_record = Trades(
                    trade_time=fill.time,
                    symbol=trade.contract.symbol,
                    action=trade.order.action,
                    quantity=fill.execution.shares,
                    fill_price=fill.execution.price,
                    exchange=fill.execution.exchange,
                    order_type=trade.order.orderType,
                    status=trade.orderStatus.status,
                    order_id=trade.order.orderId,
                    perm_id=trade.order.permId,
                    account=trade.order.account,
                    timestamp=datetime.now(timezone.utc)
                )
                session.merge(trade_record)
                session.commit()
        except Exception as e:
            self.logger.error(f"Error recording execution: {e}")

    def on_commission_report(self, trade: Trade, fill: Fill, report: CommissionReport):
        """Handle commission reports"""
        try:
            with SessionLocal() as session:
                session.query(Trades).filter(
                    Trades.order_id == trade.order.orderId,
                    Trades.symbol == trade.contract.symbol
                ).update({
                    'commission': report.commission,
                    'realized_pnl': report.realizedPNL
                })
                session.commit()
        except Exception as e:
            self.logger.error(f"Error recording commission: {e}")

    def on_order_status(self, trade: Trade):
        """Handle order status updates"""
        try:
            with SessionLocal() as session:
                order = Orders(
                    symbol=trade.contract.symbol,
                    order_id=trade.order.orderId,
                    perm_id=trade.order.permId,
                    action=trade.order.action,
                    order_type=trade.order.orderType,
                    total_quantity=trade.order.totalQuantity,
                    limit_price=trade.order.lmtPrice if hasattr(trade.order, 'lmtPrice') else None,
                    status=trade.orderStatus.status,
                    filled_quantity=trade.orderStatus.filled,
                    average_fill_price=trade.orderStatus.avgFillPrice,
                    last_fill_time=datetime.now(timezone.utc) if trade.orderStatus.status == "Filled" else None
                )
                session.merge(order)
                session.commit()
        except Exception as e:
            self.logger.error(f"Error updating order status: {e}")
    def connect(self):
        """Establish connection to IB Gateway with retry logic"""
        try:
            try:
                self.ib.connect(host=self.host, port=self.port, clientId=self.client_id)
                self.logger.info(f"Connected to IB Gateway at {self.host}:{self.port}")
                self._createEvents()
                return True
            except Exception as e:
                if 'getaddrinfo failed' in str(e):
                    self.host = '127.0.0.1'
                    self.ib.connect(host=self.host, port=self.port, clientId=self.client_id)
                    self._createEvents()
                    self.logger.info(f"Connected to IB Gateway at {self.host}:{self.port}")
                    return True
                raise
        except Exception as e:
            self.logger.error(f"Failed to connect to IB Gateway: {e}")
            return False

    def subscribe_account_updates(self):
        """Subscribe to account updates"""
        accounts = self.ib.managedAccounts()
        if not accounts:
            self.logger.error("No managed accounts available")
            return False

        self.account = accounts[0]
        self.ib.reqAccountUpdates(True, self.account)
        self.ib.reqPnL(self.account)
        return True

    def run(self):
        """Main run loop with improved error handling."""
        try:
            load_dotenv()
            logging.info("Starting Database fucker from db.py run...")
            init_db()
            if not self.connect():
                return
                
            sleep(2)  # Allow connection to stabilize
            
            print(f"jengo db.py running ={self.connect()}")
            
            print(f"jengo db.py running _createEvents ={self._createEvents()}")
            self._createEvents()
            print(f"jengo db.py ran _createEvents ={self._createEvents()}")
            
            self.no_update_counter = 0
            while True:
                try:
                    if self.ib.waitOnUpdate(timeout=1):
                        self.no_update_counter = 0
                    else:
                        self.no_update_counter += 1
                        if self.no_update_counter >= 60:
                            logging.debug("No updates for 60 seconds")
                            self.no_update_counter = 0
                except Exception as e:
                    logging.error(f"Error in main loop: {str(e)}")
                    sleep(1)  # Prevent tight error loop
                    
        except KeyboardInterrupt:
            logging.info("Shutting down by user request...")
        except Exception as e:
            logging.error(f"Critical error in run loop: {str(e)}")
        finally:
            self.ib.disconnect()

if __name__ == '__main__':
    client = IBClientDB()
    client.run()