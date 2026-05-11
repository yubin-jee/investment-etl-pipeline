"""Async-capable trade processor with a simple state machine.

States:
    IDLE               → waiting for any file
    WAITING_FOR_TRADES → confirm file arrived; waiting for trade file
    WAITING_FOR_CONFIRMS → trade file arrived; waiting for confirm file
    PROCESSING         → both files present; pipeline running
    COMPLETE           → processing finished successfully

Addresses the known issue from daily_batch.py lines 13-14:
    "If trade file is late, this script fails"
By reacting to file arrivals instead of a fixed schedule, the pipeline
runs as soon as both files are available — no 6:30 AM dependency.
"""

from __future__ import annotations

import enum
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

from modernized.shared.models import ReconStatus
from modernized.shared.parsers import parse_counterparty_dat, parse_trade_csv
from modernized.shared.reconciler import reconcile
from modernized.shared.validators import validate_trades

load_dotenv()
logger = logging.getLogger(__name__)


class PipelineState(str, enum.Enum):
    IDLE = "IDLE"
    WAITING_FOR_TRADES = "WAITING_FOR_TRADES"
    WAITING_FOR_CONFIRMS = "WAITING_FOR_CONFIRMS"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"


class TradeProcessor:
    """Event-driven trade processor with coordination logic."""

    def __init__(self, output_dir: Optional[str] = None):
        self.state = PipelineState.IDLE
        self.trade_file: Optional[Path] = None
        self.confirm_file: Optional[Path] = None
        self.output_dir = Path(
            output_dir
            or os.environ.get("OUTPUT_DIR", str(Path(__file__).resolve().parents[2] / "reports"))
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.last_result: Optional[pd.DataFrame] = None

    def receive_trade_file(self, path: Path) -> None:
        """Register a trade file for processing."""
        logger.info("Received trade file: %s", path.name)
        self.trade_file = path
        if self.state == PipelineState.IDLE:
            self.state = PipelineState.WAITING_FOR_CONFIRMS
        elif self.state == PipelineState.WAITING_FOR_TRADES:
            self.state = PipelineState.PROCESSING

    def receive_confirm_file(self, path: Path) -> None:
        """Register a counterparty confirmation file for processing."""
        logger.info("Received confirm file: %s", path.name)
        self.confirm_file = path
        if self.state == PipelineState.IDLE:
            self.state = PipelineState.WAITING_FOR_TRADES
        elif self.state == PipelineState.WAITING_FOR_CONFIRMS:
            self.state = PipelineState.PROCESSING

    def try_process(self) -> Optional[pd.DataFrame]:
        """Attempt to run the pipeline if both files are present."""
        if self.state != PipelineState.PROCESSING:
            logger.info("Not ready to process (state=%s)", self.state.value)
            return None

        if self.trade_file is None:
            logger.warning("Trade file not set")
            return None

        return self._run_pipeline()

    def _run_pipeline(self) -> pd.DataFrame:
        """Execute the full trade processing pipeline."""
        start = time.perf_counter()
        logger.info("=== Option C (Event-Driven) — Processing ===")

        # Step 1: Parse trades
        trades = parse_trade_csv(self.trade_file)
        logger.info("Step 1: Loaded %d raw trades", len(trades))

        # Step 2: Validate
        valid_trades, errors = validate_trades(trades)
        logger.info("Step 2: %d valid, %d errors", len(valid_trades), len(errors))

        # Step 3: Calculate amounts
        records = [t.model_dump() for t in valid_trades]
        df = pd.DataFrame(records)
        df["broker"] = df["broker"].apply(lambda b: b.value if hasattr(b, "value") else b)
        df["gross_amount"] = (df["quantity"] * df["price"]).round(2)
        df["net_amount"] = df["gross_amount"] + df["commission"]
        sell_mask = df["side"] == "SELL"
        df.loc[sell_mask, "net_amount"] = (
            df.loc[sell_mask, "gross_amount"] - df.loc[sell_mask, "commission"]
        )
        df["net_amount"] = df["net_amount"].round(2)
        logger.info("Step 3: Computed amounts for %d trades", len(df))

        # Steps 4-5: Parse confirms and reconcile
        if self.confirm_file and self.confirm_file.exists():
            confirms = parse_counterparty_dat(self.confirm_file)
            recon_results = reconcile(valid_trades, confirms)
            recon_map = {r.trade.trade_id: r.recon_status.value for r in recon_results}
            df["recon_status"] = df["trade_id"].map(recon_map).fillna(ReconStatus.UNMATCHED.value)
            logger.info("Steps 4-5: Reconciled %d trades", len(df))
        else:
            df["recon_status"] = ReconStatus.UNMATCHED.value
            logger.warning("No confirm file — skipping reconciliation")

        # Step 6: Write output
        trade_date = self._extract_date(self.trade_file)
        output_file = self.output_dir / f"processed_trades_{trade_date}.csv"
        self._write_csv(df, output_file)

        self.state = PipelineState.COMPLETE
        self.last_result = df
        elapsed = time.perf_counter() - start
        logger.info("=== Option C complete in %.3f seconds ===", elapsed)
        return df

    def _extract_date(self, path: Path) -> str:
        """Extract YYYYMMDD from filename like daily_trades_20240315.csv."""
        stem = path.stem  # daily_trades_20240315
        parts = stem.split("_")
        for part in reversed(parts):
            if part.isdigit() and len(part) == 8:
                return part
        return datetime.now().strftime("%Y%m%d")

    @staticmethod
    def _write_csv(df: pd.DataFrame, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out = df.copy()
        out["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        columns = [
            "trade_id", "account", "ticker", "side", "quantity", "price",
            "gross_amount", "net_amount", "commission", "trade_date",
            "settle_date", "broker", "status", "recon_status", "processed_at",
        ]
        out = out[[c for c in columns if c in out.columns]]
        out.columns = [c.upper() for c in out.columns]
        out.to_csv(output_path, index=False)
        logger.info("Wrote %d trades to %s", len(out), output_path)

    def reset(self) -> None:
        """Reset state machine for the next batch."""
        self.state = PipelineState.IDLE
        self.trade_file = None
        self.confirm_file = None
        self.last_result = None
