"""Trade reconciliation with counterparty confirmations.

Replaces the O(n²) nested loop at lines 223-248 of
legacy_scripts/process_trades.py with a pd.merge() on trade_id.
"""

import logging

import pandas as pd

from trade_processing.config import PRICE_TOLERANCE

logger = logging.getLogger(__name__)


def reconcile(
    trades_df: pd.DataFrame,
    confirms_df: pd.DataFrame,
    price_tolerance: float = PRICE_TOLERANCE,
) -> pd.DataFrame:
    """Reconcile internal trades with counterparty confirmations.

    Uses pd.merge on trade_id instead of O(n²) nested loop.

    Recon statuses:
    - MATCHED: price and quantity agree within tolerance
    - PRICE_BREAK: price difference > tolerance
    - QTY_BREAK: quantity mismatch
    - UNMATCHED: no counterparty confirmation found
    """
    merged = trades_df.merge(
        confirms_df[["trade_id", "quantity", "price"]],
        on="trade_id",
        how="left",
        suffixes=("", "_confirm"),
    )

    def _determine_status(row: pd.Series) -> str:
        if pd.isna(row.get("price_confirm")):
            return "UNMATCHED"
        if abs(float(row["price"]) - float(row["price_confirm"])) > price_tolerance:
            return "PRICE_BREAK"
        if int(row["quantity"]) != int(row["quantity_confirm"]):
            return "QTY_BREAK"
        return "MATCHED"

    merged["recon_status"] = merged.apply(_determine_status, axis=1)

    # Log summary
    status_counts = merged["recon_status"].value_counts()
    for status, count in status_counts.items():
        logger.info("Recon %s: %d", status, count)

    # Drop confirm columns from output
    result = merged.drop(columns=["quantity_confirm", "price_confirm"], errors="ignore")
    return result
