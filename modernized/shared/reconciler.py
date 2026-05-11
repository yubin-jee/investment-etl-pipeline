"""Hash-join based reconciliation — replaces the O(n*m) nested loop in legacy code."""

from __future__ import annotations

import logging
from typing import Dict, List

from modernized.shared.models import (
    CounterpartyConfirm,
    ReconResult,
    ReconStatus,
    Trade,
)

logger = logging.getLogger(__name__)

PRICE_TOLERANCE = 0.01


def reconcile(
    trades: List[Trade],
    confirms: List[CounterpartyConfirm],
) -> List[ReconResult]:
    """Reconcile internal trades with counterparty confirmations.

    Uses a dictionary (hash-join) for O(n+m) lookup instead of O(n*m).

    Matching rules:
      - Join on trade_id
      - Price tolerance: abs(trade.price - confirm.price) <= 0.01
      - Quantity must match exactly

    Returns a ReconResult for every trade (MATCHED / PRICE_BREAK / QTY_BREAK / UNMATCHED).
    """
    confirm_map: Dict[str, CounterpartyConfirm] = {c.trade_id: c for c in confirms}
    results: List[ReconResult] = []
    matched = 0
    breaks = 0

    for trade in trades:
        confirm = confirm_map.get(trade.trade_id)
        if confirm is None:
            results.append(
                ReconResult(
                    trade=trade,
                    confirm=None,
                    recon_status=ReconStatus.UNMATCHED,
                )
            )
            continue

        if abs(trade.price - confirm.price) > PRICE_TOLERANCE:
            status = ReconStatus.PRICE_BREAK
            breaks += 1
            logger.warning(
                "PRICE BREAK: %s internal=%.4f confirm=%.4f",
                trade.trade_id,
                trade.price,
                confirm.price,
            )
        elif trade.quantity != confirm.quantity:
            status = ReconStatus.QTY_BREAK
            breaks += 1
            logger.warning(
                "QTY BREAK: %s internal=%d confirm=%d",
                trade.trade_id,
                trade.quantity,
                confirm.quantity,
            )
        else:
            status = ReconStatus.MATCHED
            matched += 1

        results.append(
            ReconResult(trade=trade, confirm=confirm, recon_status=status)
        )

    logger.info("Reconciliation: %d matched, %d breaks, %d total", matched, breaks, len(results))
    return results
