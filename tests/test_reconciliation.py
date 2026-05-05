"""Tests for trade reconciliation."""

from datetime import date

import pandas as pd
import pytest

from trade_processing.reconciliation import reconcile


def _make_trades(overrides_list: list[dict] | None = None) -> pd.DataFrame:
    """Create a trades DataFrame."""
    defaults = {
        "trade_id": "T-001",
        "account_number": "ACC-1001",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 500,
        "price": 171.48,
        "gross_amount": 85740.0,
        "net_amount": 85752.5,
        "commission": 12.5,
        "trade_date": date(2024, 3, 15),
        "settle_date": date(2024, 3, 19),
        "broker": "GOLDMN",
        "status": "SETTLED",
    }
    if overrides_list is None:
        overrides_list = [{}]
    trades = []
    for overrides in overrides_list:
        trade = {**defaults, **overrides}
        trades.append(trade)
    return pd.DataFrame(trades)


def _make_confirms(overrides_list: list[dict] | None = None) -> pd.DataFrame:
    """Create a confirms DataFrame."""
    defaults = {
        "trade_id": "T-001",
        "account": "ACC-1001",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 500,
        "price": 171.48,
        "currency": "USD",
        "trade_date": date(2024, 3, 15),
        "status": "SETTLED",
    }
    if overrides_list is None:
        overrides_list = [{}]
    confirms = []
    for overrides in overrides_list:
        confirm = {**defaults, **overrides}
        confirms.append(confirm)
    return pd.DataFrame(confirms)


class TestMatched:
    def test_exact_match(self):
        trades = _make_trades([{"trade_id": "T-001"}])
        confirms = _make_confirms([{"trade_id": "T-001"}])
        result = reconcile(trades, confirms)
        assert result.iloc[0]["recon_status"] == "MATCHED"

    def test_price_within_tolerance(self):
        trades = _make_trades([{"trade_id": "T-001", "price": 171.48}])
        confirms = _make_confirms([{"trade_id": "T-001", "price": 171.489}])
        result = reconcile(trades, confirms)
        assert result.iloc[0]["recon_status"] == "MATCHED"


class TestPriceBreak:
    def test_price_diff_above_tolerance(self):
        trades = _make_trades([{"trade_id": "T-001", "price": 171.48}])
        confirms = _make_confirms([{"trade_id": "T-001", "price": 171.50}])
        result = reconcile(trades, confirms)
        assert result.iloc[0]["recon_status"] == "PRICE_BREAK"

    def test_large_price_diff(self):
        trades = _make_trades([{"trade_id": "T-001", "price": 100.0}])
        confirms = _make_confirms([{"trade_id": "T-001", "price": 200.0}])
        result = reconcile(trades, confirms)
        assert result.iloc[0]["recon_status"] == "PRICE_BREAK"


class TestQtyBreak:
    def test_quantity_mismatch(self):
        trades = _make_trades([{"trade_id": "T-001", "quantity": 500}])
        confirms = _make_confirms([{"trade_id": "T-001", "quantity": 400}])
        result = reconcile(trades, confirms)
        assert result.iloc[0]["recon_status"] == "QTY_BREAK"


class TestUnmatched:
    def test_no_confirm_for_trade(self):
        trades = _make_trades([{"trade_id": "T-001"}])
        confirms = _make_confirms([{"trade_id": "T-999"}])
        result = reconcile(trades, confirms)
        assert result.iloc[0]["recon_status"] == "UNMATCHED"

    def test_empty_confirms(self):
        trades = _make_trades([{"trade_id": "T-001"}])
        confirms = pd.DataFrame(columns=["trade_id", "quantity", "price"])
        result = reconcile(trades, confirms)
        assert result.iloc[0]["recon_status"] == "UNMATCHED"


class TestMultipleTrades:
    def test_mixed_statuses(self):
        trades = _make_trades([
            {"trade_id": "T-001", "price": 100.0, "quantity": 500},
            {"trade_id": "T-002", "price": 200.0, "quantity": 300},
            {"trade_id": "T-003", "price": 300.0, "quantity": 100},
        ])
        confirms = _make_confirms([
            {"trade_id": "T-001", "price": 100.0, "quantity": 500},   # MATCHED
            {"trade_id": "T-002", "price": 210.0, "quantity": 300},   # PRICE_BREAK
            # T-003 has no confirm → UNMATCHED
        ])
        result = reconcile(trades, confirms)
        status_map = dict(zip(result["trade_id"], result["recon_status"]))
        assert status_map["T-001"] == "MATCHED"
        assert status_map["T-002"] == "PRICE_BREAK"
        assert status_map["T-003"] == "UNMATCHED"
