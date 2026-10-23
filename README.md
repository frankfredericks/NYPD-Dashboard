# NYC Precinct Crime Dashboard

A public, self-updating dashboard: pick any of NYC's 76 residential precincts and see
25 years of population-adjusted crime, rankings, domestic-violence and CCRB context, plus a
trailing-12-month / year-over-year view fed from live NYPD data.

## What's in here
- `index.html` — the dashboard (self-contained; auto-loads `monthly.json`).
- `monthly.json` — the trailing-24-month feed (regenerated automatically).
- `refresh_live.py` — pulls the latest NYPD Complaint Data and writes `monthly.json`.
- `.github/workflows/refresh.yml` — runs the refresh on the 1st of each month.
- `pipeline/` — optional: generate a custom XLSX + PPTX for any precinct locally
  (`python pipeline/generate_precinct_report.py --precinct 108 --workbook <master>.xlsx`).

## Publish it (first time — all in the browser, no software to install)
1. **Create a GitHub account** at github.com (free) if you don't have one.
2. **New repository:** top-right **+ → New repository**. Name it e.g. `precinct-dashboard`,
   set **Public**, click **Create repository**.
3. **Upload these files:** on the empty repo page click **uploading an existing file**,
   drag in `index.html`, `monthly.json`, `refresh_live.py`, and this `README.md`,
   then **Commit changes**.
4. **Add the scheduled refresh:** open the **Actions** tab → **set up a workflow yourself** →
   delete the sample, paste the contents of `.github/workflows/refresh.yml` (below), and
   **Commit**. (This is easier than uploading the hidden `.github` folder.)
5. **Turn on Pages:** **Settings → Pages → Build and deployment → Source: Deploy from a
   branch → Branch: `main` / `(root)` → Save.** Your URL appears in a minute:
   `https://<your-username>.github.io/precinct-dashboard/`
6. **Populate the monthly panel now:** **Actions → Refresh monthly crime data → Run workflow.**
   It fetches the data and commits `monthly.json`; the panel fills in on the next page load.
7. *(Optional)* **Faster/looser rate limits:** get a free app token at
   data.cityofnewyork.us (Sign in → app tokens), then **Settings → Secrets and variables →
   Actions → New repository secret**, name `SOCRATA_APP_TOKEN`.
8. *(Optional)* **Custom domain:** Settings → Pages → Custom domain.

Note: GitHub pauses scheduled Actions after ~60 days with no repo activity — the monthly
commit normally keeps it alive; if it ever pauses, open Actions and click **Run workflow**.

## Refresh the annual data (new CompStat year)
Rebuild the master workbook, then regenerate the dashboard's embedded data and re-commit:
`python pipeline/build_dashboard_bundle.py --workbook <master>.xlsx --html index.html`
