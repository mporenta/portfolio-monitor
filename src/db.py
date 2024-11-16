# db.py
import sqlite3
import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import List, Dict, Optional
from ib_async import PortfolioItem, Trade, IB, Order
# Set up logging to file
log_file_path = os.path.join(os.path.dirname(__file__), 'db.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()  # Optional: to also output logs to the console
    ]
)

logger = logging.getLogger(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'pnl_data_jengo.db')

# db.py
def init_db():
    """Initialize the SQLite database and create the necessary tables."""
    logger.debug("Starting database initialization...")  # Basic console output for immediate feedback
    
    try:
        # First verify we can create/access the database directory
        if not os.path.exists(os.path.dirname(DATABASE_PATH)):
            os.makedirs(os.path.dirname(DATABASE_PATH))
            logger.debug(f"Created database directory at {os.path.dirname(DATABASE_PATH)}")
            
        logger.debug(f"Attempting to connect to database at: {DATABASE_PATH}")
        
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Test if we can write to the database
        try:
            cursor.execute("SELECT 1")
            logger.debug("Successfully connected to database")
        except sqlite3.Error as e:
            logger.debug(f"Database connection test failed: {e}")
            raise

        # Create tables with individual try-except blocks for better error isolation
        tables = {
            'pnl_data': '''
                CREATE TABLE IF NOT EXISTS pnl_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    daily_pnl REAL,
                    total_unrealized_pnl REAL,
                    total_realized_pnl REAL,
                    net_liquidation REAL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''',
            'positions': '''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT UNIQUE,
                    position REAL,
                    market_price REAL,
                    market_value REAL,
                    average_cost REAL,
                    unrealized_pnl REAL,
                    realized_pnl REAL,
                    account TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''',
            'trades': '''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_time TIMESTAMP NOT NULL,
                    symbol TEXT UNIQUE,
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
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''',
            'orders': '''
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
                    last_fill_time TIMESTAMP,
                    commission REAL,
                    realized_pnl REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, order_id)
                )
            '''
        }

        for table_name, create_statement in tables.items():
            try:
                logger.debug(f"Creating table: {table_name}")
                cursor.execute(create_statement)
                logger.debug(f"Successfully created/verified table: {table_name}")
            except sqlite3.Error as e:
                logger.debug(f"Error creating table {table_name}: {e}")
                raise

        # Clear orders table and create trigger
        try:
            cursor.execute('DELETE FROM orders')
            logger.debug("Cleared orders table")
            
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS update_orders_timestamp 
                AFTER UPDATE ON orders
                BEGIN
                    UPDATE orders SET updated_at = CURRENT_TIMESTAMP 
                    WHERE id = NEW.id;
                END;
            ''')
            logger.debug("Created/verified orders timestamp trigger")
            
        except sqlite3.Error as e:
            logger.debug(f"Error in orders table cleanup or trigger creation: {e}")
            raise

        conn.commit()
        logger.debug("Successfully committed all database changes")
        
        conn.close()
        logger.debug("Database initialization completed successfully")
        
    except Exception as e:
        logger.debug(f"Critical error during database initialization: {str(e)}")
        logger.error(f"Critical error during database initialization: {str(e)}")
        raise  # Re-raise the exception after logging


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
        logger.debug("PnL data inserted into the database.")
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