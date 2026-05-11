"""Event handler that dispatches file events to the processor.

Responsibilities:
  - Deduplicate events using file content hashes
  - Route events to the appropriate processor method
  - Provide dead-letter handling for files that fail processing
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Set

from watchdog.events import FileCreatedEvent, FileSystemEventHandler

from modernized.option_c_event_driven.processor import TradeProcessor

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file for deduplication."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class TradeFileHandler(FileSystemEventHandler):
    """Watchdog handler that dispatches new trade/confirm files to the processor."""

    def __init__(self, processor: TradeProcessor, dead_letter_dir: Path | None = None):
        super().__init__()
        self.processor = processor
        self.dead_letter_dir = dead_letter_dir or Path("dead_letter")
        self.dead_letter_dir.mkdir(parents=True, exist_ok=True)
        self._processed_hashes: Set[str] = set()

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return

        path = Path(event.src_path)
        logger.info("File detected: %s", path.name)

        # Deduplication via content hash
        try:
            fhash = _file_hash(path)
        except OSError:
            logger.warning("Could not read file for hashing: %s", path)
            return

        if fhash in self._processed_hashes:
            logger.info("Skipping duplicate file (same content hash): %s", path.name)
            return

        try:
            if path.name.startswith("daily_trades_") and path.suffix == ".csv":
                self.processor.receive_trade_file(path)
            elif path.name.endswith(".dat"):
                self.processor.receive_confirm_file(path)
            else:
                logger.debug("Ignoring unrecognised file: %s", path.name)
                return

            self._processed_hashes.add(fhash)
            self.processor.try_process()

        except Exception:
            logger.exception("Failed to process %s — moving to dead-letter", path.name)
            self._move_to_dead_letter(path)

    def _move_to_dead_letter(self, path: Path) -> None:
        """Move a file to the dead-letter directory for manual review."""
        dest = self.dead_letter_dir / path.name
        try:
            import shutil
            shutil.copy2(str(path), str(dest))
            logger.warning("Dead-lettered: %s -> %s", path.name, dest)
        except OSError:
            logger.exception("Could not dead-letter %s", path.name)
