"""Tests for CSV and fixed-width file parsers against sample data."""

from datetime import date
from pathlib import Path

import pytest

from modernized.shared.parsers import parse_counterparty_dat, parse_trade_csv

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "legacy_data" / "trades"
TRADE_FILE = SAMPLE_DIR / "daily_trades_20240315.csv"
CONFIRM_FILE = SAMPLE_DIR / "counterparty_confirms.dat"


class TestParseTradeCSV:
    def test_parses_correct_count(self):
        trades = parse_trade_csv(TRADE_FILE)
        assert len(trades) == 15

    def test_first_trade_fields(self):
        trades = parse_trade_csv(TRADE_FILE)
        t = trades[0]
        assert t.trade_id == "T-20240315-001"
        assert t.account == "ACC-1001"
        assert t.ticker == "AAPL"
        assert t.side == "BUY"
        assert t.quantity == 500
        assert abs(t.price - 171.48) < 0.001
        assert t.trade_date == date(2024, 3, 15)
        assert t.settle_date == date(2024, 3, 19)
        assert t.broker.value == "GOLDMN"
        assert abs(t.commission - 12.50) < 0.001
        assert t.status == "SETTLED"

    def test_missing_settle_date(self):
        """Trade T-20240315-011 has an empty settle date in the CSV."""
        trades = parse_trade_csv(TRADE_FILE)
        t011 = [t for t in trades if t.trade_id == "T-20240315-011"][0]
        assert t011.settle_date is None

    def test_all_sides_valid(self):
        trades = parse_trade_csv(TRADE_FILE)
        for t in trades:
            assert t.side in ("BUY", "SELL")


class TestParseCounterpartyDat:
    def test_parses_correct_count(self):
        confirms = parse_counterparty_dat(CONFIRM_FILE)
        # 4 (GOLDMN) + 3 (MORGAN STANLEY) + 3 (JP MORGAN) = 10
        assert len(confirms) == 10

    def test_first_confirm_fields(self):
        confirms = parse_counterparty_dat(CONFIRM_FILE)
        c = confirms[0]
        assert c.trade_id == "T-20240315-001"
        assert c.account == "ACC-1001"
        assert c.ticker == "AAPL"
        assert c.side == "BUY"
        assert c.quantity == 500
        assert abs(c.price - 171.48) < 0.001
        assert c.currency == "USD"
        assert c.trade_date == date(2024, 3, 15)
        assert c.status == "SETTLED"

    def test_broker_names_extracted(self):
        confirms = parse_counterparty_dat(CONFIRM_FILE)
        brokers = {c.broker for c in confirms}
        assert "GOLDMN SACHS" in brokers
        assert "MORGAN STANLEY" in brokers
        assert "JP MORGAN CHASE" in brokers

    def test_implied_decimal_price(self):
        """Prices in the .dat file have implied 2 decimal places."""
        confirms = parse_counterparty_dat(CONFIRM_FILE)
        c_msft = [c for c in confirms if c.ticker == "MSFT"][0]
        assert abs(c_msft.price - 412.27) < 0.001
