"""SQLite-backed trade store for event-driven pipeline.

Demonstrates DB-level idempotency (upsert on trade_id) vs the
in-memory processed_ids list in the legacy code.
"""

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    text,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class TradeRecord(Base):
    """SQLAlchemy model for persisted trade records."""

    __tablename__ = "trades"

    trade_id = Column(String, primary_key=True)
    account_number = Column(String, nullable=False)
    ticker = Column(String, nullable=False)
    side = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    gross_amount = Column(Float)
    net_amount = Column(Float)
    commission = Column(Float)
    trade_date = Column(String)
    settle_date = Column(String)
    broker = Column(String)
    status = Column(String)
    recon_status = Column(String, default="PENDING")
    processed_at = Column(DateTime, default=datetime.utcnow)


class TradeStore:
    """SQLite-backed trade store with upsert support."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path(__file__).resolve().parent / "trades.db"
        self.db_path = Path(db_path)
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(bind=self.engine)
        logger.info("TradeStore initialized at %s", self.db_path)

    def upsert_trades(self, trades_data: list[dict]) -> tuple[int, int]:
        """Upsert trades into the store. Returns (inserted, updated) counts."""
        inserted = 0
        updated = 0
        with self._Session() as session:
            for trade in trades_data:
                existing = session.get(TradeRecord, trade["trade_id"])
                if existing:
                    for key, value in trade.items():
                        if key != "trade_id":
                            setattr(existing, key, value)
                    updated += 1
                else:
                    record = TradeRecord(**trade)
                    session.add(record)
                    inserted += 1
            session.commit()
        logger.info("Upserted trades: %d inserted, %d updated", inserted, updated)
        return inserted, updated

    def get_pending_trades(self) -> list[dict]:
        """Get trades pending reconciliation."""
        with self._Session() as session:
            records = (
                session.query(TradeRecord)
                .filter(TradeRecord.recon_status == "PENDING")
                .all()
            )
            return [
                {
                    "trade_id": r.trade_id,
                    "account_number": r.account_number,
                    "ticker": r.ticker,
                    "side": r.side,
                    "quantity": r.quantity,
                    "price": r.price,
                    "gross_amount": r.gross_amount,
                    "net_amount": r.net_amount,
                    "commission": r.commission,
                    "trade_date": r.trade_date,
                    "settle_date": r.settle_date,
                    "broker": r.broker,
                    "status": r.status,
                    "recon_status": r.recon_status,
                }
                for r in records
            ]

    def update_recon_status(self, trade_id: str, recon_status: str) -> None:
        """Update reconciliation status for a trade."""
        with self._Session() as session:
            record = session.get(TradeRecord, trade_id)
            if record:
                record.recon_status = recon_status
                session.commit()

    def get_all_trades(self) -> list[dict]:
        """Get all trades from the store."""
        with self._Session() as session:
            records = session.query(TradeRecord).all()
            return [
                {
                    "trade_id": r.trade_id,
                    "account_number": r.account_number,
                    "ticker": r.ticker,
                    "side": r.side,
                    "quantity": r.quantity,
                    "price": r.price,
                    "gross_amount": r.gross_amount,
                    "net_amount": r.net_amount,
                    "commission": r.commission,
                    "trade_date": r.trade_date,
                    "settle_date": r.settle_date,
                    "broker": r.broker,
                    "status": r.status,
                    "recon_status": r.recon_status,
                    "processed_at": str(r.processed_at) if r.processed_at else None,
                }
                for r in records
            ]

    def clear(self) -> None:
        """Clear all records (for testing/demo)."""
        with self._Session() as session:
            session.execute(text("DELETE FROM trades"))
            session.commit()
        logger.info("Cleared all trades from store")
