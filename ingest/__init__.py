"""
Trade ingestion modules for Meridian Capital Partners.

Provides three parallel implementations (pandas, polars, DuckDB) of
``load_trades()`` and ``validate_trades()`` as drop-in replacements for
the legacy ``process_trades.py`` script.
"""

VALID_BROKERS: list[str] = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]

CSV_COLUMNS: list[str] = [
    "trade_id",
    "account",
    "ticker",
    "side",
    "quantity",
    "price",
    "trade_date",
    "settle_date",
    "broker",
    "commission",
    "status",
]
