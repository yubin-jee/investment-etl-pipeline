"""Tests for trade amount calculations."""

from datetime import date

import pandas as pd
import pytest

from trade_processing.calculators import calculate_amounts


def _make_trade_df(side: str, quantity: int, price: float, commission: float) -> pd.DataFrame:
    return pd.DataFrame([{
        "trade_id": "T-001",
        "account_number": "ACC-1001",
        "ticker": "AAPL",
        "side": side,
        "quantity": quantity,
        "price": price,
        "commission": commission,
        "trade_date": date(2024, 3, 15),
        "settle_date": date(2024, 3, 19),
        "broker": "GOLDMN",
        "status": "SETTLED",
    }])


class TestBuySide:
    def test_gross_amount(self):
        df = _make_trade_df("BUY", 500, 171.48, 12.50)
        result = calculate_amounts(df)
        assert result.iloc[0]["gross_amount"] == pytest.approx(85740.0)

    def test_net_amount_includes_commission(self):
        """For BUY: net = gross + commission."""
        df = _make_trade_df("BUY", 500, 171.48, 12.50)
        result = calculate_amounts(df)
        assert result.iloc[0]["net_amount"] == pytest.approx(85752.5)

    def test_net_greater_than_gross_for_buy(self):
        df = _make_trade_df("BUY", 100, 100.0, 5.0)
        result = calculate_amounts(df)
        assert result.iloc[0]["net_amount"] > result.iloc[0]["gross_amount"]


class TestSellSide:
    def test_gross_amount(self):
        df = _make_trade_df("SELL", 200, 412.27, 8.00)
        result = calculate_amounts(df)
        assert result.iloc[0]["gross_amount"] == pytest.approx(82454.0)

    def test_net_amount_deducts_commission(self):
        """For SELL: net = gross - commission."""
        df = _make_trade_df("SELL", 200, 412.27, 8.00)
        result = calculate_amounts(df)
        assert result.iloc[0]["net_amount"] == pytest.approx(82446.0)

    def test_net_less_than_gross_for_sell(self):
        df = _make_trade_df("SELL", 100, 100.0, 5.0)
        result = calculate_amounts(df)
        assert result.iloc[0]["net_amount"] < result.iloc[0]["gross_amount"]


class TestRounding:
    def test_amounts_rounded_to_2_decimals(self):
        df = _make_trade_df("BUY", 3, 33.333, 1.111)
        result = calculate_amounts(df)
        gross = result.iloc[0]["gross_amount"]
        net = result.iloc[0]["net_amount"]
        assert gross == round(gross, 2)
        assert net == round(net, 2)


class TestMultipleTrades:
    def test_calculates_for_all_rows(self):
        df = pd.DataFrame([
            {"trade_id": "T-001", "side": "BUY", "quantity": 100, "price": 50.0,
             "commission": 5.0, "account_number": "A", "ticker": "X",
             "trade_date": date(2024, 1, 1), "settle_date": date(2024, 1, 3),
             "broker": "GOLDMN", "status": "SETTLED"},
            {"trade_id": "T-002", "side": "SELL", "quantity": 200, "price": 75.0,
             "commission": 10.0, "account_number": "B", "ticker": "Y",
             "trade_date": date(2024, 1, 1), "settle_date": date(2024, 1, 3),
             "broker": "MRGST", "status": "SETTLED"},
        ])
        result = calculate_amounts(df)
        assert len(result) == 2
        assert result.iloc[0]["gross_amount"] == pytest.approx(5000.0)
        assert result.iloc[0]["net_amount"] == pytest.approx(5005.0)
        assert result.iloc[1]["gross_amount"] == pytest.approx(15000.0)
        assert result.iloc[1]["net_amount"] == pytest.approx(14990.0)
