"""SQLAlchemy ORM model and database helpers.

Provides the ``Trades`` table using proper Python/SQL types (``Date``,
``Integer``, ``Numeric``) and an idempotent ``upsert_trades()`` function.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    create_engine,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base

from trade_ingestion.config import get_db_connection_string

logger = logging.getLogger(__name__)

Base = declarative_base()


class TradeRecord(Base):  # type: ignore[misc]
    """ORM mapping for the ``dbo.Trades`` table with proper column types."""

    __tablename__ = "Trades"
    __table_args__ = {"schema": "dbo"}

    TradeID = Column(String(30), primary_key=True)
    AccountNumber = Column(String(20), nullable=False)
    Ticker = Column(String(10), nullable=False)
    Side = Column(String(4), nullable=False)
    Quantity = Column(Integer, nullable=False)
    Price = Column(Numeric(18, 4), nullable=False)
    GrossAmount = Column(Numeric(18, 2))
    NetAmount = Column(Numeric(18, 2))
    Commission = Column(Numeric(18, 2))
    TradeDate = Column(Date, nullable=False)
    SettleDate = Column(Date)
    Broker = Column(String(20))
    Status = Column(String(20))
    ReconStatus = Column(String(30))
    ProcessedAt = Column(DateTime, default=datetime.utcnow)
    CreatedDate = Column(DateTime, default=datetime.utcnow)


def get_engine() -> Engine:
    """Create a SQLAlchemy engine from config / environment."""
    url = get_db_connection_string()
    logger.info("Creating database engine for %s", url.split("@")[-1] if "@" in url else url)
    return create_engine(url)


def upsert_trades(df: pd.DataFrame, engine: Engine | None = None) -> int:
    """Insert trades that do not already exist (idempotent upsert).

    Uses ``INSERT … WHERE NOT EXISTS`` semantics via the ORM to avoid
    duplicate ``TradeID`` rows.

    Returns
    -------
    int
        Number of rows inserted.
    """
    if engine is None:
        engine = get_engine()

    inserted = 0
    with Session(engine) as session:
        for _, row in df.iterrows():
            trade_id = str(row.get("trade_id", ""))
            exists = (
                session.query(TradeRecord)
                .filter(TradeRecord.TradeID == trade_id)
                .first()
            )
            if exists is not None:
                logger.debug("Trade %s already exists, skipping", trade_id)
                continue

            def _to_date(val: object) -> date | None:
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return None
                if isinstance(val, date):
                    return val
                if isinstance(val, str) and val.strip():
                    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                        try:
                            return datetime.strptime(val, fmt).date()
                        except ValueError:
                            continue
                return None

            record = TradeRecord(
                TradeID=trade_id,
                AccountNumber=str(row.get("account", "")),
                Ticker=str(row.get("ticker", "")),
                Side=str(row.get("side", "")),
                Quantity=int(row["quantity"]) if pd.notna(row.get("quantity")) else 0,
                Price=Decimal(str(row["price"])) if pd.notna(row.get("price")) else Decimal("0"),
                GrossAmount=Decimal(str(row["gross_amount"])) if pd.notna(row.get("gross_amount")) else None,
                NetAmount=Decimal(str(row["net_amount"])) if pd.notna(row.get("net_amount")) else None,
                Commission=Decimal(str(row["commission"])) if pd.notna(row.get("commission")) else None,
                TradeDate=_to_date(row.get("trade_date")),
                SettleDate=_to_date(row.get("settle_date")),
                Broker=str(row.get("broker", "")),
                Status=str(row.get("status", "")),
                ReconStatus=str(row.get("recon_status", "")) if pd.notna(row.get("recon_status")) else None,
                ProcessedAt=datetime.utcnow(),
            )
            session.add(record)
            inserted += 1

        session.commit()

    logger.info("Upserted %d new trade records", inserted)
    return inserted
