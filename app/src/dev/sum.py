from math import log
from ib_async import *
from ib_async.util import logToConsole
import logging
import os

util.logToConsole(level=logging.INFO)
ib = IB()
ib.connect('ib-gateway', 4002, clientId=11)
lmtPrice = 3.19

contract = Stock('RGTI', 'SMART', 'USD')
action = 'BUY'
totalQuantity = 100
order = LimitOrder(action, totalQuantity, lmtPrice)
account = ""
trade = ib.trades()
logging.info(f"my trade jengo {trade}")
portfolio_items = ib.portfolio(account)
print(f"my port jengo {portfolio_items}")


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
def on_pnl_update(pnl: PnL):
        """Handle PnL updates and check conditions."""
        try:
            # Update PnL values
            daily_pnl = float(pnl.dailyPnL or 0.0)
            total_unrealized_pnl = float(pnl.unrealizedPnL or 0.0)
            total_realized_pnl = float(pnl.realizedPnL or 0.0)
            
            logger.debug(f"Daily PnL: ${daily_pnl:,.2f}, Net Liquidation: ${net_liquidation:,.2f}")

            # Update portfolio items
            portfolio_items = ib.portfolio(account)
            
            # Process trades and orders
            trades = ib.trades()
            orders = ib.openOrders()
        except Exception as e:
            logger.error(f"Error in PnL update handler: {str(e)}")
        

trade=ib.placeOrder(contract, order)
ib.pnlEvent += on_pnl_update
ib.sleep(3)

for port in portfolio_items:
    print("== jengo this is one of my trades =")
    #logging.info(portfolio_items)
  


for trade in ib.trades():
    print("== this is one of my trades =")
    print(trade)

for order in ib.orders():
    print("== this is one of my orders ==")
    print(order)

for pnl in ib.pnl():
    print("== this is my pnl ==")
    print(pnl)
ib.run()