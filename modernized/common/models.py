"""Pydantic v2 models for trade processing data structures.

Defines validated models for raw trades, counterparty confirmations,
reconciliation results, and processing summaries.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RawTrade(BaseModel):
    """A single trade record from the daily CSV file."""

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

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()


class CounterpartyConfirm(BaseModel):
    """A single counterparty confirmation from a fixed-width .dat file."""

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

    total_loaded: int
    duplicates_removed: int
    validation_errors: int
    matched: int
    breaks: int
    unmatched: int
