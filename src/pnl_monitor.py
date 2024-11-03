import logging 
from ib_async import IB, MarketOrder, LimitOrder, PnL, PortfolioItem, AccountValue, Contract, Trade
from typing import *
from datetime import datetime
import pytz 
import os
from dotenv import load_dotenv

class IBPortfolioTracker:
    def __init__(self):
        self.ib = IB()
        self.dotenv= load_dotenv()
        self.risk_percent = float(os.getenv('RISK_PERCENT', 0.01))
        self.account = "DU7397764"
        self.total_realized_pnl = 0.0
        self.total_unrealized_pnl = 0.0
        self.daily_pnl = 0.0
        self.all_have_orders = False
        self.should_close_positions = False
        self.net_liquidation = 0.0
        
          # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Connect to IB Gateway
        try:
            self.ib.connect("127.0.0.1", 4002, clientId=8)
            self.logger.info("Connected successfully to IB Gateway")
            
            # Wait for managed accounts to be populated
            self.ib.waitOnUpdate(timeout=2)

            # Get account
            accounts = self.ib.managedAccounts()
            self.logger.info(f"Managed accounts: {accounts}")
            if not accounts:
                raise Exception("No managed accounts available")
                
            self.account = accounts[0]
            self.logger.info(f"Using account {self.account}")
            
            # Set up callbacks
            self.ib.accountSummaryEvent += self.on_account_summary
            self.ib.connectedEvent += self.onConnected

            # Request initial account summary
            self.request_account_summary()
            self.ib.newOrderEvent += self.get_trades
            # Wait briefly for initial account data
            #self.ib.sleep(2)
            #self.ib.updatePortfolioEvent += self.on_portfolio_update
            #self.on_portfolio_update(self.ib.portfolio())
            self.ib.sleep(2)
            
            # Subscribe to PnL updates
            self.pnl = self.ib.reqPnL(self.account)
            if not self.pnl:
                raise RuntimeError("Failed to subscribe to PnL updates")
            self.logger.info(f"Successfully subscribed to PnL updates for account {self.account}")
            self.ib.pnlEvent += self.on_pnl_update
            
        except Exception as e:
            self.logger.error(f"Initialization failed: {str(e)}")
            raise

    def request_account_summary(self):
        """Request account summary update"""
        try:
            # Request account summary
            self.ib.reqAccountSummary()
            self.logger.info("Requested account summary update")
        except Exception as e:
            self.logger.error(f"Error requesting account summary: {str(e)}")

    def on_account_summary(self, value: AccountValue):
        """Handle account summary updates"""
        try:
            if value.tag == 'NetLiquidation':
                try:
                    new_value = float(value.value)
                    if new_value > 0:
                        if new_value != self.net_liquidation:
                            self.logger.info(f"Net liquidation changed: ${self.net_liquidation:,.2f} -> ${new_value:,.2f}")
                        self.net_liquidation = new_value
                    else:
                        self.logger.warning(f"Received non-positive net liquidation value: {new_value}")
                except ValueError:
                    self.logger.error(f"Invalid net liquidation value received: {value.value}")
        except Exception as e:
            self.logger.error(f"Error processing account summary: {str(e)}")

    def get_net_liquidation(self) -> float:
        """Get the current net liquidation value"""
        if self.net_liquidation <= 0:
            # Request a fresh update if the value is invalid
            self.request_account_summary()
            self.ib.sleep(1)  # Give time for update to arrive
        return self.net_liquidation
    def get_trades(self, trade: Trade):
        print(f"Trade received: {trade}")

        return trade

    def check_pnl_conditions(self,  pnl: PnL) -> bool:
        """Check if PnL has exceeded risk threshold"""
        try:
            net_liq = self.get_net_liquidation()
            if net_liq <= 0:
                self.logger.warning(f"Invalid net liquidation value: ${net_liq:,.2f}")
                return False
            
            self.daily_pnl = float(pnl.dailyPnL) if pnl.dailyPnL is not None else 0.0
            self.risk_amount = net_liq * self.risk_percent
            is_threshold_exceeded = self.daily_pnl <= -self.risk_amount  # Note the negative sign
            #is_threshold_exceeded = 100 <= self.risk_amount  # Note the negative sign
            self.logger.info(f"Risk amount is ${self.risk_amount:,.2f} ")
            
            if is_threshold_exceeded:
                self.logger.info(f"Risk threshold reached: Daily PnL ${self.daily_pnl:,.2f} <= -${self.risk_amount:,.2f}")
                self.logger.info(f"Threshold is {self.risk_percent:.1%} of ${net_liq:,.2f}")
                self.should_close_positions = True
                
                
                
                
                        
                        
                
            return is_threshold_exceeded
            
        except Exception as e:
            self.logger.error(f"Error checking PnL conditions: {str(e)}")
            return False

    
   

    def close_all_positions(self, account: str = ""):
    
        # Get all portfolio positions
        portfolio_items =self.ib.portfolio(account)
        if not portfolio_items:
            print("No positions to close")
            return
    
        trades = []
        # Get current NY time
        ny_tz = pytz.timezone('America/New_York')
        ny_time = datetime.now(ny_tz)
        current_hour = ny_time.hour
        # Determine if we're in after-hours (16:00-20:00 NY time)
        is_after_hours = 16 <= current_hour < 23
        
        # For each position, ensure contract details are complete
        for item in portfolio_items:
            if item.position == 0:
                continue
            
            # Set action based on position direction
            action = 'BUY' if item.position < 0 else 'SELL'
            quantity = abs(item.position)
        
            print(f"\nProcessing {item.contract.symbol}: {action} {quantity} shares")
        
            try:
                # Ensure contract has proper exchange info
                contract = item.contract
                contract.exchange = contract.primaryExchange  # Use primary exchange for orders
            
                # Create a separate contract for market data that uses SMART routing
                market_contract = Contract()
                market_contract.symbol = contract.symbol
                market_contract.secType = contract.secType
                market_contract.currency = contract.currency
                market_contract.exchange = 'SMART'
                market_contract.primaryExchange = contract.primaryExchange
                
                #Time of day condition for after hours trading
                if not is_after_hours:
                    order = MarketOrder(
                    action=action,
                    totalQuantity=quantity,
                    tif='GTC'
                )
                else:
            
                    # Get recent price data using SMART routing
                    bars =self.ib.reqHistoricalData(
                        contract=market_contract,
                        endDateTime='',
                        durationStr='60 S',
                        barSizeSetting='1 min',
                        whatToShow='TRADES',
                        useRTH=False,
                        formatDate=1
                    )
            
                    if not bars or len(bars) == 0:
                        print(f"Warning: No historical data for {contract.symbol}, using market price")
                        last_price = item.marketPrice
                        
                    else:
                        last_price = bars[-1].close
                  
                
                        # Set limit price with offset
                        offset = 0.01
                        limit_price = (last_price + offset if action == 'BUY' 
                                    else last_price - offset)
                    
                        # Create limit order
                        order = LimitOrder(
                            action=action,
                            totalQuantity=quantity,
                            lmtPrice=round(limit_price, 2),
                            tif='GTC',  # Good Till Canceled
                            outsideRth=True  # Allow trading outside regular trading hours
                        )
             
                    
                    
            
                # Place the order
                trade =self.ib.placeOrder(contract, order)
                trades.append(trade)
            
                print(f"Placed order to close {contract.symbol}: "
                      f"{action} {quantity} @ {limit_price:.2f}")
            
            except Exception as e:
                print(f"Error closing position for {item.contract.symbol}: {str(e)}")
    
        return trades
    def on_pnl_update(self, pnl: PnL):
        """Handle PnL updates from IB"""
        try:
            # Convert PnL values to float to ensure they're numeric
            self.daily_pnl = float(pnl.dailyPnL) if pnl.dailyPnL is not None else 0.0
            self.total_unrealized_pnl = float(pnl.unrealizedPnL) if pnl.unrealizedPnL is not None else 0.0
            self.total_realized_pnl = float(pnl.realizedPnL) if pnl.realizedPnL is not None else 0.0
            
            self.logger.info(f"""
PnL Update:
- Daily P&L: ${self.daily_pnl:,.2f}
- Unrealized P&L: ${self.total_unrealized_pnl:,.2f}
- Realized P&L: ${self.total_realized_pnl:,.2f}
- Current Net Liquidation: ${self.get_net_liquidation():,.2f}
""")
            
            # Check PnL conditions and get positions if needed
            if self.check_pnl_conditions(self.pnl):
                positions = [pos for pos in self.ib.positions() if pos.position != 0]
                existing_trades = self.ib.trades()
                
                # Check if all positions have pending orders
                self.all_have_orders = all(
                    any(
                        trade.contract.conId == position.contract.conId and 
                        trade.orderStatus.status not in ['Filled', 'Cancelled', 'Inactive', 'Submitted']
                        for trade in existing_trades
                    )
                    for position in positions
                )
                
                if not self.all_have_orders:
                    self.logger.info("Some positions don't have pending orders - action required")
                    
                    
                else:
                    self.ib.sleep(1)
                    self.logger.info("Waiting..ok, so chill..")   
                    
                    self.logger.info("All positions already have pending orders")
                    self.ib.loopUntil(self.all_have_orders, timeout=5)
                if self.all_have_orders:
                    self.ib.disconnect()
                    self.logger.info("Disconnected from IB Gateway...bitch....")
                   
        except Exception as e:
            self.logger.error(f"Error processing PnL update: {str(e)}")

    def onConnected(self):
        self.logger.info("Connected to IB Gateway.")
        # Request account summary when connected
        self.request_account_summary()

    def run(self):
        """Start the event loop"""
        trades = []
        try:
            self.logger.info("Starting IB event loop...")
           
            while True:
                self.ib.sleep(1)
                if self.should_close_positions:
                    self.logger.info("Initiating position closing...")
                    trades = self.close_all_positions()
                    self.should_close_positions = False  # Reset flag
                            
                            
            
                
                   
                    self.ib.sleep(1)
                   
                                                                    
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        #finally:
            #self.ib.disconnect()

if __name__ == "__main__":
    portfolio_tracker = IBPortfolioTracker()
    portfolio_tracker.run()
    

   