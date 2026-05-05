"""Modernized trade processor using Pandas + Pydantic.

A refactored, standalone replacement for legacy_scripts/process_trades.py
that eliminates global state, uses proper logging, fixes settlement date
calculation, and performs O(n) hash-join reconciliation.

Usage:
    python -m modernized.option_a_pandas.trade_processor --date 20240315 --config config/batch_config.ini
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from modernized.common.config import load_config
from modernized.common.models import ProcessingResult
from modernized.common.parsers import load_counterparty_file, load_trades_csv
from modernized.common.settlement import calculate_t_plus_2
from modernized.common.validation import validate_trades

logger = logging.getLogger(__name__)


def _calculate_amounts(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate gross and net amounts for each trade.

    - gross_amount = quantity * price
    - net_amount = gross_amount + commission (BUY) or gross_amount - commission (SELL)

    Args:
        df: Validated trades DataFrame.

    Returns:
        DataFrame with gross_amount and net_amount columns added.
    """
    df = df.copy()
    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)
    df["net_amount"] = df["gross_amount"] + df["commission"]
    sell_mask = df["side"] == "SELL"
    df.loc[sell_mask, "net_amount"] = (
        df.loc[sell_mask, "gross_amount"] - df.loc[sell_mask, "commission"]
    )
    df["net_amount"] = df["net_amount"].round(2)
    return df


