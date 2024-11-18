from sqlalchemy import Column, Integer, Float, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

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