# pnl_monitor.py

from operator import is_
import pandas as pd
import asyncio
import math
from contextlib import asynccontextmanager
from fastapi.background import P
import aiohttp
import requests
import json
from ib_async import IB, MarketOrder, LimitOrder, PnL, PortfolioItem, AccountValue, Contract, Trade, util, Ticker, Stock
from typing import *
from datetime import datetime, timedelta
import pytz
import os
from dotenv import load_dotenv
import time
import logging
from typing import Optional, List
load_dotenv()
from real_time_bars import RealtimePriceService
risk_amount = float(os.getenv('WEBHOOK_PNL_THRESHOLD', -300.0))  # Risk set 
log_file_path = os.path.join(os.path.dirname(__file__), 'pnl.log')
log_level = os.getenv('TBOT_LOGLEVEL', 'DEBUG')
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)


class PositionDataManager:
    """
    Subscribes to market data for all positions with non-zero holdings,
    and unsubscribes when a position goes to zero.
    """
    def __init__(self, ib: IB, account: str = ""):
        
        self.ib = ib
        self.account = account
        self.subscribed_tickers = {}
        
        # Setup instance logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def create_stock_contract(self, symbol: str) -> Contract:
        """
        Create a proper stock contract with minimal required fields
        """
        contract = Stock(symbol, 'SMART', 'USD')
        return contract

    async def get_contract_details(self, contract: Contract) -> Contract:
        """
        Get full contract details from IB
        """
        try:
            details = await self.ib.reqContractDetailsAsync(contract)
            if details and len(details) > 0:
                # Return the contract from the first contract details
                return details[0].contract
            self.logger.error(f"No contract details found for: {contract}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting contract details for {contract}: {str(e)}")
            return None

    async def update_positions_and_subscriptions(self):
        """
        Updates position tracking and market data subscriptions
        """
        all_positions = self.ib.positions(self.account)
        
        # Create a dictionary of positions with non-zero holdings
        pos_dict = {}
        for p in all_positions:
            if p.position != 0:
                # Create a new stock contract for this position
                contract = self.create_stock_contract(p.contract.symbol)
                # Store both the contract and position
                pos_dict[p.contract.symbol] = (contract, p.position)

        # Subscribe to any new positions
        for symbol, (contract, position) in pos_dict.items():
            if symbol not in self.subscribed_tickers:
                # Get full contract details
                detailed_contract = await self.get_contract_details(contract)
                if detailed_contract:
                    self.logger.info(f"Subscribing to {detailed_contract.symbol}")
                    try:
                        # Request market data with the detailed contract
                        ticker = self.ib.reqMktData(
                            detailed_contract,
                            genericTickList='',  # Use default tick types
                            snapshot=False,
                            regulatorySnapshot=False,
                            mktDataOptions=[]
                        )
                        ticker.updateEvent += self._on_ticker_update
                        self.subscribed_tickers[symbol] = ticker
                        self.logger.info(
                            f"Subscribed to {detailed_contract.symbol}, "
                            f"position={position}"
                        )
                    except Exception as e:
                        self.logger.error(f"Error subscribing to {detailed_contract.symbol}: {str(e)}")

        # Unsubscribe from positions we no longer own
        symbols_to_remove = []
        for symbol, ticker in self.subscribed_tickers.items():
            if symbol not in pos_dict:
                try:
                    self.ib.cancelMktData(ticker.contract)
                    symbols_to_remove.append(symbol)
                    self.logger.info(f"Unsubscribed from {symbol}")
                except Exception as e:
                    self.logger.error(f"Error unsubscribing from {symbol}: {str(e)}")

        # Clean up removed subscriptions
        for symbol in symbols_to_remove:
            del self.subscribed_tickers[symbol]

    async def _on_ticker_update(self, ticker: Ticker):
        """
        Enhanced ticker update handler with trading status and price updates
        """
        positions = await self.ib.reqPositionsAsync()
        halted_conId=ticker.contract.conId

        # Filter for the specific conId
        specific_position = next((pos for pos in positions if pos.contract.conId == halted_conId), None)

        
        symbol = ticker.contract.symbol
        updates = []

        # Check halted status (type 49)
        if hasattr(ticker, 'halted') and ticker.halted is not None:

            if ticker.halted == 1 or ticker.halted == 2 or symbol == 'TSLA':
                self.logger.info(f"jengo ticker: [{ticker}] Trading HALTED")
                if specific_position:
                    await self._place_market_order(specific_position)
                    print(f"Position for conId {positions}: specific_position {specific_position} = conId {halted_conId}")
                else:
                    print(f"No position found for conId {specific_position}.")
           
                

                updates.append("HALTED")
            elif ticker.halted == 0 or math.isnan(ticker.halted):
                updates.append("TRADING")

        # Collect all available price information with NaN checks
        if ticker.last is not None and ticker.lastSize is not None:
            if not math.isnan(ticker.last) and not math.isnan(ticker.lastSize):
                updates.append(f"Last: ${ticker.last:.2f} (size: {ticker.lastSize})")
            
        if ticker.bid is not None and ticker.ask is not None:
            if not math.isnan(ticker.bid) and not math.isnan(ticker.ask):
                updates.append(f"Bid: ${ticker.bid:.2f}, Ask: ${ticker.ask:.2f}")
            
        if ticker.volume is not None and not math.isnan(ticker.volume):
            updates.append(f"Volume: {ticker.volume:,.0f}")
            
        if ticker.high is not None and not math.isnan(ticker.high):
            updates.append(f"High: ${ticker.high:.2f}")
            
        if ticker.low is not None and not math.isnan(ticker.low):
            updates.append(f"Low: ${ticker.low:.2f}")
            
        # Only log if we have updates to report
        if updates:
            self.logger.debug(f"[{symbol}] " + " | ".join(updates))    

    async def _place_market_order(self, portfolio_item: PortfolioItem):
        """Place an order with Interactive Brokers based on the position request."""
        try:

            symbol = portfolio_item.contract.symbol
            pos = abs(portfolio_item.position)
            is_long_position = portfolio_item.position > 0
            
            contract = Contract(
                symbol=symbol,
                exchange='SMART',
                secType='STK',
                currency='USD'
            )

            action = 'SELL' if is_long_position else 'BUY'

            
            order = MarketOrder(
                action=action,
                totalQuantity=pos,
                tif='GTC'
            )

            trade = self.ib.placeOrder(contract, order)
            self.logger.info(f"Order placed for {symbol}: {trade}")
                
            return trade

        except Exception as e:
            self.logger.error(f"Error processing order for {symbol}: {str(e)}", exc_info=True)
            return None
            
