"""Pydantic v2 models shared across the modernization prototypes.

These models replace the ad-hoc ``dict`` records used by the legacy
``legacy_scripts/process_trades.py`` script. They give us:

* Explicit, typed fields instead of positional CSV indexing.
* Declarative validation (quantity/price > 0, side restricted to BUY/SELL).
* A single source of truth that all three options validate against.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ReconStatus = Literal["MATCHED", "PRICE_BREAK", "QTY_BREAK", "UNMATCHED"]


class RawTrade(BaseModel):
    """A single internal trade as read from a ``daily_trades_*.csv`` file."""

    trade_id: str
    account: str
    ticker: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0, description="Number of shares; must be positive.")
    price: float = Field(gt=0, description="Execution price; must be positive.")
    trade_date: date
    settle_date: Optional[date] = None
    broker: str
    commission: float = Field(ge=0)
    status: str

    @field_validator("trade_id", "account", "ticker", "broker", "status", "side")
    @classmethod
    def _strip_whitespace(cls, value: str) -> str:
        """Trim surrounding whitespace from string fields."""
        return value.strip()


class CounterpartyConfirm(BaseModel):
    """A broker trade confirmation parsed from the fixed-width ``.dat`` file."""

    trade_id: str
    account: str
    ticker: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    currency: str
    date: date
    status: str

    @field_validator(
        "trade_id", "account", "ticker", "currency", "status", "side"
    )
    @classmethod
    def _strip_whitespace(cls, value: str) -> str:
        """Trim surrounding whitespace from string fields."""
        return value.strip()


class ReconResult(BaseModel):
    """Outcome of reconciling one internal trade against a broker confirm."""

    trade_id: str
    recon_status: ReconStatus
    internal_price: Optional[float] = None
    confirm_price: Optional[float] = None
    internal_qty: Optional[int] = None
    confirm_qty: Optional[int] = None


class ProcessingResult(BaseModel):
    """Summary statistics for a single trade-processing run.

    All three options return one of these so their outputs can be compared
    directly against each other (and against the legacy script).
    """

    total_loaded: int = 0
    duplicates_removed: int = 0
    validation_errors: int = 0
    matched: int = 0
    breaks: int = 0
    unmatched: int = 0
