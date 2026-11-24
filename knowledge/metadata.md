# Metadata – shop system export

Sources: `inbox/shop-export-dictionary.pdf` (the "dictionary"), `inbox/norda-overview.pdf`, and the files themselves
(profiled 2026-11-24, see `runs/2026-08/1-profile/findings.md`).

The dictionary says itself that it is outdated and that **the file wins** when they disagree.

Tags: [high] = seen in the data or stated in a PDF · [med] = strong evidence, not confirmed · [guess] = needs your confirmation

---

## orders.csv — one row per product per order

160,821 rows · 9 columns · all of 2025

| Column (file) | Dictionary name | Meaning | Type / format seen |
|---|---|---|---|
| `ORD_NO` | `order_ref` | Order number. Repeats on every line of the same order. [high] | Text `SO` + 6 digits, e.g. `SO443307`. Never blank. |
| `CRTD_DT` | `order_date` | Day the customer placed the order. [high] | Date, **two formats**: `YYYY-MM-DD` (50%) and `DD/MM/YYYY` (50%). |
| `CHNL` | — not documented | Sales channel. [med] (values match the 3 channels in the overview) | `web`, `app`, `marketplace`. Never blank. |
| `CTRY` | `country` | Delivery country. [high] | Mostly ISO codes (`DE`); 1% full names (`Germany`). |
| `CUST_REF` | — not documented | Customer ID. [guess] | `C` + 6 digits. 20% blank. |
| `ART_NO` | `article_no` | Article. Joins to `products.sku`. [high] | `AA-99999`, e.g. `NO-66866`. 100% match the catalogue. |
| `QTY` | `quantity` | Number of items of that article ordered. [high] | Whole number 1–8. |
| `UNIT_PRC` | `unit_price` | Price of one item at the moment of the order, EUR, **before discount**. [high] | Decimal 8.99–2,214.99. |
| `DISC_PCT` | — not documented | Discount on the line, as a **fraction** (0.15 = 15%). [high] | Decimal 0.00–0.50 in steps of 0.05. |

## products.csv — the catalogue, one row per article

377 rows · 5 columns · none documented in the dictionary

| Column | Meaning | Type / format seen |
|---|---|---|
| `sku` | Article number. Key; joins to `orders.ART_NO` and `inventory.art_no`. [high] | `AA-99999`. Unique. First 2 letters = brand (KA Kaivo, KO Kova, NO Nodo, ON Ondia, PA Pavo, VI Visna). |
| `product_name` | Product name. [high] | Free text, always starts with the brand. Unique. |
| `brand` | Brand. [high] | 6 brands, but written in mixed case (`Nodo`, `nodo`, `NODO`). |
| `category` | Product category. [high] | 5 categories, mixed case (`Accessories`, `ACCESSORIES`). |
| `list_price` | **Latest** catalogue price, EUR. Not the price at the time of past sales. [high] | Decimal 8.99–2,104.99. |

## inventory.csv — stock per article at month end

4,222 rows · 4 columns · none documented in the dictionary

| Column | Meaning | Type / format seen |
|---|---|---|
| `art_no` | Article. Joins to `products.sku`. [high] | `AA-99999`. |
| `stk_month` | Month the stock was counted (month end). [high] | `YYYY-MM`; 6 rows as `YYYY-M` (`2025-4`). |
| `qty_hand` | Units on hand at month end. [high] | Whole number 0–1,165. |
| `reserved_qty` | Units reserved for open orders. [guess] **Dropped from the export**, so it carries no data. [high] | **Always blank.** |

---

## Where the PDFs and the files do not match

