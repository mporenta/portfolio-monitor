# -*- coding: utf-8 -*-
"""__init__.py"""
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Union, Any
from sqlalchemy.orm import Session
# Import SQLAlchemy models with different names to avoid conflicts
from src.db import (
    SessionLocal, 
    Position as DBPosition,  # Rename the SQLAlchemy model import
    PnLData,
    Trade,
    Order
)


from dotenv import load_dotenv
from ib_async import Contract, PortfolioItem, IB
import logging
import signal
import requests
import asyncio
import os
from src.db import init_db, fetch_latest_pnl_data, fetch_latest_positions_data, fetch_latest_trades_data
from dev3 import IBClient
from fastapi.middleware.cors import CORSMiddleware
