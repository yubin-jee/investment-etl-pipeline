"""Dagster resources for trade processing.

Provides configurable resources that wrap file path resolution and
configuration loading for the trade processing pipeline.
"""

from __future__ import annotations

from pathlib import Path

from dagster import ConfigurableResource

from modernized.common.config import load_config


class TradeFileResource(ConfigurableResource):
    """Resource that provides file paths based on partition date and config.

    Wraps the batch_config.ini loader and resolves file paths for
    trade CSVs, counterparty confirmations, and output directories.

    Attributes:
        config_path: Path to batch_config.ini.
        base_dir: Base directory for resolving relative paths (project root).
    """

    config_path: str = "config/batch_config.ini"
    base_dir: str = "."

    def get_config(self) -> dict:
        """Load and return the parsed configuration."""
        return load_config(Path(self.config_path))

    def trade_file_path(self, run_date: str) -> Path:
        """Resolve the path to a daily trade CSV.

        Args:
            run_date: Date string in YYYYMMDD format.

        Returns:
            Path to the trade CSV file.
        """
        config = self.get_config()
        trade_dir = Path(config.get("trade_input", "legacy_data/trades"))
        if not trade_dir.is_absolute():
            trade_dir = Path(self.base_dir) / trade_dir
        return trade_dir / f"daily_trades_{run_date}.csv"

    def confirm_file_path(self) -> Path:
        """Resolve the path to the counterparty confirmations file.

        Returns:
            Path to the counterparty_confirms.dat file.
        """
        config = self.get_config()
        trade_dir = Path(config.get("trade_input", "legacy_data/trades"))
        if not trade_dir.is_absolute():
            trade_dir = Path(self.base_dir) / trade_dir
        return trade_dir / "counterparty_confirms.dat"

    def output_dir(self) -> Path:
        """Resolve the output directory path.

        Returns:
            Path to the report output directory (created if needed).
        """
        config = self.get_config()
        output = Path(config.get("report_output", "reports"))
        if not output.is_absolute():
            output = Path(self.base_dir) / output
        output.mkdir(parents=True, exist_ok=True)
        return output
