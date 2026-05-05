"""Option A: Pandas + Pydantic standalone trade processor.

Replaces the legacy process_trades.py with a clean, modular script that
uses the shared common layer for parsing, validation, settlement, and
configuration. Eliminates global state, hardcoded paths, print statements,
and O(n^2) reconciliation.
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from modernized.common.config import load_config
from modernized.common.models import ProcessingResult
from modernized.common.parsers import load_counterparty_file, load_trades_csv
from modernized.common.settlement import calculate_t_plus_2
from modernized.common.validation import validate_trades

logger = logging.getLogger(__name__)


def _resolve_trade_file(run_date: str, config: dict) -> Path:
    """Locate the daily trades CSV, falling back to legacy_data/trades/.

    Args:
        run_date: Date string in YYYYMMDD format.
        config: Configuration dictionary from load_config.

    Returns:
        Path to the trades CSV file.

    Raises:
        FileNotFoundError: If the file cannot be found in either location.
    """
    filename = f"daily_trades_{run_date}.csv"

    config_dir = Path(config.get("trade_input", ""))
    if config_dir.is_dir():
        candidate = config_dir / filename
        if candidate.exists():
            logger.info("Found trade file at config path: %s", candidate)
            return candidate

    fallback = Path(__file__).resolve().parents[2] / "legacy_data" / "trades" / filename
    if fallback.exists():
        logger.info("Found trade file at fallback path: %s", fallback)
        return fallback

    raise FileNotFoundError(
        f"Trade file '{filename}' not found in config path "
        f"'{config_dir}' or fallback 'legacy_data/trades/'"
    )


def _resolve_counterparty_file(trade_file: Path) -> Path | None:
    """Locate the counterparty confirms file in the same directory as trades.

    Args:
        trade_file: Path to the daily trades CSV.

    Returns:
        Path to counterparty_confirms.dat, or None if not found.
    """
    candidate = trade_file.parent / "counterparty_confirms.dat"
    if candidate.exists():
        return candidate
    logger.warning("Counterparty file not found: %s", candidate)
    return None


def calculate_amounts(df: pd.DataFrame) -> pd.DataFrame:
    """Compute gross and net trade amounts.

    gross_amount = quantity * price
    net_amount   = gross_amount + commission  (BUY)
                 = gross_amount - commission  (SELL)

    Both values are rounded to 2 decimal places.

    Args:
        df: Validated trades DataFrame with quantity, price, commission, side.

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

    logger.info("Calculated amounts for %d trades", len(df))
    return df


def fix_settlement_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing settlement dates using T+2 business day calculation.

    Args:
        df: Trades DataFrame with trade_date and settle_date columns.

    Returns:
        DataFrame with missing settle_date values filled.
    """
    df = df.copy()
    missing_mask = df["settle_date"].isna()
    missing_count = missing_mask.sum()

    if missing_count > 0:
        df.loc[missing_mask, "settle_date"] = df.loc[missing_mask, "trade_date"].apply(
            lambda td: pd.Timestamp(
                calculate_t_plus_2(td.date() if hasattr(td, "date") else td)
            )
            if pd.notna(td)
            else pd.NaT
        )
        logger.info("Filled %d missing settlement dates via T+2", missing_count)

    return df


def reconcile_trades(
    trades_df: pd.DataFrame,
    confirms_df: pd.DataFrame,
) -> pd.DataFrame:
    """Reconcile internal trades against counterparty confirmations.

    Uses a pandas merge (O(n) hash join) instead of the legacy O(n^2)
    nested loop. Detects MATCHED, PRICE_BREAK, QTY_BREAK, and UNMATCHED.

    Args:
        trades_df: Processed trades DataFrame.
        confirms_df: Counterparty confirmations DataFrame.

    Returns:
        Trades DataFrame with a recon_status column added.
    """
    if confirms_df.empty:
        trades_df = trades_df.copy()
        trades_df["recon_status"] = "UNMATCHED"
        logger.warning("No counterparty confirms — all trades marked UNMATCHED")
        return trades_df

    confirms_subset = confirms_df[["trade_id", "price", "quantity"]].rename(
        columns={"price": "confirm_price", "quantity": "confirm_qty"}
    )

    merged = pd.merge(trades_df, confirms_subset, on="trade_id", how="left")

    merged["recon_status"] = "MATCHED"
    merged.loc[merged["confirm_price"].isna(), "recon_status"] = "UNMATCHED"
    merged.loc[
        (merged["confirm_price"].notna())
        & ((merged["price"] - merged["confirm_price"]).abs() > 0.01),
        "recon_status",
    ] = "PRICE_BREAK"
    merged.loc[
        (merged["confirm_price"].notna())
        & ((merged["price"] - merged["confirm_price"]).abs() <= 0.01)
        & (merged["quantity"] != merged["confirm_qty"]),
        "recon_status",
    ] = "QTY_BREAK"

    matched = int((merged["recon_status"] == "MATCHED").sum())
    breaks = int(merged["recon_status"].isin(["PRICE_BREAK", "QTY_BREAK"]).sum())
    unmatched = int((merged["recon_status"] == "UNMATCHED").sum())
    logger.info(
        "Reconciliation: %d matched, %d breaks, %d unmatched",
        matched,
        breaks,
        unmatched,
    )

    merged.drop(columns=["confirm_price", "confirm_qty"], inplace=True)
    return merged


def write_output_csv(df: pd.DataFrame, output_path: Path) -> None:
    """Write processed trades to output CSV with legacy-compatible columns.

    Args:
        df: Final processed trades DataFrame.
        output_path: Path for the output CSV file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = df.copy()
    df["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    column_map = {
        "trade_id": "TRADE_ID",
        "account": "ACCT_NUM",
        "ticker": "TICKER",
        "side": "SIDE",
        "quantity": "QTY",
        "price": "PRICE",
        "gross_amount": "GROSS_AMT",
        "net_amount": "NET_AMT",
        "commission": "COMMISSION",
        "trade_date": "TRADE_DATE",
        "settle_date": "SETTLE_DATE",
        "broker": "BROKER",
        "status": "STATUS",
        "recon_status": "RECON_STATUS",
        "processed_at": "PROCESSED_AT",
    }

    output_cols = [c for c in column_map if c in df.columns]
    out_df = df[output_cols].rename(columns=column_map)

    with open(output_path, "w", newline="") as f:
        out_df.to_csv(f, index=False)

    logger.info("Wrote %d trades to %s", len(out_df), output_path)


