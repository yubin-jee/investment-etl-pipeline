"""Airflow task functions for the trade processing pipeline.

Each function is designed to be called by a PythonOperator. Functions accept
**kwargs (Airflow context), call the shared common layer, and return a dict
of stats/results that Airflow pushes to XCom automatically.
"""

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from modernized.common.parsers import load_counterparty_file, load_trades_csv
from modernized.common.settlement import calculate_t_plus_2
from modernized.common.validation import validate_trades

logger = logging.getLogger(__name__)

# Repository root resolved relative to this file
_REPO_ROOT = Path(__file__).resolve().parents[4]
_TRADE_DIR = _REPO_ROOT / "legacy_data" / "trades"
_CONFIRM_FILE = _REPO_ROOT / "legacy_data" / "trades" / "counterparty_confirms.dat"
_OUTPUT_DIR = _REPO_ROOT / "reports"


def _execution_date_str(kwargs: dict[str, Any]) -> str:
    """Extract execution date as YYYYMMDD from Airflow context."""
    ds: str | None = kwargs.get("ds")
    if ds:
        return ds.replace("-", "")
    execution_date = kwargs.get("execution_date", datetime.now())
    if isinstance(execution_date, datetime):
        return execution_date.strftime("%Y%m%d")
    return datetime.now().strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Task 1: Load trades
# ---------------------------------------------------------------------------

def load_trades(**kwargs: Any) -> dict[str, Any]:
    """Load the daily trade CSV for the execution date.

    Reads the CSV via ``common.parsers.load_trades_csv``, persists the
    DataFrame to a temporary Parquet file for downstream tasks, and returns
    row-count metadata pushed to XCom.

    Returns:
        dict with ``row_count`` and ``file_path``.
    """
    date_str = _execution_date_str(kwargs)
    csv_path = _TRADE_DIR / f"daily_trades_{date_str}.csv"

    if not csv_path.exists():
        logger.warning("Trade file not found: %s — falling back to latest available file", csv_path)
        available = sorted(_TRADE_DIR.glob("daily_trades_*.csv"))
        if not available:
            raise FileNotFoundError(f"No trade CSV files found in {_TRADE_DIR}")
        csv_path = available[-1]
        logger.info("Using fallback trade file: %s", csv_path)

    df = load_trades_csv(csv_path)

    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False, prefix="trades_raw_")
    df.to_parquet(tmp.name, index=False)
    logger.info("Saved %d raw trades to %s", len(df), tmp.name)

    return {"row_count": len(df), "file_path": tmp.name}


# ---------------------------------------------------------------------------
# Task 2: Validate trades
# ---------------------------------------------------------------------------

def validate_trades_task(**kwargs: Any) -> dict[str, Any]:
    """Validate raw trades pulled from the upstream load task.

    Reads the Parquet file path from XCom, validates each row via
    ``common.validation.validate_trades``, and persists valid trades to a
    new temporary Parquet file.

    Returns:
        dict with ``valid_count``, ``error_count``, and ``file_path``.
    """
    ti = kwargs["ti"]
    upstream: dict[str, Any] = ti.xcom_pull(task_ids="load_trades")
    raw_path = upstream["file_path"]

    df = pd.read_parquet(raw_path)
    valid_df, error_df = validate_trades(df)

    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False, prefix="trades_valid_")
    valid_df.to_parquet(tmp.name, index=False)
    logger.info(
        "Validation: %d valid, %d errors — saved to %s",
        len(valid_df),
        len(error_df),
        tmp.name,
    )

    return {
        "valid_count": len(valid_df),
        "error_count": len(error_df),
        "file_path": tmp.name,
    }


# ---------------------------------------------------------------------------
# Task 3: Enrich trades
# ---------------------------------------------------------------------------

def enrich_trades(**kwargs: Any) -> dict[str, Any]:
    """Enrich validated trades with calculated amounts and settlement dates.

    Computes:
    - ``gross_amount`` = quantity * price
    - ``net_amount`` = gross + commission (BUY) or gross - commission (SELL)
    - Missing ``settle_date`` filled via ``common.settlement.calculate_t_plus_2``

    Returns:
        dict with ``row_count`` and ``file_path``.
    """
    ti = kwargs["ti"]
    upstream: dict[str, Any] = ti.xcom_pull(task_ids="validate_trades")
    valid_path = upstream["file_path"]

    df = pd.read_parquet(valid_path)

    # Compute amounts
    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)

    net = df["gross_amount"] + df["commission"]
    sell_mask = df["side"] == "SELL"
    net[sell_mask] = df.loc[sell_mask, "gross_amount"] - df.loc[sell_mask, "commission"]
    df["net_amount"] = net.round(2)

    # Fill missing settlement dates
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["settle_date"] = pd.to_datetime(df["settle_date"], errors="coerce")

    missing_settle = df["settle_date"].isna()
    if missing_settle.any():
        logger.info("Filling %d missing settlement dates via T+2", missing_settle.sum())
        df.loc[missing_settle, "settle_date"] = df.loc[missing_settle, "trade_date"].apply(
            lambda td: pd.Timestamp(calculate_t_plus_2(td.date()))
        )

    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False, prefix="trades_enriched_")
    df.to_parquet(tmp.name, index=False)
    logger.info("Enriched %d trades — saved to %s", len(df), tmp.name)

    return {"row_count": len(df), "file_path": tmp.name}


