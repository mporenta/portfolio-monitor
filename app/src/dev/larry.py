from math import log
from ib_async import *
from ib_async.util import logToConsole
import logging


util.logToConsole(level=logging.INFO)
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=11)
lmtPrice = 175.00

stock = Stock('GOOGL', 'SMART', 'USD')
action = 'BUY'
totalQuantity = 10
order = LimitOrder(action, totalQuantity, lmtPrice)
account = ""
trade = ib.trades()
logging.info(f"my trade jengo {trade}")
portfolio_items = ib.portfolio(account)
print(f"my port jengo {portfolio_items}")





ib.sleep(3)

for trade in portfolio_items:
    print("== jengo this is one of my trades =")
    #logging.info(portfolio_items)
  



ib.run()