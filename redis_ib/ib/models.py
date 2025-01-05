from pydantic import BaseModel
from typing import List, Optional

class Channel(BaseModel):
    title: str
    link: str
    copyright: str
    pubDate: str
    ttl: str
    numItems: str

class Item(BaseModel):
    title: str
    pubDate: str
    IssueSymbol: str
    IssueName: str
    Mkt: str
    ReasonCode: str
    HaltDate: str
    HaltTime: str
    ResumptionDate: str
    ResumptionQuoteTime: str
    ResumptionTradeTime: str
    PauseThresholdPrice: Optional[str] = ""  # sometimes empty

class HaltedData(BaseModel):
    channel: Channel
    items: List[Item]
