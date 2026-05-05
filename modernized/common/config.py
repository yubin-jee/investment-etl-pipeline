"""Configuration loader for batch_config.ini."""

from __future__ import annotations

import configparser
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    """Read ``batch_config.ini`` and return a flat settings dictionary.

    Parameters
    ----------
    config_path : Path
        Path to the INI file (e.g. ``config/batch_config.ini``).

    Returns
    -------
    dict
        Keys include ``trade_input``, ``holdings_input``, ``pricing_input``,
        ``report_output``, ``log_output``, ``db_server``, ``db_name``, and
        any other values present in the config file.
    """
    parser = configparser.ConfigParser()
    parser.read(config_path)

    cfg: dict = {}

    if parser.has_section("paths"):
        cfg["trade_input"] = parser.get("paths", "trade_input", fallback="")
        cfg["holdings_input"] = parser.get("paths", "holdings_input", fallback="")
        cfg["pricing_input"] = parser.get("paths", "pricing_input", fallback="")
        cfg["report_output"] = parser.get("paths", "report_output", fallback="")
        cfg["log_output"] = parser.get("paths", "log_output", fallback="")

    if parser.has_section("database"):
        cfg["db_server"] = parser.get("database", "server", fallback="")
        cfg["db_name"] = parser.get("database", "database", fallback="")

    if parser.has_section("tolerances"):
        cfg["recon_tolerance_usd"] = parser.getfloat(
            "tolerances", "recon_tolerance_usd", fallback=1.00
        )

    logger.info("Loaded config from %s", config_path)
    return cfg
