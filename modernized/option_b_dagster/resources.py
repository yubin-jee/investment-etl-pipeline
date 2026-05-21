"""Dagster resources for trade file I/O and configuration."""

from __future__ import annotations

from pathlib import Path

from dagster import ConfigurableResource

from modernized.common.config import load_config


class TradeFileResource(ConfigurableResource):
    """Provides file paths and configuration for trade processing assets."""

    base_dir: str
    config_path: str

    def get_trade_file_path(self, partition_date: str) -> Path:
        """Return the path to the daily trade CSV for a given partition date.

        Args:
            partition_date: Date string in YYYY-MM-DD format.

        Returns:
            Path to the trade CSV file (e.g. daily_trades_20240115.csv).
        """
        date_str = partition_date.replace("-", "")
        return Path(self.base_dir) / f"daily_trades_{date_str}.csv"

    def get_confirm_file_path(self) -> Path:
        """Return the path to the counterparty confirmations file."""
        return Path(self.base_dir) / "counterparty_confirms.dat"

    def get_output_dir(self) -> Path:
        """Return (and create) the output directory for processed results."""
        output_dir = Path(self.base_dir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_config(self) -> dict:
        """Load and return the batch configuration dictionary."""
        return load_config(Path(self.config_path))
