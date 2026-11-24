# Data quality profile – run 2026-08

- **Data:** `data/raw/orders.csv`, `products.csv`, `inventory.csv` (all of 2025, Jan–Dec)
- **Script:** `.claude/skills/profile/profile.py` (read-only)
- **Full output:** `runs/2026-08/1-profile/profile-output.txt`
- **Status:** findings only. Nothing has been cleaned or changed.

Tags: [high] = counted in the data · [med] = strong evidence, not confirmed · [guess] = needs confirmation

**Scale (orders, as delivered):** 160,821 rows · 101,142 orders · €35.08M qty × price · €34.32M after discount (if `DISC_PCT` is a fraction)

---

## Summary: what changes the numbers

| # | Finding | Rows | Value (after disc.) | Decision needed |
|---|---|---|---|---|
| 1 | Spain + Austria orders, not in our 4 markets | 22,486 (14.0%) | €4.47M (13.0%) | Include or exclude? |
| 2 | Exact duplicate order lines | 3,997 extra (2.5%) | €0.81M (2.4%) | Drop the copies? |
| 3 | Two date formats in one column | 80,742 (50.2%) | – | None. Fix is safe [high]. |
| 4 | `DISC_PCT` is a fraction; unknown whether price is before or after it | 20,872 discounted (13.0%) | €0.76M of discount | Confirm the meaning |
| 5 | Unit price above catalogue list price | 66,320 (41.2%) | €1.72M above list | Which price is "right"? |

---

## Orders

**O1. Two date formats in `CRTD_DT`** [high]
- About half the rows are `YYYY-MM-DD` and half `DD/MM/YYYY`. The mix is the same in every month, so it isn't a one-time format change.
- The slash dates are DD/MM:
  - 47,610 rows can only be DD/MM (first part > 12).
  - 0 rows can only be MM/DD.
- The 30,271 ambiguous rows (e.g. `04/07/2025`) are also DD/MM, because order numbers rise with the date:
  - read as DD/MM: 0 orders out of sequence
  - read as MM/DD: 9,522 out of sequence
- All dates parse. The range is 2025-01-01 → 2025-12-31, with no missing days.
- **Impact:** if Excel or Power BI auto-detects the date, about 19% of rows can land in the wrong month without any warning.

**O2. Exact duplicate lines** [high on the count, med on the cause]
- 3,997 lines appear exactly twice, with all 9 columns identical. That makes 7,994 rows involved and 3,997 extras.
- There are no triplicates. They appear in every month (249–494) and every channel.
- Every case of the same order + article twice is an exact copy, so I can't tell a true repeat apart from an export bug.
- **Impact:** revenue and units are overstated by about 2.4% if the copies are bugs.

**O3. Countries outside the 4 markets** [high]
- ES has 15,434 rows and AT has 7,052: together 14.0% of rows and €4.47M.
- The share is steady at 13–15% every month and similar across all channels, so it looks like normal business, not a glitch [med].
- This contradicts the company overview, which lists DE, FR, IT and NL only.

**O4. Country written two ways** [high]
- 1,642 rows (1.0%) use full names (`Germany`, `Spain` …) instead of codes.
- 1,017 orders mix both on different lines. After mapping names to codes, every order has exactly one country.
- **Impact:** a country slicer splits DE into `DE` and `Germany`. This is fixable with a simple mapping.

**O5. Customer ref on marketplace orders** [high]
- 6,618 of 27,110 marketplace rows (24.4%) have a `CUST_REF`, but the overview says marketplace orders come without customer details.
- 1,565 of those 3,415 IDs also appear on web/app orders.
- Customer ref is blank on 10.8% of web rows and 5.9% of app rows. Maybe guest checkout [guess].
- **Impact:** any "customer" metric depends on what these IDs mean.

**O6. `DISC_PCT` meaning** [med]
- Values run from 0 to 0.50 in steps of 0.05, so this is a fraction, not a percent. Read as a percent, the discount would be ~0.
- 13.0% of rows are discounted, with peaks in July (27.6%), November (23.6%) and December (18.9%). These might be promotions [guess].
- It's **unknown** whether `UNIT_PRC` is before or after the discount. The difference is €0.76M (2.2%).

**O7. Unit price vs catalogue list price** [high on the count, guess on the cause]
- 55.8% of rows are at list price, 41.2% above it (up to 1.395×) and 2.9% below it.
- There is nothing extreme: no prices in cents and nothing beyond 0.5× or 1.5×.
- 101 articles sold at 2–3 different prices, and the same prices appear on every channel.
- The share above list falls steadily from 47.7% in January to 35.9% in December.
- My guess is that `list_price` is today's price and prices drifted down during the year [guess].
- **Impact:** don't value sales with `list_price`. Use `UNIT_PRC`, which the dictionary defines as the price at the moment of the order.

**O8. June is low** [high on the count, guess on the cause]
- 329 rows/day in June, against 396–418 in January–May.
- No day is missing: every day is just lower, with the lowest days being the June Sundays.
- That could be a real dip or partially loaded days. I can't tell from the file.

**O9. Order number gaps** [high on the count, guess on the cause]
- 13,216 numbers between SO443307 and SO557664 never appear (11.6% of the range).
- They might be cancelled orders, or orders held in another system [guess].

**Clean in orders** [high]
- No blanks in key fields.
- Quantity is always 1–8.
- Price is always above 0.
- Channel always has one of the 3 expected values.
- Every `ART_NO` is in the catalogue.
- Each order has exactly one date, channel and customer.

## Products

**P1. Brand and category in mixed case** [high]
- 60 of 377 products (15.9%) have a brand or category that isn't written in the standard way: `nodo`, `NODO`, `ACCESSORIES`, `phones & tablets` …
- After fixing the case, they map cleanly to the 6 brands and 5 categories.
- **Impact:** without the fix, Power BI shows up to 16 "brands" and 15 "categories".

**P2. Two products never sold and never stocked** [high]
- `KO-27064` Kova K3-1950 and `NO-78001` Nodo Vertical Mouse Grey.
- This is harmless, but they will show as zero rows.

**Clean in products** [high]
- SKUs are unique.
- The SKU prefix always matches the brand.
- Product names are unique.
- Prices are always above 0.
- Brand × category matches the overview: Kova also has 5 monitors and Kaivo 6 audio products.

## Inventory

**I1. Month written two ways** [high]
- 6 rows use `2025-4` instead of `2025-04`.
- After normalising, there are no duplicates and no gaps.

**I2. `reserved_qty` is always blank** [high]
- All 4,222 rows are empty. It's unusable.

**I3. Articles appear in stock only from their first sale month** [high on the count, med on the meaning]
- 320 articles are in stock from January. The other 55 start later, and each one in the month it was first sold.
- There are no sales without a stock row.

**Clean in inventory** [high]
- No negative stock.
- Every article is in the catalogue.
- 72 rows have zero stock; in 3 of those, the article sold that month (so it sold out).

---

## Questions before cleaning

1. **ES/AT:** do we really sell in Spain and Austria? Should they be in the monthly numbers?
2. **Duplicates:** can the shop system team confirm the duplicate lines are an export bug?
3. **`UNIT_PRC`:** is it before or after the discount? Can you confirm `DISC_PCT` is a fraction?
4. **`CUST_REF` on marketplace rows:** what is it?
5. **`list_price`:** is it the current price?
6. **June:** was there a known event, such as an outage, or a known data load issue?
7. **Order number gaps:** are they cancellations?
