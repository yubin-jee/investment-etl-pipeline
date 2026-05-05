"""Dagster resources for trade file path configuration."""

from pathlib import Path

from dagster import ConfigurableResource


class TradeFileResource(ConfigurableResource):
    """Provides file paths for trade processing inputs and outputs."""

    base_dir: str = "legacy_data/trades"
    report_dir: str = "reports"
    run_date: str

    @property
    def trade_file_path(self) -> Path:
        return Path(self.base_dir) / f"daily_trades_{self.run_date}.csv"

    @property
    def confirm_file_path(self) -> Path:
        return Path(self.base_dir) / "counterparty_confirms.dat"

    @property
    def output_file_path(self) -> Path:
        return Path(self.report_dir) / f"processed_trades_{self.run_date}.csv"
