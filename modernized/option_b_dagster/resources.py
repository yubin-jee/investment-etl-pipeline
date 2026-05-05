"""Dagster resources for trade file access and configuration."""

from pathlib import Path

from dagster import ConfigurableResource

from modernized.common.config import load_config


class TradeFileResource(ConfigurableResource):
    """Resource providing file paths and configuration for trade processing.

    Resolves trade file locations from the batch config INI file,
    falling back to conventional paths under base_data_dir.
    """

    base_data_dir: str = "legacy_data"
    config_path: str = "config/batch_config.ini"

    def get_trade_file_path(self, run_date: str) -> Path:
        """Return the path to the daily trades CSV for a given run date."""
        config = self.get_config()
        trade_input = config.get("trade_input", "").strip()
        if trade_input:
            directory = Path(trade_input)
        else:
            directory = Path(self.base_data_dir) / "trades"
        return directory / f"daily_trades_{run_date}.csv"

    def get_confirm_file_path(self) -> Path:
        """Return the path to the counterparty confirms file."""
        config = self.get_config()
        trade_input = config.get("trade_input", "").strip()
        if trade_input:
            directory = Path(trade_input)
        else:
            directory = Path(self.base_data_dir) / "trades"
        return directory / "counterparty_confirms.dat"

    def get_output_dir(self) -> Path:
        """Return the output directory, creating it if it does not exist."""
        config = self.get_config()
        report_output = config.get("report_output", "").strip()
        if report_output:
            output_dir = Path(report_output)
        else:
            output_dir = Path(self.base_data_dir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_config(self) -> dict:
        """Load and return the batch configuration dictionary."""
        return load_config(Path(self.config_path))
