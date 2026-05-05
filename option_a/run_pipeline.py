"""Option A: Pandas + SQLAlchemy — Minimal Lift sequential pipeline.

Direct modernization of legacy_scripts/process_trades.py with pandas,
proper error handling, and structured logging.
"""

import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from trade_processing.calculators import calculate_amounts
from trade_processing.config import DEFAULT_CONFIRM_FILE, DEFAULT_TRADE_FILE
from trade_processing.loaders.csv_loader import load_trades
from trade_processing.loaders.fwf_loader import load_confirms
from trade_processing.reconciliation import reconcile
from trade_processing.settlement import calculate_settlement_dates
from trade_processing.validators import validate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("option_a")

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def run(
    trade_file: str | Path | None = None,
    confirm_file: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Run the full trade processing pipeline sequentially."""
    trade_file = trade_file or DEFAULT_TRADE_FILE
    confirm_file = confirm_file or DEFAULT_CONFIRM_FILE
    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    logger.info("=" * 50)
    logger.info("OPTION A: Pandas + SQLAlchemy Sequential Pipeline")
    logger.info("Run Time: %s", datetime.now().isoformat())
    logger.info("=" * 50)

    # Step 1: Load trades
    step_start = time.time()
    trades_df = load_trades(trade_file)
    logger.info("Step 1 (Load Trades): %.3fs, %d rows", time.time() - step_start, len(trades_df))

    # Step 2: Load counterparty confirms
    step_start = time.time()
    confirms_df = load_confirms(confirm_file)
    logger.info("Step 2 (Load Confirms): %.3fs, %d rows", time.time() - step_start, len(confirms_df))

    # Step 3: Validate trades
    step_start = time.time()
    valid_trades_df, rejected_df = validate(trades_df)
    logger.info(
        "Step 3 (Validate): %.3fs, %d valid, %d rejected",
        time.time() - step_start,
        len(valid_trades_df),
        len(rejected_df),
    )

    # Step 4: Calculate settlement dates
    step_start = time.time()
    valid_trades_df = calculate_settlement_dates(valid_trades_df)
    logger.info("Step 4 (Settlement): %.3fs", time.time() - step_start)

    # Step 5: Calculate amounts
    step_start = time.time()
    valid_trades_df = calculate_amounts(valid_trades_df)
    logger.info("Step 5 (Amounts): %.3fs", time.time() - step_start)

    # Step 6: Reconcile with confirms
    step_start = time.time()
    result_df = reconcile(valid_trades_df, confirms_df)
    logger.info("Step 6 (Reconcile): %.3fs", time.time() - step_start)

    # Step 7: Add processed_at timestamp
    result_df["processed_at"] = datetime.now().isoformat()

    # Step 8: Write output
    step_start = time.time()
    output_file = output_dir / "processed_trades.csv"
    result_df.to_csv(output_file, index=False)
    logger.info("Step 7 (Write Output): %.3fs → %s", time.time() - step_start, output_file)

    if not rejected_df.empty:
        rejected_file = output_dir / "rejected_trades.csv"
        rejected_df.to_csv(rejected_file, index=False)
        logger.info("Wrote %d rejected trades → %s", len(rejected_df), rejected_file)

    # Summary
    total_time = time.time() - start_time
    matched = len(result_df[result_df["recon_status"] == "MATCHED"])
    breaks = len(result_df[result_df["recon_status"].isin(["PRICE_BREAK", "QTY_BREAK"])])
    unmatched = len(result_df[result_df["recon_status"] == "UNMATCHED"])

    logger.info("=" * 50)
    logger.info("PROCESSING COMPLETE")
    logger.info("Total Time: %.3fs", total_time)
    logger.info("Valid Trades: %d", len(result_df))
    logger.info("Rejected: %d", len(rejected_df))
    logger.info("Matched: %d | Breaks: %d | Unmatched: %d", matched, breaks, unmatched)
    logger.info("=" * 50)

    return result_df


if __name__ == "__main__":
    run()
