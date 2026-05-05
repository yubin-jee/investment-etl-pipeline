"""Configuration loader for batch_config.ini.

Replaces the legacy approach of hardcoded paths throughout scripts with
a centralized config that reads from the existing INI file.
"""

import configparser
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "batch_config.ini"


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Load configuration from the batch_config.ini file.

    Reads the INI file and returns a flat dictionary with the most
    commonly needed settings for the trade processing pipeline.

    Args:
        config_path: Path to the INI config file.

    Returns:
        Dictionary with keys:
        - trade_input, holdings_input, pricing_input, report_output,
          log_output: directory path strings
        - db_server, db_name: database connection info
        - recon_tolerance_usd: float tolerance for reconciliation
        - max_trade_errors: int max errors before aborting

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    parser = configparser.ConfigParser()
    parser.read(config_path)

    config = {
        # Paths
        "trade_input": parser.get("paths", "trade_input", fallback=""),
        "holdings_input": parser.get("paths", "holdings_input", fallback=""),
        "pricing_input": parser.get("paths", "pricing_input", fallback=""),
        "report_output": parser.get("paths", "report_output", fallback=""),
        "log_output": parser.get("paths", "log_output", fallback=""),
        # Database
        "db_server": parser.get("database", "server", fallback=""),
        "db_name": parser.get("database", "database", fallback=""),
        # Tolerances
        "recon_tolerance_usd": parser.getfloat(
            "tolerances", "recon_tolerance_usd", fallback=1.00
        ),
        "max_trade_errors": parser.getint(
            "tolerances", "max_trade_errors", fallback=50
        ),
    }

    logger.info("Loaded config from %s", config_path)
    return config
