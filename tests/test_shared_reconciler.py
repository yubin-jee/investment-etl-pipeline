"""Tests for hash-join reconciliation logic."""

from datetime import date

import pytest

from modernized.shared.models import CounterpartyConfirm, ReconStatus, Trade
from modernized.shared.reconciler import reconcile


def _trade(**kw) -> Trade:
    defaults = dict(
        trade_id="T-001",
        account="ACC-1001",
        ticker="AAPL",
        side="BUY",
        quantity=500,
        price=171.48,
        trade_date=date(2024, 3, 15),
        settle_date=date(2024, 3, 19),
        broker="GOLDMN",
        commission=12.50,
        status="SETTLED",
    )
    defaults.update(kw)
    return Trade(**defaults)


def _confirm(**kw) -> CounterpartyConfirm:
    defaults = dict(
        trade_id="T-001",
        account="ACC-1001",
        ticker="AAPL",
        side="BUY",
        quantity=500,
        price=171.48,
        currency="USD",
        trade_date=date(2024, 3, 15),
        status="SETTLED",
        broker="GOLDMN SACHS",
    )
    defaults.update(kw)
    return CounterpartyConfirm(**defaults)


class TestReconcile:
    def test_exact_match(self):
        results = reconcile([_trade()], [_confirm()])
        assert len(results) == 1
        assert results[0].recon_status == ReconStatus.MATCHED

    def test_price_break(self):
        results = reconcile(
            [_trade(price=171.48)],
            [_confirm(price=172.00)],
        )
        assert results[0].recon_status == ReconStatus.PRICE_BREAK

    def test_price_within_tolerance(self):
        results = reconcile(
            [_trade(price=171.48)],
            [_confirm(price=171.489)],
        )
        assert results[0].recon_status == ReconStatus.MATCHED

    def test_qty_break(self):
        results = reconcile(
            [_trade(quantity=500)],
            [_confirm(quantity=501)],
        )
        assert results[0].recon_status == ReconStatus.QTY_BREAK

    def test_unmatched_trade(self):
        results = reconcile(
            [_trade(trade_id="T-999")],
            [_confirm(trade_id="T-001")],
        )
        assert results[0].recon_status == ReconStatus.UNMATCHED
        assert results[0].confirm is None

    def test_multiple_trades_and_confirms(self):
        trades = [
            _trade(trade_id="T-001"),
            _trade(trade_id="T-002", ticker="MSFT", price=412.27, quantity=200, side="SELL"),
            _trade(trade_id="T-003", ticker="GOOGL", price=138.92, quantity=100),
        ]
        confirms = [
            _confirm(trade_id="T-001"),
            _confirm(trade_id="T-002", ticker="MSFT", price=412.27, quantity=200, side="SELL"),
            # T-003 not in confirms
        ]
        results = reconcile(trades, confirms)
        status_map = {r.trade.trade_id: r.recon_status for r in results}
        assert status_map["T-001"] == ReconStatus.MATCHED
        assert status_map["T-002"] == ReconStatus.MATCHED
        assert status_map["T-003"] == ReconStatus.UNMATCHED

    def test_empty_confirms(self):
        results = reconcile([_trade()], [])
        assert all(r.recon_status == ReconStatus.UNMATCHED for r in results)

    def test_empty_trades(self):
        results = reconcile([], [_confirm()])
        assert len(results) == 0
