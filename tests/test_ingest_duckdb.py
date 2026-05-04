"""Unit tests for the DuckDB trade ingestion module."""

from __future__ import annotations

from tests.conftest import EXPECTED_REJECTION_REASONS, EXPECTED_VALID_COUNT, EXPECTED_VALID_IDS

from ingest.ingest_duckdb import load_trades, validate_trades


def test_load_trades_row_count(synthetic_csv: str) -> None:
    df = load_trades(synthetic_csv)
    assert len(df) == 10, f"Expected 10 raw rows, got {len(df)}"


def test_load_trades_columns(synthetic_csv: str) -> None:
    df = load_trades(synthetic_csv)
    for col in ["trade_id", "account", "ticker", "side", "quantity", "price",
                 "trade_date", "settle_date", "broker", "commission", "status"]:
        assert col in df.columns, f"Missing column: {col}"


def test_validate_accepted_count(synthetic_csv: str) -> None:
    df = load_trades(synthetic_csv)
    clean, _ = validate_trades(df)
    assert len(clean) == EXPECTED_VALID_COUNT


def test_validate_accepted_ids(synthetic_csv: str) -> None:
    df = load_trades(synthetic_csv)
    clean, _ = validate_trades(df)
    assert set(clean["trade_id"]) == EXPECTED_VALID_IDS


def test_validate_rejected_reasons(synthetic_csv: str) -> None:
    df = load_trades(synthetic_csv)
    _, rejected = validate_trades(df)
    for _, row in rejected.iterrows():
        tid = row["trade_id"]
        if tid in EXPECTED_REJECTION_REASONS:
            assert row["rejection_reason"] == EXPECTED_REJECTION_REASONS[tid], (
                f"Trade {tid}: expected reason '{EXPECTED_REJECTION_REASONS[tid]}', "
                f"got '{row['rejection_reason']}'"
            )


def test_validate_rejected_count(synthetic_csv: str) -> None:
    df = load_trades(synthetic_csv)
    _, rejected = validate_trades(df)
    assert len(rejected) == len(EXPECTED_REJECTION_REASONS)
