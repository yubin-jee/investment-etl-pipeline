"""Tests for trade validation logic."""

from datetime import date

import pandas as pd
import pytest

from trade_processing.validators import validate


def _make_trade(overrides: dict | None = None) -> dict:
    """Create a sample trade dict with optional overrides."""
    trade = {
        "trade_id": "T-001",
        "account_number": "ACC-1001",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 100,
        "price": 150.0,
        "trade_date": date(2024, 3, 15),
        "settle_date": date(2024, 3, 19),
        "broker": "GOLDMN",
        "commission": 10.0,
        "status": "SETTLED",
    }
    if overrides:
        trade.update(overrides)
    return trade


class TestDuplicateRejection:
    def test_rejects_duplicate_trade_ids(self):
        trades = pd.DataFrame([
            _make_trade({"trade_id": "T-001"}),
            _make_trade({"trade_id": "T-001"}),
            _make_trade({"trade_id": "T-002"}),
        ])
        valid, rejected = validate(trades)
        assert len(valid) == 2
        assert len(rejected) == 1
        assert rejected.iloc[0]["reason"] == "DUPLICATE"

    def test_keeps_first_of_duplicates(self):
        trades = pd.DataFrame([
            _make_trade({"trade_id": "T-001", "quantity": 100}),
            _make_trade({"trade_id": "T-001", "quantity": 200}),
        ])
        valid, _ = validate(trades)
        assert len(valid) == 1
        assert valid.iloc[0]["quantity"] == 100


class TestBrokerValidation:
    def test_rejects_invalid_broker(self):
        trades = pd.DataFrame([
            _make_trade({"trade_id": "T-001", "broker": "INVALID"}),
        ])
        valid, rejected = validate(trades)
        assert len(valid) == 0
        assert len(rejected) == 1
        assert rejected.iloc[0]["reason"] == "INVALID_BROKER"

    def test_accepts_valid_brokers(self):
        valid_brokers = ["GOLDMN", "MRGST", "JPMC", "BARCL", "CITI", "UBS"]
        for broker in valid_brokers:
            trades = pd.DataFrame([
                _make_trade({"trade_id": f"T-{broker}", "broker": broker}),
            ])
            valid, rejected = validate(trades)
            assert len(valid) == 1, f"Broker {broker} should be valid"

    def test_custom_broker_list(self):
        trades = pd.DataFrame([
            _make_trade({"trade_id": "T-001", "broker": "CUSTOM"}),
        ])
        valid, rejected = validate(trades, valid_brokers=["CUSTOM"])
        assert len(valid) == 1


class TestQuantityValidation:
    def test_rejects_zero_quantity(self):
        trades = pd.DataFrame([
            _make_trade({"trade_id": "T-001", "quantity": 0}),
        ])
        valid, rejected = validate(trades)
        assert len(valid) == 0
        assert rejected.iloc[0]["reason"] == "INVALID_QUANTITY"

    def test_rejects_negative_quantity(self):
        trades = pd.DataFrame([
            _make_trade({"trade_id": "T-001", "quantity": -10}),
        ])
        valid, rejected = validate(trades)
        assert len(valid) == 0


class TestPriceValidation:
    def test_rejects_zero_price(self):
        trades = pd.DataFrame([
            _make_trade({"trade_id": "T-001", "price": 0}),
        ])
        valid, rejected = validate(trades)
        assert len(valid) == 0
        assert rejected.iloc[0]["reason"] == "INVALID_PRICE"

    def test_rejects_negative_price(self):
        trades = pd.DataFrame([
            _make_trade({"trade_id": "T-001", "price": -5.0}),
        ])
        valid, rejected = validate(trades)
        assert len(valid) == 0


class TestCombinedValidation:
    def test_multiple_errors(self):
        trades = pd.DataFrame([
            _make_trade({"trade_id": "T-001"}),  # valid
            _make_trade({"trade_id": "T-001"}),  # duplicate
            _make_trade({"trade_id": "T-002", "broker": "BAD"}),  # bad broker
            _make_trade({"trade_id": "T-003", "quantity": -1}),  # bad qty
            _make_trade({"trade_id": "T-004", "price": 0}),  # bad price
        ])
        valid, rejected = validate(trades)
        assert len(valid) == 1
        assert len(rejected) == 4

    def test_empty_input(self):
        trades = pd.DataFrame(columns=[
            "trade_id", "account_number", "ticker", "side",
            "quantity", "price", "trade_date", "settle_date",
            "broker", "commission", "status",
        ])
        valid, rejected = validate(trades)
        assert len(valid) == 0
        assert len(rejected) == 0
