# Option A: Pandas + Pydantic Trade Processor

Drop-in replacement for `legacy_scripts/process_trades.py` using **Pandas** for
data manipulation and **Pydantic v2** for row-level validation.

## Architecture

```
modernized/
├── common/              # Shared layer (models, parsers, validation, settlement, config)
├── option_a_pandas/
│   ├── __init__.py
│   └── trade_processor.py   # This module
├── requirements_option_a.txt
└── test_data/           # Sample CSV / DAT files
```

All business logic lives in the shared `common` package.  `trade_processor.py`
orchestrates the pipeline:

1. Load config (`batch_config.ini`)
2. Parse trade CSV via `common.parsers.load_trades_csv`
3. Validate rows with Pydantic models + broker whitelist + dedup
4. Calculate gross/net amounts (vectorised Pandas)
5. Fill missing settlement dates with T+2 (business-day aware)
6. Parse fixed-width counterparty confirms
7. Reconcile via `pd.merge` O(n) hash join
8. Write output CSV and error log
9. Return `ProcessingResult` summary

## Quick Start

```bash
# Install dependencies
pip install -r modernized/requirements_option_a.txt

# Run against the bundled test data
cd /path/to/investment-etl-pipeline
python -m modernized.option_a_pandas.trade_processor \
    --date 20240115 \
    --config config/batch_config.ini
```

The processor automatically falls back to `modernized/test_data/` when the
Windows network paths in `batch_config.ini` are unavailable, so it works
out-of-the-box on any dev machine.

## Pros

- **Familiar ecosystem** — Pandas is the most widely adopted Python data tool;
  easy to hire for and onboard new team members.
- **Rich validation** — Pydantic v2 provides declarative, typed models with
  automatic coercion and clear error messages.
- **O(n) reconciliation** — `pd.merge` hash join replaces the legacy O(n²)
  nested loop.
- **No global state** — pure function signature makes testing and composition
  straightforward.
- **Incremental adoption** — can run side-by-side with the legacy script; just
  point the scheduler at the new entry point.

## Cons

- **Memory** — Pandas loads the full dataset into memory.  Fine for the current
  ~$2 M AUM / hundreds of trades, but may need chunking at scale.
- **GIL-bound** — single-threaded by default; heavy CPU work stays on one core.
- **Startup cost** — importing Pandas/NumPy adds ~0.5 s cold-start overhead
  (negligible for a batch job).
