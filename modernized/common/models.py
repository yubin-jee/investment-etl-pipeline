"""Pydantic v2 models for trade processing domain objects."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RawTrade(BaseModel):
    """A single trade row as parsed from the daily CSV file."""

    trade_id: str
    account: str
    ticker: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    trade_date: date
    settle_date: Optional[date] = None
    broker: str
    commission: float
    status: str

    @field_validator("side", mode="before")
    @classmethod
    def normalize_side(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("broker", mode="before")
    @classmethod
    def normalize_broker(cls, v: str) -> str:
        return v.strip().upper()


class CounterpartyConfirm(BaseModel):
    """A single record from a fixed-width counterparty confirmation file."""

    trade_id: str
    account: str
    ticker: str
    side: str
    quantity: int
    price: float
    currency: str
    date: date
    status: str


class ReconResult(BaseModel):
    """Result of reconciling one trade against counterparty confirmations."""

    trade_id: str
    recon_status: Literal["MATCHED", "PRICE_BREAK", "QTY_BREAK", "UNMATCHED"]
    internal_price: float
    confirm_price: Optional[float] = None
    internal_qty: int
    confirm_qty: Optional[int] = None


class ProcessingResult(BaseModel):
    """Summary statistics for a trade processing run."""

    total_loaded: int = 0
    duplicates_removed: int = 0
    validation_errors: int = 0
    matched: int = 0
    breaks: int = 0
    unmatched: int = 0
