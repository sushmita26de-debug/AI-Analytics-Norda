---
name: mart
description: Build and validate the NORDA sales data model (star schema for the Power BI dashboard) from the combined clean history data/clean/all/ (every monthly delivery) into data/mart/, and query it. Two facts (fact_sales, fact_inventory) and four dimensions (date, product, country, channel), plus a generated diagram (data/mart/model.html), checked with 43 pass/fail checks. Use after /clean has passed for that month, when the user asks to build/rebuild the model or the mart, or to answer a question from the model with SQL.
---

# Build the sales data model

Usage: `/mart <run-month>`, e.g. `/mart 2026-09`. If no month is given, ask for it.
The model is always built from **`data/clean/all/`**: the whole history, i.e. every monthly delivery combined by `/clean`. The run month only names the log folder `runs/<run>/3-mart/`.

Pipeline: `/profile` → `/clean` → **`/mart`** → `/quality-gate` → `/html-dashboard` and `/powerbi` (every month) · `/ppt-review` (when there are questions). This skill is step 3.

Follow CLAUDE.md throughout: tag load-bearing claims [high]/[med]/[guess], don't guess about the business, keep it short.

## Files in this folder

| File | What it is |
|---|---|
| `mart.py` | `data/clean/all/` → `data/mart/` (overwritten each build, so Power BI reads one fixed folder), plus `runs/<run>/3-mart/mart-log.md`. It writes:<br>• six CSVs<br>• **`model.html`**, the diagram, regenerated on every build from the design and the real row counts. Dark theme, join keys highlighted, and hovering a table lights up its relationships.<br>Its RULES section holds the table design: columns, types, keys, relationships and diagram layout. It stops and writes nothing if it finds a country or channel that isn't in `knowledge/rules.json`. |
| `check.py` | 43 checks on the model, reading the files back as text, and writes `runs/<run>/3-mart/mart-checks.md` with the headline numbers. Any FAIL → exit code 1. |

Run both scripts from the project root. Neither ever modifies `data/clean`. `check.py` reconciles the model with `data/clean/all/`.

## The checks

43 checks; every one must PASS.

| IDs | What they check |
|---|---|
| F01–F19 | Facts: columns, values, revenue and discount recomputed independently from clean; rows, orders, units and stock per month reconciled with `data/clean/all/` |
| D01–D16 | Dimensions: columns, unique keys, calendar with no gaps (whole years), every attribute incl. `month_label` recomputed from the date, products/countries/channels match clean |
| X01–X07 | Relationships: every fact key exists in its dimension; `is_core_market` agrees with clean |
| M01 | The diagram `data/mart/model.html` shows every table, column and relationship |

## Steps

1. **Gate: the clean layer must have passed.**
   Read `runs/<run>/2-clean/clean-checks.md` (written by the `/clean` skill).
   - Missing → stop and ask the user to run `/clean <run>` first.
   - Not "PASS - clean layer OK" → stop, show the failing checks, and ask.

2. **Build**
   `python .claude/skills/mart/mart.py --run <run>`
   If it prints `STOPPED`, report the reason and ask. Don't add values to `rules.json` on your own.

3. **Check**
   `python .claude/skills/mart/check.py --run <run>`
   - All PASS → the model is ready for Power BI.
   - Any FAIL → the model must not be used. Show the failing checks with their examples, find the cause, and propose a fix. Only make the fix after a yes.

4. **Report to the user:** short, result first.
   - the verdict (e.g. 43/43 PASS)
   - rows per table, and the path of the diagram (`data/mart/model.html`)
   - headline numbers: total revenue (core markets vs ES/AT), orders, stock on hand (latest month), discount amount, units sold
   - anything unusual compared with the previous build: check the previous `runs/*/3-mart/mart-checks.md`

## The model (full design: `knowledge/data-model.md`)

| Table | Grain | Key columns |
|---|---|---|
| `fact_sales` | one order line | `date_key`, `sku`, `country_code`, `channel` (+ `order_id` for counting orders) |
| `fact_inventory` | one sku × month end | `date_key` (month-end date), `sku` |
| `dim_date` | one day, full calendar years | `date_key` (yyyymmdd) (+ `month_label`, e.g. "Jan 2025", so months of different years stay apart) |
| `dim_product` | one sku | `sku` |
| `dim_country` | one country | `country_code` (+ `is_core_market`) |
| `dim_channel` | one channel | `channel` |

**Measures** (`knowledge/metrics.md`):
- **Revenue:** sum of `revenue`. Per line, quantity × unit_price × (1 − discount_rate), rounded half-up.
- **Orders:** distinct `order_id`.
- **Units sold:** sum of `quantity`.
- **Discount amount:** sum of `discount_amount`.
- **Stock on hand:** `qty_on_hand` at the latest month in the selection, never summed across months.

**Decisions:**
- Best-selling products are ranked by revenue.
- "Ran out" means `qty_on_hand = 0` at month end.
- All countries are shown by default, with `is_core_market` available as a filter.

**Limits:**
- Stock doesn't respond to the country or channel filters.
- Revenue is before returns.

## Querying the model

When the user asks a question of the model, answer with SQL against `data/mart/` and run it, so the answer is real output, not a guess. Use Python's built-in `sqlite3` in memory (load the CSVs with pandas). Show the result first, then the SQL. Confirm the total ties out to `3-mart/mart-checks.md`.

Worked example: products ranked by sales (revenue), highest first.
```sql
SELECT
    p.sku,
    p.product_name,
    p.brand,
    p.category,
    COALESCE(SUM(f.quantity), 0)          AS units_sold,
    COUNT(DISTINCT f.order_id)            AS orders,
    ROUND(COALESCE(SUM(f.revenue), 0), 2) AS revenue
FROM dim_product AS p
LEFT JOIN fact_sales AS f
       ON f.sku = p.sku
GROUP BY p.sku, p.product_name, p.brand, p.category
ORDER BY revenue DESC;
```
- **Start from the dimension with a LEFT JOIN**, so items with no sales still appear (with 0).
- **Count orders with `COUNT(DISTINCT order_id)`**, never `COUNT(*)`, which counts lines.
- **Core markets only:** join `dim_country` and add `WHERE c.is_core_market = 'True'`.
- **Stock:** filter `fact_inventory` to one month-end `date_key`. Never sum stock across months.
- **Ambiguous questions:** if "sales" could mean revenue or units, say which you used and show how to switch.

2025 reference: total revenue €33,506,864.27; 101,142 orders; stock on hand in December 2025 is 41,307 units.

## Rules

- **Never modify `data/clean`.** Only overwrite the six CSVs and `model.html` in `data/mart/`.
- **Never hand-edit `model.html`.** It's regenerated on every build; change the design in `mart.py` instead.
- **Business-list changes go into `knowledge/rules.json` only.** That covers new markets, countries and channels. The profile, clean and mart scripts all read it.
- **Table design changes are proposed first.** That covers a new column, table or relationship. Make them only after a yes. Then update all of these together:
  - the RULES section of `mart.py` (incl. `COLUMN_TYPES`; the diagram follows automatically)
  - the checks in `check.py`
  - `knowledge/data-model.md`
- **Business definitions belong to the user.** Don't invent new measures or definitions; ask.
- **A script failure is a blocker.** If a script errors twice the same way, stop and tell the user what's blocking you.
- **Clean up.** Delete any temporary files when done.
