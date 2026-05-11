"""SQLAlchemy ORM model and session management for the Trades table.

Improves on the legacy schema (sql/create_tables.sql) by using proper DATE
columns instead of VARCHAR(10) for TradeDate and SettleDate, and adds a
primary key on TradeID.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, Numeric, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class TradeRecord(Base):
    """SQLAlchemy model matching dbo.Trades with modernized column types."""

    __tablename__ = "trades"
    __table_args__ = {"schema": "dbo"}

    trade_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    account_number: Mapped[str] = mapped_column("AccountNumber", String(20))
    ticker: Mapped[str] = mapped_column(String(10))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Numeric(18, 4))
    gross_amount: Mapped[Optional[float]] = mapped_column("GrossAmount", Numeric(18, 2), nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column("NetAmount", Numeric(18, 2), nullable=True)
    commission: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    trade_date: Mapped[date] = mapped_column("TradeDate", Date)
    settle_date: Mapped[Optional[date]] = mapped_column("SettleDate", Date, nullable=True)
    broker: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    recon_status: Mapped[Optional[str]] = mapped_column("ReconStatus", String(30), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column("ProcessedAt", DateTime, nullable=True)
    created_date: Mapped[Optional[datetime]] = mapped_column(
        "CreatedDate", DateTime, nullable=True, default=datetime.utcnow
    )


def get_engine(connection_string: Optional[str] = None):
    """Create a SQLAlchemy engine from a connection string or env var."""
    conn = connection_string or os.environ.get(
        "DB_CONNECTION_STRING", "sqlite:///trades.db"
    )
    return create_engine(conn, echo=False)


def get_session(connection_string: Optional[str] = None) -> Session:
    """Create a new SQLAlchemy session."""
    engine = get_engine(connection_string)
    factory = sessionmaker(bind=engine)
    return factory()


def init_db(connection_string: Optional[str] = None) -> None:
    """Create all tables (useful for SQLite / testing)."""
    engine = get_engine(connection_string)
    Base.metadata.create_all(engine)
