---
name: powerbi
description: Check the NORDA Power BI project (reports/powerbi/NORDA Sales.pbip) after the monthly data update. Opens it in Power BI Desktop (only when no other Power BI is open), refreshes it from data/mart/, compares every measure with SQL on data/mart (KPIs, months, countries, top 10, stock, ran out, display texts and colours for the dashboard's filter states), captures the Power BI window, and writes runs/<month>/7-powerbi/powerbi-checks.md. Use after /quality-gate has passed, or when the user asks to check, update or refresh the Power BI report. Never saves the project; the user opens it and clicks Refresh.
---

# Check the Power BI report

Usage: `/powerbi <run-month>`, e.g. `/powerbi 2026-09`. If no month is given, ask for it.

Pipeline: `/profile` → `/clean` → `/mart` → `/quality-gate` → `/html-dashboard` and **`/powerbi`** (every month) · `/ppt-review` (when there are questions). This skill is step 7.

Follow CLAUDE.md throughout: tag load-bearing claims [high]/[med]/[guess], don't guess about the business, keep it short.

**The Power BI file updates itself:** it reads `data/mart/` every time the user clicks Refresh. This skill proves that the refreshed numbers are right before anyone uses them.

## Files in this folder

| File | What it is |
|---|---|
| `check.py` | Opens the project, refreshes it, runs DAX queries and compares them with SQL on `data/mart/`, then closes the Power BI it started. Writes `runs/<run>/7-powerbi/powerbi-checks.md` and `powerbi.png`. Any FAIL → exit code 1. Road B is the same SQL model as the HTML dashboard check (`html-dashboard/check.py`), so both reports are held to the same numbers. |
| `pbi.ps1` | Helper called by `check.py`: `open` (refuses if any Power BI is already open), `query` (DAX, DMV, refresh through Power BI's own local engine), `shot` (captures only the Power BI window's own content), `close` (only the processes it started). |

The project itself lives in `reports/powerbi/`: `NORDA Sales.pbip`, `NORDA Sales.SemanticModel/` (TMDL text files) and `NORDA Sales.Report/` (PBIR text files). Run the script from the project root.

## The checks

| IDs | What they check |
|---|---|
| B01–B04 | Every table reads its CSV from this `data/mart/`; the model loads with no measure errors; refresh works; row counts = the mart CSVs |
| P01–P07 | Measures vs SQL for the dashboard's filter states (default, latest month, top country + channel, one category, two months + category, two categories, two months): revenue, orders, stock and its month, ran out, at 0, stock note, period text, every month, every country, top 10 |
| D01–D10 | Display measures vs SQL: top 10, months at 0, products, summary text, stock caption, amber only on the top month / country / product, amber on exactly the products that ran out |
| S01 | Screenshot of the Power BI window saved as evidence |

Tested 2026-11-25: 22/22 PASS on real data (run 2026-08, Jan–Dec 2025) and 22/22 PASS on a test copy with a fake second delivery (Jan 2025–Jan 2026: stock shown for Jan 2026, 13 months on the axis, prices from the newest delivery).

## Steps

1. **Gate: the quality gate must have passed.**
   Read `runs/<run>/4-quality-gate/quality-gate-checks.md`.
   - Missing → stop and ask the user to run `/quality-gate <run>` first.
   - Not "PASS - all quality rules hold" → stop, show the failing rules, and ask.

2. **Power BI must be closed.** Ask the user to save their work and close Power BI Desktop. **Never close a Power BI window you didn't start**: it may hold unsaved work. If the user saves while you change the project files, one side's changes are lost.

3. **Check**
   `python .claude/skills/powerbi/check.py --run <run>`
   - `STOPPED: Power BI Desktop is already open` → back to step 2.
   - All PASS → the report shows the right numbers after Refresh.
   - Any FAIL → the report must not be used. Show the failing checks, find the cause, and propose a fix. Only make the fix after a yes. Never weaken a check to make it pass.

4. **Look at `runs/<run>/7-powerbi/powerbi.png`**: no error messages, no "(Blank)", nothing cut off, amber only on the top items.

5. **Report to the user:** short, result first.
   - the verdict (e.g. 22/22 PASS) and the headline numbers as `powerbi-checks.md` shows them
   - **"Open the project and click Refresh"**: the file shows the old data until then
   - anything unusual compared with the previous run's `powerbi-checks.md`

## The report (same design rules as `/html-dashboard`)

- **Model:** the 6 mart tables, each loaded with a plain Power Query (read CSV, headers, column types; no functions, no parameters). Relationships as in `knowledge/data-model.md`, one-to-many, single direction. `month_name` sorts by `month_no`, `month_label` by `year_month`.
- **`_Measures`:** Total Revenue, Orders, Units Sold, Discount Amount (from `knowledge/metrics.md`); Stock on Hand, Stock Month, Products Ran Out, Products at 0 in Selection, Stock Note, Selected Period; display measures Top 10 Revenue, Months at 0, Products in Selection, Table Summary, Stock Caption, Colour Month / Country / Product / Stock.
- **Stock** is shown at the latest month **with stock data** in the selection, never summed across months, and is not filtered by country or channel. `dim_date` holds whole calendar years, so empty future months must never become "latest".
- **Page:** dark theme `NORDA_Dark.json`; 3 big numbers; sales per month (by `month_label`), per country, top 10 products, product table. One calm colour (`#5F87B4`) and amber (`#F0A73A`) only on the top item. Clicking filters the page.
- **Known differences from the HTML dashboard:** a clicked bar is shown by dimming the others; "Months at 0" column instead of the 12-month strip; table revenue shows cents; no "Clear all" button.
- **Data paths are absolute** (no parameters, as agreed). If the project folder moves, change the path once per table in Power Query; B01 fails until then.

## Rules

- **Never touch the user's Power BI.** `check.py` refuses to start when any Power BI is open and closes only what it started. Never use `Stop-Process` on Power BI yourself.
- **Never save the project from a script.** Model or report changes are made in the text files only while Power BI is closed, and only after a yes. Start from the user's last saved version, never regenerate it, so their own edits stay.
- **Business definitions belong to the user.** Measures follow `knowledge/metrics.md` and the decisions in `knowledge/data-model.md`; a new or changed measure is proposed first.
- **Code computes every number.** Quote numbers exactly as `powerbi-checks.md` shows them.
- **A script failure is a blocker.** If a script errors twice the same way, stop and tell the user what's blocking you.
- **Clean up.** `check.py` removes its temporary files itself; delete anything else you created.
