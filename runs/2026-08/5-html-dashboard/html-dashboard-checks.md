# Dashboard checks - run 2026-08

Script: `.claude/skills/html-dashboard/check.py` · Page: `reports/html/dashboard.html` · Road B: SQL on `data/mart`

**PASS - dashboard OK**

Headline numbers (page = SQL):
- Total revenue €33,506,864.27
- Orders 101,142
- Stock on hand 41,307 units (Dec 2025)
- 11 products ran out (stock 0 at end of Dec 2025)

| ID | Check | Result | Detail |
|---|---|---|---|
| H01 | Dashboard file exists | PASS | reports\html\dashboard.html (2.64 MB) |
| H02 | Self-contained (no internet links, no external scripts/styles) | PASS | none found |
| H03 | No test hook left in the page | PASS | none |
| H04 | Built from the current mart (page newer than every mart CSV) | PASS | ok |
| P01 | Default (no filters) | PASS | revenue €33,506,864.27 · orders 101,142 · stock 41,307 (Dec 2025) · 12 months, 6 countries, top 10, table line |
| P02 | Month = 2025-12 | PASS | revenue €3,417,243.75 · orders 12,359 · stock 41,307 (Dec 2025) · 12 months, 6 countries, top 10, table line |
| P03 | Country DE + channel web | PASS | revenue €8,542,764.87 · orders 22,215 · stock 41,307 (Dec 2025) · 12 months, 6 countries, top 10, table line |
| P04 | Category = Accessories | PASS | revenue €3,432,190.70 · orders 69,414 · stock 26,532 (Dec 2025) · 12 months, 6 countries, top 10, table line |
| P05 | Months 2025-03+2025-04, category Phones & Tablets | PASS | revenue €1,887,111.21 · orders 4,087 · stock 5,411 (Apr 2025) · 12 months, 6 countries, top 10, table line |
| P06 | Categories Accessories + Phones & Tablets (13,547 orders have both) | PASS | revenue €16,327,929.58 · orders 83,954 · stock 32,551 (Dec 2025) · 12 months, 6 countries, top 10, table line · orders 83,954 = union, not the sum 97,501 |
| I01 | Click a bar twice at the same spot: filters, then clears | PASS | 7 bars tested |
| I02 | Nothing moves or resizes when filters change | PASS | all panels identical |
| I03 | Sort the table, then Clear all: default order back | PASS | ok |
| I04 | Stock ignores country/channel, and both notes say so | PASS | stock unchanged under P03, notes shown only when country/channel filtered |
| I05 | Header period follows the month filter | PASS | (none) -> 'Jan–Dec 2025' · Mar 2025 + Jul 2025 -> 'Mar, Jul 2025' · Oct 2025 + Nov 2025 + Dec 2025 -> 'Oct–Dec 2025' |
| I06 | No script errors on the page | PASS | none |
