# Option A — Pandas + Pydantic (standalone script)

A modernization of the legacy `legacy_scripts/process_trades.py` built as a
single, well-typed Python script on top of the shared `modernized/common/`
layer.

## Approach

`trade_processor.py` orchestrates the full daily trade pipeline using the common
modules so that all three modernization options produce **identical** output:

1. **Config** — `common.config.load_config` parses `config/batch_config.ini`.
2. **Load** — `common.parsers.load_trades_csv` reads the daily trade CSV into a
   typed `pandas` DataFrame. `total_loaded = len(df)`.
3. **Validate** — `common.validation.validate_trades` drops duplicate
   `trade_id`s, validates each row against the Pydantic `RawTrade` model, and
   enforces the broker whitelist, returning `(valid, errors)`.
4. **Enrich** — vectorized `pandas` computation of
   `gross_amount = round(qty * price, 2)` and
   `net_amount = gross ± commission` (`+` for BUY, `−` for SELL); missing
   settle dates are filled with `common.settlement.calculate_t_plus_2`.
5. **Confirms** — `common.parsers.load_counterparty_file` parses the
   fixed-width broker `.dat` file (implied-decimal prices, `T-` records only).
6. **Reconcile** — a left merge on `trade_id`
   (`suffixes=("", "_confirm")`) classifies each trade as `UNMATCHED`
   (no confirm), `PRICE_BREAK` (`|price − price_confirm| > 0.01`),
   `QTY_BREAK` (`qty != qty_confirm`), or `MATCHED`.
7. **Report** — writes the processed-trades CSV (uppercase header in the
   required order, dates as `MM/DD/YYYY`) plus an error log of rejected rows.
8. **Summarize** — returns a Pydantic `ProcessingResult` with all six counters.

### Counting note

On the test data `validate_trades` returns three error rows: one `DUPLICATE`,
one `INVALID_BROKER:WRONGBK`, and one `VALIDATION` (negative quantity).
`duplicates_removed` counts the `DUPLICATE` rows and `validation_errors` is the
natural count of the remaining error rows
(`len(error_df) - duplicates_removed`), so a non-whitelisted broker counts as a
validation error — matching the legacy script. All error rows are also written
to the error log.

## Input/output file resolution

The configured paths in `batch_config.ini` are the original Windows network
drives (e.g. `C:\MeridianData\trades\`) which don't exist off the production
hosts, so each input is resolved by trying, in order:

1. `<configured trade_input>/<file>` (the Windows path),
2. `modernized/test_data/<file>` (committed sample data),
3. `legacy_data/trades/<file>` (real legacy flat files).

The trade file is `daily_trades_<run_date>.csv`; the confirm file is
`counterparty_confirms.dat`. Output goes to the configured `report_output`
directory if it exists, otherwise to `modernized/option_a_pandas/output/`.

## How to run

From the **repository root** (so the `modernized` package resolves):

```bash
# Install dependencies (referenced from modernized/requirements_option_a.txt)
pip install -r modernized/requirements_option_a.txt

# Run against the committed test data
python -m modernized.option_a_pandas.trade_processor --date 20240115

# Optional flags
python -m modernized.option_a_pandas.trade_processor \
    --date 20240115 --config config/batch_config.ini
```

Expected summary on the test data:

```
ProcessingResult: total_loaded=7, duplicates_removed=1, validation_errors=2, matched=1, breaks=2, unmatched=1
```

The run writes `processed_trades_20240115.csv` and `trade_errors_20240115.txt`
into the resolved output directory.

## Pros / cons

**Pros**
- Minimal moving parts: one standalone script, easy to read and run.
- Vectorized `pandas` enrichment and a single left merge for reconciliation.
- Pydantic validation gives declarative, typed guarantees on every row.
- Mature, ubiquitous dependency set (`pandas`, `pydantic`).

**Cons**
- `pandas` holds the whole batch in memory; not ideal for very large files.
- Row-wise `apply` for recon classification is convenient but not the fastest
  for millions of rows (would vectorize with `np.select` at scale).
- No SQL push-down — all logic runs in Python (compare with the DuckDB option).