def write_error_log(error_df: pd.DataFrame, log_path: Path) -> None:
    """Write validation errors to a log file.

    Args:
        error_df: DataFrame of trades that failed validation.
        log_path: Path for the error log file.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "w", newline="") as f:
        f.write(f"Trade Processing Error Log - {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"{'=' * 60}\n")
        f.write(f"Total errors: {len(error_df)}\n\n")

        if not error_df.empty:
            error_df.to_csv(f, index=False)

    logger.info("Wrote %d errors to %s", len(error_df), log_path)


def process_trades(run_date: str, config_path: Path | None = None) -> ProcessingResult:
    """Run the full trade processing pipeline for a given date.

    Orchestrates loading, validation, amount calculation, settlement
    date fixing, counterparty reconciliation, and output generation.

    Args:
        run_date: Date string in YYYYMMDD format (e.g. '20240315').
        config_path: Path to batch_config.ini. Uses default if None.

    Returns:
        ProcessingResult with summary statistics.
    """
    logger.info("Starting trade processing for run_date=%s", run_date)

    # 1. Load config
    config = load_config(config_path) if config_path else load_config()
    logger.info("Config loaded: %d settings", len(config))

    # 2. Load trades
    trade_file = _resolve_trade_file(run_date, config)
    trades_df = load_trades_csv(trade_file)
    total_loaded = len(trades_df)

    # 3. Validate
    valid_df, error_df = validate_trades(trades_df)
    duplicates_removed = total_loaded - len(valid_df) - len(error_df)
    validation_errors = len(error_df)

    if valid_df.empty:
        logger.warning("No valid trades after validation — aborting")
        return ProcessingResult(
            total_loaded=total_loaded,
            duplicates_removed=max(duplicates_removed, 0),
            validation_errors=validation_errors,
            matched=0,
            breaks=0,
            unmatched=0,
        )

    # 4. Calculate amounts
    valid_df = calculate_amounts(valid_df)

    # 5. Fix settlement dates
    valid_df = fix_settlement_dates(valid_df)

    # 6. Reconcile with counterparty confirms
    confirm_path = _resolve_counterparty_file(trade_file)
    if confirm_path is not None:
        confirms_df = load_counterparty_file(confirm_path)
    else:
        confirms_df = pd.DataFrame()

    valid_df = reconcile_trades(valid_df, confirms_df)

    # 7. Write outputs
    report_dir = Path(config.get("report_output", ""))
    if not report_dir.is_dir():
        report_dir = Path(__file__).resolve().parents[2] / "reports"

    output_csv = report_dir / f"processed_trades_{run_date}.csv"
    write_output_csv(valid_df, output_csv)

    log_dir = Path(config.get("log_output", ""))
    if not log_dir.is_dir():
        log_dir = report_dir

    error_log = log_dir / f"trade_errors_{run_date}.log"
    write_error_log(error_df, error_log)

    # 8. Build result summary
    matched = int((valid_df["recon_status"] == "MATCHED").sum())
    breaks = int(
        valid_df["recon_status"].isin(["PRICE_BREAK", "QTY_BREAK"]).sum()
    )
    unmatched = int((valid_df["recon_status"] == "UNMATCHED").sum())

    result = ProcessingResult(
        total_loaded=total_loaded,
        duplicates_removed=max(duplicates_removed, 0),
        validation_errors=validation_errors,
        matched=matched,
        breaks=breaks,
        unmatched=unmatched,
    )

    logger.info(
        "Processing complete: %d loaded, %d valid, %d matched, %d breaks, %d unmatched",
        result.total_loaded,
        result.total_loaded - result.duplicates_removed - result.validation_errors,
        result.matched,
        result.breaks,
        result.unmatched,
    )

    return result


def main() -> None:
    """CLI entry point for the trade processor."""
    parser = argparse.ArgumentParser(
        description="Meridian Capital Partners - Daily Trade Processor (Option A: Pandas)",
    )
    parser.add_argument(
        "--date",
        required=False,
        default=datetime.now().strftime("%Y%m%d"),
        help="Run date in YYYYMMDD format (default: today)",
    )
    parser.add_argument(
        "--config",
        required=False,
        default=None,
        help="Path to batch_config.ini (default: config/batch_config.ini)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config_path = Path(args.config) if args.config else None
    result = process_trades(args.date, config_path)

    logger.info("Result: %s", result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
