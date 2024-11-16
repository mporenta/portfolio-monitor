from ib_async import *

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=29)


stock = Stock('AMZN', 'SMART', 'USD')

order = MarketOrder('SELL', 10)

trade = ib.placeOrder(stock, order)

print(trade)

def orderFilled(trade, fill):
    print("order has been filled")
    print(trade)
    print(fill)

trade.fillEvent += orderFilled

ib.sleep(3)

for trade in ib.trades():
    print("== this is one of my trades =")
    print(trade)

for order in ib.orders():
    print("== this is one of my orders ==")
    print(order)

ib.run()