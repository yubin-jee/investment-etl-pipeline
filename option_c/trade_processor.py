"""Event handler for trade and confirmation file processing.

On CSV file arrival: load → validate → calculate → store as "pending reconciliation"
On DAT file arrival: load confirms → reconcile against pending trades → write output
"""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from option_c.store import TradeStore
from trade_processing.calculators import calculate_amounts
from trade_processing.loaders.csv_loader import load_trades
from trade_processing.loaders.fwf_loader import load_confirms
from trade_processing.reconciliation import reconcile
from trade_processing.settlement import calculate_settlement_dates
from trade_processing.validators import validate

logger = logging.getLogger(__name__)


class TradeEventProcessor:
    """Processes trade and confirmation files as they arrive."""

    def __init__(self, store: TradeStore, output_dir: str | Path):
        self.store = store
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def process_trade_file(self, file_path: str | Path) -> int:
        """Process a trade CSV file: load → validate → enrich → store."""
        file_path = Path(file_path)
        logger.info("Processing trade file: %s", file_path)

        # Load
        trades_df = load_trades(file_path)

        # Validate
        valid_df, rejected_df = validate(trades_df)
        if not rejected_df.empty:
            logger.warning("Rejected %d trades", len(rejected_df))

        # Calculate settlement dates
        valid_df = calculate_settlement_dates(valid_df)

        # Calculate amounts
        valid_df = calculate_amounts(valid_df)

        # Convert to dicts for DB storage
        records = []
        for _, row in valid_df.iterrows():
            records.append({
                "trade_id": row["trade_id"],
                "account_number": row["account_number"],
                "ticker": row["ticker"],
                "side": row["side"],
                "quantity": int(row["quantity"]),
                "price": float(row["price"]),
                "gross_amount": float(row["gross_amount"]),
                "net_amount": float(row["net_amount"]),
                "commission": float(row["commission"]),
                "trade_date": str(row["trade_date"]),
                "settle_date": str(row["settle_date"]),
                "broker": row["broker"],
                "status": row["status"],
                "recon_status": "PENDING",
            })

        inserted, updated = self.store.upsert_trades(records)
        logger.info("Stored %d trades (%d new, %d updated)", len(records), inserted, updated)
        return len(records)

    def process_confirm_file(self, file_path: str | Path) -> pd.DataFrame:
        """Process a confirmation file: load → reconcile pending trades → write output."""
        file_path = Path(file_path)
        logger.info("Processing confirm file: %s", file_path)

        # Load confirms
        confirms_df = load_confirms(file_path)

        # Get pending trades from store
        pending = self.store.get_pending_trades()
        if not pending:
            logger.warning("No pending trades to reconcile")
            return pd.DataFrame()

        trades_df = pd.DataFrame(pending)

        # Reconcile
        result_df = reconcile(trades_df, confirms_df)

        # Update recon status in store
        for _, row in result_df.iterrows():
            self.store.update_recon_status(row["trade_id"], row["recon_status"])

        # Write output
        result_df["processed_at"] = datetime.now().isoformat()
        output_file = self.output_dir / "processed_trades.csv"
        result_df.to_csv(output_file, index=False)
        logger.info("Wrote %d reconciled trades to %s", len(result_df), output_file)

        return result_df
