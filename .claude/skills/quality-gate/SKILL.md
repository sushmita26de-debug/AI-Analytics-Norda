---
name: quality-gate
description: Run the NORDA quality gate (knowledge/quality-rules.md) on a month's data before numbers go to stakeholders. Every dashboard number is computed twice (SQL on data/mart vs pandas straight from every monthly delivery in data/raw/<month>/), 10 random orders of the new delivery are traced raw -> clean -> model, and the always-true rules are tested (every month has sales, no empty files, no negative revenue, December biggest month of 2025). Writes runs/<month>/4-quality-gate/quality-gate-checks.md. Use after /mart has passed, or when the user asks to run the quality gate / quality checks.
---

# Quality gate

Usage: `/quality-gate <run-month>`, e.g. `/quality-gate 2026-09`. If no month is given, ask for it.
To replay a previous trace sample: add `--seed <seed>`. The seed is in the previous report.

Pipeline: `/profile` → `/clean` → `/mart` → **`/quality-gate`** → `/html-dashboard` and `/powerbi` (every month) · `/ppt-review` (when there are questions). This skill is step 4.

Follow CLAUDE.md throughout: tag load-bearing claims [high]/[med]/[guess], don't guess about the business, keep it short.

## Files in this folder

| File | What it is |
|---|---|
| `check.py` | One section per rule in `knowledge/quality-rules.md`. Reads `data/raw`, `data/clean/<run>/` and `data/mart/` (read-only). Writes `runs/<run>/4-quality-gate/quality-gate-checks.md` itself. Each check is PASS or FAIL; any FAIL → exit code 1. Business lists come from `knowledge/rules.json`. |

## The checks (one group per quality rule)

| Rule | Checks | How |
|---|---|---|
| 1. Code computes, Claude understands | none (process rule) | The script computes and writes every number in the report. **This rule also applies to you in every answer** (see below). |
| 2. Two roads, one number | G00–G10 | Every number the dashboard needs, computed twice and compared in whole cents (table below). |
| 3. Trace orders | T01–T10 | 10 random orders **of this run's delivery** (seed recorded) followed `data/raw/<run>/` → `data/clean/<run>/` → model, comparing per order the line count (raw minus identical copies), sku, quantity, price, discount, date (DD/MM), country, channel, customer (cleared if marketplace) and revenue. |
| 4. What must always be true | Q01–Q04 | Every month from first to last has revenue > 0; every CSV in raw, clean and model has at least one row; no negative revenue line; December is the biggest month of 2025, with the margin to the runner-up shown. |

**The two roads in rule 2:**
- **Road A:** SQL on `data/mart/`, which is what Power BI sees.
- **Road B:** pandas straight from **every delivery** in `data/raw/<month>/`. It re-applies the cleaning decisions independently: identical rows removed, DD/MM dates, country names mapped. It also re-applies the delivery rules: orders and stock appended, newest price per product. It recalculates revenue per `knowledge/metrics.md`, rounded half-up.

**The numbers compared:**

| Dashboard element | Compared |
|---|---|
| Headline numbers | Total revenue, number of orders, stock on hand for the latest month |
| Sales per month | Every month |
| Sales per country | Every country |
| Best-selling products | Top 10 by revenue: same products, same order, same values |
| Stock and sales per product | Every product |
| Also from `metrics.md` | Units sold, discount amount |
| Monthly deliveries | Product prices = the newest delivery's price per product (G10) |

## Steps

1. **Gate: the model must have passed.**
   Read `runs/<run>/3-mart/mart-checks.md` (written by `/mart`).
   - Missing → stop and ask the user to run `/mart <run>` first.
   - Not "PASS - mart OK" → stop, show the failing checks, and ask.

2. **Run**
   `python .claude/skills/quality-gate/check.py --run <run> [--seed <seed>]`

3. **If anything fails:** the numbers must not go to stakeholders. Show the failing checks with their details, find the cause, and propose a fix. Only make the fix after a yes. Never weaken a check to make it pass.

4. **Report to the user:** short, result first.
   - the verdict per rule (e.g. Rule 2: 10/10 PASS)
   - the seed, so the sample can be replayed
   - which tricky cases the 10 traced orders happened to cover or miss (read the trace tables in the report): DD/MM dates, mixed formats, identical copies, full country names, marketplace with a customer ID, ES/AT
   - what the results mean for the numbers going to stakeholders

## Rule 1 applies to you

- **Never state a number you didn't get from code.** Quote numbers exactly as the script printed them or as they appear in `quality-gate-checks.md`.
- **No new numbers by hand.** If a new number is needed (a percentage, a difference, a ratio), write and run code to compute it, then quote the output.
- **Your job is the meaning,** not the arithmetic.

## Rules

- **Read-only on all data.** The gate only writes `runs/<run>/4-quality-gate/quality-gate-checks.md`.
- **New rules become checks only after a yes.** If `knowledge/quality-rules.md` gains a rule, propose the new check(s) first, with an ID, how it's tested and what fails it. After a yes, add a section to `check.py`, update the table above, and test that the check can fail on a tampered copy (in the scratchpad, never on real data).
- **Business definitions belong to the user.** If a rule is ambiguous, ask what it means; don't pick one silently.
- **A script failure is a blocker.** If the script errors twice the same way, stop and tell the user what's blocking you.
- **Clean up.** Delete any temporary files when done.
