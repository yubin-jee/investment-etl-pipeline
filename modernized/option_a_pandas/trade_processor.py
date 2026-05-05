"""Option A: Pandas + Pydantic standalone trade processor.

Replaces the legacy ``legacy_scripts/process_trades.py`` with a clean,
functional implementation that uses the shared ``modernized.common`` layer
for configuration, parsing, validation, and settlement-date logic.

Key improvements over the legacy script:
- No global state — all data is passed via function arguments/returns.
- O(n) hash-join reconciliation instead of O(n²) nested loops.
- Correct T+2 business-day settlement (skips weekends).
- Pydantic-validated trades with structured error reporting.
- Configurable via ``batch_config.ini`` (no hardcoded Windows paths).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from modernized.common.config import load_config
from modernized.common.models import ProcessingResult
from modernized.common.parsers import load_counterparty_file, load_trades_csv
from modernized.common.settlement import calculate_t_plus_2
from modernized.common.validation import validate_trades

# Corrected column specs for the counterparty fixed-width files actually
# shipped in this repository (76-char lines).  The common parser's specs
# target an 83-char layout that doesn't match the sample / legacy data,
# so we fall back to these when the common parser raises.
_CONFIRM_COLSPECS_FALLBACK = [
    (0, 14),   # trade_id
    (14, 22),  # account
    (22, 34),  # ticker
    (34, 38),  # side
    (38, 46),  # quantity (zero-padded)
    (46, 56),  # price (implied 2 decimals)
    (56, 59),  # currency
    (59, 67),  # date (MMDDYYYY)
    (67, 76),  # status
]

_CONFIRM_COL_NAMES = [
    "trade_id", "account", "ticker", "side",
    "quantity", "price", "currency", "date", "status",
]

logger = logging.getLogger(__name__)

# Repository root — used for fallback paths when config dirs don't exist
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_path(config_dir: str, filename: str, fallback_subdir: str) -> Path:
    """Return *config_dir / filename* if it exists, else fall back to a
    repo-relative legacy path or the test-data directory.

    Args:
        config_dir: Directory path from the config file (may be a Windows path
            that doesn't exist on this host).
        filename: Name of the file to locate.
        fallback_subdir: Repo-relative fallback directory
            (e.g. ``legacy_data/trades``).

    Returns:
        Resolved :class:`Path` to the file.

    Raises:
        FileNotFoundError: If no candidate path exists.
    """
    candidates = [
        Path(config_dir) / filename,
        _REPO_ROOT / fallback_subdir / filename,
        _REPO_ROOT / "modernized" / "test_data" / filename,
    ]

    for path in candidates:
        if path.exists():
            if path != candidates[0]:
                logger.info(
                    "Primary path %s not found; using fallback %s",
                    candidates[0],
                    path,
                )
            return path

    raise FileNotFoundError(
        f"File not found at any of: {', '.join(str(p) for p in candidates)}"
    )


def _load_counterparty_fallback(filepath: Path) -> pd.DataFrame:
    """Fallback parser for counterparty files when the common parser fails.

    Uses corrected column widths that match the 76-char lines in the
    repository's sample and legacy data files.
    """
    from io import StringIO

    trade_lines: list[str] = []
    with open(filepath, "r") as fh:
        for line in fh:
            if line.startswith("T-"):
                trade_lines.append(line)

    if not trade_lines:
        return pd.DataFrame(columns=_CONFIRM_COL_NAMES)

    buf = StringIO("\n".join(trade_lines))
    df = pd.read_fwf(
        buf,
        colspecs=_CONFIRM_COLSPECS_FALLBACK,
        names=_CONFIRM_COL_NAMES,
        header=None,
    )

    for col in ["trade_id", "account", "ticker", "side", "currency", "status"]:
        df[col] = df[col].astype(str).str.strip()

    df["quantity"] = df["quantity"].astype(int)
    df["price"] = df["price"].astype(float) / 100.0
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%m%d%Y")

    logger.info("Parsed %d counterparty confirms (fallback parser) from %s", len(df), filepath)
    return df


def _safe_load_counterparty(filepath: Path) -> pd.DataFrame:
    """Try the common parser first; fall back to corrected column widths."""
    try:
        return load_counterparty_file(filepath)
    except (ValueError, Exception) as exc:
        logger.warning(
            "Common parser failed (%s); retrying with fallback column specs",
            exc,
        )
        return _load_counterparty_fallback(filepath)


def _calculate_amounts(df: pd.DataFrame) -> pd.DataFrame:
    """Compute gross and net amounts for each trade row.

    - ``gross_amount = quantity * price``
    - BUY:  ``net_amount = gross_amount + commission``
    - SELL: ``net_amount = gross_amount - commission``

    All monetary values are rounded to 2 decimal places.
    """
    df = df.copy()
    df["gross_amount"] = (df["quantity"] * df["price"]).round(2)

    df["net_amount"] = df["gross_amount"] + df["commission"]
    sell_mask = df["side"].str.upper() == "SELL"
    df.loc[sell_mask, "net_amount"] = (
        df.loc[sell_mask, "gross_amount"] - df.loc[sell_mask, "commission"]
    )
    df["net_amount"] = df["net_amount"].round(2)

    return df


def _fill_missing_settlement_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Fill NaT settlement dates using T+2 business-day logic."""
    df = df.copy()
    missing = df["settle_date"].isna()
    if missing.any():
        logger.info("Filling %d missing settlement dates with T+2", missing.sum())
        df.loc[missing, "settle_date"] = df.loc[missing, "trade_date"].apply(
            lambda td: pd.Timestamp(calculate_t_plus_2(td.date()))
        )
    return df


def _reconcile(
    trades: pd.DataFrame, confirms: pd.DataFrame
) -> pd.DataFrame:
    """Reconcile trades against counterparty confirmations.

    Uses a left hash-join on ``trade_id`` (O(n)) instead of the legacy
    O(n²) nested loop.

    Reconciliation status:
    - MATCHED — price (within 0.01 tolerance) and quantity both agree.
    - PRICE_BREAK — price differs beyond tolerance.
    - QTY_BREAK — quantity differs.
    - UNMATCHED — no matching confirmation found.
    """
    confirms_renamed = confirms.rename(
        columns={"quantity": "confirm_qty", "price": "confirm_price"}
    )
    merged = pd.merge(
        trades,
        confirms_renamed[["trade_id", "confirm_qty", "confirm_price"]],
        on="trade_id",
        how="left",
    )

    def _status(row: pd.Series) -> str:
        if pd.isna(row.get("confirm_price")):
            return "UNMATCHED"
        if abs(row["price"] - row["confirm_price"]) > 0.01:
            return "PRICE_BREAK"
        if int(row["quantity"]) != int(row["confirm_qty"]):
            return "QTY_BREAK"
        return "MATCHED"

    merged["recon_status"] = merged.apply(_status, axis=1)
    return merged


def _write_output(
    df: pd.DataFrame, output_path: Path, run_date: str
) -> Path:
    """Write the processed-trades CSV report.

    Returns the path to the written file.
    """
    output_path.mkdir(parents=True, exist_ok=True)
    outfile = output_path / f"processed_trades_{run_date}.csv"

    processed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df = df.copy()
    df["processed_at"] = processed_at

    columns = [
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

    header_map = {
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

    out_df = df[columns].rename(columns=header_map)
    with open(outfile, "w", newline="") as fh:
        out_df.to_csv(fh, index=False)

    logger.info("Wrote %d trades to %s", len(out_df), outfile)
    return outfile


def _write_error_log(
    error_df: pd.DataFrame, output_path: Path, run_date: str
) -> Optional[Path]:
    """Write validation errors to a log file.

    Returns the path to the error log, or ``None`` if there were no errors.
    """
    if error_df.empty:
        logger.info("No validation errors to log")
        return None

    output_path.mkdir(parents=True, exist_ok=True)
    errfile = output_path / f"trade_errors_{run_date}.csv"
    with open(errfile, "w", newline="") as fh:
        error_df.to_csv(fh, index=False)

    logger.warning("Wrote %d validation errors to %s", len(error_df), errfile)
    return errfile


def process_trades(run_date: str, config_path: Path) -> ProcessingResult:
    """Run the full trade-processing pipeline for a given date.

    Steps:
        1. Load configuration.
        2. Read daily trade CSV.
        3. Validate trades (deduplicate, Pydantic checks, broker whitelist).
        4. Calculate gross/net amounts.
        5. Fill missing settlement dates (T+2).
        6. Load counterparty confirmations.
        7. Reconcile trades against confirmations.
        8. Write output CSV report.
        9. Write validation error log.

    Args:
        run_date: Processing date in ``YYYYMMDD`` format.
        config_path: Path to ``batch_config.ini``.

    Returns:
        :class:`ProcessingResult` with summary statistics.
    """
    logger.info("Starting trade processing for date=%s, config=%s", run_date, config_path)

    # 1. Load config
    config = load_config(config_path)
    trade_input_dir = config.get("trade_input", "")
    report_output_dir = config.get("report_output", "")
    log_output_dir = config.get("log_output", "")

    # 2. Read trade CSV
    trade_filename = f"daily_trades_{run_date}.csv"
    trade_file = _resolve_path(trade_input_dir, trade_filename, "legacy_data/trades")
    raw_df = load_trades_csv(trade_file)
    total_loaded = len(raw_df)

    # 3. Validate
    valid_df, error_df = validate_trades(raw_df)
    duplicates_removed = total_loaded - len(valid_df) - len(error_df)
    validation_errors = len(error_df)

    # 4. Calculate amounts
    valid_df = _calculate_amounts(valid_df)

    # 5. Fill missing settlement dates
    valid_df = _fill_missing_settlement_dates(valid_df)

    # 6. Load counterparty confirms
    confirms_df = pd.DataFrame()
    for confirm_filename in [
        f"counterparty_confirms_{run_date}.dat",
        "counterparty_confirms.dat",
    ]:
        try:
            confirm_file = _resolve_path(
                trade_input_dir, confirm_filename, "legacy_data/trades"
            )
            confirms_df = _safe_load_counterparty(confirm_file)
            break
        except FileNotFoundError:
            continue
    if confirms_df.empty:
        logger.warning("Counterparty file not found — skipping reconciliation")

    # 7. Reconcile
    if not confirms_df.empty:
        valid_df = _reconcile(valid_df, confirms_df)
    else:
        valid_df["recon_status"] = "UNMATCHED"

    matched = int((valid_df["recon_status"] == "MATCHED").sum())
    breaks = int(
        (valid_df["recon_status"].isin(["PRICE_BREAK", "QTY_BREAK"])).sum()
    )
    unmatched = int((valid_df["recon_status"] == "UNMATCHED").sum())

    # 8. Write output CSV
    report_path = Path(report_output_dir)
    if not report_path.exists():
        report_path = _REPO_ROOT / "reports"
    _write_output(valid_df, report_path, run_date)

    # 9. Write error log
    log_path = Path(log_output_dir) if log_output_dir else _REPO_ROOT / "reports"
    if not log_path.exists():
        log_path = _REPO_ROOT / "reports"
    _write_error_log(error_df, log_path, run_date)

    # 10. Build result
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
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Meridian Capital — Pandas + Pydantic Trade Processor"
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Run date in YYYYMMDD format (e.g. 20240315)",
    )
    parser.add_argument(
        "--config",
        default="config/batch_config.ini",
        help="Path to batch_config.ini (default: config/batch_config.ini)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config_path = Path(args.config)
    result = process_trades(args.date, config_path)

    print("\n" + "=" * 60)
    print("TRADE PROCESSING COMPLETE")
    print("=" * 60)
    print(f"  Total loaded:       {result.total_loaded}")
    print(f"  Duplicates removed: {result.duplicates_removed}")
    print(f"  Validation errors:  {result.validation_errors}")
    print(f"  Matched:            {result.matched}")
    print(f"  Breaks:             {result.breaks}")
    print(f"  Unmatched:          {result.unmatched}")
    print("=" * 60)


if __name__ == "__main__":
    main()
