#!/usr/bin/env python
"""
Centralized, OS-agnostic configuration for the Meridian ETL scripts.

Replaces the old hardcoded Windows network-drive paths (``C:\\MeridianData\\``)
with configurable, ``pathlib.Path``-based locations that work on Linux and
inside containers. Values are resolved in this order of precedence:

1. Environment variables (optionally loaded from a ``.env`` file)
2. ``config/batch_config.ini`` ``[paths]`` section
3. Repo-local defaults (``legacy_data/``, ``reports/``, ``logs/``)
"""

import configparser
import os
from pathlib import Path

# Optional: load variables from a .env file if python-dotenv is installed.
try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional; env vars still work without it
    load_dotenv = None

REPO_ROOT = Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env")

CONFIG_FILE = Path(
    os.environ.get("MERIDIAN_CONFIG_FILE", REPO_ROOT / "config" / "batch_config.ini")
)

_config = configparser.ConfigParser()
if CONFIG_FILE.exists():
    _config.read(CONFIG_FILE)


def _resolve(path_str):
    """Resolve a path string relative to the repo root when it is not absolute."""
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _get_dir(env_var, ini_key, default):
    """Resolve a directory using env var, then ini [paths], then default."""
    value = os.environ.get(env_var)
    if not value and _config.has_option("paths", ini_key):
        value = _config.get("paths", ini_key)
    if not value:
        value = default
    return _resolve(value)


# Base directories (env var > ini > repo-local default)
DATA_DIR = _get_dir("MERIDIAN_DATA_DIR", "data_dir", "legacy_data")
REPORT_DIR = _get_dir("MERIDIAN_REPORT_DIR", "report_dir", "reports")
LOG_DIR = _get_dir("MERIDIAN_LOG_DIR", "log_dir", "logs")

# Input subdirectories derived from the base data directory
TRADE_DIR = DATA_DIR / "trades"
HOLDINGS_DIR = DATA_DIR / "holdings"
PRICING_DIR = DATA_DIR / "pricing"
CLIENTS_DIR = DATA_DIR / "clients"
COMPLIANCE_DIR = DATA_DIR / "compliance"


def ensure_dirs():
    """Create output directories if they do not already exist."""
    for directory in (REPORT_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
