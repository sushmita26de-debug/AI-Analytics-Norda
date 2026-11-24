---
name: html-dashboard
description: Build and check the NORDA interactive sales dashboard, one self-contained offline HTML file (reports/html/dashboard.html) generated from data/mart/ for the Purchasing team. Shows 3 big KPIs (revenue, orders, stock on hand), sales per month, sales per country, top 10 products and stock and sales per product, with slicers for month, category, country and channel and Power BI style click-to-filter. A check script drives the real page in headless Edge and compares every number with SQL on data/mart (16 pass/fail checks). Use after /quality-gate has passed for that month, or when the user asks to build/rebuild/check the HTML dashboard.
---

# Build the HTML dashboard

Usage: `/html-dashboard <run-month>`, e.g. `/html-dashboard 2026-09`. If no month is given, ask for it.

Pipeline: `/profile` → `/clean` → `/mart` → `/quality-gate` → **`/html-dashboard`** and `/powerbi` (every month) · `/ppt-review` (when there are questions). This skill is step 5.

Follow CLAUDE.md throughout: tag load-bearing claims [high]/[med]/[guess], don't guess about the business, keep it short.

## Files in this folder

| File | What it is |
|---|---|
| `dashboard.py` | `data/mart/` → `reports/html/dashboard.html` (overwritten each build), plus `runs/<run>/5-html-dashboard/html-dashboard-log.md`. It holds the data in the page as compact integer arrays (revenue in whole cents, orders as distinct order numbers), and the page recomputes every number on each click. The HTML/CSS/JavaScript template is section 6 of the script. No libraries, no internet, standard library + pandas only. |
| `check.py` | 16 checks. Opens the real page in headless Edge (Chrome also works), uses it like a person would (slicer checkboxes, clicks on bars at screen positions, sorting, Clear all) and compares what the page **shows** with SQL on `data/mart/`. Writes `runs/<run>/5-html-dashboard/html-dashboard-checks.md`. Any FAIL → exit code 1. Temporary files go into a temp folder that is deleted automatically. |

Run both scripts from the project root. Neither ever modifies `data/`.

## The checks

| ID | Check |
|---|---|
| H01–H04 | The file exists (size reported); it is self-contained (no internet links, no external scripts or styles); no test hook was left in it; it is newer than every mart CSV, so it was built from the current mart. |
| P01–P06 | Page vs SQL, in whole cents, for 6 filter states picked from the data, so they work every month: default; latest month; top country + top channel; one category; two months + one category; the two categories that share the most orders. Each state checks the 3 KPIs (plus the big number = exact value rounded), all 12 months, every country and its order, the top 10 and its order, and the "N products, N ran out, N were at 0" line. P06 proves orders are counted once (union), not summed. |
| I01 | Clicking the same spot twice filters, then clears (every country bar + one month column). |
| I02 | Nothing moves or resizes when filters change (every panel measured). |
| I03 | Sorting the table, then Clear all, brings back the default order. |
| I04 | Stock ignores country/channel, and both notes say so only when those filters are on. |
| I05 | The header period follows the month filter ("Mar, Jul 2025", "Oct–Dec 2025"). |
| I06 | No script errors on the page. |

Every check except H04 was shown to FAIL on a deliberately broken copy (2026-11-24). H04 is a file-date comparison.

## Steps

1. **Gate: the quality gate must have passed.**
   Read `runs/<run>/4-quality-gate/quality-gate-checks.md` (written by `/quality-gate`).
   - Missing → stop and ask the user to run `/quality-gate <run>` first.
   - Not "PASS - all quality rules hold" → stop, show the failing rules, and ask.

2. **Build**
   `python .claude/skills/html-dashboard/dashboard.py --run <run>`
   If it prints `ERROR`, report the reason and ask.

3. **Check**
   `python .claude/skills/html-dashboard/check.py --run <run>`
   - All PASS → the dashboard can be shared.
   - Any FAIL → it must not be shared. Show the failing checks with their details, find the cause, and propose a fix. Only make the fix after a yes. Never weaken a check to make it pass.
   - `STOPPED: no Microsoft Edge or Chrome found` → tell the user; pass `--browser <path>` if they have one elsewhere.

4. **Report to the user:** short, result first.
   - the verdict (e.g. 16/16 PASS)
   - the 3 KPIs and the number of products that ran out, as printed in `html-dashboard-checks.md`
   - file path and size
   - anything unusual compared with the previous run (read the previous `runs/*/5-html-dashboard/html-dashboard-checks.md`), for example more products running out or a new inventory gap count in `html-dashboard-log.md`

## Design rules (agreed with Sushmita, 2026-11-24)

