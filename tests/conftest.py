"""Shared fixtures for trade ingestion tests."""

from __future__ import annotations

import os
import tempfile

import pytest

# Synthetic CSV with deliberate issues:
#   - Row 6 is a duplicate of row 1 (same trade_id)
#   - Row 7 has an invalid broker ("FAKEB")
#   - Row 8 has zero quantity
#   - Row 9 has negative price
#   - Row 10 has missing price
#   - Rows 1-5 are valid
_SYNTHETIC_CSV = """\
TRADE_ID,ACCT_NUM,TICKER,SIDE,QTY,PRICE,TRADE_DATE,SETTLE_DATE,BROKER,COMMISSION,STATUS
T-001,ACC-1001,AAPL,BUY,100,150.00,01/02/2024,01/04/2024,GOLDMN,5.00,SETTLED
T-002,ACC-1002,MSFT,SELL,200,400.00,01/02/2024,01/04/2024,MRGST,8.00,SETTLED
T-003,ACC-1001,GOOGL,BUY,50,140.00,01/02/2024,01/04/2024,JPMC,6.00,PENDING
T-004,ACC-1003,AMZN,BUY,300,175.00,01/02/2024,01/04/2024,BARCL,10.00,SETTLED
T-005,ACC-1004,TSLA,SELL,150,250.00,01/02/2024,01/04/2024,CITI,7.50,SETTLED
T-001,ACC-1001,AAPL,BUY,100,150.00,01/02/2024,01/04/2024,GOLDMN,5.00,SETTLED
T-006,ACC-1005,META,BUY,80,480.00,01/02/2024,01/04/2024,FAKEB,12.00,SETTLED
T-007,ACC-1001,NVDA,BUY,0,800.00,01/02/2024,01/04/2024,UBS,15.00,SETTLED
T-008,ACC-1002,JPM,BUY,120,-50.00,01/02/2024,01/04/2024,GOLDMN,9.00,SETTLED
T-009,ACC-1003,V,SELL,60,,01/02/2024,01/04/2024,JPMC,4.00,FAILED
"""

EXPECTED_VALID_COUNT = 5
EXPECTED_VALID_IDS = {"T-001", "T-002", "T-003", "T-004", "T-005"}

EXPECTED_REJECTION_REASONS = {
    "T-001": "duplicate_trade_id",   # second occurrence
    "T-006": "invalid_broker",
    "T-007": "non_positive_quantity",
    "T-008": "non_positive_price",
    "T-009": "missing_price",
}


@pytest.fixture()
def synthetic_csv(tmp_path: pytest.TempPathFactory) -> str:
    """Write the synthetic CSV to a temp file and return its path."""
    path = os.path.join(str(tmp_path), "test_trades.csv")
    with open(path, "w") as fh:
        fh.write(_SYNTHETIC_CSV)
    return path
