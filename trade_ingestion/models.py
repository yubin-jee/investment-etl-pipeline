"""Pydantic data models for trade and confirmation records."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

VALID_BROKERS: list[str] = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]


class Trade(BaseModel):
    """Validated trade record — replaces ad-hoc dict validation in legacy
    ``validate_trades()`` (process_trades.py lines 60-110)."""

    trade_id: str
    account: str
    ticker: str
    side: Literal["BUY", "SELL"]
    quantity: int
    price: float
    trade_date: date
    settle_date: Optional[date] = None
    broker: str
    commission: float
    status: str
    recon_status: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"quantity must be positive, got {v}")
        return v

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"price must be positive, got {v}")
        return v

    @field_validator("broker")
    @classmethod
    def broker_must_be_valid(cls, v: str) -> str:
        if v not in VALID_BROKERS:
            raise ValueError(f"invalid broker '{v}', must be one of {VALID_BROKERS}")
        return v

    @field_validator("trade_date", mode="before")
    @classmethod
    def coerce_trade_date(cls, v: object) -> object:
        if isinstance(v, str):
            for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                try:
                    from datetime import datetime as _dt

                    return _dt.strptime(v, fmt).date()
                except ValueError:
                    continue
        return v

    @field_validator("settle_date", mode="before")
    @classmethod
    def coerce_settle_date(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        try:
            import math

            if isinstance(v, float) and math.isnan(v):
                return None
        except (TypeError, ValueError):
            pass
        if isinstance(v, str):
            for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                try:
                    from datetime import datetime as _dt

                    return _dt.strptime(v, fmt).date()
                except ValueError:
                    continue
        return v


class Confirmation(BaseModel):
    """Counterparty confirmation record parsed from fixed-width .dat files."""

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
    def coerce_trade_date(cls, v: object) -> object:
        if isinstance(v, str):
            for fmt in ("%m/%d/%Y", "%m%d%Y", "%Y-%m-%d"):
                try:
                    from datetime import datetime as _dt

                    return _dt.strptime(v, fmt).date()
                except ValueError:
                    continue
        return v
