# Raw data check - run 2026-08

Data: `data\raw\2026-08`

**Verdict: OK - no blockers**  ·  blockers failing: 0  ·  known issues present: 8  ·  checks: 40

FAIL = the case is present. *known* = decided, reported, run continues. *blocker* = stop and ask.

| ID | Label | Check | Result | Found | Detail |
|---|---|---|---|---|---|
| S01 | blocker | File missing (orders/products/inventory) | PASS | 0 |  |
| S02 | blocker | orders: columns differ from expected | PASS | 0 |  |
| S03 | blocker | products: columns differ from expected | PASS | 0 |  |
| S04 | blocker | inventory: columns differ from expected | PASS | 0 |  |
| S05 | blocker | File has no rows | PASS | 0 |  |
| O01 | known | Dates in DD/MM/YYYY instead of YYYY-MM-DD | FAIL | 80,742 (50.21%) |  |
| O02 | blocker | Date in unknown format or not a real date | PASS | 0 |  |
| O03 | blocker | Slash date only valid as MM/DD (DD/MM rule broken) | PASS | 0 |  |
| O04 | blocker | Order dated earlier than the previous order number | PASS | 0 |  |
| O05 | blocker | Order dated outside expected month | NOT RUN | - | no --expect-month given; data range 2025-01-01 -> 2025-12-31 |
| O06 | known | Completely identical rows (extra copies) | FAIL | 3,997 (2.49%) |  |
| O07 | blocker | Blank key field | PASS | 0 |  |
| O08 | known | Rows for countries outside the 4 markets ['AT', 'ES'] (kept for now) | FAIL | 22,486 (13.98%) | by country: {'ES': 15434, 'AT': 7052} |
| O09 | known | Full country name instead of code | FAIL | 1,642 (1.02%) |  |
| O10 | blocker | Unknown country value | PASS | 0 |  |
| O11 | blocker | Unknown channel value | PASS | 0 |  |
| O12 | known | Marketplace row with CUST_REF | FAIL | 6,618 (4.12%) |  |
| O13 | blocker | Order with >1 date, channel, country or customer | PASS | 0 |  |
| O14 | blocker | DISC_PCT not a number in 0..0.5 (fraction) | PASS | 0 |  |
| O15 | blocker | QTY missing, <= 0 or not a whole number | PASS | 0 |  |
| O16 | blocker | UNIT_PRC missing or <= 0 | PASS | 0 |  |
| O17 | blocker | ART_NO not in products | PASS | 0 |  |
| O18 | blocker | UNIT_PRC outside 0.5x-1.5x of list_price | PASS | 0 |  |
| P01 | known | Brand or category in wrong case | FAIL | 60 (15.92%) |  |
| P02 | blocker | Unknown brand or category (after case fix) | PASS | 0 |  |
| P03 | blocker | Duplicate sku | PASS | 0 |  |
| P04 | blocker | list_price missing or <= 0 | PASS | 0 |  |
| I01 | known | stk_month written as YYYY-M (no leading zero) | FAIL | 6 (0.14%) |  |
| I02 | known | reserved_qty empty (dropped from export) | FAIL | 4,222 (100.00%) |  |
| I03 | blocker | reserved_qty has values (was dropped, now back?) | PASS | 0 |  |
| I04 | blocker | stk_month in unknown format | PASS | 0 |  |
| I05 | blocker | qty_hand missing or negative | PASS | 0 |  |
| I06 | blocker | Duplicate art_no + month | PASS | 0 |  |
| I07 | blocker | art_no not in products | PASS | 0 |  |
| I08 | blocker | Article sold in a month with no stock row | PASS | 0 |  |
| H01 | blocker | Order number already loaded in an earlier delivery (would count twice) | PASS | 0 | first delivery - no history yet |
| H02 | blocker | Stock row (art_no + month) already loaded in an earlier delivery | PASS | 0 | first delivery - no history yet |
| H03 | blocker | Existing sku with a different product_name, brand or category than loaded | PASS | 0 | first delivery - no history yet |
| H04 | known | Existing sku with a new list_price (updated in the products table) | PASS | 0 | first delivery - no history yet |
| H05 | known | New sku (added to the products table) | PASS | 0 | first delivery - no history yet |
