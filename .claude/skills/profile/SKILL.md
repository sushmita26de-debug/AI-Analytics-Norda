---
name: profile
description: Profile and check a new monthly NORDA delivery (orders, products, inventory in data/raw/<month>/). Runs pass/fail checks for every known data issue and against the history of earlier deliveries (order or stock row already loaded, product attribute changes, price changes, new products), profiles every column, compares against baseline.md and knowledge/metadata.md, and writes runs/<month>/1-profile/ (profile-checks.md, profile-output.txt, findings.md). Use when new raw data arrives or the user asks to profile or check the raw files. Never cleans data.
---

# Profile a new delivery

Usage: `/profile <run-month>`, e.g. `/profile 2026-09`. If no month is given, ask for it.
If the user says which month the orders should cover, pass it as `--expect-month`.

Pipeline: **`/profile`** → `/clean` → `/mart` → `/quality-gate` → `/html-dashboard` and `/powerbi` (every month) · `/ppt-review` (when there are questions). This skill is step 1.

Follow CLAUDE.md throughout: tag load-bearing claims [high]/[med]/[guess], don't guess about the business, keep it short.

## Files in this folder

| File | What it is |
|---|---|
| `check.py` | 40 pass/fail checks on `data/raw/<run>/`. Writes `runs/<run>/1-profile/profile-checks.md`. Business lists (markets, countries, channels, brands, categories) come from `knowledge/rules.json`. Its RULES section holds the rest: raw columns, date formats, limits. |
| `profile.py` | Full profile of every column plus business checks. Reads the rules from `check.py`. Writes `runs/<run>/1-profile/profile-output.txt`. |
| `baseline.md` | Reference values from 2025: volumes, known-issue levels, distributions. Compare every new month against it. |

Both scripts are read-only on the raw folder. Run them from the project root.

## The checks

FAIL = the case is present. *known* = decided, reported, the run continues. *blocker* = stop and ask. Exit code 1 if a blocker fails.

| IDs | What they check |
|---|---|
| S01–S05 | Structure: the 3 files exist, have the expected columns, and are not empty |
| O01–O18 | Orders: dates, identical rows, countries, channels, marketplace customers, one date/channel/country per order, discount, quantity, price, sku in the catalogue, price near the list price |
| P01–P04 | Products: brand/category case, unknown values, duplicate sku, list price |
| I01–I08 | Inventory: month format, `reserved_qty`, negative stock, duplicates, sku in the catalogue, every sold article has a stock row |
| H01–H05 | History: the new delivery against every earlier delivery folder (table below) |

| ID | Label | Case |
|---|---|---|
| H01 | blocker | An order number that is already loaded (it would count twice) |
| H02 | blocker | A stock row (art_no + month) that is already loaded |
| H03 | blocker | An existing sku with a different name, brand or category |
| H04 | known | An existing sku with a new price (listed: sku, old → new) |
| H05 | known | A new sku |

Orders and stock rows may use products from earlier deliveries, because a monthly products file may hold only new or changed products.

## Steps

1. **Check**
   `python .claude/skills/profile/check.py --run <run> [--expect-month YYYY-MM]`
   This reads `data/raw/<run>/` and writes `runs/<run>/1-profile/profile-checks.md`.

2. **If any blocker fails or a check is NOT RUN:** stop. Show the user the failing blockers with their examples, and ask how to proceed. Don't continue to step 3 without a yes. O05 is the only exception: it is NOT RUN when no `--expect-month` was given, and that's fine.

3. **Profile**
   `python .claude/skills/profile/profile.py --run <run>` (reads `data/raw/<run>/`)
   Then read `runs/<run>/1-profile/profile-output.txt`.

4. **Compare**
   - Against `baseline.md`: volumes, known-issue counts and shares, distributions.
   - Against `knowledge/metadata.md`: columns, meanings, decisions.
   - Against the previous run in `runs/`, if there is one.
   - `baseline.md` holds a whole year (2025). A monthly delivery has about one twelfth of the volume, so compare its volumes with the baseline's monthly figures.
   - Flag anything outside the baseline range, a known-issue share that moved by more than a few points, or anything new that no check covers. Examples: a new value, a volume drop, a new pattern.

5. **Write `runs/<run>/1-profile/findings.md`**
   Use the same structure as `runs/2026-08/1-profile/findings.md`:
   - summary table of what changes the numbers, with rows and EUR value
   - findings per file
   - questions for the user

   Findings only. No cleaning.

6. **Report to the user:** short, result first.
   - the verdict
   - blockers
   - known issues compared with the baseline
   - new findings
   - history: new products, price changes (old → new), and any H01–H03 blocker
   - questions

## Monthly deliveries

Every month brings a new delivery of 3 files in its own folder, `data/raw/<run>/`. Earlier folders are the history and are never changed. The first delivery, `data/raw/2026-08/`, holds all of 2025.
- **orders** and **inventory** are appended to the history;
- **products**: new skus are added; existing skus get the new price.

This skill checks **only the new delivery**, plus the H checks that compare it with the history. Decisions: `knowledge/metadata.md`, "Decisions: monthly deliveries".

## Decisions (full list in `knowledge/metadata.md`)

These are encoded as *known* checks:
- **ES/AT:** kept for now, not removed. O08 fails every month as a report, but doesn't stop the run.
- **Identical rows:** extra copies to be removed at cleanup.
- **Marketplace `CUST_REF`:** ignored; the ID is cleared at cleanup and the rows are kept.
- **Dates:** slash dates are DD/MM.
- **`DISC_PCT`:** a fraction; `UNIT_PRC` is before discount.
- **`list_price`:** the latest price, not for valuing past sales.
- **`reserved_qty`:** dropped from the export.
- **Brand/category:** case is normalised.
- **Price change / new product:** expected every month (H04, H05).

## Rules

- **Never modify `data/raw`.** Never clean or fix data in this skill. A new delivery always goes into a new folder `data/raw/<run>/`; never put files into an earlier delivery's folder.
- **New findings become questions.** A new finding is not something to decide. Once the user decides, propose the change:
  - a new check in `check.py`
  - a decision line in `knowledge/metadata.md`

  Make the change only after a yes.
- **Business-list changes go into `knowledge/rules.json` only.** That covers a new market, country, channel, brand or category. The profile, clean and mart scripts all read it. Other rule changes (columns, limits) go into the RULES section of `check.py`, and `profile.py` follows automatically.
- **The baseline stays fixed.** Don't update `baseline.md` unless the user asks for it, e.g. when a new year becomes the reference.
- **A script failure is a blocker.** If a script errors twice the same way, stop and tell the user what's blocking you.
- **Clean up.** Delete any temporary files when done.
