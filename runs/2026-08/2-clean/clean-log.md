# Clean log - run 2-clean

- Raw: `data\raw\2026-08`  ->  Clean: `data\clean\2026-08`
- Run: 2026-11-25 01:39
- Rules: decisions in `knowledge/metadata.md`

| File | Step | Rows |
|---|---|---|
| orders | rows in (raw) | 160,821 |
| orders | removed: completely identical rows (extra copies) | 3,997 |
| orders | changed: DD/MM/YYYY dates converted to YYYY-MM-DD | 78,757 |
| orders | changed: full country name -> code | 1,600 |
| orders | flagged: is_core_market = False (ES/AT, rows kept) | 21,941 |
| orders | changed: customer_id cleared on marketplace rows | 6,452 |
| orders | rows out (clean) | 156,824 |
| products | rows in (raw) | 377 |
| products | changed: brand case fixed | 28 |
| products | changed: category case fixed | 36 |
| products | rows out (clean) | 377 |
| inventory | rows in (raw) | 4,222 |
| inventory | removed column: reserved_qty (always empty) | 0 |
| inventory | changed: stock month YYYY-M -> YYYY-MM | 6 |
| inventory | rows out (clean) | 4,222 |
| all | delivery 2026-08: order rows / stock rows / product rows | 156,824 / 4,222 / 377 |
| all | orders: rows (appended) | 156,824 |
| all | inventory: rows (appended) | 4,222 |
| all | products: skus (new skus added) | 377 |
| all | products: skus whose latest_list_price changed across deliveries | 0 |

Column renames:

| File | Raw | Clean |
|---|---|---|
| orders | ORD_NO, CRTD_DT, CHNL, CTRY, CUST_REF, ART_NO, QTY, UNIT_PRC, DISC_PCT | order_id, order_date, channel, country_code, customer_id, sku, quantity, unit_price, discount_rate |
| orders | (new) | is_core_market |
| products | list_price | latest_list_price |
| inventory | art_no, stk_month, qty_hand, reserved_qty | sku, stock_month, qty_on_hand, (removed) |
