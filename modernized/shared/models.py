"""Shared Pydantic models for the modernized trade processing pipeline."""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class BrokerCode(str, enum.Enum):
    GOLDMN = "GOLDMN"
    MRGST = "MRGST"
    JPMC = "JPMC"
    BARCL = "BARCL"
    CITI = "CITI"
    UBS = "UBS"


VALID_BROKERS = [b.value for b in BrokerCode]


class Trade(BaseModel):
    """Represents a single trade from the daily CSV file."""

    trade_id: str
    account: str
    ticker: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    trade_date: date
    settle_date: Optional[date] = None
    broker: BrokerCode
    commission: float
    status: str

    @field_validator("trade_date", "settle_date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(v, fmt).date()
                except ValueError:
                    continue
            raise ValueError(f"Cannot parse date: {v}")
        return v


class EnrichedTrade(BaseModel):
    """Trade with computed amounts and reconciliation status."""

    trade_id: str
    account: str
    ticker: str
    side: Literal["BUY", "SELL"]
    quantity: int
    price: float
    gross_amount: float
    net_amount: float
    commission: float
    trade_date: date
    settle_date: Optional[date] = None
    broker: str
    status: str
    recon_status: str = "UNMATCHED"
    processed_at: Optional[datetime] = None


class CounterpartyConfirm(BaseModel):
    """Represents a counterparty confirmation from the fixed-width .dat file."""

    trade_id: str
    account: str
    ticker: str
    side: str
    quantity: int
    price: float
    currency: str
    trade_date: date
    status: str
    broker: str

    @field_validator("trade_date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            for fmt in ("%m/%d/%Y", "%m%d%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(v, fmt).date()
                except ValueError:
                    continue
            raise ValueError(f"Cannot parse date: {v}")
        return v


class ReconStatus(str, enum.Enum):
    MATCHED = "MATCHED"
    PRICE_BREAK = "PRICE_BREAK"
    QTY_BREAK = "QTY_BREAK"
    UNMATCHED = "UNMATCHED"


class ReconResult(BaseModel):
    """Result of reconciling a trade with a counterparty confirmation."""

    trade: Trade
    confirm: Optional[CounterpartyConfirm] = None
    recon_status: ReconStatus