The page follows these. A change to any of them is a design change (see below).

**From the owner:**
- Dark.
- One calm colour (muted blue `#5f87b4`) for everything, and one highlight colour (amber `#f0a73a`) on the most important item in each chart.
- The three numbers big at the top.
- Clicking a bar filters the whole page; clicking it again clears that filter.
- Hover shows the exact number in a floating tooltip and nothing else changes (no hover band, no growth, no shift).

**Layout:** one page, fits 1280×900. One 12-column grid:
- row 1: the 3 KPIs, 4/4/4;
- row 2: sales per month 8 + sales per country 4;
- row 3: best-selling products 4 + stock and sales per product 8.

**Charts:**

| Requirement | Form |
|---|---|
| Sales per month | Columns |
| Sales per country | Sorted horizontal bars |
| Best-selling products | Top 10 by revenue, horizontal bars |
| Stock and sales per product | Table, explained below |

The product table has data bars for units sold and stock on hand, and a 12-month strip that shows stock 0 in the calm colour. Rows with stock 0 at the latest selected month come first, and their stock cell gets an amber dot. The columns can be sorted.

**Decisions:**

| # | Decision |
|---|---|
| Highlight | When a chart has its own selection, amber moves to the selected item(s). Otherwise amber marks the top item: the peak month, the top country, the #1 product, and in the table the products that ran out. |
| Filters | Power BI style: the month, category, country and channel slicers are multi-select, and Ctrl/Shift+click adds to a selection. A chart is not filtered by its own dimension; its selection only moves the highlight. Esc and Clear all reset everything, including the table sort. |
| Months (monthly deliveries, 2026-11-25) | The page shows the months from the first to the last month **with data**; `dim_date` holds whole calendar years, but empty future months are never shown or used as "latest". When the data spans more than one year, January on the month axis shows its year ("Jan 2026"). |
| Stock | Shown at the latest selected month, never summed. It follows month, category and product, but not country or channel, because inventory has neither. Both the KPI and the table say so when those filters are on. |
| Ran out | `qty_on_hand = 0` at month end. A missing stock record shows "no stock data", never 0. |
| Product table | Lists the whole catalogue for the selected categories, including products with no sales. |
| Labels | Compact on bars (€15.9M). The big KPI number is in whole euros. Exact cents only in tooltips. |
| Keep | The "ranks #N" note, keyboard support, and hover effects on controls (not on data marks). |
| Removed | The hover band on data marks, the "Months at 0" column, and the `#test` hook. |

**Known limits:** revenue is before returns, and the page says so. Best sellers are ranked by revenue only; a units view is on the wish list and not agreed.

## Design changes: the review team

Use this only when the design changes, never on the monthly run. Before starting, tell the user how many agent runs this takes and how big they are, and wait for a yes. The process that built this page used 6 runs: Builder, then three reviewers in parallel, then a Builder fix round, then an auditor re-check.

| Agent | Its rules |
|---|---|
| **Builder** | Changes only `dashboard.py` and rebuilds the page. No libraries. Code computes every number. Does only the agreed list; lists any extras instead of doing them. |
| **Number auditor** | Read-only. Never reads `dashboard.py` or the page's internal state; uses the page like a user and reads hover tooltips. Recomputes everything with pandas straight from `data/raw` (the quality gate's road), on random filter states with a recorded seed. |
| **Design critic** | Read-only. Takes headless Edge screenshots of the key states and judges the owner's design rules first, then the dataviz skill's anti-patterns. Ranks findings MUST/SHOULD/NICE. |
| **Purchasing user** | Read-only. Plays a buyer and answers the requirement questions from the page alone. Reports friction ranked BLOCKER/ANNOYING/MINOR, with a separate short wish list. |

Bring all findings to the user with a proposed fix list and recommendations. The fix round starts only after a yes. After any design change, `check.py` must still pass. If a change breaks a check because the design changed (not the numbers), propose the check update together with the design change.

## Rules

- **Never modify `data/`.** Only overwrite `reports/html/dashboard.html` and `runs/<run>/5-html-dashboard/`.
- **Never hand-edit `dashboard.html`.** It's regenerated on every build; change the template in `dashboard.py` instead.
- **Code computes every number.** Quote numbers exactly as the scripts printed them or as they appear in `html-dashboard-checks.md`.
- **Business definitions belong to the user.** That covers new measures, a different ranking, or a different "ran out". Don't invent them; ask.
- **A script failure is a blocker.** If a script errors twice the same way, stop and tell the user what's blocking you.
- **Clean up.** Delete any temporary files when done (screenshots, test copies, `__pycache__`).
