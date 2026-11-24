# Power BI checks - run 2026-08

Script: `.claude/skills/powerbi/check.py` · Project: `reports/powerbi/NORDA Sales.pbip` · Road B: SQL on `data/mart`

**PASS - Power BI OK**

| ID | Check | Result | Detail |
|---|---|---|---|
| B01 | Every table reads its CSV from this mart | PASS | C:\Users\Sushmita\OneDrive\Desktop\AI in Analytics Linkedin\data\mart |
| B02 | Model loads, no measure errors | PASS | 19 measures |
| B03 | Refresh from data/mart works | PASS | ok |
| B04 | Row counts = the mart CSVs | PASS | dim_date 365 · dim_product 377 · dim_country 6 · dim_channel 3 · fact_sales 156,824 · fact_inventory 4,222 |
| P01 | Default (no filters) | PASS | revenue 33506864.27 · orders 101142 · stock 41307 (Dec 2025) · ran out 11 · period 'Jan–Dec 2025' · 12 months, countries, top 10 |
| P02 | Month = 2025-12 | PASS | revenue 3417243.75 · orders 12359 · stock 41307 (Dec 2025) · ran out 11 · period 'Dec 2025' · 12 months, countries, top 10 |
| P03 | Country DE + channel web | PASS | revenue 8542764.87 · orders 22215 · stock 41307 (Dec 2025) · ran out 11 · period 'Jan–Dec 2025' · 12 months, countries, top 10 |
| P04 | Category = Accessories | PASS | revenue 3432190.7 · orders 69414 · stock 26532 (Dec 2025) · ran out 7 · period 'Jan–Dec 2025' · 12 months, countries, top 10 |
| P05 | Months 2025-03+2025-04, category Phones & Tablets | PASS | revenue 1887111.21 · orders 4087 · stock 5411 (Apr 2025) · ran out 0 · period 'Mar, Apr 2025' · 12 months, countries, top 10 |
| P06 | Categories Accessories + Phones & Tablets (13,547 orders have both) | PASS | revenue 16327929.58 · orders 83954 · stock 32551 (Dec 2025) · ran out 7 · period 'Jan–Dec 2025' · 12 months, countries, top 10 |
| P07 | Months 2025-03 + 2025-07 (period text) | PASS | revenue 5274764.84 · orders 15461 · stock 34472 (Jul 2025) · ran out 4 · period 'Mar, Jul 2025' · 12 months, countries, top 10 |
| D01 | Top 10 Revenue: same 10 products and values | PASS | #1 Kova K7-2800 |
| D02 | Top 10 Revenue, Accessories | PASS |  |
| D03 | Months at 0 per product | PASS | 23 products with a month at 0 |
| D04 | Products in Selection | PASS | 377 |
| D05 | Table Summary text | PASS | 377 products, 11 ran out (stock 0 at end of Dec 2025) · 23 were at 0 in at least one month |
| D06 | Stock Caption text | PASS | units at month end, Dec 2025 |
| D07 | Colour Month: amber only on Dec 2025 | PASS | ['Dec 2025'] |
| D08 | Colour Country: amber only on Germany | PASS | ['Germany'] |
| D09 | Colour Product: amber only on Kova K7-2800 | PASS | ['Kova K7-2800'] |
| D10 | Colour Stock: amber on exactly the 11 products that ran out | PASS |  |
| S01 | Screenshot of the Power BI window | PASS | runs/2026-08/7-powerbi/powerbi.png |
