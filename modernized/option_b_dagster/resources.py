"""Dagster resources for the trade-processing asset graph.

The :class:`TradeFileResource` wraps the shared :func:`modernized.common.config`
loader and resolves the per-partition input/output file paths. The legacy
``batch_config.ini`` points at Windows network drives that do not exist on this
host, so the resource transparently falls back to the committed sample data
(``modernized/test_data``) and the real legacy data (``legacy_data/trades``).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from dagster import ConfigurableResource
from pydantic import PrivateAttr

from modernized.common import config


class TradeFileResource(ConfigurableResource):
    """Resolve trade/confirm input files and output paths for a partition date.

    Attributes:
        config_path: Path to ``batch_config.ini`` (relative to the repo root).
        test_data_dir: Directory holding the committed sample data.
        legacy_data_dir: Directory holding the real legacy trade files.
        output_dir: Directory where reconciled reports / error logs are written.
    """

    config_path: str = "config/batch_config.ini"
    test_data_dir: str = "modernized/test_data"
    legacy_data_dir: str = "legacy_data/trades"
    output_dir: str = "modernized/option_b_dagster/output"

    _config: dict[str, Any] = PrivateAttr()

    def setup_for_execution(self, context) -> None:  # noqa: D401, ANN001
        """Load and cache the parsed INI config once per execution."""
        self._config = config.load_config(Path(self.config_path))

    @property
    def config(self) -> dict[str, Any]:
        """Return the parsed ``batch_config.ini`` dict (lazily loaded)."""
        if not hasattr(self, "_config") or self._config is None:
            self._config = config.load_config(Path(self.config_path))
        return self._config

    @staticmethod
    def _compact_date(partition_key: str) -> str:
        """Convert a ``YYYY-MM-DD`` partition key to ``YYYYMMDD``."""
        return datetime.strptime(partition_key, "%Y-%m-%d").strftime("%Y%m%d")

    def _search_dirs(self) -> list[Path]:
        """Candidate directories to search for input files, in priority order."""
        dirs: list[Path] = []
        configured = self.config.get("trade_input", "")
        if configured:
            dirs.append(Path(configured))
        dirs.append(Path(self.test_data_dir))
        dirs.append(Path(self.legacy_data_dir))
        return dirs

    def trade_file(self, partition_key: str) -> Path:
        """Return the trade CSV for ``partition_key`` (falls back to test data).

        Args:
            partition_key: Dagster partition key in ``YYYY-MM-DD`` form.

        Returns:
            The first ``daily_trades_<YYYYMMDD>.csv`` that exists across the
            candidate directories; defaults to the sample file if none match.
        """
        compact = self._compact_date(partition_key)
        filename = f"daily_trades_{compact}.csv"
        for directory in self._search_dirs():
            candidate = directory / filename
            if candidate.exists():
                return candidate
        return Path(self.test_data_dir) / "daily_trades_20240115.csv"

    def confirm_file(self, partition_key: str) -> Path:
        """Return the counterparty confirmation file for ``partition_key``.

        Args:
            partition_key: Dagster partition key in ``YYYY-MM-DD`` form.

        Returns:
            The first ``counterparty_confirms.dat`` that exists across the
            candidate directories; defaults to the sample file if none match.
        """
        for directory in self._search_dirs():
            candidate = directory / "counterparty_confirms.dat"
            if candidate.exists():
                return candidate
        return Path(self.test_data_dir) / "counterparty_confirms.dat"

    def report_path(self, partition_key: str) -> Path:
        """Return the output report CSV path, ensuring the directory exists."""
        compact = self._compact_date(partition_key)
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"reconciled_trades_{compact}.csv"

    def error_log_path(self, partition_key: str) -> Path:
        """Return the error-log CSV path, ensuring the directory exists."""
        compact = self._compact_date(partition_key)
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"trade_errors_{compact}.csv"
