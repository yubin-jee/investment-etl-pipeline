"""Pydantic models for trade processing pipeline."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator

from trade_processing.config import VALID_BROKERS


class Trade(BaseModel):
    """Internal trade record."""

    trade_id: str
    account_number: str
    ticker: str
    side: str
    quantity: int
    price: Decimal
    gross_amount: Optional[Decimal] = None
    net_amount: Optional[Decimal] = None
    commission: Decimal = Decimal("0")
    trade_date: date
    settle_date: Optional[date] = None
    broker: str
    status: str
    recon_status: Optional[str] = None
    processed_at: Optional[datetime] = None

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"quantity must be > 0, got {v}")
        return v

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError(f"price must be > 0, got {v}")
        return v

    @field_validator("broker")
    @classmethod
    def broker_must_be_valid(cls, v: str) -> str:
        if v not in VALID_BROKERS:
            raise ValueError(f"invalid broker '{v}', must be one of {VALID_BROKERS}")
        return v


class CounterpartyConfirm(BaseModel):
    """Counterparty trade confirmation record."""

    trade_id: str
    account: str
    ticker: str
    side: str
    quantity: int
    price: Decimal
    currency: str
    trade_date: date
    status: str


class ReconResult(BaseModel):
    """Result of reconciling a trade with its counterparty confirmation."""

    trade_id: str
    recon_status: str
    internal_price: Decimal
    confirm_price: Optional[Decimal] = None
    internal_qty: int
    confirm_qty: Optional[int] = None
