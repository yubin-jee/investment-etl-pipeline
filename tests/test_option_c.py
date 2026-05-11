"""Tests for Option C: file watcher event handling and state machine."""

from pathlib import Path

import pandas as pd
import pytest

from modernized.option_c_event_driven.processor import PipelineState, TradeProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRADE_DIR = PROJECT_ROOT / "legacy_data" / "trades"
TRADE_FILE = TRADE_DIR / "daily_trades_20240315.csv"
CONFIRM_FILE = TRADE_DIR / "counterparty_confirms.dat"


class TestPipelineStateMachine:
    def test_initial_state_idle(self):
        p = TradeProcessor()
        assert p.state == PipelineState.IDLE

    def test_trade_file_moves_to_waiting_for_confirms(self):
        p = TradeProcessor()
        p.receive_trade_file(TRADE_FILE)
        assert p.state == PipelineState.WAITING_FOR_CONFIRMS

    def test_confirm_file_moves_to_waiting_for_trades(self):
        p = TradeProcessor()
        p.receive_confirm_file(CONFIRM_FILE)
        assert p.state == PipelineState.WAITING_FOR_TRADES

    def test_both_files_move_to_processing(self):
        p = TradeProcessor()
        p.receive_trade_file(TRADE_FILE)
        p.receive_confirm_file(CONFIRM_FILE)
        assert p.state == PipelineState.PROCESSING

    def test_reverse_order_also_works(self):
        p = TradeProcessor()
        p.receive_confirm_file(CONFIRM_FILE)
        p.receive_trade_file(TRADE_FILE)
        assert p.state == PipelineState.PROCESSING

    def test_try_process_when_not_ready(self):
        p = TradeProcessor()
        p.receive_trade_file(TRADE_FILE)
        result = p.try_process()
        assert result is None

    def test_reset_returns_to_idle(self):
        p = TradeProcessor()
        p.receive_trade_file(TRADE_FILE)
        p.receive_confirm_file(CONFIRM_FILE)
        p.reset()
        assert p.state == PipelineState.IDLE
        assert p.trade_file is None
        assert p.confirm_file is None


class TestTradeProcessorEndToEnd:
    def test_full_pipeline(self, tmp_path):
        p = TradeProcessor(output_dir=str(tmp_path))
        p.receive_trade_file(TRADE_FILE)
        p.receive_confirm_file(CONFIRM_FILE)
        df = p.try_process()

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 15
        assert p.state == PipelineState.COMPLETE

    def test_output_csv_created(self, tmp_path):
        p = TradeProcessor(output_dir=str(tmp_path))
        p.receive_trade_file(TRADE_FILE)
        p.receive_confirm_file(CONFIRM_FILE)
        p.try_process()

        output_files = list(tmp_path.glob("processed_trades_*.csv"))
        assert len(output_files) == 1
        df = pd.read_csv(output_files[0])
        assert len(df) == 15

    def test_recon_statuses(self, tmp_path):
        p = TradeProcessor(output_dir=str(tmp_path))
        p.receive_trade_file(TRADE_FILE)
        p.receive_confirm_file(CONFIRM_FILE)
        df = p.try_process()

        valid_statuses = {"MATCHED", "PRICE_BREAK", "QTY_BREAK", "UNMATCHED"}
        assert set(df["recon_status"].unique()).issubset(valid_statuses)


class TestTradeFileHandler:
    def test_handler_dispatches_trade_file(self, tmp_path):
        from modernized.option_c_event_driven.handler import TradeFileHandler

        processor = TradeProcessor(output_dir=str(tmp_path))
        handler = TradeFileHandler(processor, dead_letter_dir=tmp_path / "dead")

        class FakeEvent:
            is_directory = False
            src_path = str(TRADE_FILE)

        handler.on_created(FakeEvent())
        assert processor.state == PipelineState.WAITING_FOR_CONFIRMS

    def test_handler_dispatches_confirm_file(self, tmp_path):
        from modernized.option_c_event_driven.handler import TradeFileHandler

        processor = TradeProcessor(output_dir=str(tmp_path))
        handler = TradeFileHandler(processor, dead_letter_dir=tmp_path / "dead")

        class FakeEvent:
            is_directory = False
            src_path = str(CONFIRM_FILE)

        handler.on_created(FakeEvent())
        assert processor.state == PipelineState.WAITING_FOR_TRADES

    def test_deduplication_by_hash(self, tmp_path):
        from modernized.option_c_event_driven.handler import TradeFileHandler

        processor = TradeProcessor(output_dir=str(tmp_path))
        handler = TradeFileHandler(processor, dead_letter_dir=tmp_path / "dead")

        class FakeEvent:
            is_directory = False
            src_path = str(TRADE_FILE)

        handler.on_created(FakeEvent())
        # Second call with same file — should be deduplicated
        processor2 = TradeProcessor(output_dir=str(tmp_path))
        handler2 = TradeFileHandler(processor2, dead_letter_dir=tmp_path / "dead")
        handler2._processed_hashes = handler._processed_hashes
        handler2.processor = processor
        handler2.on_created(FakeEvent())
        # State should not change further (still waiting for confirms)
        assert processor.state == PipelineState.WAITING_FOR_CONFIRMS
