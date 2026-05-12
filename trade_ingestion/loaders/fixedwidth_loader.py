"""Parse counterparty confirmation ``.dat`` files (fixed-width format).

Replaces ``process_counterparty_file()`` in ``process_trades.py`` lines
164-213.  The format has three record types:

* **HDR** — header row; broker name at positions 11-33.
* **TRL** — trailer row (record count); skipped.
* **T-**  — trade record with fixed field positions (derived from actual
  file analysis: trade_id 0-14, account 14-24, ticker 24-34, side 34-38,
  qty 38-46, price 46-56, currency 56-59, date 59-67, status 67-75).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from trade_ingestion.config import get_path

logger = logging.getLogger(__name__)


def load_confirms(filepath: str | None = None) -> pd.DataFrame:
    """Parse a fixed-width counterparty confirms file.

    Parameters
    ----------
    filepath : str, optional
        Explicit path.  Defaults to ``<trade_input>/counterparty_confirms.dat``.

    Returns
    -------
    pd.DataFrame
        Columns: trade_id, account, ticker, side, quantity, price, currency,
        trade_date, status, broker.
    """
    if filepath is None:
        filepath = str(Path(get_path("trade_input")) / "counterparty_confirms.dat")

    path = Path(filepath)
    if not path.exists():
        logger.warning("Counterparty file not found: %s", filepath)
        return pd.DataFrame()

    records: list[dict[str, object]] = []
    current_broker = ""

    with open(path, "r") as fh:
        for line in fh:
            if line.startswith("HDR"):
                current_broker = line[11:33].strip()
                logger.info("Broker section: %s", current_broker)
            elif line.startswith("TRL"):
                trailer_count = int(line[3:12])
                logger.debug("Trailer count: %d", trailer_count)
            elif line.startswith("T-"):
                raw_price = int(line[46:56])
                date_str = line[59:67]
                formatted_date = f"{date_str[0:2]}/{date_str[2:4]}/{date_str[4:8]}"
                records.append(
                    {
                        "trade_id": line[0:14].strip(),
                        "account": line[14:24].strip(),
                        "ticker": line[24:34].strip(),
                        "side": line[34:38].strip(),
                        "quantity": int(line[38:46]),
                        "price": raw_price / 100.0,
                        "currency": line[56:59].strip(),
                        "trade_date": formatted_date,
                        "status": line[67:75].strip(),
                        "broker": current_broker,
                    }
                )

    df = pd.DataFrame(records)
    logger.info("Parsed %d confirmation records", len(df))
    return df
