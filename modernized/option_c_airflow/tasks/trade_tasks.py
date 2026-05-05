"""PythonOperator callables for Airflow trade processing tasks.

Each function receives the Airflow context via **kwargs and uses
the common layer for actual processing logic.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from modernized.common.config import load_config
from modernized.common.parsers import load_counterparty_file, load_trades_csv
from modernized.common.settlement import calculate_t_plus_2
from modernized.common.validation import validate_trades

logger = logging.getLogger(__name__)


def _resolve_paths(
    execution_date: datetime,
    config_path: str = "config/batch_config.ini",
) -> dict[str, Path]:
    """Resolve file paths from config and execution date.

    Args:
        execution_date: Airflow logical execution date.
        config_path: Path to batch_config.ini.

    Returns:
        Dict with keys: trade_file, confirm_file, output_dir, run_date.
    """
    config = load_config(Path(config_path))
    run_date = execution_date.strftime("%Y%m%d")
    trade_dir = Path(config.get("trade_input", "legacy_data/trades"))
    output_dir = Path(config.get("report_output", "reports"))
    output_dir.mkdir(parents=True, exist_ok=True)

    return {
        "trade_file": trade_dir / f"daily_trades_{run_date}.csv",
        "confirm_file": trade_dir / "counterparty_confirms.dat",
        "output_dir": output_dir,
        "run_date": run_date,
    }


def load_and_validate_trades(**kwargs: Any) -> dict[str, Any]:
    """Load trades from CSV and validate using Pydantic models.

    Pushes validated trades to XCom as JSON for downstream tasks.

    Returns:
        Dict with keys: valid_count, error_count, duplicate_count.
    """
    execution_date = kwargs["execution_date"]
    config_path = kwargs.get("config_path", "config/batch_config.ini")
    paths = _resolve_paths(execution_date, config_path)

    logger.info("Loading trades from %s", paths["trade_file"])
    raw_df = load_trades_csv(paths["trade_file"])
    total_loaded = len(raw_df)

    valid_df, error_df = validate_trades(raw_df)

    # Count duplicates vs other errors
    duplicate_count = 0
    validation_errors = len(error_df)
    if not error_df.empty and "validation_error" in error_df.columns:
        dup_mask = error_df["validation_error"].str.contains("Duplicate", na=False)
        duplicate_count = int(dup_mask.sum())
        validation_errors = len(error_df) - duplicate_count

    # Store intermediate results as temp file for downstream tasks
    temp_dir = paths["output_dir"] / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    valid_df.to_csv(temp_dir / f"valid_trades_{paths['run_date']}.csv", index=False)
    if not error_df.empty:
        error_df.to_csv(temp_dir / f"trade_errors_{paths['run_date']}.csv", index=False)

    stats = {
        "total_loaded": total_loaded,
        "valid_count": len(valid_df),
        "error_count": validation_errors,
        "duplicate_count": duplicate_count,
        "run_date": paths["run_date"],
    }
    logger.info("Load & validate complete: %s", stats)
    return stats


def enrich_trades(**kwargs: Any) -> dict[str, Any]:
    """Enrich validated trades with amounts and corrected settlement dates.

    Reads validated trades from temp storage, calculates gross/net amounts,
    and fixes missing settlement dates using T+2 business day logic.

    Returns:
        Dict with keys: enriched_count, settlement_fixes, total_gross.
    """
    execution_date = kwargs["execution_date"]
    config_path = kwargs.get("config_path", "config/batch_config.ini")
    paths = _resolve_paths(execution_date, config_path)
    temp_dir = paths["output_dir"] / "temp"

    df = pd.read_csv(
        temp_dir / f"valid_trades_{paths['run_date']}.csv",
        parse_dates=["trade_date", "settle_date"],
    )

    # Fix settlement dates
    missing_settle = df["settle_date"].isna()
    settlement_fixes = int(missing_settle.sum())
    if missing_settle.any():
        logger.info("Fixing %d missing settlement dates", settlement_fixes)
        df.loc[missing_settle, "settle_date"] = df.loc[missing_settle, "trade_date"].apply(
            lambda td: pd.Timestamp(calculate_t_plus_2(td.date()))
        )

    # Calculate amounts
    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)
    df["net_amount"] = df["gross_amount"] + df["commission"]
    sell_mask = df["side"] == "SELL"
    df.loc[sell_mask, "net_amount"] = (
        df.loc[sell_mask, "gross_amount"] - df.loc[sell_mask, "commission"]
    )
    df["net_amount"] = df["net_amount"].round(2)

    df.to_csv(temp_dir / f"enriched_trades_{paths['run_date']}.csv", index=False)

    stats = {
        "enriched_count": len(df),
        "settlement_fixes": settlement_fixes,
        "total_gross": float(df["gross_amount"].sum()),
    }
    logger.info("Enrichment complete: %s", stats)
    return stats


def load_and_reconcile(**kwargs: Any) -> dict[str, Any]:
    """Load counterparty confirms and reconcile with enriched trades.

    Performs O(n) hash join and detects price/quantity breaks.

    Returns:
        Dict with keys: matched, breaks, unmatched.
    """
    execution_date = kwargs["execution_date"]
    config_path = kwargs.get("config_path", "config/batch_config.ini")
    paths = _resolve_paths(execution_date, config_path)
    temp_dir = paths["output_dir"] / "temp"
    tolerance = 0.01

    trades_df = pd.read_csv(
        temp_dir / f"enriched_trades_{paths['run_date']}.csv",
        parse_dates=["trade_date", "settle_date"],
    )

    confirm_path = paths["confirm_file"]
    if confirm_path.exists():
        confirms_df = load_counterparty_file(confirm_path)
        logger.info("Loaded %d counterparty confirms", len(confirms_df))
    else:
        logger.warning("Counterparty file not found: %s", confirm_path)
        confirms_df = pd.DataFrame()

    if confirms_df.empty:
        trades_df["recon_status"] = "UNMATCHED"
    else:
        merged = pd.merge(
            trades_df,
            confirms_df[["trade_id", "price", "quantity"]],
            on="trade_id",
            how="left",
            suffixes=("", "_confirm"),
        )

        def _status(row: pd.Series) -> str:
            if pd.isna(row.get("price_confirm")):
                return "UNMATCHED"
            if abs(row["price"] - row["price_confirm"]) > tolerance:
                return "PRICE_BREAK"
            if row["quantity"] != row.get("quantity_confirm"):
                return "QTY_BREAK"
            return "MATCHED"

        merged["recon_status"] = merged.apply(_status, axis=1)
        trades_df = merged.drop(columns=["price_confirm", "quantity_confirm"], errors="ignore")

    trades_df.to_csv(temp_dir / f"reconciled_trades_{paths['run_date']}.csv", index=False)

    recon_counts = trades_df["recon_status"].value_counts()
    stats = {
        "matched": int(recon_counts.get("MATCHED", 0)),
        "breaks": int(
            recon_counts.get("PRICE_BREAK", 0) + recon_counts.get("QTY_BREAK", 0)
        ),
        "unmatched": int(recon_counts.get("UNMATCHED", 0)),
    }
    logger.info("Reconciliation complete: %s", stats)
    return stats


def write_results(**kwargs: Any) -> dict[str, Any]:
    """Write final output CSV and clean up temp files.

    Returns:
        Dict with keys: output_path, row_count.
    """
    execution_date = kwargs["execution_date"]
    config_path = kwargs.get("config_path", "config/batch_config.ini")
    paths = _resolve_paths(execution_date, config_path)
    temp_dir = paths["output_dir"] / "temp"

    df = pd.read_csv(
        temp_dir / f"reconciled_trades_{paths['run_date']}.csv",
        parse_dates=["trade_date", "settle_date"],
    )

    df["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    output_path = paths["output_dir"] / f"processed_trades_{paths['run_date']}.csv"
    df.to_csv(output_path, index=False)
    logger.info("Wrote %d processed trades to %s", len(df), output_path)

    stats = {
        "output_path": str(output_path),
        "row_count": len(df),
    }
    logger.info("Output written: %s", stats)
    return stats
