"""Trade-vs-confirmation reconciliation using ``pd.merge()``.

Replaces the O(n²) nested loop in ``process_trades.py`` lines 216-250.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PRICE_TOLERANCE = 0.01


def reconcile(trades_df: pd.DataFrame, confirms_df: pd.DataFrame) -> pd.DataFrame:
    """Merge trades with counterparty confirmations and assign recon status.

    Statuses
    --------
    * **MATCHED** — price diff ≤ 0.01 and quantity equal.
    * **PRICE_BREAK** — price diff > 0.01.
    * **QTY_BREAK** — quantity mismatch.
    * **UNMATCHED** — no matching confirmation found.

    Returns
    -------
    pd.DataFrame
        The trades DataFrame with ``recon_status`` populated.
    """
    if confirms_df.empty:
        out = trades_df.copy()
        out["recon_status"] = "UNMATCHED"
        logger.warning("No confirmations provided; all trades marked UNMATCHED")
        return out

    merged = pd.merge(
        trades_df,
        confirms_df[["trade_id", "quantity", "price"]],
        on="trade_id",
        how="left",
        suffixes=("", "_confirm"),
    )

    price_diff = (merged["price"] - merged["price_confirm"]).abs()
    qty_match = merged["quantity"] == merged["quantity_confirm"]
    has_confirm = merged["price_confirm"].notna()

    conditions = [
        has_confirm & (price_diff <= PRICE_TOLERANCE) & qty_match,
        has_confirm & (price_diff > PRICE_TOLERANCE),
        has_confirm & ~qty_match,
        ~has_confirm,
    ]
    choices = ["MATCHED", "PRICE_BREAK", "QTY_BREAK", "UNMATCHED"]

    merged["recon_status"] = np.select(conditions, choices, default="UNMATCHED")

    merged.drop(columns=["quantity_confirm", "price_confirm"], inplace=True)

    counts = merged["recon_status"].value_counts().to_dict()
    logger.info("Reconciliation results: %s", counts)
    return merged
