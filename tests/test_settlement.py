"""Tests for T+2 settlement date calculation."""

from datetime import date

import pandas as pd
import pytest

from trade_processing.settlement import calculate_settlement_dates


def _make_trades_df(trade_dates: list[date]) -> pd.DataFrame:
    """Create a DataFrame with the given trade dates."""
    return pd.DataFrame({
        "trade_id": [f"T-{i}" for i in range(len(trade_dates))],
        "trade_date": trade_dates,
        "settle_date": [None] * len(trade_dates),
        "account_number": ["ACC-1001"] * len(trade_dates),
        "ticker": ["AAPL"] * len(trade_dates),
        "side": ["BUY"] * len(trade_dates),
        "quantity": [100] * len(trade_dates),
        "price": [150.0] * len(trade_dates),
        "broker": ["GOLDMN"] * len(trade_dates),
        "commission": [10.0] * len(trade_dates),
        "status": ["PENDING"] * len(trade_dates),
    })


class TestWeekdaySettlement:
    def test_monday_settles_wednesday(self):
        df = _make_trades_df([date(2024, 3, 11)])  # Monday
        result = calculate_settlement_dates(df)
        assert result.iloc[0]["settle_date"] == date(2024, 3, 13)  # Wednesday

    def test_tuesday_settles_thursday(self):
        df = _make_trades_df([date(2024, 3, 12)])  # Tuesday
        result = calculate_settlement_dates(df)
        assert result.iloc[0]["settle_date"] == date(2024, 3, 14)  # Thursday

    def test_wednesday_settles_friday(self):
        df = _make_trades_df([date(2024, 3, 13)])  # Wednesday
        result = calculate_settlement_dates(df)
        assert result.iloc[0]["settle_date"] == date(2024, 3, 15)  # Friday


class TestWeekendSkipping:
    def test_thursday_settles_monday(self):
        """T+2 from Thursday skips weekend → Monday."""
        df = _make_trades_df([date(2024, 3, 14)])  # Thursday
        result = calculate_settlement_dates(df)
        assert result.iloc[0]["settle_date"] == date(2024, 3, 18)  # Monday

    def test_friday_settles_tuesday(self):
        """T+2 from Friday skips weekend → Tuesday."""
        df = _make_trades_df([date(2024, 3, 15)])  # Friday
        result = calculate_settlement_dates(df)
        assert result.iloc[0]["settle_date"] == date(2024, 3, 19)  # Tuesday

    def test_legacy_would_be_wrong_for_friday(self):
        """Legacy code adds 2 calendar days to Friday → Sunday (wrong).
        Our code should give Tuesday."""
        df = _make_trades_df([date(2024, 3, 15)])  # Friday
        result = calculate_settlement_dates(df)
        # Legacy would give 03/17/2024 (Sunday) — our code gives 03/19/2024 (Tuesday)
        assert result.iloc[0]["settle_date"] != date(2024, 3, 17)
        assert result.iloc[0]["settle_date"] == date(2024, 3, 19)


class TestMonthEndBoundary:
    def test_month_end_crossing(self):
        """Settlement crosses month boundary correctly."""
        df = _make_trades_df([date(2024, 3, 28)])  # Thursday
        result = calculate_settlement_dates(df)
        assert result.iloc[0]["settle_date"] == date(2024, 4, 1)  # Monday (April 1)

    def test_february_end(self):
        """T+2 from Feb 28 in leap year."""
        df = _make_trades_df([date(2024, 2, 28)])  # Wednesday (leap year)
        result = calculate_settlement_dates(df)
        assert result.iloc[0]["settle_date"] == date(2024, 3, 1)  # Friday


class TestYearEndBoundary:
    def test_year_end_crossing(self):
        """Settlement crosses year boundary."""
        df = _make_trades_df([date(2024, 12, 30)])  # Monday
        result = calculate_settlement_dates(df)
        assert result.iloc[0]["settle_date"] == date(2025, 1, 1)  # Wednesday

    def test_friday_before_new_year(self):
        """T+2 from Friday Dec 27 → Tuesday Dec 31."""
        df = _make_trades_df([date(2024, 12, 27)])  # Friday
        result = calculate_settlement_dates(df)
        assert result.iloc[0]["settle_date"] == date(2024, 12, 31)  # Tuesday
