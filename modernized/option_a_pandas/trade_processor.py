"""Option A: Pandas + Pydantic trade processor.

Replaces ``legacy_scripts/process_trades.py`` with a clean, functional
implementation backed by the shared common layer. Key improvements over
the legacy script:

- No global state — all data flows through function arguments and returns.
- Pandas vectorised operations for amount calculations.
- O(n) hash-join reconciliation via ``pd.merge`` (was O(n²) nested loop).
- Pydantic v2 model validation for every row.
- Proper T+2 settlement using business-day offsets.
- Structured logging instead of ``print``.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from modernized.common import config as common_config
from modernized.common import parsers as common_parsers
from modernized.common import settlement as common_settlement
from modernized.common import validation as common_validation
from modernized.common.models import ProcessingResult

logger = logging.getLogger(__name__)

# Repo-relative fallback directory for demo / test runs
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEST_DATA_DIR = _REPO_ROOT / "modernized" / "test_data"


def _resolve_trade_path(cfg_paths: dict, run_date: str) -> Path:
    """Build the trade CSV path from config, falling back to test_data."""
    filename = f"daily_trades_{run_date}.csv"
    if cfg_paths:
        configured = Path(cfg_paths.get("trade_input", "")) / filename
        if configured.exists():
            return configured
    fallback = _TEST_DATA_DIR / filename
    if fallback.exists():
        logger.info("Config trade path unavailable — using test_data fallback")
        return fallback
    raise FileNotFoundError(
        f"Trade file not found in config path or test_data: {filename}"
    )


def _resolve_confirm_path(cfg_paths: dict) -> Path:
    """Build the counterparty confirms path, falling back to test_data."""
    filename = "counterparty_confirms.dat"
    if cfg_paths:
        configured = Path(cfg_paths.get("trade_input", "")) / filename
        if configured.exists():
            return configured
    fallback = _TEST_DATA_DIR / filename
    if fallback.exists():
        logger.info("Config confirm path unavailable — using test_data fallback")
        return fallback
    raise FileNotFoundError(
        f"Counterparty file not found in config path or test_data: {filename}"
    )


def _calculate_amounts(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised gross/net amount calculation.

    Args:
        df: Valid trades DataFrame with ``quantity``, ``price``,
            ``commission``, and ``side`` columns.

    Returns:
        DataFrame with ``gross_amount`` and ``net_amount`` columns added.
    """
    df = df.copy()
    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)

    # For SELL trades commission is subtracted; for BUY it is added
    sell_mask = df["side"].str.upper() == "SELL"
    df["net_amount"] = df["gross_amount"] + df["commission"]
    df.loc[sell_mask, "net_amount"] = (
        df.loc[sell_mask, "gross_amount"] - df.loc[sell_mask, "commission"]
    )
    df["net_amount"] = df["net_amount"].round(2)
    return df


def _fill_missing_settle_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Apply T+2 settlement for rows with missing settle_date.

    Args:
        df: Trades DataFrame with ``trade_date`` and ``settle_date`` columns.

    Returns:
        DataFrame with missing ``settle_date`` values filled in.
    """
    df = df.copy()
    missing = df["settle_date"].isna()
    if missing.any():
        logger.info("Filling %d missing settlement dates with T+2", missing.sum())
        df.loc[missing, "settle_date"] = df.loc[missing, "trade_date"].apply(
            common_settlement.calculate_t_plus_2
        )
    return df


def _reconcile(
    trades: pd.DataFrame, confirms: pd.DataFrame
) -> tuple[pd.DataFrame, int, int, int]:
    """Reconcile internal trades against counterparty confirms.

    Uses ``pd.merge`` on ``trade_id`` for O(n) hash-join performance,
    replacing the legacy O(n²) nested-loop approach.

    Args:
        trades: Validated trades DataFrame.
        confirms: Counterparty confirms DataFrame.

    Returns:
        Tuple of (merged DataFrame with ``recon_status``, matched count,
        breaks count, unmatched count).
    """
    merged = pd.merge(
        trades,
        confirms[["trade_id", "quantity", "price"]].rename(
            columns={"quantity": "confirm_qty", "price": "confirm_price"}
        ),
        on="trade_id",
        how="left",
    )

    conditions = [
        merged["confirm_qty"].isna(),
        (merged["price"] - merged["confirm_price"]).abs() > 0.01,
        merged["quantity"] != merged["confirm_qty"],
    ]
    choices = ["UNMATCHED", "PRICE_BREAK", "QTY_BREAK"]
    merged["recon_status"] = pd.Series("MATCHED", index=merged.index)
    for cond, status in zip(conditions, choices):
        merged.loc[cond, "recon_status"] = status

    matched = int((merged["recon_status"] == "MATCHED").sum())
    breaks = int(
        merged["recon_status"].isin(["PRICE_BREAK", "QTY_BREAK"]).sum()
    )
    unmatched = int((merged["recon_status"] == "UNMATCHED").sum())

    logger.info(
        "Reconciliation: %d matched, %d breaks, %d unmatched",
        matched,
        breaks,
        unmatched,
    )
    return merged, matched, breaks, unmatched


def _write_output(df: pd.DataFrame, output_path: Path) -> None:
    """Write processed trades to a CSV file.

    Args:
        df: Processed trades DataFrame.
        output_path: Destination file path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
    ]
    cols_to_write = [c for c in output_columns if c in df.columns]
    df[cols_to_write].to_csv(output_path, index=False)
    logger.info("Wrote %d processed trades to %s", len(df), output_path)


