"""Tests for CSV and fixed-width file loaders."""

from datetime import date
from pathlib import Path

import pytest

from trade_processing.config import DEFAULT_CONFIRM_FILE, DEFAULT_TRADE_FILE
from trade_processing.loaders.csv_loader import load_trades
from trade_processing.loaders.fwf_loader import load_confirms


class TestCSVLoader:
    """Tests for csv_loader.load_trades()."""

    def test_loads_correct_number_of_rows(self):
        df = load_trades(DEFAULT_TRADE_FILE)
        assert len(df) == 15

    def test_column_names(self):
        df = load_trades(DEFAULT_TRADE_FILE)
        expected_cols = [
            "trade_id", "account_number", "ticker", "side",
            "quantity", "price", "trade_date", "settle_date",
            "broker", "commission", "status",
        ]
        for col in expected_cols:
            assert col in df.columns, f"Missing column: {col}"

    def test_trade_id_parsing(self):
        df = load_trades(DEFAULT_TRADE_FILE)
        assert df.iloc[0]["trade_id"] == "T-20240315-001"
        assert df.iloc[-1]["trade_id"] == "T-20240315-015"

    def test_numeric_types(self):
        df = load_trades(DEFAULT_TRADE_FILE)
        assert df["quantity"].dtype in ("int64", "int32")
        assert df["price"].dtype == "float64"
        assert df["commission"].dtype == "float64"

    def test_date_parsing(self):
        df = load_trades(DEFAULT_TRADE_FILE)
        first_trade_date = df.iloc[0]["trade_date"]
        assert first_trade_date == date(2024, 3, 15)

    def test_missing_settle_date(self):
        df = load_trades(DEFAULT_TRADE_FILE)
        # Trade T-20240315-011 has empty settle_date
        row = df[df["trade_id"] == "T-20240315-011"].iloc[0]
        assert row["settle_date"] is None

    def test_price_values(self):
        df = load_trades(DEFAULT_TRADE_FILE)
        first = df.iloc[0]
        assert first["price"] == pytest.approx(171.48)
        assert first["quantity"] == 500


class TestFWFLoader:
    """Tests for fwf_loader.load_confirms()."""

    def test_loads_correct_number_of_rows(self):
        df = load_confirms(DEFAULT_CONFIRM_FILE)
        # 10 trade records (excluding HDR and TRL lines)
        assert len(df) == 10

    def test_skips_header_and_trailer(self):
        df = load_confirms(DEFAULT_CONFIRM_FILE)
        # No HDR or TRL records
        assert not df["trade_id"].str.startswith("HDR").any()
        assert not df["trade_id"].str.startswith("TRL").any()

    def test_column_names(self):
        df = load_confirms(DEFAULT_CONFIRM_FILE)
        expected = ["trade_id", "account", "ticker", "side",
                     "quantity", "price", "currency", "trade_date", "status"]
        for col in expected:
            assert col in df.columns

    def test_trade_id_parsing(self):
        df = load_confirms(DEFAULT_CONFIRM_FILE)
        assert "T-20240315-001" in df["trade_id"].values

    def test_quantity_parsing(self):
        df = load_confirms(DEFAULT_CONFIRM_FILE)
        row = df[df["trade_id"] == "T-20240315-001"].iloc[0]
        assert row["quantity"] == 500

    def test_price_parsing(self):
        df = load_confirms(DEFAULT_CONFIRM_FILE)
        row = df[df["trade_id"] == "T-20240315-001"].iloc[0]
        assert row["price"] == pytest.approx(171.48)

    def test_date_parsing(self):
        df = load_confirms(DEFAULT_CONFIRM_FILE)
        row = df[df["trade_id"] == "T-20240315-001"].iloc[0]
        assert row["trade_date"] == date(2024, 3, 15)

    def test_currency(self):
        df = load_confirms(DEFAULT_CONFIRM_FILE)
        assert (df["currency"] == "USD").all()
