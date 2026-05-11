"""Option A: pandas + SQLAlchemy — Minimal-lift modernization.

Replaces legacy_scripts/process_trades.py with:
  - pandas DataFrames for vectorized operations
  - Pydantic models for validation
  - SQLAlchemy for database persistence
  - Structured logging instead of print()
  - Environment-variable config instead of hardcoded paths

Usage:
    python -m modernized.option_a_pandas.process_trades --date 20240315
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
from dotenv import load_dotenv

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from modernized.shared.db import TradeRecord, get_session, init_db
from modernized.shared.models import EnrichedTrade, ReconStatus, Trade
from modernized.shared.parsers import parse_counterparty_dat, parse_trade_csv
from modernized.shared.reconciler import reconcile
from modernized.shared.validators import validate_trades

load_dotenv()

logger = logging.getLogger(__name__)


def _configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _trades_to_dataframe(trades: List[Trade]) -> pd.DataFrame:
    """Convert validated Trade models into a DataFrame for vectorized ops."""
    records = [t.model_dump() for t in trades]
    df = pd.DataFrame(records)
    df["broker"] = df["broker"].apply(lambda b: b.value if hasattr(b, "value") else b)
    return df


def calculate_amounts(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized gross/net amount calculation."""
    df = df.copy()
    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)
    df["net_amount"] = df["gross_amount"] + df["commission"]
    sell_mask = df["side"] == "SELL"
    df.loc[sell_mask, "net_amount"] = (
        df.loc[sell_mask, "gross_amount"] - df.loc[sell_mask, "commission"]
    )
    df["net_amount"] = df["net_amount"].round(2)
    return df


def apply_recon_results(df: pd.DataFrame, recon_results: list) -> pd.DataFrame:
    """Merge reconciliation statuses back into the trade DataFrame."""
    recon_map = {r.trade.trade_id: r.recon_status.value for r in recon_results}
    df = df.copy()
    df["recon_status"] = df["trade_id"].map(recon_map).fillna(ReconStatus.UNMATCHED.value)
    return df


def write_output_csv(df: pd.DataFrame, output_path: Path) -> None:
    """Write processed trades to an output CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df = df.copy()
    df["processed_at"] = now

    columns = [
        "trade_id", "account", "ticker", "side", "quantity", "price",
        "gross_amount", "net_amount", "commission", "trade_date",
        "settle_date", "broker", "status", "recon_status", "processed_at",
    ]
    out = df[[c for c in columns if c in df.columns]]
    out.columns = [c.upper() for c in out.columns]
    out.to_csv(output_path, index=False)
    logger.info("Wrote %d trades to %s", len(out), output_path)


def write_to_db(df: pd.DataFrame, connection_string: Optional[str] = None) -> None:
    """Persist trades to the database via SQLAlchemy."""
    init_db(connection_string)
    session = get_session(connection_string)
    now = datetime.utcnow()

    try:
        for _, row in df.iterrows():
            record = TradeRecord(
                trade_id=row["trade_id"],
                account_number=row["account"],
                ticker=row["ticker"],
                side=row["side"],
                quantity=int(row["quantity"]),
                price=float(row["price"]),
                gross_amount=float(row.get("gross_amount", 0)),
                net_amount=float(row.get("net_amount", 0)),
                commission=float(row["commission"]),
                trade_date=row["trade_date"],
                settle_date=row.get("settle_date"),
                broker=row["broker"],
                status=row["status"],
                recon_status=row.get("recon_status", "UNMATCHED"),
                processed_at=now,
            )
            session.merge(record)  # upsert
        session.commit()
        logger.info("Persisted %d records to database", len(df))
    except Exception:
        session.rollback()
        logger.exception("Database write failed")
        raise
    finally:
        session.close()


def run(
    trade_date: str,
    trade_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    db_conn: Optional[str] = None,
) -> pd.DataFrame:
    """Execute the full trade processing pipeline. Returns the enriched DataFrame."""
    start = time.perf_counter()
    trade_dir = Path(trade_dir or os.environ.get("TRADE_DIR", str(PROJECT_ROOT / "legacy_data" / "trades")))
    output_dir = Path(output_dir or os.environ.get("OUTPUT_DIR", str(PROJECT_ROOT / "reports")))

    trade_file = trade_dir / f"daily_trades_{trade_date}.csv"
    confirm_file = trade_dir / "counterparty_confirms.dat"

    logger.info("=== Option A (pandas + SQLAlchemy) — Processing %s ===", trade_date)

    # Step 1: Parse
    trades = parse_trade_csv(trade_file)
    logger.info("Step 1: Loaded %d raw trades", len(trades))

    # Step 2: Validate
    valid_trades, errors = validate_trades(trades)
    logger.info("Step 2: %d valid, %d errors", len(valid_trades), len(errors))

    # Step 3: Calculate amounts (vectorized)
    df = _trades_to_dataframe(valid_trades)
    df = calculate_amounts(df)
    logger.info("Step 3: Computed amounts for %d trades", len(df))

    # Step 4 & 5: Parse confirms & reconcile
    if confirm_file.exists():
        confirms = parse_counterparty_dat(confirm_file)
        recon_results = reconcile(valid_trades, confirms)
        df = apply_recon_results(df, recon_results)
        logger.info("Steps 4-5: Reconciled %d trades", len(df))
    else:
        logger.warning("Counterparty file not found, skipping reconciliation")
        df["recon_status"] = ReconStatus.UNMATCHED.value

    # Step 6: Write output
    output_file = output_dir / f"processed_trades_{trade_date}.csv"
    write_output_csv(df, output_file)

    # Optional: DB write
    if db_conn or os.environ.get("DB_CONNECTION_STRING"):
        write_to_db(df, db_conn)

    elapsed = time.perf_counter() - start
    logger.info("=== Option A complete in %.3f seconds ===", elapsed)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Option A: pandas trade processor")
    parser.add_argument("--date", required=True, help="Trade date YYYYMMDD")
    parser.add_argument("--trade-dir", help="Trade input directory")
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    _configure_logging(args.log_level)
    run(args.date, args.trade_dir, args.output_dir)


if __name__ == "__main__":
    main()
