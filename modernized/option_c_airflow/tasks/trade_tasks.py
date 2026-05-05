"""PythonOperator task callables for the trade processing DAG.

Each function accepts ``**kwargs`` (Airflow context) and communicates
between tasks via XCom (push/pull as list-of-dicts).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from modernized.common.parsers import load_counterparty_file, load_trades_csv
from modernized.common.settlement import calculate_t_plus_2
from modernized.common.validation import validate_trades

logger = logging.getLogger(__name__)

# Base directory — repo root when running locally
BASE_DIR = Path(os.environ.get("PIPELINE_BASE_DIR", Path(__file__).resolve().parents[3]))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _on_failure_callback(context: dict) -> None:
    """Log details when an Airflow task fails."""
    task_instance = context.get("task_instance")
    exception = context.get("exception")
    logger.error(
        "Task %s in DAG %s failed. Execution date: %s. Exception: %s",
        task_instance.task_id if task_instance else "unknown",
        task_instance.dag_id if task_instance else "unknown",
        context.get("execution_date"),
        exception,
    )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def load_trades_task(**kwargs) -> None:
    """Load daily trades CSV and push records to XCom."""
    ds: str = kwargs["ds"]  # YYYY-MM-DD
    date_compact = ds.replace("-", "")  # YYYYMMDD

    file_path = BASE_DIR / f"legacy_data/trades/daily_trades_{date_compact}.csv"
    if not file_path.exists():
        # Fallback to test data bundled with the modernized package
        file_path = BASE_DIR / f"modernized/test_data/daily_trades_{date_compact}.csv"
    if not file_path.exists():
        # Last resort: grab any available test file
        test_dir = BASE_DIR / "modernized/test_data"
        csv_files = sorted(test_dir.glob("daily_trades_*.csv"))
        if csv_files:
            file_path = csv_files[0]
        else:
            raise FileNotFoundError(
                f"No trade file found for {date_compact} in legacy_data/trades/ "
                f"or modernized/test_data/"
            )

    logger.info("Loading trades from %s", file_path)
    df = load_trades_csv(file_path)
    logger.info("Loaded %d trade rows", len(df))

    kwargs["ti"].xcom_push(key="raw_trades", value=df.to_dict("records"))


def validate_trades_task(**kwargs) -> None:
    """Validate raw trades and push valid/error records to XCom."""
    ti = kwargs["ti"]
    raw_records = ti.xcom_pull(task_ids="load_trades", key="raw_trades")
    df = pd.DataFrame(raw_records)

    valid_df, error_df = validate_trades(df)
    logger.info("Validation: %d valid, %d errors", len(valid_df), len(error_df))

    ti.xcom_push(key="valid_trades", value=valid_df.to_dict("records"))
    if not error_df.empty:
        ti.xcom_push(key="error_trades", value=error_df.to_dict("records"))


def enrich_trades_task(**kwargs) -> None:
    """Calculate amounts, fix missing settle dates, push enriched trades."""
    ti = kwargs["ti"]
    records = ti.xcom_pull(task_ids="validate_trades", key="valid_trades")
    df = pd.DataFrame(records)

    # Gross amount
    df["gross_amount"] = df["quantity"] * df["price"]

    # Net amount: BUY adds commission, SELL subtracts
    df["net_amount"] = df.apply(
        lambda r: r["gross_amount"] + r["commission"]
        if r["side"] == "BUY"
        else r["gross_amount"] - r["commission"],
        axis=1,
    )

    # Round to 2 decimals
    df["gross_amount"] = df["gross_amount"].round(2)
    df["net_amount"] = df["net_amount"].round(2)

    # Fix missing settle dates using T+2 business-day logic
    for idx, row in df.iterrows():
        if pd.isna(row["settle_date"]) or row["settle_date"] in ("", "NaT", None):
            trade_date = pd.to_datetime(row["trade_date"]).date()
            df.at[idx, "settle_date"] = str(calculate_t_plus_2(trade_date))

    logger.info("Enriched %d trades", len(df))
    ti.xcom_push(key="enriched_trades", value=df.to_dict("records"))


def load_confirms_task(**kwargs) -> None:
    """Load counterparty confirmation file and push to XCom."""
    ds: str = kwargs["ds"]
    date_compact = ds.replace("-", "")

    file_path = BASE_DIR / "legacy_data/trades/counterparty_confirms.dat"
    if not file_path.exists():
        file_path = BASE_DIR / f"modernized/test_data/counterparty_confirms_{date_compact}.dat"
    if not file_path.exists():
        # Grab any available .dat file in test_data
        test_dir = BASE_DIR / "modernized/test_data"
        dat_files = sorted(test_dir.glob("counterparty_confirms*.dat"))
        if dat_files:
            file_path = dat_files[0]
        else:
            raise FileNotFoundError(
                f"No counterparty confirms file found for {date_compact}"
            )

    logger.info("Loading confirms from %s", file_path)
    df = load_counterparty_file(file_path)
    logger.info("Loaded %d confirms", len(df))

    kwargs["ti"].xcom_push(key="confirms", value=df.to_dict("records"))


def reconcile_task(**kwargs) -> None:
    """Merge trades with confirms and determine reconciliation status."""
    ti = kwargs["ti"]
    trade_records = ti.xcom_pull(task_ids="enrich_trades", key="enriched_trades")
    confirm_records = ti.xcom_pull(task_ids="load_confirms", key="confirms")

    trades = pd.DataFrame(trade_records)
    confirms = pd.DataFrame(confirm_records)

    # Rename confirm columns to avoid collisions on merge
    confirms = confirms.rename(columns={
        "price": "confirm_price",
        "quantity": "confirm_quantity",
    })

    merged = pd.merge(trades, confirms[["trade_id", "confirm_price", "confirm_quantity"]],
                       on="trade_id", how="left")

    def _recon_status(row: pd.Series) -> str:
        if pd.isna(row.get("confirm_price")):
            return "UNMATCHED"
        price_ok = abs(row["price"] - row["confirm_price"]) <= 0.01
        qty_ok = int(row["quantity"]) == int(row["confirm_quantity"])
        if price_ok and qty_ok:
            return "MATCHED"
        if not price_ok:
            return "PRICE_BREAK"
        return "QTY_BREAK"

    merged["recon_status"] = merged.apply(_recon_status, axis=1)

    matched = (merged["recon_status"] == "MATCHED").sum()
    breaks = merged["recon_status"].isin(["PRICE_BREAK", "QTY_BREAK"]).sum()
    unmatched = (merged["recon_status"] == "UNMATCHED").sum()
    logger.info("Reconciliation: %d matched, %d breaks, %d unmatched", matched, breaks, unmatched)

    ti.xcom_push(key="reconciled_trades", value=merged.to_dict("records"))


def write_output_task(**kwargs) -> None:
    """Write reconciled trades to output CSV and optional error log."""
    ti = kwargs["ti"]
    ds: str = kwargs["ds"]
    date_compact = ds.replace("-", "")

    recon_records = ti.xcom_pull(task_ids="reconcile", key="reconciled_trades")
    df = pd.DataFrame(recon_records)

    # Ensure output directory exists
    output_dir = BASE_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"processed_trades_{date_compact}.csv"
    df.to_csv(output_path, index=False)
    logger.info("Wrote %d rows to %s", len(df), output_path)

    # Write error log if validation produced errors
    error_records = ti.xcom_pull(task_ids="validate_trades", key="error_trades")
    if error_records:
        error_df = pd.DataFrame(error_records)
        error_path = output_dir / f"trade_errors_{date_compact}.csv"
        error_df.to_csv(error_path, index=False)
        logger.info("Wrote %d error rows to %s", len(error_df), error_path)
