
from ib_async import *

ib = IB()
symbol = None

ib.connect('ib-gateway', 4002, clientId=71)
# use this instead for IB Gateway
# ib.connect('127.0.0.1', 7497, clientId=1)
def run():
    portfolio_items = ib.portfolio('DU7397764')
    for item in portfolio_items:
        symbol = item.contract.symbol
        exchange = item.contract.exchange
        currency = item.contract.currency
        print("jengo item: ", type(item))
        print(item)
    
    # us this for TWS (Workstation)
    

        stock = Stock(symbol, exchange, currency)

        bars = ib.reqHistoricalData(
            stock, endDateTime='', durationStr='30 D',
            barSizeSetting='1 hour', whatToShow='MIDPOINT', useRTH=True)

        # convert to pandas dataframe
        df = util.df(bars)
        print(df)

        market_data = ib.reqMktData(stock, '', False, False)

def onPendingTicker(ticker):
    print("pending ticker event received")
    print(ticker)

ib.pendingTickersEvent += onPendingTicker

if __name__ == '__main__':


    ib.run()