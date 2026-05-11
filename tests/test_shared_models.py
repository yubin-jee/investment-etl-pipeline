"""Unit tests for shared Pydantic models."""

from datetime import date

import pytest
from pydantic import ValidationError

from modernized.shared.models import (
    BrokerCode,
    CounterpartyConfirm,
    ReconResult,
    ReconStatus,
    Trade,
)


class TestTradeModel:
    def test_valid_trade(self):
        t = Trade(
            trade_id="T-001",
            account="ACC-1001",
            ticker="AAPL",
            side="BUY",
            quantity=100,
            price=150.25,
            trade_date="03/15/2024",
            settle_date="03/19/2024",
            broker="GOLDMN",
            commission=12.50,
            status="SETTLED",
        )
        assert t.trade_id == "T-001"
        assert t.side == "BUY"
        assert t.quantity == 100
        assert t.trade_date == date(2024, 3, 15)
        assert t.settle_date == date(2024, 3, 19)
        assert t.broker == BrokerCode.GOLDMN

    def test_trade_with_iso_dates(self):
        t = Trade(
            trade_id="T-002",
            account="ACC-1002",
            ticker="MSFT",
            side="SELL",
            quantity=200,
            price=412.27,
            trade_date="2024-03-15",
            settle_date="2024-03-19",
            broker="MRGST",
            commission=8.00,
            status="SETTLED",
        )
        assert t.trade_date == date(2024, 3, 15)

    def test_trade_none_settle_date(self):
        t = Trade(
            trade_id="T-003",
            account="ACC-1001",
            ticker="GOOGL",
            side="BUY",
            quantity=50,
            price=138.92,
            trade_date="03/15/2024",
            settle_date=None,
            broker="GOLDMN",
            commission=10.00,
            status="PENDING",
        )
        assert t.settle_date is None

    def test_trade_invalid_side(self):
        with pytest.raises(ValidationError):
            Trade(
                trade_id="T-004",
                account="ACC-1001",
                ticker="AAPL",
                side="SHORT",
                quantity=100,
                price=150.0,
                trade_date="03/15/2024",
                broker="GOLDMN",
                commission=10.0,
                status="SETTLED",
            )

    def test_trade_negative_quantity(self):
        with pytest.raises(ValidationError):
            Trade(
                trade_id="T-005",
                account="ACC-1001",
                ticker="AAPL",
                side="BUY",
                quantity=-100,
                price=150.0,
                trade_date="03/15/2024",
                broker="GOLDMN",
                commission=10.0,
                status="SETTLED",
            )

    def test_trade_zero_price(self):
        with pytest.raises(ValidationError):
            Trade(
                trade_id="T-006",
                account="ACC-1001",
                ticker="AAPL",
                side="BUY",
                quantity=100,
                price=0,
                trade_date="03/15/2024",
                broker="GOLDMN",
                commission=10.0,
                status="SETTLED",
            )

    def test_trade_invalid_broker(self):
        with pytest.raises(ValidationError):
            Trade(
                trade_id="T-007",
                account="ACC-1001",
                ticker="AAPL",
                side="BUY",
                quantity=100,
                price=150.0,
                trade_date="03/15/2024",
                broker="INVALID",
                commission=10.0,
                status="SETTLED",
            )


class TestCounterpartyConfirmModel:
    def test_valid_confirm(self):
        c = CounterpartyConfirm(
            trade_id="T-001",
            account="ACC-1001",
            ticker="AAPL",
            side="BUY",
            quantity=500,
            price=171.48,
            currency="USD",
            trade_date="03/15/2024",
            status="SETTLED",
            broker="GOLDMN SACHS",
        )
        assert c.trade_id == "T-001"
        assert c.trade_date == date(2024, 3, 15)
        assert abs(c.price - 171.48) < 0.001

    def test_confirm_mmddyyyy_date(self):
        c = CounterpartyConfirm(
            trade_id="T-002",
            account="ACC-1002",
            ticker="MSFT",
            side="SELL",
            quantity=200,
            price=412.27,
            currency="USD",
            trade_date="03152024",
            status="SETTLED",
            broker="MORGAN STANLEY",
        )
        assert c.trade_date == date(2024, 3, 15)


class TestReconResult:
    def test_matched_result(self):
        trade = Trade(
            trade_id="T-001",
            account="ACC-1001",
            ticker="AAPL",
            side="BUY",
            quantity=500,
            price=171.48,
            trade_date="03/15/2024",
            broker="GOLDMN",
            commission=12.50,
            status="SETTLED",
        )
        confirm = CounterpartyConfirm(
            trade_id="T-001",
            account="ACC-1001",
            ticker="AAPL",
            side="BUY",
            quantity=500,
            price=171.48,
            currency="USD",
            trade_date="03/15/2024",
            status="SETTLED",
            broker="GOLDMN SACHS",
        )
        result = ReconResult(
            trade=trade,
            confirm=confirm,
            recon_status=ReconStatus.MATCHED,
        )
        assert result.recon_status == ReconStatus.MATCHED

    def test_unmatched_result(self):
        trade = Trade(
            trade_id="T-099",
            account="ACC-1001",
            ticker="AAPL",
            side="BUY",
            quantity=500,
            price=171.48,
            trade_date="03/15/2024",
            broker="GOLDMN",
            commission=12.50,
            status="SETTLED",
        )
        result = ReconResult(
            trade=trade,
            confirm=None,
            recon_status=ReconStatus.UNMATCHED,
        )
        assert result.confirm is None
