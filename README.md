# NYC Precinct Public Safety Dashboard

index.html loads core_data.json (crime + DV, 2000-present) and the live feeds, all refreshed on a schedule; it falls back to the baked snapshot if a file is missing.

## Auto-refresh (GitHub Action, every 6h)
- refresh_core.py downloads NYPD CompStat "Historical Crime Data by Precinct" Excel + annual DV xlsx, re-parses, rebuilds core_data.json (validated; keeps the old file if a download/parse fails).
- refresh_live.py writes the shootings/arrests/traffic/311/911/citations feeds + 311 resolution time.
- CCRB + the population model carry forward from core_base.json.

## One-time setup
1. Replace the whole folder (easiest). 2. Commit. 3. Actions -> Run workflow. 4. Runs every 6h; hard-refresh the site.
