# Option B — Dagster asset graph

This option re-expresses the legacy `legacy_scripts/process_trades.py` batch as a
**partitioned [Dagster](https://dagster.io) asset graph**. Each stage of the
pipeline is a first-class, materializable *asset*; Dagster tracks lineage,
metadata, partitions and retries for you, and gives you a UI to observe and
re-run individual stages.

All business logic lives in the shared `modernized/common/` layer, so this option
produces the **same** result as Options A and C — the Dagster code here is purely
orchestration.

## Approach

The pipeline is modelled as five assets (see `assets.py`):

| Asset | Depends on | What it does |
|-------|------------|--------------|
| `raw_trades` | — | Loads the daily trade CSV for the partition via `common.parsers.load_trades_csv`. |
| `validated_trades` | `raw_trades` | Drops duplicates + validates against `RawTrade` via `common.validation.validate_trades`; writes the error log. |
| `enriched_trades` | `validated_trades` | Computes `gross_amount` / `net_amount` and fills missing settle dates with `common.settlement.calculate_t_plus_2`. |
| `counterparty_confirms` | — | Parses the fixed-width `.dat` confirmations via `common.parsers.load_counterparty_file`. |
| `reconciled_trades` | `enriched_trades`, `counterparty_confirms` | LEFT-merges on `trade_id`, classifies `MATCHED` / `PRICE_BREAK` / `QTY_BREAK` / `UNMATCHED`, writes the report CSV and a `ProcessingResult`. |

Key Dagster features used:

- **Partitioning** — `DailyPartitionsDefinition(start_date="2024-01-01")`. The
  partition key (`YYYY-MM-DD`) selects the input files for that trade date.
- **Resource** — `TradeFileResource(ConfigurableResource)` (`resources.py`) wraps
  the `common.config` loader and resolves per-partition input/output paths. The
  legacy `batch_config.ini` points at Windows network drives that don't exist
  here, so the resource falls back to `modernized/test_data/` and then
  `legacy_data/trades/`.
- **Retries** — every asset carries `RetryPolicy(max_retries=3, delay=60)` so a
  transient failure (e.g. a network drive blip) is retried automatically.
- **Observability** — each asset logs via `context.log.info()` and attaches
  `MetadataValue` outputs (row counts, error counts, file paths, table previews,
  and the final summary JSON) that render in the Dagster UI.

## Install

From the repo root:

```bash
pip install -r modernized/requirements_option_b.txt
```

(`modernized/requirements_option_b.txt` pins `dagster`, `dagster-webserver`,
`pandas`, `pydantic`, `python-dotenv`.)

## How to run

> Run everything **from the repo root** so the `modernized` package resolves
> (the code relies on absolute `modernized.common.*` imports).

### 1. Quick verification harness (no UI)

```bash
python -m modernized.option_b_dagster.verify --partition 2024-01-15
```

This materializes all assets in-process and prints the reconciliation summary.

### 2. Materialize via the Dagster CLI

```bash
dagster asset materialize \
  --select '*' \
  --partition 2024-01-15 \
  -m modernized.option_b_dagster.definitions
```

### 3. Launch the Dagster UI (webserver)

```bash
dagster dev -m modernized.option_b_dagster.definitions
```

Then open <http://localhost:3000>, go to **Assets**, select the
`trade_pipeline` assets, click **Materialize**, and pick the `2024-01-15`
partition. The asset graph, run logs, and per-asset metadata are all visible in
the UI.

### Output

The reconciled report and the validation error log are written to
`modernized/option_b_dagster/output/`:

- `reconciled_trades_<YYYYMMDD>.csv` — columns
  `TRADE_ID, ACCT_NUM, TICKER, SIDE, QTY, PRICE, GROSS_AMT, NET_AMT, COMMISSION,
  TRADE_DATE, SETTLE_DATE, BROKER, STATUS, RECON_STATUS` (dates `MM/DD/YYYY`).
- `trade_errors_<YYYYMMDD>.csv` — the rejected rows and their `error_reason`.

## Expected result on the sample partition (`2024-01-15`)

```
total_loaded=7 duplicates_removed=1 validation_errors=2 matched=1 breaks=2 unmatched=1
```

> **Note on `validation_errors`:** the task brief states `validation_errors=1`,
> but the committed `modernized/test_data/daily_trades_20240115.csv` contains
> *two* non-duplicate bad rows — an invalid broker (`WRONGBK`) **and** a negative
> quantity (`-400`). The shared `common.validation.validate_trades` flags both,
> and the required shared logic defines `validation_errors` as the count of
> non-duplicate error rows, so the faithful result is `2`. This option does not
> modify `modernized/common/` or the test data, so it reports the true count.
> All other counts match the brief exactly.

## Pros / cons

**Pros**

- **Lineage & observability out of the box** — the asset graph, run history, logs
  and metadata are all visible in a UI; easy to see *which* stage failed and why.
- **Native partitioning & backfills** — re-run a single day or backfill a date
  range without custom plumbing.
- **Built-in retries** — `RetryPolicy` handles transient infra failures.
- **Incremental re-execution** — materialize just the downstream assets after a
  fix, reusing cached upstream outputs.
- **Clear separation** — orchestration (Dagster) is cleanly separated from the
  shared business logic in `modernized/common/`.

**Cons**

- **Heavier dependency footprint** — Dagster pulls in gRPC, SQLAlchemy, Alembic,
  a webserver, etc., versus a plain script.
- **Conceptual overhead** — assets, resources, IO managers, partitions and
  definitions are a learning curve for a small batch job.
- **Default IO manager pickles intermediates** to local storage; for large data
  you'd configure a custom IO manager (e.g. Parquet/warehouse-backed).
- **Operational surface** — running the webserver/daemon for schedules and
  sensors is more infrastructure than a cron-triggered script.
