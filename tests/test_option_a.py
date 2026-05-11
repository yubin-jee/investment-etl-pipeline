"""Integration test for Option A: pandas + SQLAlchemy end-to-end."""

import os
from pathlib import Path

import pandas as pd
import pytest

from modernized.option_a_pandas.process_trades import run

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRADE_DIR = PROJECT_ROOT / "legacy_data" / "trades"


class TestOptionAEndToEnd:
    def test_runs_successfully(self, tmp_path):
        df = run(
            trade_date="20240315",
            trade_dir=str(TRADE_DIR),
            output_dir=str(tmp_path),
        )
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_output_csv_created(self, tmp_path):
        run(
            trade_date="20240315",
            trade_dir=str(TRADE_DIR),
            output_dir=str(tmp_path),
        )
        output_file = tmp_path / "processed_trades_20240315.csv"
        assert output_file.exists()
        df = pd.read_csv(output_file)
        assert len(df) > 0

    def test_amounts_calculated(self, tmp_path):
        df = run(
            trade_date="20240315",
            trade_dir=str(TRADE_DIR),
            output_dir=str(tmp_path),
        )
        assert "gross_amount" in df.columns
        assert "net_amount" in df.columns
        # gross = qty * price for first trade: 500 * 171.48 = 85740.0
        first = df.iloc[0]
        assert first["gross_amount"] == 500 * 171.48

    def test_recon_statuses_present(self, tmp_path):
        df = run(
            trade_date="20240315",
            trade_dir=str(TRADE_DIR),
            output_dir=str(tmp_path),
        )
        assert "recon_status" in df.columns
        valid_statuses = {"MATCHED", "PRICE_BREAK", "QTY_BREAK", "UNMATCHED"}
        assert set(df["recon_status"].unique()).issubset(valid_statuses)

    def test_all_trades_present(self, tmp_path):
        """All 15 trades have unique trade_ids — none are duplicates."""
        df = run(
            trade_date="20240315",
            trade_dir=str(TRADE_DIR),
            output_dir=str(tmp_path),
        )
        assert len(df) == 15
