"""Configuration loader — reads ``config/batch_config.ini`` and supports
environment-variable overrides via ``python-dotenv``.

Eliminates hardcoded ``C:\\MeridianData\\`` paths from legacy scripts.
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_BASE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _BASE_DIR / "config" / "batch_config.ini"


def _read_ini(path: Path | None = None) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    config_path = path or _DEFAULT_CONFIG
    if config_path.exists():
        cfg.read(str(config_path))
    return cfg


_cfg = _read_ini()


def get_path(key: str) -> str:
    """Return a filesystem path from the ``[paths]`` section, with env-var
    override support.  Falls back to ``legacy_data/<category>`` when the
    configured Windows path does not exist on the current host."""
    env_key = f"MERIDIAN_{key.upper()}"
    val = os.getenv(env_key)
    if val:
        return val
    val = _cfg.get("paths", key, fallback="")
    if val and os.path.exists(val):
        return val
    fallback_map = {
        "trade_input": str(_BASE_DIR / "legacy_data" / "trades"),
        "holdings_input": str(_BASE_DIR / "legacy_data" / "holdings"),
        "pricing_input": str(_BASE_DIR / "legacy_data" / "pricing"),
        "clients_input": str(_BASE_DIR / "legacy_data" / "clients"),
        "compliance_input": str(_BASE_DIR / "legacy_data" / "compliance"),
        "report_output": str(_BASE_DIR / "reports"),
        "log_output": str(_BASE_DIR / "reports"),
    }
    return fallback_map.get(key, val)


def get_db_connection_string() -> str:
    """Build a SQLAlchemy-compatible connection string from config or env."""
    conn = os.getenv("MERIDIAN_DB_URL")
    if conn:
        return conn
    server = _cfg.get("database", "server", fallback="localhost")
    database = _cfg.get("database", "database", fallback="MeridianOMS")
    return (
        f"mssql+pyodbc://{server}/{database}"
        "?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
    )


def get_tolerance(key: str, default: float = 0.0) -> float:
    """Read a tolerance value from ``[tolerances]``."""
    return float(_cfg.get("tolerances", key, fallback=str(default)))
