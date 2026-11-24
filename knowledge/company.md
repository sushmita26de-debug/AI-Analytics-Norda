# NORDA – Company

Source: `inbox/norda-overview.pdf` (internal intranet overview)

## Who we are
- European consumer electronics retailer. Started as a single computer shop.
- Does not manufacture. Buys from suppliers, holds stock in own warehouse, sells direct to consumers.
- Small range on purpose: few brands, known well.

## Markets
- Germany (home market, largest), France, Italy, Netherlands.
- All eurozone → all prices in EUR, no currency column.

## Channels
- **Web** – own online shop.
- **App** – NORDA mobile app.
- **Marketplace** – third-party platforms. Customers belong to the platform, so orders arrive **without customer details**.

## Categories
| Category | Notes |
|---|---|
| Computers | Laptops, desktops. Highest value. |
| Phones & Tablets | Highest volume. |
| Monitors | Home and office displays. |
| Audio | Headphones, speakers, sound bars. |
| Accessories | Cables, cases, chargers, keyboards, add-ons. |

## Brands
| Brand | Covers |
|---|---|
| Kova | Premium computers, a few monitors. Most expensive products. |
| Kaivo | Mid/upper phones & tablets, a few audio products. |
| Pavo | Budget phones & tablets. |
| Visna | Monitors. |
| Ondia | Audio only. |
| Nodo | Accessories only. Widest range, lowest prices. |

## Data: the monthly export
- All channels' orders land in the shop system (operational, not built for reporting).
- Monthly flat file, **one row per order line**. Also: product catalogue + month-end warehouse stock.
- Raw dump: nobody cleans or checks it. Format has changed over the years.
- **Returns/refunds are not included** (separate system) → every row is a sale that shipped.

## Reporting
- Analytics team reports on the closed month.
- Audience: commercial and purchasing teams (buying plans, category performance).
- They ask business questions, not data requests.
- Whoever presents a number must explain where it came from.