| # | PDF says | File shows | Tag |
|---|---|---|---|
| 1 | Files cover "the month that just closed". | Orders and stock cover **all 12 months of 2025**. | [high] |
| 2 | Order columns are `order_ref`, `order_date`, `country`, `article_no`, `quantity`, `unit_price`. | All 6 are **renamed** (`ORD_NO`, `CRTD_DT`, `CTRY`, `ART_NO`, `QTY`, `UNIT_PRC`). | [high] |
| 3 | 6 order columns. | 9 columns: `CHNL`, `CUST_REF`, `DISC_PCT` are **not documented**. | [high] |
| 4 | Describes the order file only. | `products` and `inventory` columns are **not documented at all**. | [high] |
| 5 | Overview: "we ship to Germany, France, Italy and the Netherlands". | **Spain (ES) and Austria (AT)** = 14% of order rows, every month, every channel. | [high] |
| 6 | Overview: marketplace orders "reach us without customer details". | **24% of marketplace rows have a `CUST_REF`.** | [high] |
| 7 | `country` = delivery country (no format given). | Codes and full names mixed, even within one order. | [high] |
| 8 | `DISC_PCT` name suggests a percent. | Values 0–0.5, so a fraction (confirmed). | [high] |
| 9 | Dictionary implies one row per product per order. | 3,997 lines appear **exactly twice**. | [high] |

## Decisions (answered by Sushmita, 2026-11-24)

| Topic | Answer | What it means for the data |
|---|---|---|
| Spain and Austria | Earlier answer was to exclude; now **kept for now**. | The rows are not removed yet. `check.py` O08 reports them as FAIL (known) every month. |
| Marketplace `CUST_REF` | Ignore it. | At cleanup, clear `CUST_REF` on marketplace rows and keep the rows. |
| `UNIT_PRC` | Before discount. | The discount is not included in `UNIT_PRC`. How amounts are calculated will be defined later. |
| `DISC_PCT` | A fraction. | 0.15 = 15%. |
| `list_price` | The latest price. | Don't use it to value past sales; use `UNIT_PRC`. |
| `reserved_qty` | Dropped from the export. | The column is always empty, so don't use it. |
| Duplicate lines | Remove completely identical rows. (The first answer, "real repeated lines", was corrected.) | At cleanup, keep one copy of each fully identical row (3,997 extra copies in 2025). |
| Money rounding | Round half-up to the cent. | Applies when calculations are added later; use exact decimal maths, so 104.465 → 104.47. |
| Calculated columns | None in the clean layer (`net_amount` was removed). | Amounts and business definitions will be added later, outside the cleanup. |
| Clean column names | Friendly English names in lower snake_case. | See `.claude/skills/clean/SKILL.md` for the full list (e.g. `CRTD_DT` → `order_date`). |
| Spain and Austria in the clean layer | Rows kept, with a flag. | `is_core_market = False` for ES/AT. |
| Clean output location | One folder per month. | `data/clean/<run>/`; earlier months are never overwritten. |

## Decisions: monthly deliveries (answered by Sushmita, 2026-11-25)

From 2026-09 on, every month brings a new delivery of the 3 files. The first delivery (2026-08) holds all of 2025.

| Topic | Answer | What it means for the data |
|---|---|---|
| Raw location | One folder per delivery, never overwritten. | `data/raw/<run>/orders.csv, products.csv, inventory.csv`. The 2025 files moved to `data/raw/2026-08/` unchanged (same checksums). |
| Orders | Appended to the existing orders. | `data/clean/all/orders.csv` = every delivery's clean orders, each once. |
| Inventory | Appended to the existing inventory. | `data/clean/all/inventory.csv` = every delivery's stock rows, each once. |
| Products | New products are added; existing products get the new price. | `data/clean/all/products.csv`: one row per sku, `latest_list_price` from the newest delivery that has the sku. |
| Order number already loaded | Blocker: stop and ask. | Profile H01; clean stops and writes nothing. Loading it again would count the revenue twice. |
| Stock row (sku + month) already loaded | Blocker: stop and ask. | Profile H02; clean stops and writes nothing. |
| Existing sku with a new name, brand or category | Blocker: stop and ask. | Profile H03; clean stops and writes nothing. A category change would move history between categories. |
| Price change on an existing sku | Expected. | Profile H04 (known) lists sku, old and new price; the run continues. |
| New sku | Expected. | Profile H05 (known) lists them; the run continues. |
| Model source | The whole history. | The mart is built from `data/clean/all/`. |
