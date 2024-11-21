#models.py
from sqlalchemy import Column, Integer, Float, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime



Base = declarative_base()


class PositionClose(Base):
    __tablename__ = 'position_close'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(50), nullable=False)
    action = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(datetime.timezone.utc))
class PnLData(Base):
    __tablename__ = 'pnl_data'
    
    id = Column(Integer, primary_key=True)
    daily_pnl = Column(Float)
    total_unrealized_pnl = Column(Float)
    total_realized_pnl = Column(Float)
    net_liquidation = Column(Float)
    timestamp = Column(DateTime, default=lambda: datetime.now(datetime.timezone.utc))

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
    exchange = Column(String)  # Keep as 'exchange' in the database
    timestamp = Column(DateTime, default=lambda: datetime.now(datetime.timezone.utc))

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
    timestamp = Column(DateTime, default=lambda: datetime.now(datetime.timezone.utc))

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