"""Shared configuration for trade processing pipeline."""

from pathlib import Path

# Valid brokers (extracted from legacy VALID_BROKERS constant)
VALID_BROKERS = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]

# Default data paths (relative to repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DATA_DIR = REPO_ROOT / "legacy_data" / "trades"
DEFAULT_TRADE_FILE = LEGACY_DATA_DIR / "daily_trades_20240315.csv"
DEFAULT_CONFIRM_FILE = LEGACY_DATA_DIR / "counterparty_confirms.dat"

# Commission rate in basis points (1 bp = 0.01%)
DEFAULT_COMMISSION_BPS = None  # Legacy uses CSV-provided commission values

# Reconciliation tolerance
PRICE_TOLERANCE = 0.01

# Fixed-width counterparty confirmation column specs
# NOTE: The legacy code comments (lines 164-176) documented wider positions
# (0-16, 16-26, etc.) which don't match the actual data file format.
# These corrected positions were reverse-engineered from the sample data.
CONFIRM_COLSPECS = [
    (0, 14),   # trade_id
    (14, 24),  # account
    (24, 34),  # ticker
    (34, 38),  # side
    (38, 46),  # quantity (zero-padded int)
    (46, 56),  # price (implied 2 decimals, divide by 100)
    (56, 59),  # currency
    (59, 67),  # trade_date (MMDDYYYY)
    (67, 76),  # status
]

CONFIRM_COLUMN_NAMES = [
    "trade_id", "account", "ticker", "side",
    "quantity", "price", "currency", "trade_date", "status",
]
