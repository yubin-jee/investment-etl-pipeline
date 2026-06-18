---
name: testing-etl-modernization
description: End-to-end runtime testing for the Meridian investment-etl-pipeline modernization (Python 3.12 pipeline, SQL Server 2022 schema/procs, Docker/config). Use when verifying PRs that upgrade the EOL stack (Python 3.6→3.12, SQL Server 2016→2022, Windows→containerized).
---

# Testing the investment-etl-pipeline modernization

This repo is a legacy investment ETL pipeline. Modernization is split across **independent PRs**, each scoped to one EOL component and each merging into `initial-setup`. Test each PR on its own branch.

## Environment
- Python (3.12+), Docker available on the VM. No GUI involved → **shell-only testing, do NOT record** (recording would show an idle desktop).
- No external secrets needed. SQL Server runs locally in a throwaway container with a local-only SA password.

## Devin Secrets Needed
- None. (SQL Server SA password is a local-dev-only value, fine to hardcode in the test container.)

## Key gotchas (likely still true)
- **`process_trades.py` crashes** on the counterparty `.dat` parse (`int(line[52:64])` → `ValueError` on `'7148USD03152'`). This is a **pre-existing data bug**, identical on `initial-setup` and on Python 3.6/3.12. `daily_batch.py` continues past it. Out of scope for the modernization PRs (a `fix-counterparty-parser` branch owns it). Don't flag it as a regression.
- **Scope separation matters:** the Python-version PR keeps `C:\MeridianData` paths (de-Windowsing belongs to the Windows PR); the Windows PR keeps `os.system` in `daily_batch.py` (subprocess conversion belongs to the Python PR). Check the PR description for its declared scope before asserting "no Windows paths" or "uses subprocess".
- **Cross-PR conflict:** the SQL PR and the Windows PR both edit `README.md` and `config/batch_config.ini`. Each merges into `initial-setup` cleanly alone, but the second-merged conflicts. Report this.
- When grepping for Windows paths, match a **single** backslash: `grep -rn 'C:' ...` (a `C:\\\\`-style pattern needs two backslashes and misses real `C:\` paths).

## Python pipeline (Python-version PR)
```bash
python -m py_compile legacy_scripts/*.py
pip install ruff -q && ruff check legacy_scripts/ && ruff format --check legacy_scripts/
python legacy_scripts/daily_batch.py 20240315   # generates reports/nav_report_*, recon_*, compliance_*, client_reports/*.txt
```
Behavior-preservation check: run `calc_nav.py 20240315` on both `initial-setup` and the PR, then diff `reports/nav_report_20240315.csv` with the trailing `GENERATED_AT` timestamp column normalized (`sed 's/,20240315,.*/,20240315,TS/'`) — data columns should be identical.

## SQL Server 2022 (SQL PR)
```bash
docker run -d --name meridian-mssql -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD='Test_Str0ng!Pass' \
  -e MSSQL_PID=Developer -p 14333:1433 mcr.microsoft.com/mssql/server:2022-latest
# wait ~20-30s for startup, tools live at /opt/mssql-tools18/bin/sqlcmd (note -No flag to skip cert validation)
SQLCMD="docker exec meridian-mssql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P Test_Str0ng!Pass -No"
$SQLCMD -Q "CREATE DATABASE MeridianOMS;"
$SQLCMD -d MeridianOMS -i /tmp/create_tables.sql -b        # docker cp the sql files in first
$SQLCMD -d MeridianOMS -i /tmp/stored_procedures.sql -b
```
Assertions: temporal table via `sys.tables.temporal_type_desc` (`Positions` → `PositionsHistory`); counts from `sys.key_constraints`/`sys.foreign_keys`/`sys.indexes`; date types via `INFORMATION_SCHEMA.COLUMNS`; cross-year `sp_GetTrades` — insert a Client (FK) + a 2023 and a 2024 trade, then `EXEC sp_GetTrades @StartDate='2023-12-01',@EndDate='2024-02-01'` must return **both** rows.

## Containerization (Windows PR)
```bash
cp .env.example .env && docker compose config   # must validate; defines etl + sqlserver + meridian_data
rm .env
# Adversarial: env var must control output path
MERIDIAN_REPORT_DIR=/tmp/meridian_test python legacy_scripts/calc_nav.py 20240315  # writes to /tmp/meridian_test, NOT repo reports/
git check-ignore .env   # .env must be gitignored; .env.example password must be a placeholder
```

## Reporting
Post ONE results comment per PR. Lead with the cross-PR conflict + the pre-existing `.dat` bug as caveats. Clean up: `docker rm -f meridian-mssql`, remove temp dirs, `git checkout` the repo back to a clean branch.
