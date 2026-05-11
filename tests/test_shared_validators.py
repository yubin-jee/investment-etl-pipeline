"""Tests for validation logic including duplicate detection, broker validation,
and the corrected T+2 settlement date calculation.
"""

from datetime import date

import pytest

from modernized.shared.models import Trade
from modernized.shared.validators import calculate_t_plus_2, validate_trades


def _make_trade(**overrides) -> Trade:
    defaults = dict(
        trade_id="T-001",
        account="ACC-1001",
        ticker="AAPL",
        side="BUY",
        quantity=100,
        price=150.0,
        trade_date="03/15/2024",
        settle_date="03/19/2024",
        broker="GOLDMN",
        commission=10.0,
        status="SETTLED",
    )
    defaults.update(overrides)
    return Trade(**defaults)


class TestCalculateTPlusTwo:
    def test_normal_weekday(self):
        # Friday 2024-03-15 -> T+2 = Tuesday 2024-03-19
        assert calculate_t_plus_2(date(2024, 3, 15)) == date(2024, 3, 19)

    def test_monday(self):
        # Monday 2024-03-18 -> T+2 = Wednesday 2024-03-20
        assert calculate_t_plus_2(date(2024, 3, 18)) == date(2024, 3, 20)

    def test_wednesday(self):
        # Wednesday 2024-03-13 -> T+2 = Friday 2024-03-15
        assert calculate_t_plus_2(date(2024, 3, 13)) == date(2024, 3, 15)

    def test_thursday_spans_weekend(self):
        # Thursday 2024-03-14 -> T+2 = Monday 2024-03-18
        assert calculate_t_plus_2(date(2024, 3, 14)) == date(2024, 3, 18)

    def test_month_boundary(self):
        # Friday 2024-03-29 -> T+2 = Tuesday 2024-04-02
        assert calculate_t_plus_2(date(2024, 3, 29)) == date(2024, 4, 2)

    def test_year_boundary(self):
        # Friday 2023-12-29 -> T+2 = Tuesday 2024-01-02
        assert calculate_t_plus_2(date(2023, 12, 29)) == date(2024, 1, 2)


class TestValidateTrades:
    def test_valid_trades(self):
        trades = [_make_trade(trade_id="T-001"), _make_trade(trade_id="T-002")]
        valid, errors = validate_trades(trades)
        assert len(valid) == 2
        assert len(errors) == 0

    def test_duplicate_detection(self):
        trades = [_make_trade(trade_id="T-001"), _make_trade(trade_id="T-001")]
        valid, errors = validate_trades(trades)
        assert len(valid) == 1
        assert len(errors) == 1
        assert errors[0]["error"] == "DUPLICATE"

    def test_fills_missing_settle_date(self):
        t = _make_trade(settle_date=None, trade_date="03/15/2024")
        valid, errors = validate_trades([t])
        assert len(valid) == 1
        # Friday 2024-03-15 -> T+2 = Tuesday 2024-03-19
        assert valid[0].settle_date == date(2024, 3, 19)

    def test_preserves_existing_settle_date(self):
        t = _make_trade(settle_date="03/20/2024", trade_date="03/15/2024")
        valid, _ = validate_trades([t])
        assert valid[0].settle_date == date(2024, 3, 20)
