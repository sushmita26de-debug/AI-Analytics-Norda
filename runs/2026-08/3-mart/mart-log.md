# Mart build log - run 2026-08

- Source: `data\clean\all`  ->  Mart: `data\mart`
- Built: 2026-11-25 01:51
- Design: `knowledge/data-model.md` · Metrics: `knowledge/metrics.md`

| Table | Rows | Columns |
|---|---|---|
| fact_sales | 156,824 | order_id, date_key, sku, country_code, channel, quantity, unit_price, discount_rate, revenue, discount_amount |
| fact_inventory | 4,222 | date_key, sku, qty_on_hand |
| dim_date | 365 | date_key, date, year, quarter, month_no, month_name, year_month, weekday, is_weekend, month_label |
| dim_product | 377 | sku, product_name, brand, category, latest_list_price |
| dim_country | 6 | country_code, country_name, is_core_market |
| dim_channel | 3 | channel |

Diagram: `data\mart\model.html` (generated from the design in mart.py)
