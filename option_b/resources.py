"""Dagster resources for configurable file paths.

Replaces hardcoded C:\\MeridianData\\ paths with configurable resources.
"""

from pathlib import Path

from dagster import ConfigurableResource

from trade_processing.config import DEFAULT_CONFIRM_FILE, DEFAULT_TRADE_FILE


class FilePathResource(ConfigurableResource):
    """Configurable file paths for trade data."""

    trade_file: str = str(DEFAULT_TRADE_FILE)
    confirm_file: str = str(DEFAULT_CONFIRM_FILE)
    output_dir: str = str(Path(__file__).resolve().parent / "output")

    @property
    def trade_path(self) -> Path:
        return Path(self.trade_file)

    @property
    def confirm_path(self) -> Path:
        return Path(self.confirm_file)

    @property
    def output_path(self) -> Path:
        p = Path(self.output_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
