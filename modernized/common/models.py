"""Pydantic v2 models for the trade processing pipeline.

Defines structured models for trades, counterparty confirmations,
reconciliation results, and processing summaries.
"""

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

    @field_validator("trade_date", "settle_date", mode="before")
    @classmethod
    def parse_date_string(cls, v: object) -> object:
        """Parse MM/DD/YYYY date strings into date objects."""
        if isinstance(v, str) and v.strip():
            parts = v.strip().split("/")
            if len(parts) == 3:
                return date(int(parts[2]), int(parts[0]), int(parts[1]))
        if v == "" or v is None:
            return None
        return v


class CounterpartyConfirm(BaseModel):
    """A trade confirmation record from fixed-width counterparty files."""

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
    """Result of reconciling a single trade against counterparty data."""

    trade_id: str
    recon_status: Literal["MATCHED", "PRICE_BREAK", "QTY_BREAK", "UNMATCHED"]
    internal_price: float
    confirm_price: Optional[float] = None
    internal_qty: int
    confirm_qty: Optional[int] = None


class ProcessingResult(BaseModel):
    """Summary statistics from a trade processing run."""

    total_loaded: int
    duplicates_removed: int
    validation_errors: int
    matched: int
    breaks: int
    unmatched: int
