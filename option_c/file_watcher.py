"""File watcher using watchdog library.

Monitors a directory for new trade CSV files and counterparty
confirmation DAT files, triggering processing on arrival.
"""

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from option_c.store import TradeStore
from option_c.trade_processor import TradeEventProcessor

logger = logging.getLogger(__name__)


class TradeFileHandler(FileSystemEventHandler):
    """Handles file creation events for trade and confirm files."""

    def __init__(self, processor: TradeEventProcessor):
        self.processor = processor

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        logger.info("File detected: %s", file_path)

        if file_path.suffix == ".csv":
            try:
                self.processor.process_trade_file(file_path)
            except Exception:
                logger.exception("Error processing trade file: %s", file_path)
        elif file_path.suffix == ".dat":
            try:
                self.processor.process_confirm_file(file_path)
            except Exception:
                logger.exception("Error processing confirm file: %s", file_path)
        else:
            logger.debug("Ignoring file: %s", file_path)


def start_watcher(
    watch_dir: str | Path,
    store: TradeStore,
    output_dir: str | Path,
    timeout: float | None = None,
) -> Observer:
    """Start watching a directory for trade files.

    Args:
        watch_dir: Directory to monitor for new files.
        store: TradeStore instance for persistence.
        output_dir: Directory for output files.
        timeout: If set, stop after this many seconds (for demo/testing).

    Returns:
        The observer instance.
    """
    watch_dir = Path(watch_dir)
    watch_dir.mkdir(parents=True, exist_ok=True)

    processor = TradeEventProcessor(store=store, output_dir=output_dir)
    handler = TradeFileHandler(processor=processor)

    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)
    observer.start()
    logger.info("Watching %s for trade files...", watch_dir)

    if timeout is not None:
        try:
            time.sleep(timeout)
        finally:
            observer.stop()
            observer.join()
    return observer
