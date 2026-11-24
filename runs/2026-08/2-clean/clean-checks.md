# Clean layer check - run 2026-08

Clean: `data\clean\2026-08` · reconciled against raw: `data\raw\2026-08` · combined history: `data\clean\all`

**PASS - clean layer OK** (49 checks)

| ID | Check | Result | Failing | Detail |
|---|---|---|---|---|
| A01 | orders: columns exactly ['order_id', 'order_date', 'channel', 'country_code', 'is_core_market', 'customer_id', 'sku', 'quantity', 'unit_price', 'discount_rate'] | PASS | 0 |  |
| A02 | products: columns exactly ['sku', 'product_name', 'brand', 'category', 'latest_list_price'] | PASS | 0 |  |
| A03 | inventory: columns exactly ['sku', 'stock_month', 'qty_on_hand'] | PASS | 0 |  |
| A04 | No leading/trailing spaces in any value | PASS | 0 |  |
| A05 | No completely identical rows in any file | PASS | 0 | {'orders': 0, 'products': 0, 'inventory': 0} |
| C01 | all: the 3 combined files exist with the clean columns | PASS | 0 |  |
| C02 | all/orders: every delivery's order lines exactly once (2026-08) | PASS | 0 | deliveries 156,824 rows, all 156,824 |
| C04 | all/inventory: every delivery's stock rows exactly once (2026-08) | PASS | 0 | deliveries 4,222 rows, all 4,222 |
| C03 | all/orders: no order number in two deliveries | PASS | 0 |  |
| C05 | all/inventory: sku + stock_month unique | PASS | 0 |  |
| C06 | all/products: exactly the skus of all deliveries | PASS | 0 | deliveries 377, all 377 |
| C07 | all/products: price, name, brand, category = the newest delivery's row | PASS | 0 |  |
| C08 | all/products: no sku changed name, brand or category between deliveries | PASS | 0 |  |
| C09 | all/orders: every sku exists in all/products | PASS | 0 |  |
| C10 | all/inventory: every sku exists in all/products | PASS | 0 |  |
| O01 | orders: no blank values (except customer_id) | PASS | 0 |  |
| O02 | orders: order_id format SO + 6 digits | PASS | 0 |  |
| O03 | orders: order_date is a real date in YYYY-MM-DD | PASS | 0 |  |
| O04 | orders: channel in ['app', 'marketplace', 'web'] | PASS | 0 |  |
| O05 | orders: country_code in ['AT', 'DE', 'ES', 'FR', 'IT', 'NL'] | PASS | 0 |  |
| O06 | orders: is_core_market = True exactly for ['DE', 'FR', 'IT', 'NL'] | PASS | 0 |  |
| O07 | orders: customer_id empty on marketplace rows | PASS | 0 |  |
| O08 | orders: customer_id format C + 6 digits when filled | PASS | 0 |  |
| O09 | orders: quantity whole number >= 1 | PASS | 0 |  |
| O10 | orders: unit_price > 0 with 2 decimals | PASS | 0 |  |
| O11 | orders: discount_rate between 0 and 0.5 | PASS | 0 |  |
| O12 | orders: every sku exists in products (this delivery + history) | PASS | 0 |  |
| O13 | orders: one date, channel, country and customer per order | PASS | 0 |  |
| P01 | products: sku unique | PASS | 0 |  |
| P02 | products: sku format AA-99999 | PASS | 0 |  |
| P03 | products: brand exactly one of ['Kaivo', 'Kova', 'Nodo', 'Ondia', 'Pavo', 'Visna'] | PASS | 0 |  |
| P04 | products: category exactly one of the 5 categories | PASS | 0 |  |
| P05 | products: latest_list_price > 0 with 2 decimals | PASS | 0 |  |
| P06 | products: no blank product_name | PASS | 0 |  |
| I01 | inventory: stock_month in YYYY-MM | PASS | 0 |  |
| I02 | inventory: sku + stock_month unique | PASS | 0 |  |
| I03 | inventory: qty_on_hand whole number >= 0 | PASS | 0 |  |
| I04 | inventory: every sku exists in products (this delivery + history) | PASS | 0 |  |
| R01 | orders: clean rows = raw rows - identical copies | PASS | 0 | raw 160,821 - copies 3,997 = 156,824; clean 156,824 |
| R02 | orders: every raw order_id is in clean | PASS | 0 |  |
| R03 | orders: every raw line (order, sku, qty, price, discount) is in clean, same count | PASS | 0 |  |
| R04 | orders: each order_date equals the raw date read as DD/MM (row by row) | PASS | 0 |  |
| R05 | orders: sum of quantity per month = raw minus identical copies | PASS | 0 |  |
| R06 | orders: rows per country and per channel match raw | PASS | 0 |  |
| R07 | orders: customer_id unchanged on web/app rows | PASS | 0 |  |
| R08 | products: same skus as raw | PASS | 0 | raw 377, clean 377 |
| R09 | products: only the case of brand/category changed vs raw | PASS | 0 |  |
| R10 | inventory: same rows as raw | PASS | 0 | raw 4,222, clean 4,222 |
| R11 | inventory: same sku, month and qty_on_hand as raw | PASS | 0 |  |
