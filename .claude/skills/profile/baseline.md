# Baseline – 2025 raw data

These are the reference values for checking each new monthly export. They come from the first profile run (`runs/2026-08`), which covered orders, products and inventory for 2025-01 → 2025-12, profiled on 2026-11-24.

All values are raw, as delivered (before any cleaning). EUR values are calculated as `QTY × UNIT_PRC × (1 − DISC_PCT)`.

**How to use:** compare the new month against the monthly ranges below. If a value falls outside its range, or a share moves by more than a few points, report it as a finding. It isn't automatically a problem.

---

## Volumes

| Measure | 2025 total | Per month (min – max) |
|---|---|---|
| Order rows | 160,821 | 9,869 (Jun) – 19,355 (Dec); Jan–Sep 11.4k–13.9k, Oct–Dec 15.3k–19.4k |
| Orders | 101,142 | – |
| Lines per order | mean 1.59, max 10 | – |
| Order rows per day | median 423 | min 191 (Sun 22 Jun) – max 1,830 (1 Dec) |
| Value (EUR) | 34.32M | 2.20M (Jun) – 3.51M (Dec); Jan–Sep 2.5M–3.1M, Oct–Dec 3.2M–3.5M |
| Order number range | SO443307 – SO557664 | 11.6% of numbers in the range never appear |

Seasonality: volume rises September → December, peaking 29 Nov – 2 Dec. June is the lowest month.

## Known issues (check.py), 2025 level

| ID | Known issue | 2025 count | Share | Per month |
|---|---|---|---|---|
| O01 | Dates in DD/MM/YYYY | 80,742 rows | 50.2% | ~50% every month |
| O06 | Completely identical rows (extra copies) | 3,997 rows | 2.5% · €0.81M | 249 – 494; always exact pairs |
| O08 | ES + AT rows (kept for now) | 22,486 rows (ES 15,434 · AT 7,052) | 14.0% · €4.47M | 12.8% – 14.8% |
| O09 | Full country name instead of code | 1,642 rows | 1.0% | – |
| O12 | Marketplace row with CUST_REF | 6,618 rows | 24.4% of marketplace rows | 17.9% – 27.8% |
| P01 | Brand or category in wrong case | 60 products | 15.9% | – |
| I01 | stk_month as YYYY-M | 6 rows | 0.1% | – |
| I02 | reserved_qty empty | 4,222 rows | 100% | 100% |

All blocker checks passed in 2025 (count 0).

## Distributions

**Channel (rows):** web 50.8% · app 32.4% · marketplace 16.9%

**Country (rows, names mapped to codes):** DE 45.2% · FR 17.1% · NL 12.0% · IT 11.8% · ES 9.6% · AT 4.4%

**CUST_REF blank:**
- web 10.8%
- app 5.9%
- marketplace 75.6%

**QTY:** always 1–8. 81.6% of rows are 1.

**DISC_PCT:**
- Values: 0 – 0.50, in steps of 0.05.
- Rows with a discount: 13.0% overall. That's 7–10% in normal months, with peaks in Jul 27.6%, Nov 23.6%, Dec 18.9% and Mar 13.0%.
- The rate is similar across channels (12.7%–13.9%).

**UNIT_PRC vs list_price:**
- The ratio ranges from 0.925 to 1.395. Nothing falls outside 0.5–1.5.
- 55.8% of rows are at list, 41.2% above and 2.9% below.
- The share above list falls from 47.7% (Jan) to 35.9% (Dec), because `list_price` is the latest price.
- Each article sells at no more than 3 distinct prices.

## Products

- 377 SKUs, all unique. 2 are never sold or stocked: `KO-27064` and `NO-78001`.
- The SKU prefix always matches the brand: KA Kaivo, KO Kova, NO Nodo, ON Ondia, PA Pavo, VI Visna.

| Brand | SKUs | Categories |
|---|---|---|
| Nodo | 178 | Accessories |
| Ondia | 56 | Audio |
| Kova | 48 | Computers 43, Monitors 5 |
| Kaivo | 44 | Phones & Tablets 38, Audio 6 |
| Visna | 27 | Monitors |
| Pavo | 24 | Phones & Tablets |

| Category | list_price min – median – max (EUR) |
|---|---|
| Accessories | 8.99 – 21.03 – 109.99 |
| Audio | 26.99 – 80.47 – 279.99 |
| Monitors | 119.99 – 314.48 – 832.99 |
| Phones & Tablets | 129.55 – 514.47 – 1,297.99 |
| Computers | 360.99 – 1,041.99 – 2,104.99 |

## Inventory

- Articles with a stock row: 320 (Jan) rising to 375 (Dec). New articles each month range from 1 to 10.
- A new article's first stock row is in the month it's first sold. There are no gaps between an article's first and last row.
- qty_hand: 0 – 1,165, median 79. Zero stock appears in 1.7% of rows.
