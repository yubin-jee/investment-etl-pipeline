"""Unit tests for individual Airflow task functions (standalone, no Airflow)."""

from datetime import date
from pathlib import Path
from typing import Dict, List

import pytest

from modernized.option_b_airflow.tasks.trade_tasks import (
    calculate_amounts_task,
    load_trades,
    parse_confirms_task,
    reconcile_task,
    validate_trades_task,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRADE_DIR = str(PROJECT_ROOT / "legacy_data" / "trades")


class TestLoadTrades:
    def test_loads_correct_count(self):
        result = load_trades("20240315", trade_dir=TRADE_DIR)
        assert isinstance(result, list)
        assert len(result) == 15

    def test_returns_serialisable_dicts(self):
        result = load_trades("20240315", trade_dir=TRADE_DIR)
        assert all(isinstance(r, dict) for r in result)
        assert "trade_id" in result[0]


class TestValidateTradesTask:
    def test_validates_all(self):
        raw = load_trades("20240315", trade_dir=TRADE_DIR)
        valid, errors = validate_trades_task(raw)
        # All 15 have unique trade_ids
        assert len(valid) == 15
        assert len(errors) == 0

    def test_returns_dicts(self):
        raw = load_trades("20240315", trade_dir=TRADE_DIR)
        valid, _ = validate_trades_task(raw)
        assert all(isinstance(v, dict) for v in valid)


class TestCalculateAmountsTask:
    def test_adds_amount_columns(self):
        raw = load_trades("20240315", trade_dir=TRADE_DIR)
        valid, _ = validate_trades_task(raw)
        enriched = calculate_amounts_task(valid)
        assert "gross_amount" in enriched[0]
        assert "net_amount" in enriched[0]

    def test_gross_calculation(self):
        raw = load_trades("20240315", trade_dir=TRADE_DIR)
        valid, _ = validate_trades_task(raw)
        enriched = calculate_amounts_task(valid)
        first = enriched[0]
        expected_gross = round(first["quantity"] * first["price"], 2)
        assert first["gross_amount"] == expected_gross


class TestParseConfirmsTask:
    def test_parses_confirms(self):
        result = parse_confirms_task("20240315", trade_dir=TRADE_DIR)
        assert isinstance(result, list)
        assert len(result) == 10


class TestReconcileTask:
    def test_reconciliation(self):
        raw = load_trades("20240315", trade_dir=TRADE_DIR)
        valid, _ = validate_trades_task(raw)
        enriched = calculate_amounts_task(valid)
        confirms = parse_confirms_task("20240315", trade_dir=TRADE_DIR)
        reconciled = reconcile_task(enriched, confirms)
        assert all("recon_status" in r for r in reconciled)
        statuses = {r["recon_status"] for r in reconciled}
        assert statuses.issubset({"MATCHED", "PRICE_BREAK", "QTY_BREAK", "UNMATCHED"})
