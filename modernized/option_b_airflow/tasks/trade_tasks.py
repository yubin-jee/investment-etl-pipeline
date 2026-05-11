"""Airflow task implementations wrapping the shared modules.

Each function is designed to be called by an Airflow PythonOperator but is
also fully testable standalone — no Airflow runtime required.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from modernized.shared.db import TradeRecord, get_session, init_db
from modernized.shared.models import (
    CounterpartyConfirm,
    EnrichedTrade,
    ReconStatus,
    Trade,
)
from modernized.shared.parsers import parse_counterparty_dat, parse_trade_csv
from modernized.shared.reconciler import reconcile
from modernized.shared.validators import validate_trades

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_trades(trade_date: str, trade_dir: Optional[str] = None, **kwargs: Any) -> List[Dict]:
    """Task 1: Load trades from CSV. Returns serialisable list of dicts."""
    trade_dir = Path(
        trade_dir or os.environ.get("TRADE_DIR", str(PROJECT_ROOT / "legacy_data" / "trades"))
    )
    trade_file = trade_dir / f"daily_trades_{trade_date}.csv"
    trades = parse_trade_csv(trade_file)
    logger.info("Loaded %d trades for %s", len(trades), trade_date)
    return [t.model_dump(mode="json") for t in trades]


def validate_trades_task(
    trade_dicts: List[Dict], **kwargs: Any
) -> Tuple[List[Dict], List[Dict]]:
    """Task 2: Validate trades. Returns (valid_trade_dicts, error_dicts)."""
    trades = [Trade.model_validate(d) for d in trade_dicts]
    valid, errors = validate_trades(trades)
    logger.info("Validated: %d valid, %d errors", len(valid), len(errors))
    return [t.model_dump(mode="json") for t in valid], errors


def calculate_amounts_task(trade_dicts: List[Dict], **kwargs: Any) -> List[Dict]:
    """Task 3: Compute gross_amount and net_amount (vectorized via pandas)."""
    df = pd.DataFrame(trade_dicts)
    df["broker"] = df["broker"].apply(lambda b: b.value if hasattr(b, "value") else b)
    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)
    df["net_amount"] = df["gross_amount"] + df["commission"]
    sell_mask = df["side"] == "SELL"
    df.loc[sell_mask, "net_amount"] = (
        df.loc[sell_mask, "gross_amount"] - df.loc[sell_mask, "commission"]
    )
    df["net_amount"] = df["net_amount"].round(2)
    logger.info("Calculated amounts for %d trades", len(df))
    return df.to_dict(orient="records")


def parse_confirms_task(
    trade_date: str, trade_dir: Optional[str] = None, **kwargs: Any
) -> List[Dict]:
    """Task 4: Parse counterparty confirmation file."""
    trade_dir = Path(
        trade_dir or os.environ.get("TRADE_DIR", str(PROJECT_ROOT / "legacy_data" / "trades"))
    )
    confirm_file = trade_dir / "counterparty_confirms.dat"
    if not confirm_file.exists():
        logger.warning("Counterparty file not found: %s", confirm_file)
        return []
    confirms = parse_counterparty_dat(confirm_file)
    logger.info("Parsed %d confirms", len(confirms))
    return [c.model_dump(mode="json") for c in confirms]


def reconcile_task(
    trade_dicts: List[Dict], confirm_dicts: List[Dict], **kwargs: Any
) -> List[Dict]:
    """Task 5: Reconcile trades with confirms."""
    trades = [Trade.model_validate(d) for d in trade_dicts]
    confirms = [CounterpartyConfirm.model_validate(d) for d in confirm_dicts]
    results = reconcile(trades, confirms)

    enriched = []
    for r in results:
        d = r.trade.model_dump(mode="json")
        d["recon_status"] = r.recon_status.value
        enriched.append(d)
    logger.info("Reconciled %d trades", len(enriched))
    return enriched


def write_to_db_task(
    trade_dicts: List[Dict],
    db_conn: Optional[str] = None,
    **kwargs: Any,
) -> int:
    """Task 6: Upsert trades into the database. Returns count written."""
    conn = db_conn or os.environ.get("DB_CONNECTION_STRING")
    if not conn:
        logger.info("No DB_CONNECTION_STRING — skipping DB write")
        return 0

    init_db(conn)
    session = get_session(conn)
    now = datetime.now(timezone.utc)

    try:
        for d in trade_dicts:
            record = TradeRecord(
                trade_id=d["trade_id"],
                account_number=d["account"],
                ticker=d["ticker"],
                side=d["side"],
                quantity=int(d["quantity"]),
                price=float(d["price"]),
                gross_amount=float(d.get("gross_amount", 0)),
                net_amount=float(d.get("net_amount", 0)),
                commission=float(d["commission"]),
                trade_date=d["trade_date"],
                settle_date=d.get("settle_date"),
                broker=d.get("broker", ""),
                status=d.get("status", ""),
                recon_status=d.get("recon_status", "UNMATCHED"),
                processed_at=now,
            )
            session.merge(record)
        session.commit()
        logger.info("Persisted %d records to database", len(trade_dicts))
        return len(trade_dicts)
    except Exception:
        session.rollback()
        logger.exception("Database write failed")
        raise
    finally:
        session.close()


def write_output_csv_task(
    trade_dicts: List[Dict],
    trade_date: str,
    output_dir: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Write enriched trades to an output CSV. Returns the output path."""
    output_dir = Path(
        output_dir or os.environ.get("OUTPUT_DIR", str(PROJECT_ROOT / "reports"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"processed_trades_{trade_date}.csv"

    df = pd.DataFrame(trade_dicts)
    df["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    columns = [
        "trade_id", "account", "ticker", "side", "quantity", "price",
        "gross_amount", "net_amount", "commission", "trade_date",
        "settle_date", "broker", "status", "recon_status", "processed_at",
    ]
    out = df[[c for c in columns if c in df.columns]]
    out.columns = [c.upper() for c in out.columns]
    out.to_csv(output_file, index=False)
    logger.info("Wrote %d trades to %s", len(out), output_file)
    return str(output_file)


def run_pipeline(
    trade_date: str,
    trade_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    db_conn: Optional[str] = None,
) -> pd.DataFrame:
    """Run the full Airflow-style pipeline without Airflow (for comparison)."""
    start = time.perf_counter()
    logger.info("=== Option B (Airflow DAG) — Processing %s ===", trade_date)

    raw = load_trades(trade_date, trade_dir)
    valid, errors = validate_trades_task(raw)
    enriched = calculate_amounts_task(valid)
    confirms = parse_confirms_task(trade_date, trade_dir)
    reconciled = reconcile_task(enriched, confirms)
    write_output_csv_task(reconciled, trade_date, output_dir)

    if db_conn or os.environ.get("DB_CONNECTION_STRING"):
        write_to_db_task(reconciled, db_conn)

    elapsed = time.perf_counter() - start
    logger.info("=== Option B complete in %.3f seconds ===", elapsed)
    return pd.DataFrame(reconciled)