def _write_error_log(error_df: pd.DataFrame, log_path: Path) -> None:
    """Append validation errors to a log file.

    Args:
        error_df: DataFrame of invalid rows with ``validation_error`` column.
        log_path: Path to the error log file.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as fh:
        fh.write(f"\n{'=' * 50}\n")
        fh.write(
            f"Trade Processing Run: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        fh.write(f"Validation Errors: {len(error_df)}\n")
        if not error_df.empty:
            for _, row in error_df.iterrows():
                fh.write(
                    f"  {row.get('trade_id', 'N/A')}: "
                    f"{row.get('validation_error', 'unknown')}\n"
                )
    logger.info("Error log written to %s", log_path)


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------


def process_trades(run_date: str, config_path: Path) -> ProcessingResult:
    """Execute the full trade-processing pipeline for a given date.

    Steps:
        1. Load configuration.
        2. Read trade CSV.
        3. Validate trades (Pydantic + broker whitelist + dedup).
        4. Calculate gross / net amounts.
        5. Fill missing settlement dates (T+2).
        6. Read counterparty confirms.
        7. Reconcile trades ↔ confirms (hash-join).
        8. Write output CSV and error log.
        9. Return summary statistics.

    Args:
        run_date: Date string in ``YYYYMMDD`` format.
        config_path: Path to ``batch_config.ini``.

    Returns:
        A :class:`ProcessingResult` with all processing statistics.
    """
    logger.info("Starting trade processing for %s", run_date)

    # 1. Config
    cfg = common_config.load_config(config_path)
    cfg_paths: dict = cfg.get("paths", {})

    # 2. Load trades
    trade_path = _resolve_trade_path(cfg_paths, run_date)
    trades_df = common_parsers.load_trades_csv(trade_path)
    total_loaded = len(trades_df)
    logger.info("Loaded %d trades from %s", total_loaded, trade_path)

    # 3. Validate
    valid_df, error_df = common_validation.validate_trades(trades_df)
    duplicates_removed = int(
        (error_df["validation_error"] == "Duplicate trade_id").sum()
        if "validation_error" in error_df.columns
        else 0
    )
    validation_errors = len(error_df) - duplicates_removed

    # 4. Calculate amounts
    valid_df = _calculate_amounts(valid_df)

    # 5. Fill missing settlement dates
    valid_df = _fill_missing_settle_dates(valid_df)

    # 6. Load counterparty confirms
    confirm_path = _resolve_confirm_path(cfg_paths)
    confirms_df = common_parsers.load_counterparty_file(confirm_path)
    logger.info("Loaded %d counterparty confirms from %s", len(confirms_df), confirm_path)

    # 7. Reconcile
    reconciled_df, matched, breaks, unmatched = _reconcile(valid_df, confirms_df)

    # 8. Write outputs — fall back to repo-local reports/ if config path
    #    is unreachable (e.g. Windows UNC path on Linux)
    configured_output = Path(str(cfg_paths.get("report_output", "")))
    if configured_output.is_absolute() and configured_output.exists():
        output_dir = configured_output
    else:
        output_dir = _REPO_ROOT / "reports"
    output_csv = output_dir / f"processed_trades_{run_date}.csv"
    error_log = output_dir / f"trade_errors_{run_date}.log"

    _write_output(reconciled_df, output_csv)
    _write_error_log(error_df, error_log)

    # 9. Summary
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


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Option A (Pandas + Pydantic) trade processor",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Run date in YYYYMMDD format (e.g. 20240115)",
    )
    parser.add_argument(
        "--config",
        default="config/batch_config.ini",
        help="Path to batch_config.ini (default: config/batch_config.ini)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = _parse_args()
    result = process_trades(run_date=args.date, config_path=Path(args.config))

    print("\n" + "=" * 50)
    print("PROCESSING SUMMARY")
    print("=" * 50)
    print(f"  Total loaded:       {result.total_loaded}")
    print(f"  Duplicates removed: {result.duplicates_removed}")
    print(f"  Validation errors:  {result.validation_errors}")
    print(f"  Matched:            {result.matched}")
    print(f"  Breaks:             {result.breaks}")
    print(f"  Unmatched:          {result.unmatched}")
    print("=" * 50)
