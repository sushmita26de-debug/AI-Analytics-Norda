# Mart check - run 2026-08

Mart: `data\mart` · reconciled against clean: `data\clean\all`

**PASS - mart OK** (43 checks)

Dashboard headline numbers:

- Total revenue: EUR 33,506,864.27  (core markets EUR 29,138,441.73 · ES/AT EUR 4,368,422.54)
- Number of orders: 101,142
- Stock on hand (latest month, 2025-12): 41,307 units
- Discount amount: EUR 738,946.09 · Units sold: 205,473

| ID | Check | Result | Failing | Detail |
|---|---|---|---|---|
| F01 | fact_sales columns exact and in order | PASS | 0 |  |
| F02 | fact_inventory columns exact and in order | PASS | 0 |  |
| F03 | fact_sales has no blank values | PASS | 0 |  |
| F04 | fact_inventory has no blank values | PASS | 0 |  |
| F05 | fact_sales rows = clean orders rows | PASS | 0 | 156,824 vs 156,824 |
| F06 | fact_inventory rows = clean inventory rows | PASS | 0 | 4,222 vs 4,222 |
| F07 | sales date_key = order_date (yyyymmdd) | PASS | 0 |  |
| F08 | quantity is a whole number >= 1 | PASS | 0 |  |
| F09 | unit_price > 0 | PASS | 0 |  |
| F10 | discount_rate between 0 and 0.5 | PASS | 0 |  |
| F11 | revenue = quantity x unit_price x (1 - discount_rate), half-up | PASS | 0 |  |
| F12 | discount_amount = quantity x unit_price x discount_rate, half-up | PASS | 0 |  |
| F13 | revenue between 0 and quantity x unit_price | PASS | 0 |  |
| F14 | units per month = clean orders | PASS | 0 | 12 months compared |
| F15 | distinct order_id = clean orders | PASS | 0 | 101,142 vs 101,142 |
| F16 | inventory date_key = last day of stock_month | PASS | 0 |  |
| F17 | inventory sku + date_key unique | PASS | 0 |  |
| F18 | qty_on_hand is a whole number >= 0 | PASS | 0 |  |
| F19 | stock per month = clean inventory | PASS | 0 | 12 months compared |
| D01 | dimension columns exact and in order | PASS | 0 |  |
| D02 | dimension keys unique | PASS | 0 |  |
| D03 | dimension keys never blank | PASS | 0 |  |
| D04 | no blank values in any dimension column | PASS | 0 |  |
| D05 | dim_date has no missing days | PASS | 0 |  |
| D06 | dim_date starts on 1 Jan and ends on 31 Dec | PASS | 0 | 2025-01-01 .. 2025-12-31 |
| D07 | dim_date covers every order date | PASS | 0 |  |
| D08 | date_key = date without dashes | PASS | 0 |  |
| D09 | dim_date attributes match the date | PASS | 0 |  |
| D10 | dim_product has the same skus as clean products | PASS | 0 | 377 vs 377 |
| D11 | dim_product rows identical to clean products | PASS | 0 |  |
| D12 | dim_country codes = country codes in orders | PASS | 0 |  |
| D13 | country_name matches the country list | PASS | 0 |  |
| D14 | is_core_market True exactly for ['DE', 'FR', 'IT', 'NL'] | PASS | 0 |  |
| D15 | dim_channel = channels in orders | PASS | 0 |  |
| D16 | all channels allowed ['app', 'marketplace', 'web'] | PASS | 0 |  |
| X01 | every fact_sales.date_key exists in dim_date.date_key | PASS | 0 |  |
| X02 | every fact_sales.sku exists in dim_product.sku | PASS | 0 |  |
| X03 | every fact_sales.country_code exists in dim_country.country_code | PASS | 0 |  |
| X04 | every fact_sales.channel exists in dim_channel.channel | PASS | 0 |  |
| X05 | every fact_inventory.date_key exists in dim_date.date_key | PASS | 0 |  |
| X06 | every fact_inventory.sku exists in dim_product.sku | PASS | 0 |  |
| X07 | clean orders is_core_market agrees with dim_country | PASS | 0 |  |
| M01 | model.html shows every table, column and relationship | PASS | 0 |  |
