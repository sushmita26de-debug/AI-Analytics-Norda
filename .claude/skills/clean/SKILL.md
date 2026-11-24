---
name: clean
description: Clean a monthly NORDA delivery from data/raw/<month>/ into data/clean/<month>/ (fixes all known data issues, friendly snake_case column names, standard formats), then rebuild the combined history data/clean/all/ (orders and inventory appended, new products added, existing products get the newest price), and verify both with pass/fail checks reconciled against raw. Use when the user asks to clean the raw data, after /profile has run for that month. Never modifies data/raw.
---

# Clean a delivery

Usage: `/clean <run-month>`, e.g. `/clean 2026-09`. If no month is given, ask for it.

Pipeline: `/profile` → **`/clean`** → `/mart` → `/quality-gate` → `/html-dashboard` and `/powerbi` (every month) · `/ppt-review` (when there are questions). This skill is step 2.

Follow CLAUDE.md throughout: tag load-bearing claims [high]/[med]/[guess], don't guess about the business, keep it short.

## Files in this folder

| File | What it does |
|---|---|
| `clean.py` | `data/raw/<run>/` → `data/clean/<run>/` (`orders.csv`, `products.csv`, `inventory.csv`). Then it rebuilds **`data/clean/all/`** from every delivery folder, oldest first. It also writes `runs/<run>/2-clean/clean-log.md`, with each delivery's rows and the combined totals. Allowed values come from `knowledge/rules.json`. Its RULES section holds the column names. It stops and writes nothing if the raw data contains something the rules don't cover, or if the delivery overlaps the history (an order number or stock row already loaded, or an existing sku with a new name, brand or category). |
| `check.py` | Checks the clean layer and writes `runs/<run>/2-clean/clean-checks.md`. There are three parts, 49 checks: (A) rules on the delivery's clean files, (B) reconciliation against `data/raw/<run>/`, and (C) the combined history `data/clean/all/` re-derived independently from every delivery folder. Every check must PASS; any FAIL → exit code 1. |

Run both from the project root. Neither ever modifies `data/raw`.

## The checks

49 checks; every one must PASS.

| IDs | What they check |
|---|---|
| A01–A05, O01–O13, P01–P06, I01–I04 | (A) The delivery's clean files on their own: columns, no spaces, no identical rows, formats, allowed values, keys, every sku in the catalogue (this delivery + history) |
| R01–R11 | (B) Reconciliation with `data/raw/<run>/`: only the identical copies were removed, every order line, date, country, channel, customer, product and stock row is still there |
| C01–C10 | (C) The combined history `data/clean/all/`, re-derived independently from every delivery folder: every order line and stock row exactly once, no order in two deliveries, products = the newest delivery's row, no name/brand/category change, every sku known |

## Steps

1. **Gate: the raw data must be profiled.**
   Read `runs/<run>/1-profile/profile-checks.md` (written by the `/profile` skill).
   - Missing → stop and ask the user to run `/profile <run>` first.
   - Verdict is not "OK - no blockers" → stop, show the blockers, and ask.

2. **Clean**
   `python .claude/skills/clean/clean.py --run <run>`
   If it prints `STOPPED`, report the reason and ask the user how to handle it. Don't change the rules on your own.

3. **Check**
   `python .claude/skills/clean/check.py --run <run>`
   - All PASS → the clean data is ready.
   - Any FAIL → the clean data must not be used. Show the failing checks with their examples, find the cause, and propose a fix. Only make the fix after a yes.

4. **Report to the user:** short, result first.
   - the check verdict (e.g. 49/49 PASS)
   - rows in and out per file, with each step's count (from `2-clean/clean-log.md`)
   - order rows: total, core markets (`is_core_market = True`) and ES/AT
   - the combined history: order rows, stock rows, products, and how many prices changed
   - anything unusual compared with the previous month in `data/clean/`

   Don't calculate revenue or other business measures here. Those will be defined later, outside the clean layer.

## What the cleaning does (decisions in `knowledge/metadata.md`)

**orders.csv:** `order_id, order_date, channel, country_code, is_core_market, customer_id, sku, quantity, unit_price, discount_rate`
- **Duplicates:** completely identical raw rows are removed, keeping one copy.
- **Dates:** become `YYYY-MM-DD`. Slash dates are read as DD/MM.
- **Countries:** full names become codes. ES/AT are **kept**, with `is_core_market = False`.
- **Customer IDs:** `customer_id` is cleared on marketplace rows; the rows are kept.
- **Discount:** `discount_rate` is a fraction, and `unit_price` is the price before discount.
- **No calculated columns:** amounts and business definitions are added later, outside this skill.

**products.csv:** `sku, product_name, brand, category, latest_list_price`
- Brand and category case is fixed.
- `latest_list_price` is the current price, so don't use it to value past sales.

**inventory.csv:** `sku, stock_month, qty_on_hand`
- `stock_month` becomes `YYYY-MM`.
- `reserved_qty` is removed, because it was dropped from the export.

**Combined history `data/clean/all/`** (what the model is built from):
- **orders:** every delivery's orders, each exactly once (appended).
- **inventory:** every delivery's stock rows, each exactly once (appended).
- **products:** one row per sku. New skus are added; `latest_list_price` comes from the newest delivery that has the sku. Name, brand and category must never change.
- It is rebuilt from the delivery folders on every run, so it can always be recreated.

**All files:**
- UTF-8, comma-separated
- spaces trimmed
- money written with 2 decimals

## Rules

- **Never modify `data/raw`.** Each run writes only to its own folder, `data/clean/<run>/`, and to `data/clean/all/`. It never touches another month's folder. Never edit `data/clean/all/` by hand; it is rebuilt from the delivery folders.
- **Business-list changes go into `knowledge/rules.json` only.** Examples: a new market, country, brand or channel. The profile, clean and mart scripts all read it. Column changes go into the RULES section of `clean.py`, which `check.py` reads. Either way, propose the change first and make it only after a yes.
- **New issues become questions.** A new issue in the raw data is not something to decide yourself. Record any decision in `knowledge/metadata.md`.
- **A script failure is a blocker.** If a script errors twice the same way, stop and tell the user what's blocking you.
- **Clean up.** Delete any temporary files when done.
