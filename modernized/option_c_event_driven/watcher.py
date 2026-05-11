"""Option C: Event-Driven file watcher for trade processing.

Uses ``watchdog`` to monitor a configurable input directory for new trade
files matching ``daily_trades_*.csv``.  On file arrival the processing
pipeline is triggered automatically — no fixed 6:30 AM schedule needed.

Cloud equivalents:
  - AWS:   S3 event notifications → Lambda / Step Functions
  - Azure: Blob Storage triggers  → Azure Functions / Logic Apps
  - GCP:   Cloud Storage triggers → Cloud Functions / Cloud Run

Usage:
    python -m modernized.option_c_event_driven.watcher --watch-dir ./legacy_data/trades
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from watchdog.observers import Observer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from modernized.option_c_event_driven.handler import TradeFileHandler
from modernized.option_c_event_driven.processor import TradeProcessor

load_dotenv()
logger = logging.getLogger(__name__)


def _configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def watch(
    watch_dir: str | Path,
    output_dir: str | Path | None = None,
    dead_letter_dir: str | Path | None = None,
    timeout: int | None = None,
) -> None:
    """Start watching *watch_dir* for new trade/confirm files.

    Parameters
    ----------
    watch_dir : path
        Directory to watch for incoming files.
    output_dir : path, optional
        Where to write processed output CSVs.
    dead_letter_dir : path, optional
        Where to move files that fail processing.
    timeout : int, optional
        If set, stop watching after this many seconds (useful for tests).
    """
    watch_dir = Path(watch_dir)
    if not watch_dir.exists():
        logger.error("Watch directory does not exist: %s", watch_dir)
        return

    processor = TradeProcessor(output_dir=str(output_dir) if output_dir else None)
    handler = TradeFileHandler(
        processor,
        dead_letter_dir=Path(dead_letter_dir) if dead_letter_dir else None,
    )

    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)
    observer.start()
    logger.info("Watching %s for trade files...", watch_dir)

    # Graceful shutdown
    running = True

    def _shutdown(signum, frame):
        nonlocal running
        logger.info("Received signal %s — shutting down", signum)
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    start = time.time()
    try:
        while running:
            time.sleep(1)
            if timeout and (time.time() - start) >= timeout:
                logger.info("Timeout reached (%ds) — stopping watcher", timeout)
                break
    finally:
        observer.stop()
        observer.join()
        logger.info("Watcher stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Option C: Event-driven trade watcher")
    parser.add_argument(
        "--watch-dir",
        default=os.environ.get("TRADE_DIR", str(PROJECT_ROOT / "legacy_data" / "trades")),
        help="Directory to watch for trade files",
    )
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--dead-letter-dir", help="Dead-letter directory")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    _configure_logging(args.log_level)
    watch(args.watch_dir, args.output_dir, args.dead_letter_dir)


if __name__ == "__main__":
    main()