def _fix_settlement_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing settlement dates using correct T+2 business day logic.

    Args:
        df: Trades DataFrame with trade_date and settle_date columns.

    Returns:
        DataFrame with settle_date filled for all rows.
    """
    df = df.copy()
    missing_mask = df["settle_date"].isna()
    if missing_mask.any():
        logger.info("Fixing %d missing settlement dates with T+2 calculation", missing_mask.sum())
        df.loc[missing_mask, "settle_date"] = df.loc[missing_mask, "trade_date"].apply(
            lambda td: pd.Timestamp(calculate_t_plus_2(td.date()))
        )
    return df


def _reconcile(
    trades_df: pd.DataFrame,
    confirms_df: pd.DataFrame,
    tolerance: float = 0.01,
) -> pd.DataFrame:
    """Reconcile trades against counterparty confirmations via hash join.

    Replaces the legacy O(n^2) nested loop with a pandas merge (O(n)).

    Args:
        trades_df: Enriched trades DataFrame.
        confirms_df: Counterparty confirmations DataFrame.
        tolerance: Allowed price difference for matching (default 0.01).

    Returns:
        Trades DataFrame with recon_status column added.
    """
    if confirms_df.empty:
        trades_df = trades_df.copy()
        trades_df["recon_status"] = "UNMATCHED"
        return trades_df

    merged = pd.merge(
        trades_df,
        confirms_df[["trade_id", "price", "quantity"]],
        on="trade_id",
        how="left",
        suffixes=("", "_confirm"),
    )

    def _determine_status(row: pd.Series) -> str:
        if pd.isna(row.get("price_confirm")):
            return "UNMATCHED"
        if abs(row["price"] - row["price_confirm"]) > tolerance:
            return "PRICE_BREAK"
        if row["quantity"] != row.get("quantity_confirm"):
            return "QTY_BREAK"
        return "MATCHED"

    merged["recon_status"] = merged.apply(_determine_status, axis=1)

    merged = merged.drop(columns=["price_confirm", "quantity_confirm"], errors="ignore")

    return merged


def process_trades(
    run_date: str,
    config_path: Path,
    trade_file: Path | None = None,
    confirm_file: Path | None = None,
    output_dir: Path | None = None,
) -> ProcessingResult:
    """Execute the full trade processing pipeline.

    Args:
        run_date: Date string in YYYYMMDD format.
        config_path: Path to batch_config.ini.
        trade_file: Override path to the trade CSV (optional).
        confirm_file: Override path to the counterparty .dat file (optional).
        output_dir: Override path for output directory (optional).

    Returns:
        ProcessingResult with summary statistics.
    """
    config = load_config(config_path)

    # Resolve file paths
    trade_input_dir = Path(config.get("trade_input", "legacy_data/trades"))
    report_output_dir = output_dir or Path(config.get("report_output", "reports"))
    report_output_dir.mkdir(parents=True, exist_ok=True)

    trade_csv = trade_file or (trade_input_dir / f"daily_trades_{run_date}.csv")
    confirm_dat = confirm_file or (trade_input_dir / "counterparty_confirms.dat")

    # Step 1: Load trades
    logger.info("Loading trades from %s", trade_csv)
    raw_df = load_trades_csv(trade_csv)
    total_loaded = len(raw_df)
    logger.info("Loaded %d raw trades", total_loaded)

    # Step 2: Validate
    valid_df, error_df = validate_trades(raw_df)
    duplicates_removed = len(raw_df) - len(valid_df) - len(error_df.query("'Duplicate' not in validation_error")) if not error_df.empty else 0
    validation_errors = len(error_df)

    # Count duplicates specifically
    if not error_df.empty and "validation_error" in error_df.columns:
        dup_mask = error_df["validation_error"].str.contains("Duplicate", na=False)
        duplicates_removed = int(dup_mask.sum())
        validation_errors = len(error_df) - duplicates_removed

    # Step 3: Fix settlement dates
    valid_df = _fix_settlement_dates(valid_df)

    # Step 4: Calculate amounts
    valid_df = _calculate_amounts(valid_df)

    # Step 5: Reconcile with counterparty confirms
    matched = 0
    breaks = 0
    unmatched = 0

    if confirm_dat.exists():
        logger.info("Loading counterparty confirms from %s", confirm_dat)
        confirms_df = load_counterparty_file(confirm_dat)
        logger.info("Loaded %d counterparty confirms", len(confirms_df))

        valid_df = _reconcile(valid_df, confirms_df)
        recon_counts = valid_df["recon_status"].value_counts()
        matched = int(recon_counts.get("MATCHED", 0))
        breaks = int(
            recon_counts.get("PRICE_BREAK", 0) + recon_counts.get("QTY_BREAK", 0)
        )
        unmatched = int(recon_counts.get("UNMATCHED", 0))
    else:
        logger.warning("Counterparty file not found: %s — skipping reconciliation", confirm_dat)
        valid_df["recon_status"] = "UNMATCHED"
        unmatched = len(valid_df)

    # Step 6: Write output
    output_file = report_output_dir / f"processed_trades_{run_date}.csv"
    valid_df["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(output_file, "w", newline="") as f:
        valid_df.to_csv(f, index=False)
    logger.info("Wrote %d processed trades to %s", len(valid_df), output_file)

    # Write error log
    if not error_df.empty:
        error_file = report_output_dir / f"trade_errors_{run_date}.csv"
        with open(error_file, "w", newline="") as f:
            error_df.to_csv(f, index=False)
        logger.info("Wrote %d errors to %s", len(error_df), error_file)

    result = ProcessingResult(
        total_loaded=total_loaded,
        duplicates_removed=duplicates_removed,
        validation_errors=validation_errors,
        matched=matched,
        breaks=breaks,
        unmatched=unmatched,
    )
    logger.info("Processing complete: %s", result.model_dump())
    return result


def main() -> None:
    """CLI entry point for standalone trade processing."""
    parser = argparse.ArgumentParser(
        description="Meridian Capital — Modernized Trade Processor (Option A)",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Run date in YYYYMMDD format (e.g., 20240315)",
    )
    parser.add_argument(
        "--config",
        default="config/batch_config.ini",
        help="Path to batch_config.ini (default: config/batch_config.ini)",
    )
    parser.add_argument(
        "--trade-file",
        default=None,
        help="Override path to trade CSV file",
    )
    parser.add_argument(
        "--confirm-file",
        default=None,
        help="Override path to counterparty .dat file",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory path",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    result = process_trades(
        run_date=args.date,
        config_path=Path(args.config),
        trade_file=Path(args.trade_file) if args.trade_file else None,
        confirm_file=Path(args.confirm_file) if args.confirm_file else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )

    print(f"\nProcessing Summary:")
    print(f"  Total loaded:       {result.total_loaded}")
    print(f"  Duplicates removed: {result.duplicates_removed}")
    print(f"  Validation errors:  {result.validation_errors}")
    print(f"  Matched:            {result.matched}")
    print(f"  Breaks:             {result.breaks}")
    print(f"  Unmatched:          {result.unmatched}")


if __name__ == "__main__":
    main()
