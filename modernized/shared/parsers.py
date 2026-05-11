"""Parsers for trade CSV and fixed-width counterparty confirmation files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import pandas as pd

from modernized.shared.models import CounterpartyConfirm, Trade

logger = logging.getLogger(__name__)


def parse_trade_csv(filepath: str | Path) -> List[Trade]:
    """Parse daily trade CSV into a list of Trade models.

    Expected columns: TRADE_ID, ACCT_NUM, TICKER, SIDE, QTY, PRICE,
    TRADE_DATE, SETTLE_DATE, BROKER, COMMISSION, STATUS
    """
    filepath = Path(filepath)
    logger.info("Parsing trade CSV: %s", filepath)

    df = pd.read_csv(
        filepath,
        dtype={
            "TRADE_ID": str,
            "ACCT_NUM": str,
            "TICKER": str,
            "SIDE": str,
            "BROKER": str,
            "STATUS": str,
        },
        keep_default_na=False,
    )

    trades: List[Trade] = []
    for _, row in df.iterrows():
        try:
            trade = Trade(
                trade_id=row["TRADE_ID"].strip(),
                account=row["ACCT_NUM"].strip(),
                ticker=row["TICKER"].strip(),
                side=row["SIDE"].strip(),
                quantity=int(row["QTY"]),
                price=float(row["PRICE"]),
                trade_date=row["TRADE_DATE"].strip(),
                settle_date=row["SETTLE_DATE"].strip() if row["SETTLE_DATE"] else None,
                broker=row["BROKER"].strip(),
                commission=float(row["COMMISSION"]),
                status=row["STATUS"].strip(),
            )
            trades.append(trade)
        except Exception:
            logger.exception("Failed to parse row: %s", dict(row))

    logger.info("Parsed %d trades from %s", len(trades), filepath.name)
    return trades


def parse_counterparty_dat(filepath: str | Path) -> List[CounterpartyConfirm]:
    """Parse fixed-width counterparty confirmation file.

    Record types:
      HDR — Header record (broker name at positions 14-36)
      TRL — Trailer record (count at positions 3-12)
      T-  — Trade record with fixed-width fields:
            trade_id   0:14
            account   14:24
            ticker    24:34
            side      34:38
            quantity  38:46  (zero-padded integer)
            price     46:56  (implied 2 decimal places)
            currency  56:59
            date      59:67  (MMDDYYYY)
            status    67:75
    """
    filepath = Path(filepath)
    logger.info("Parsing counterparty file: %s", filepath)

    confirms: List[CounterpartyConfirm] = []
    current_broker = ""

    with open(filepath, "r") as f:
        for line in f:
            if line.startswith("HDR"):
                current_broker = line[11:33].strip()
                logger.debug("Broker section: %s", current_broker)
            elif line.startswith("TRL"):
                count = int(line[3:12])
                logger.debug("Trailer count: %d", count)
            elif line.startswith("T-"):
                trade_id = line[0:14].strip()
                account = line[14:24].strip()
                ticker = line[24:34].strip()
                side = line[34:38].strip()
                quantity = int(line[38:46])
                raw_price = int(line[46:56])
                price = raw_price / 100.0
                currency = line[56:59].strip()
                date_str = line[59:67]
                trade_date = f"{date_str[0:2]}/{date_str[2:4]}/{date_str[4:8]}"
                status = line[67:75].strip()

                confirm = CounterpartyConfirm(
                    trade_id=trade_id,
                    account=account,
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    price=price,
                    currency=currency,
                    trade_date=trade_date,
                    status=status,
                    broker=current_broker,
                )
                confirms.append(confirm)

    logger.info("Parsed %d confirms from %s", len(confirms), filepath.name)
    return confirms
