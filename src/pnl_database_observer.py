import sqlite3
from datetime import datetime
import logging
from pathlib import Path
from typing import Optional, Dict, Any

class PnLDatabaseObserver:
    def __init__(self, db_path: str = "pnl_monitor.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.initialize_db()
    
    def initialize_db(self) -> None:
        """Initialize the SQLite database with necessary tables"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Main PnL tracking table
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS account_pnl (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    account_id TEXT,
                    daily_pnl REAL,
                    total_realized_pnl REAL,
                    total_unrealized_pnl REAL,
                    net_liquidation REAL,
                    risk_percent REAL,
                    risk_amount REAL,
                    should_close_positions BOOLEAN
                )
                ''')
                
                # Portfolio positions table
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    account_id TEXT,
                    symbol TEXT,
                    position REAL,
                    market_price REAL,
                    market_value REAL,
                    average_cost REAL,
                    unrealized_pnl REAL,
                    realized_pnl REAL,
                    exchange TEXT,
                    currency TEXT
                )
                ''')
                
                # Create indices for better query performance
                cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_account_pnl_timestamp 
                ON account_pnl(timestamp DESC)
                ''')
                
                cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_positions_timestamp 
                ON positions(timestamp DESC)
                ''')
                
                conn.commit()
                self.logger.info(f"Database initialized at {self.db_path}")
                
        except sqlite3.Error as e:
            self.logger.error(f"Database initialization error: {e}")
            raise

    def record_pnl_update(self, portfolio_tracker) -> None:
        """Record PnL update from IBPortfolioTracker instance"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Store main PnL data
                cursor.execute('''
                INSERT INTO account_pnl (
                    timestamp,
                    account_id,
                    daily_pnl,
                    total_realized_pnl,
                    total_unrealized_pnl,
                    net_liquidation,
                    risk_percent,
                    risk_amount,
                    should_close_positions
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', [
                    datetime.now().isoformat(),
                    portfolio_tracker.account,
                    portfolio_tracker.daily_pnl,
                    portfolio_tracker.total_realized_pnl,
                    portfolio_tracker.total_unrealized_pnl,
                    portfolio_tracker.net_liquidation,
                    portfolio_tracker.risk_percent,
                    getattr(portfolio_tracker, 'risk_amount', 
                           portfolio_tracker.net_liquidation * portfolio_tracker.risk_percent),
                    portfolio_tracker.should_close_positions
                ])
                
                # Store current positions
                portfolio = portfolio_tracker.ib.portfolio()
                if portfolio:
                    for item in portfolio:
                        if item.position != 0:  # Only store non-zero positions
                            cursor.execute('''
                            INSERT INTO positions (
                                timestamp,
                                account_id,
                                symbol,
                                position,
                                market_price,
                                market_value,
                                average_cost,
                                unrealized_pnl,
                                realized_pnl,
                                exchange,
                                currency
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', [
                                datetime.now().isoformat(),
                                portfolio_tracker.account,
                                item.contract.symbol,
                                item.position,
                                item.marketPrice,
                                item.marketValue,
                                item.averageCost,
                                item.unrealizedPNL,
                                0.0,  # realized PnL is per position not available directly
                                item.contract.exchange,
                                item.contract.currency
                            ])
                
                conn.commit()
                self.logger.info(f"Recorded PnL update for account {portfolio_tracker.account}")
                
        except Exception as e:
            self.logger.error(f"Error recording PnL update: {e}")

    def get_latest_pnl(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Get most recent PnL data"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Get latest PnL data
                cursor.execute('''
                SELECT * FROM account_pnl 
                WHERE account_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
                ''', [account_id])
                pnl_data = dict(cursor.fetchone()) if cursor.fetchone() else None
                
                if pnl_data:
                    # Get latest positions
                    cursor.execute('''
                    SELECT * FROM positions 
                    WHERE account_id = ? 
                    AND timestamp = (
                        SELECT MAX(timestamp) FROM positions WHERE account_id = ?
                    )
                    ''', [account_id, account_id])
                    positions = [dict(row) for row in cursor.fetchall()]
                    
                    pnl_data['positions'] = positions
                    return pnl_data
                    
                return None
                
        except Exception as e:
            self.logger.error(f"Error retrieving latest PnL data: {e}")
            return None

    def get_pnl_history(self, account_id: str, limit: int = 100) -> list:
        """Get historical PnL data"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                SELECT * FROM account_pnl 
                WHERE account_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
                ''', [account_id, limit])
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            self.logger.error(f"Error retrieving PnL history: {e}")
            return []

    def cleanup_old_records(self, days_to_keep: int = 30) -> None:
        """Remove old records to manage database size"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cutoff_date = (datetime.now().date() - 
                             datetime.timedelta(days=days_to_keep)).isoformat()
                
                cursor.execute('''
                DELETE FROM account_pnl 
                WHERE DATE(timestamp) < ?
                ''', [cutoff_date])
                
                cursor.execute('''
                DELETE FROM positions 
                WHERE DATE(timestamp) < ?
                ''', [cutoff_date])
                
                conn.commit()
                self.logger.info(f"Cleaned up records older than {days_to_keep} days")
        except Exception as e:
            self.logger.error(f"Error cleaning up old records: {e}")