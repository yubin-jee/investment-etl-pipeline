"""Entry point for event-driven trade processing pipeline.

Starts the file watcher. Includes a demo mode that copies sample files
into the watched directory to trigger processing.
"""

import argparse
import logging
import shutil
import time
from pathlib import Path

import pandas as pd

from option_c.file_watcher import start_watcher
from option_c.store import TradeStore
from trade_processing.config import DEFAULT_CONFIRM_FILE, DEFAULT_TRADE_FILE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("option_c")

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = BASE_DIR / "trades.db"


def run_demo(
    trade_file: str | Path | None = None,
    confirm_file: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Run in demo mode: copy sample files to trigger processing, then return results."""
    trade_file = Path(trade_file) if trade_file else DEFAULT_TRADE_FILE
    confirm_file = Path(confirm_file) if confirm_file else DEFAULT_CONFIRM_FILE
    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR

    # Clean up previous run
    input_dir = INPUT_DIR
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir.parent / "trades.db"

    store = TradeStore(db_path=db_path)
    store.clear()

    from option_c.trade_processor import TradeEventProcessor

    processor = TradeEventProcessor(store=store, output_dir=output_dir)

    logger.info("=" * 50)
    logger.info("OPTION C: Event-Driven Pipeline (Demo Mode)")
    logger.info("=" * 50)

    # Process trade file
    start = time.time()
    processor.process_trade_file(trade_file)
    logger.info("Trade processing: %.3fs", time.time() - start)

    # Process confirm file
    start = time.time()
    result_df = processor.process_confirm_file(confirm_file)
    logger.info("Confirm processing: %.3fs", time.time() - start)

    logger.info("=" * 50)
    logger.info("DEMO COMPLETE")
    logger.info("=" * 50)

    return result_df


def run_watcher_mode() -> None:
    """Run in watcher mode: monitor input directory for files."""
    input_dir = INPUT_DIR
    store = TradeStore(db_path=DB_PATH)

    logger.info("Starting file watcher on %s", input_dir)
    logger.info("Drop CSV files for trades, DAT files for confirms.")
    logger.info("Press Ctrl+C to stop.")

    observer = start_watcher(
        watch_dir=input_dir,
        store=store,
        output_dir=OUTPUT_DIR,
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
        logger.info("Watcher stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Option C: Event-Driven Trade Processing")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run demo mode: process sample files directly",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        run_watcher_mode()
