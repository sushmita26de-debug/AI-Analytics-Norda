# Data model: sales data model (star schema)

This model is for the Power BI sales dashboard (`inbox/dashboard-requirements.pdf`).
- **Source:** the combined clean history, `data/clean/all/` (every monthly delivery: orders and stock appended, newest price per product; built by `/clean`)
- **Metrics:** `knowledge/metrics.md`
- **Diagram:** `data/mart/model.html`, regenerated on every build from the design in `mart.py`

Status: **built and checked** on 2026-11-24 from `data/clean/2026-08/` (2025 data). All 43 checks pass.

## Build

| Step | Command | Output |
|---|---|---|
| Build | `python .claude/skills/mart/mart.py --run <month>` (or `/mart <month>`) | 6 CSVs + `model.html` in `data/mart/` (overwritten each build) and `runs/<month>/3-mart/mart-log.md` |
| Check | `python .claude/skills/mart/check.py --run <month>` | `runs/<month>/3-mart/mart-checks.md`; any FAIL reports an error |

The check covers:
- **F01–F19 (facts):** columns, values, and revenue/discount recomputed independently from clean. Reconciliation with clean: rows, orders, units per month, stock per month.
- **D01–D16 (dimensions):** columns, unique keys, calendar with no gaps, and matches with clean products, countries and channels.
- **X01–X07 (relationships):** every fact key exists in its dimension, and the clean `is_core_market` agrees with `dim_country`.
- **M01 (diagram):** `model.html` shows every table, column and relationship.

**2025 headline numbers** [high]:
- Revenue €33,506,864.27 (core markets €29,138,441.73 · ES/AT €4,368,422.54)
- 101,142 orders
- Stock on hand in December 2025: 41,307 units
- Discount amount €738,946.09 · 205,473 units sold

**Rounding effect:** revenue and discount amount are each rounded on their own, as `metrics.md` defines them. On 1,517 lines their sum differs from quantity × unit price by 1 cent.

## Tables

| Table | Grain | Columns | Rows (2025) |
|---|---|---|---|
| `fact_sales` | one order line | `order_id`, `date_key`, `sku`, `country_code`, `channel`, `quantity`, `unit_price`, `discount_rate`, `revenue`, `discount_amount` | ~156,824 |
| `fact_inventory` | one sku × month end | `date_key` (month-end date), `sku`, `qty_on_hand` | ~4,222 |
| `dim_date` | one day | `date_key` (yyyymmdd), `date`, `year`, `quarter`, `month_no`, `month_name`, `year_month`, `weekday`, `is_weekend`, `month_label` ("Jan 2025") | 365 |
| `dim_product` | one sku | `sku`, `product_name`, `brand`, `category`, `latest_list_price` | 377 |
| `dim_country` | one country | `country_code`, `country_name`, `is_core_market` | 6 |
| `dim_channel` | one channel | `channel` | 3 |

Relationships are one-to-many, with each dimension filtering the facts in a single direction:
- `dim_date.date_key` → `fact_sales.date_key`, `fact_inventory.date_key`
- `dim_product.sku` → `fact_sales.sku`, `fact_inventory.sku`
- `dim_country.country_code` → `fact_sales.country_code`
- `dim_channel.channel` → `fact_sales.channel`

Keys are natural keys (`sku`, `country_code`, `channel`, date as yyyymmdd), not generated IDs. `order_id` stays in `fact_sales` so orders can be counted. `customer_id` is not in the model, because no requirement needs it.

## Decisions (Sushmita, 2026-11-24)

| Topic | Decision |
|---|---|
| Revenue | Stored as a **column** in `fact_sales`: `quantity × unit_price × (1 − discount_rate)`, rounded half-up to the cent per line. `discount_amount` = `quantity × unit_price × discount_rate`, same rounding. Power BI only sums them. |
| Best-selling products | Ranked by **revenue**. |
| Ran out | `qty_on_hand = 0` at month end. |
| Spain/Austria | **All** countries shown by default; `is_core_market` is available as a filter. |
| Stock on hand, several months selected | The **latest month** in the selection. Stock is never summed across months. |
| Monthly deliveries (2026-11-25) | The model is built from `data/clean/all/`, the whole history. `dim_date` keeps whole calendar years, so reports must use the latest month **with data**, not the end of the calendar. `month_label` ("Jan 2025") tells months of different years apart. |

## Dashboard → model

| Element | Measure |
|---|---|
| Total revenue | sum of `fact_sales.revenue` |
| Number of orders | distinct count of `fact_sales.order_id` |
| Stock on hand | sum of `fact_inventory.qty_on_hand` at the latest month in the selection |
| Sales per month / per country | revenue by `dim_date.year_month` / `dim_country` |
| Best-selling products | revenue by `dim_product`, ranked |
| Stock and sales per product | units sold + stock on hand by `dim_product`; ran out = stock on hand is 0 |
| Filters | month `dim_date`, category `dim_product`, country `dim_country`, channel `dim_channel` |

## Known limits

- **Stock doesn't respond to the country or channel filters.** The inventory file has no country or channel [high].
- **Revenue is before returns.** Returns are in a separate system [high]. Label the dashboard accordingly.
- **"What did it cost us"** (from the December questions) needs a lost-sales estimate. That isn't in the data, and how to estimate it is still to be defined.
