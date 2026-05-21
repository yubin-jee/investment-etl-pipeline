"""Airflow task functions for the trade processing pipeline.

Each function is designed to be called by an Airflow PythonOperator,
receiving the Airflow context via **kwargs. Data is passed between
tasks using XCom (via temp file paths).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import pandas as pd

from modernized.common.parsers import load_counterparty_file, load_trades_csv
from modernized.common.settlement import calculate_t_plus_2
from modernized.common.validation import validate_trades

logger = logging.getLogger(__name__)


def _get_base_dir(**kwargs) -> Path:
    """Resolve the base directory for input/output files."""
    base = kwargs.get("base_dir") or os.environ.get("TRADE_DATA_DIR")
    if base:
        return Path(base)
    return Path(__file__).resolve().parents[2] / "test_data"


def _get_output_dir(**kwargs) -> Path:
    """Resolve the output directory, creating it if needed."""
    out = kwargs.get("output_dir") or os.environ.get("TRADE_OUTPUT_DIR")
    if out:
        p = Path(out)
    else:
        p = _get_base_dir(**kwargs) / "output"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_and_validate_trades(**kwargs) -> dict:
    """Load the daily trade CSV, validate, and persist valid trades.

    Pushes the valid trades temp file path via XCom for downstream tasks.

    Returns:
        Stats dict with total_loaded, duplicates_removed,
        validation_errors, and valid_trades_path.
    """
    ti = kwargs.get("ti")
    base_dir = _get_base_dir(**kwargs)

    execution_date = kwargs.get("execution_date")
    if execution_date is not None:
        date_str = execution_date.strftime("%Y%m%d")
    else:
        date_str = "20240115"

    csv_path = base_dir / f"daily_trades_{date_str}.csv"
    if not csv_path.exists():
        csv_files = sorted(base_dir.glob("daily_trades_*.csv"))
        if csv_files:
            csv_path = csv_files[-1]
        else:
            raise FileNotFoundError(f"No trade CSV found in {base_dir}")

    logger.info("Loading trades from %s", csv_path)
    df = load_trades_csv(csv_path)
    total_loaded = len(df)

    valid_df, error_df = validate_trades(df)
    duplicates_removed = len(df[df.duplicated(subset=["trade_id"], keep="first")])
    validation_errors = len(error_df)

    output_dir = _get_output_dir(**kwargs)
    valid_path = str(output_dir / "valid_trades.csv")
    valid_df.to_csv(valid_path, index=False)

    error_path = str(output_dir / "validation_errors.csv")
    error_df.to_csv(error_path, index=False)

    if ti is not None:
        ti.xcom_push(key="valid_trades_path", value=valid_path)
        ti.xcom_push(key="error_path", value=error_path)

    stats = {
        "total_loaded": total_loaded,
        "duplicates_removed": duplicates_removed,
        "validation_errors": validation_errors,
        "valid_trades_path": valid_path,
    }
    logger.info("Load & validate complete: %s", stats)
    return stats


def enrich_trades(**kwargs) -> dict:
    """Enrich validated trades with calculated amounts and settlement dates.

    Reads valid trades from the path pushed by load_and_validate_trades.
    Calculates gross_amount, net_amount, and fills missing settlement dates.

    Returns:
        Stats dict with trades_enriched, settlement_dates_fixed,
        and enriched_trades_path.
    """
    ti = kwargs.get("ti")

    valid_path = kwargs.get("valid_trades_path")
    if valid_path is None and ti is not None:
        valid_path = ti.xcom_pull(
            task_ids="load_validate", key="valid_trades_path"
        )
    if valid_path is None:
        output_dir = _get_output_dir(**kwargs)
        valid_path = str(output_dir / "valid_trades.csv")

    logger.info("Enriching trades from %s", valid_path)
    df = pd.read_csv(valid_path)

    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["settle_date"] = pd.to_datetime(df["settle_date"], errors="coerce").dt.date

    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)

    df["net_amount"] = df.apply(
        lambda r: round(r["gross_amount"] + r["commission"], 2)
        if r["side"] == "BUY"
        else round(r["gross_amount"] - r["commission"], 2),
        axis=1,
    )

    settlement_dates_fixed = 0
    for idx, row in df.iterrows():
        if pd.isna(row["settle_date"]) or row["settle_date"] is None:
            df.at[idx, "settle_date"] = calculate_t_plus_2(row["trade_date"])
            settlement_dates_fixed += 1

    output_dir = _get_output_dir(**kwargs)
    enriched_path = str(output_dir / "enriched_trades.csv")
    df.to_csv(enriched_path, index=False)

    if ti is not None:
        ti.xcom_push(key="enriched_trades_path", value=enriched_path)

    stats = {
        "trades_enriched": len(df),
        "settlement_dates_fixed": settlement_dates_fixed,
        "enriched_trades_path": enriched_path,
    }
    logger.info("Enrichment complete: %s", stats)
    return stats


def load_and_reconcile(**kwargs) -> dict:
    """Reconcile enriched trades against counterparty confirmations.

    Loads counterparty confirms via common parsers, merges with enriched
    trades on trade_id (left join), and classifies each record as
    MATCHED, PRICE_BREAK, QTY_BREAK, or UNMATCHED.

    Returns:
        Stats dict with matched, price_breaks, qty_breaks, unmatched,
        and reconciled_trades_path.
    """
    ti = kwargs.get("ti")
    base_dir = _get_base_dir(**kwargs)

    enriched_path = kwargs.get("enriched_trades_path")
    if enriched_path is None and ti is not None:
        enriched_path = ti.xcom_pull(
            task_ids="enrich", key="enriched_trades_path"
        )
    if enriched_path is None:
        output_dir = _get_output_dir(**kwargs)
        enriched_path = str(output_dir / "enriched_trades.csv")

    logger.info("Loading enriched trades from %s", enriched_path)
    trades_df = pd.read_csv(enriched_path)

    confirm_path = base_dir / "counterparty_confirms.dat"
    if not confirm_path.exists():
        dat_files = sorted(base_dir.glob("*.dat"))
        if dat_files:
            confirm_path = dat_files[0]
        else:
            raise FileNotFoundError(f"No counterparty file found in {base_dir}")

    logger.info("Loading counterparty confirms from %s", confirm_path)
    confirms_df = load_counterparty_file(confirm_path)

    confirms_df = confirms_df.rename(columns={
        "price": "confirm_price",
        "quantity": "confirm_quantity",
    })

    merged = pd.merge(
        trades_df,
        confirms_df[["trade_id", "confirm_price", "confirm_quantity"]],
        on="trade_id",
        how="left",
    )

    def classify(row):
        if pd.isna(row.get("confirm_price")):
            return "UNMATCHED"
        if abs(row["price"] - row["confirm_price"]) > 0.01:
            return "PRICE_BREAK"
        if row["quantity"] != row.get("confirm_quantity"):
            return "QTY_BREAK"
        return "MATCHED"

    merged["recon_status"] = merged.apply(classify, axis=1)

    matched = int((merged["recon_status"] == "MATCHED").sum())
    price_breaks = int((merged["recon_status"] == "PRICE_BREAK").sum())
    qty_breaks = int((merged["recon_status"] == "QTY_BREAK").sum())
    unmatched = int((merged["recon_status"] == "UNMATCHED").sum())

    output_dir = _get_output_dir(**kwargs)
    recon_path = str(output_dir / "reconciled_trades.csv")
    merged.to_csv(recon_path, index=False)

    if ti is not None:
        ti.xcom_push(key="reconciled_trades_path", value=recon_path)

    stats = {
        "matched": matched,
        "price_breaks": price_breaks,
        "qty_breaks": qty_breaks,
        "unmatched": unmatched,
        "reconciled_trades_path": recon_path,
    }
    logger.info("Reconciliation complete: %s", stats)
    return stats


def write_results(**kwargs) -> dict:
    """Write final output CSV and error log.

    Returns:
        Summary stats dict with output_path, error_log_path, and counts.
    """
    ti = kwargs.get("ti")

    recon_path = kwargs.get("reconciled_trades_path")
    if recon_path is None and ti is not None:
        recon_path = ti.xcom_pull(
            task_ids="load_reconcile", key="reconciled_trades_path"
        )
    if recon_path is None:
        output_dir = _get_output_dir(**kwargs)
        recon_path = str(output_dir / "reconciled_trades.csv")

    error_path = kwargs.get("error_path")
    if error_path is None and ti is not None:
        error_path = ti.xcom_pull(
            task_ids="load_validate", key="error_path"
        )

    logger.info("Writing final results from %s", recon_path)
    recon_df = pd.read_csv(recon_path)

    output_dir = _get_output_dir(**kwargs)
    final_path = str(output_dir / "final_output.csv")
    recon_df.to_csv(final_path, index=False)

    error_log_path = str(output_dir / "error_log.csv")
    if error_path and Path(error_path).exists():
        error_df = pd.read_csv(error_path)
        breaks_df = recon_df[recon_df["recon_status"] != "MATCHED"]
        all_errors = pd.concat([error_df, breaks_df], ignore_index=True)
        all_errors.to_csv(error_log_path, index=False)
        total_errors = len(all_errors)
    else:
        breaks_df = recon_df[recon_df["recon_status"] != "MATCHED"]
        breaks_df.to_csv(error_log_path, index=False)
        total_errors = len(breaks_df)

    stats = {
        "total_records": len(recon_df),
        "output_path": final_path,
        "error_log_path": error_log_path,
        "total_errors": total_errors,
    }
    logger.info("Results written: %s", stats)
    return stats
