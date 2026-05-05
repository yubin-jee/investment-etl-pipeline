# Option B: Dagster Asset-Based Pipeline

## Approach

Uses Dagster's software-defined assets to model each trade processing step as a declarative data asset with built-in lineage, retry policies, and a rich web UI.

```
┌─────────────────────────────────────────────────────────────────┐
│              Dagster Asset Graph (Option B)                     │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────┐  │
│  │  raw_trades   │──►│ validated_trades  │──►│enriched_trades│  │
│  │  (@asset)     │    │   (@asset)       │    │  (@asset)     │──┤
│  └──────────────┘    └──────────────────┘    └───────────────┘  │
│                                                                 │
│  ┌──────────────────────┐                    ┌───────────────┐  │
│  │counterparty_confirms │────────────────────►│ reconciled_  │  │
│  │      (@asset)        │                    │   trades      │  │
│  └──────────────────────┘                    │  (@asset)     │  │
│                                              └───────────────┘  │
│                                                    │            │
│                                              Output CSV +       │
│                                              Dagster metadata   │
│                                                                 │
│  ┌─────────────────────────────────────────────┐                │
│  │  Resources: TradeFileResource               │                │
│  │  Partitions: DailyPartitionsDefinition      │                │
│  │  Schedule: 6:30 AM weekdays                 │                │
│  │  Retry: max_retries=3, delay=60s            │                │
│  └─────────────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

## Key Improvements over Legacy

| Legacy Issue | How Dagster Fixes It |
|---|---|
| Global mutable state | Each asset is a pure function |
| No retry logic | Built-in `RetryPolicy(max_retries=3, delay=60)` |
| No observability | Full web UI with lineage, logs, metadata |
| No backfill support | One-click backfill via Dagster UI |
| No date partitioning | Native `DailyPartitionsDefinition` |
| No data lineage | Automatic asset dependency graph |
| Hardcoded paths | `ConfigurableResource` with config file |
| No scheduling | Built-in `ScheduleDefinition` |

## How to Run

```bash
# Install dependencies
pip install -r modernized/requirements_option_b.txt

# Launch the Dagster development server
dagster dev -m modernized.option_b_dagster.definitions

# Open the Dagster UI at http://localhost:3000
# Navigate to Assets > trade_processing group
# Select a partition date and click "Materialize"
```

### Materializing Assets

1. Open the Dagster UI at `http://localhost:3000`
2. Navigate to the **Assets** page
3. Select the `trade_processing` group
4. Choose a partition date (e.g., `2024-03-15`)
5. Click **Materialize All** to run the full pipeline

### Running a Backfill

1. In the Dagster UI, go to **Assets** > select all trade processing assets
2. Click **Backfill** and select a date range
3. Monitor progress in the **Runs** tab

## Pros

- **Full asset lineage** — automatic dependency graph in the UI
- **Built-in retry and error handling** — configurable per asset
- **Rich observability** — metadata, logs, and run history in the UI
- **Native partitioning** — daily partitions with one-click backfill
- **Testable** — Dagster provides testing utilities for assets
- **Idempotent** — re-materializing an asset overwrites cleanly
- **Growing ecosystem** — active development, good documentation

## Cons

- **Infrastructure overhead** — requires Dagster webserver process
- **Learning curve** — asset-based paradigm may be unfamiliar
- **Smaller community** than Airflow (but growing rapidly)
- **Deployment complexity** — needs Dagster daemon for schedules
- **Less suited for non-data workflows** — optimized for data pipelines