# ---------------------------------------------------------------------------
# Task 4: Load counterparty confirmations
# ---------------------------------------------------------------------------

def load_confirms(**kwargs: Any) -> dict[str, Any]:
    """Load counterparty confirmation file.

    Reads the fixed-width .dat file via
    ``common.parsers.load_counterparty_file`` and persists the result
    to a temporary Parquet file.

    Returns:
        dict with ``row_count`` and ``file_path``.
    """
    confirm_path = _CONFIRM_FILE
    if not confirm_path.exists():
        available = sorted(_TRADE_DIR.glob("counterparty_confirms*.dat"))
        if not available:
            raise FileNotFoundError(f"No counterparty confirmation files found in {_TRADE_DIR}")
        confirm_path = available[-1]
        logger.info("Using fallback confirms file: %s", confirm_path)

    df = load_counterparty_file(confirm_path)

    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False, prefix="confirms_")
    df.to_parquet(tmp.name, index=False)
    logger.info("Loaded %d counterparty confirms — saved to %s", len(df), tmp.name)

    return {"row_count": len(df), "file_path": tmp.name}


# ---------------------------------------------------------------------------
# Task 5: Reconciliation
# ---------------------------------------------------------------------------

def reconcile(**kwargs: Any) -> dict[str, Any]:
    """Reconcile enriched trades against counterparty confirmations.

    Performs a left join on ``trade_id`` and classifies each trade as:
    - ``MATCHED`` — quantities and prices agree
    - ``PRICE_BREAK`` — quantities match but prices differ
    - ``QTY_BREAK`` — prices match but quantities differ
    - ``UNMATCHED`` — no counterparty confirmation found

    Returns:
        dict with ``matched``, ``breaks``, ``unmatched``, and ``file_path``.
    """
    ti = kwargs["ti"]
    enriched: dict[str, Any] = ti.xcom_pull(task_ids="enrich_trades")
    confirms: dict[str, Any] = ti.xcom_pull(task_ids="load_confirms")

    trades_df = pd.read_parquet(enriched["file_path"])
    confirms_df = pd.read_parquet(confirms["file_path"])

    merged = pd.merge(
        trades_df,
        confirms_df[["trade_id", "quantity", "price"]].rename(
            columns={"quantity": "confirm_qty", "price": "confirm_price"}
        ),
        on="trade_id",
        how="left",
    )

    def _classify(row: pd.Series) -> str:
        if pd.isna(row.get("confirm_qty")):
            return "UNMATCHED"
        if row["quantity"] != row["confirm_qty"]:
            return "QTY_BREAK"
        if abs(row["price"] - row["confirm_price"]) > 0.01:
            return "PRICE_BREAK"
        return "MATCHED"

    merged["recon_status"] = merged.apply(_classify, axis=1)

    matched = int((merged["recon_status"] == "MATCHED").sum())
    breaks = int(
        ((merged["recon_status"] == "PRICE_BREAK") | (merged["recon_status"] == "QTY_BREAK")).sum()
    )
    unmatched = int((merged["recon_status"] == "UNMATCHED").sum())

    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False, prefix="trades_reconciled_")
    merged.to_parquet(tmp.name, index=False)
    logger.info(
        "Reconciliation: %d matched, %d breaks, %d unmatched — saved to %s",
        matched,
        breaks,
        unmatched,
        tmp.name,
    )

    return {"matched": matched, "breaks": breaks, "unmatched": unmatched, "file_path": tmp.name}


# ---------------------------------------------------------------------------
# Task 6: Write output
# ---------------------------------------------------------------------------

def write_output(**kwargs: Any) -> dict[str, Any]:
    """Write reconciled trades to a final output CSV.

    Produces a CSV with the standard output columns including
    ``RECON_STATUS`` and ``PROCESSED_AT`` timestamp.

    Returns:
        dict with ``output_file`` and ``row_count``.
    """
    ti = kwargs["ti"]
    recon: dict[str, Any] = ti.xcom_pull(task_ids="reconcile")
    recon_path = recon["file_path"]

    df = pd.read_parquet(recon_path)
    df["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    output_columns = [
        "trade_id",
        "account",
        "ticker",
        "side",
        "quantity",
        "price",
        "gross_amount",
        "net_amount",
        "commission",
        "trade_date",
        "settle_date",
        "broker",
        "status",
        "recon_status",
        "processed_at",
    ]

    column_headers = [
        "TRADE_ID",
        "ACCT_NUM",
        "TICKER",
        "SIDE",
        "QTY",
        "PRICE",
        "GROSS_AMT",
        "NET_AMT",
        "COMMISSION",
        "TRADE_DATE",
        "SETTLE_DATE",
        "BROKER",
        "STATUS",
        "RECON_STATUS",
        "PROCESSED_AT",
    ]

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = _execution_date_str(kwargs)
    output_path = _OUTPUT_DIR / f"processed_trades_{date_str}.csv"

    out_df = df[output_columns].copy()
    out_df.columns = column_headers
    out_df.to_csv(output_path, index=False)

    logger.info("Wrote %d trades to %s", len(out_df), output_path)

    return {"output_file": str(output_path), "row_count": len(out_df)}
