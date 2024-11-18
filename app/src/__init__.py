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
from db import (
    SessionLocal, 
    Position as DBPosition,  # Rename the SQLAlchemy model import
    PnLData,
    Trade,
    Order
)


