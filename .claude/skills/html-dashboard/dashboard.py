"""
NORDA Sales Dashboard builder
=============================

Reads the sales data model (star schema) in data/mart/ and writes ONE
self-contained HTML file: an interactive, Power BI style sales dashboard.
    data/mart/  ->  reports/html/dashboard.html
                +   runs/<run>/5-html-dashboard/html-dashboard-log.md

Run from the project root (or use /html-dashboard <run>):
    python .claude/skills/html-dashboard/dashboard.py --run 2026-08
    python .claude/skills/html-dashboard/check.py --run 2026-08

How it works (in SQL terms):
  1. Read the 6 CSV tables from data/mart/.
  2. Turn every text key (order_id, sku, country, channel, month) into a small
     integer "index" - like a surrogate key. Integers are much smaller to store.
  3. Store revenue in integer CENTS, so totals add up exactly (no 0.000001 drift).
  4. Put everything into one JSON blob inside the HTML page.
  5. JavaScript in the page sums the data again on every filter click.

The HTML/CSS/JavaScript template is at the bottom of this file (section 6).
Nothing is loaded from the internet: no libraries, no fonts, no CDN.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# 1. Command line arguments
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Build the NORDA sales dashboard (HTML).")
    parser.add_argument("--run", required=True, help="run month, e.g. 2026-08 (for the log folder)")
    parser.add_argument("--mart", default="data/mart", help="folder with the mart CSVs")
    parser.add_argument("--out", default="reports/html/dashboard.html", help="output HTML file")
    return parser.parse_args()


def fail(message):
    """Stop the build with a clear error message (exit code 1)."""
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(1)


def read_table(mart, name, **kwargs):
    """Read one CSV from the mart folder; stop loudly if it is missing or empty."""
    path = Path(mart) / name
    if not path.exists():
        fail(f"input file not found: {path}")
    df = pd.read_csv(path, **kwargs)
    if df.empty:
        fail(f"input file is empty: {path}")
    return df


# ---------------------------------------------------------------------------
# 2. Read the mart
# ---------------------------------------------------------------------------
def load_mart(mart):
    tables = {
        "sales": read_table(mart, "fact_sales.csv",
                            dtype={"order_id": str, "sku": str, "country_code": str, "channel": str}),
        "inventory": read_table(mart, "fact_inventory.csv", dtype={"sku": str}),
        "date": read_table(mart, "dim_date.csv", dtype={"year_month": str}),
        "product": read_table(mart, "dim_product.csv", dtype={"sku": str}),
        "country": read_table(mart, "dim_country.csv", dtype={"country_code": str}),
        "channel": read_table(mart, "dim_channel.csv", dtype={"channel": str}),
    }
    return tables


# ---------------------------------------------------------------------------
# 3. Build lookup lists (the "dimensions" as plain lists, index = position)
# ---------------------------------------------------------------------------
def build_dimensions(t):
    # Months: one entry per year_month in dim_date, in calendar order.
    d = t["date"].copy()
    months = (d.groupby("year_month", as_index=False)
                .agg(year=("year", "first"), month_no=("month_no", "first"),
                     month_name=("month_name", "first"))
                .sort_values("year_month")
                .reset_index(drop=True))
    months["yyyymm"] = months["year"] * 100 + months["month_no"]
    # dim_date holds whole calendar years. Keep only the months from the first to the last month
    # WITH DATA (sales or stock), so "latest month" is never an empty month at the end of the year.
    data_yyyymm = set(t["sales"]["date_key"] // 100) | set(t["inventory"]["date_key"] // 100)
    months = months[months["yyyymm"].between(min(data_yyyymm), max(data_yyyymm))].reset_index(drop=True)
    month_list = [
        {
            "key": row.year_month,                              # 2025-01
            "short": row.month_name[:3],                        # Jan
            "label": f"{row.month_name[:3]} {row.year}",        # Jan 2025
            "long": f"{row.month_name} {row.year}",             # January 2025
        }
        for row in months.itertuples()
    ]
    month_index = {yyyymm: i for i, yyyymm in enumerate(months["yyyymm"])}

    # Data period text, e.g. "Jan–Dec 2025", computed from the months that have sales.
    sales_yyyymm = sorted((t["sales"]["date_key"] // 100).unique())
    first, last = month_list[month_index[sales_yyyymm[0]]], month_list[month_index[sales_yyyymm[-1]]]
    if first["key"][:4] == last["key"][:4]:
        period = f"{first['short']}–{last['short']} {last['key'][:4]}"
    else:
        period = f"{first['label']}–{last['label']}"

    countries = t["country"].reset_index(drop=True)
    country_index = {c: i for i, c in enumerate(countries["country_code"])}

    channels = t["channel"]["channel"].tolist()
    channel_index = {c: i for i, c in enumerate(channels)}

    products = t["product"].reset_index(drop=True)
    categories = sorted(products["category"].unique())
    category_index = {c: i for i, c in enumerate(categories)}
    sku_index = {s: i for i, s in enumerate(products["sku"])}

    return {
        "months": month_list, "month_index": month_index, "period": period,
        "countries": countries, "country_index": country_index,
        "channels": channels, "channel_index": channel_index,
        "products": products, "categories": categories,
        "category_index": category_index, "sku_index": sku_index,
    }


def map_or_fail(series, lookup, what):
    """Like a SQL inner join check: every key must exist in its dimension."""
    mapped = series.map(lookup)
    if mapped.isna().any():
        missing = sorted(series[mapped.isna()].astype(str).unique())[:5]
        fail(f"{what}: {mapped.isna().sum()} rows have a key not in the dimension, e.g. {missing}")
    return mapped.astype("int64")


# ---------------------------------------------------------------------------
# 4. Encode the facts as compact integer columns
# ---------------------------------------------------------------------------
def encode_sales(sales, dims):
    s = sales.copy()

    # Check the order grain: one order = one date, one country, one channel.
    # (If this ever fails, the page would need these columns per line instead.)
    grain = s.groupby("order_id").agg(d=("date_key", "nunique"), c=("country_code", "nunique"),
                                      ch=("channel", "nunique"))
    bad = int(((grain["d"] > 1) | (grain["c"] > 1) | (grain["ch"] > 1)).sum())
    if bad:
        fail(f"{bad} orders have more than one date/country/channel - order-level encoding not valid")

    # Integer indexes for every key.
    s["month_i"] = map_or_fail(s["date_key"] // 100, dims["month_index"], "fact_sales month")
    s["country_i"] = map_or_fail(s["country_code"], dims["country_index"], "fact_sales country")
    s["channel_i"] = map_or_fail(s["channel"], dims["channel_index"], "fact_sales channel")
    s["sku_i"] = map_or_fail(s["sku"], dims["sku_index"], "fact_sales sku")

    # Revenue in integer cents. Check that nothing is lost in the conversion.
    cents = (s["revenue"] * 100).round()
    if ((s["revenue"] * 100 - cents).abs() > 1e-6).any():
        fail("some revenue values have more than 2 decimals")
    s["cents"] = cents.astype("int64")

    # Sort lines by date and order, then number the orders 0, 1, 2, ... in that order.
    s = s.sort_values(["date_key", "order_id", "sku"], kind="stable").reset_index(drop=True)
    s["order_i"] = pd.factorize(s["order_id"])[0]

    # Order table: one row per order (month, country, channel).
    orders = s.drop_duplicates("order_i").sort_values("order_i")

    # Lines store the order index as a "step" from the previous line (0 = same order,
    # 1 = next order). The page adds the steps back up. Same information, smaller file.
    order_delta = s["order_i"].diff().fillna(s["order_i"].iloc[0]).astype("int64")
    if not order_delta.isin([0, 1]).all():
        fail("order index steps are not 0/1 - sorting problem")

    encoded = {
        "orders": {
            "month": orders["month_i"].tolist(),
            "country": orders["country_i"].tolist(),
            "channel": orders["channel_i"].tolist(),
        },
        "lines": {
            "orderDelta": order_delta.tolist(),
            "sku": s["sku_i"].tolist(),
            "qty": s["quantity"].astype("int64").tolist(),
            "cents": s["cents"].tolist(),
        },
    }
    return encoded, s


def encode_inventory(inventory, dims):
    """sku x month matrix of qty_on_hand. A missing record stays None (null), never 0."""
    inv = inventory.copy()
    inv["month_i"] = map_or_fail(inv["date_key"] // 100, dims["month_index"], "fact_inventory month")
    inv["sku_i"] = map_or_fail(inv["sku"], dims["sku_index"], "fact_inventory sku")
    if inv.duplicated(["sku_i", "month_i"]).any():
        fail("fact_inventory has more than one row per sku and month")

    n_products, n_months = len(dims["products"]), len(dims["months"])
    matrix = [[None] * n_months for _ in range(n_products)]
    for row in inv.itertuples():
        matrix[row.sku_i][row.month_i] = int(row.qty_on_hand)
    missing = sum(v is None for r in matrix for v in r)
    return matrix, missing


# ---------------------------------------------------------------------------
# 5. Main: build, check, write, print summary
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    t = load_mart(args.mart)
    dims = build_dimensions(t)
    encoded, sales = encode_sales(t["sales"], dims)
    inventory, missing_inv = encode_inventory(t["inventory"], dims)

    # Totals in Python (the page computes them again in JavaScript).
    revenue_cents = int(sales["cents"].sum())
    distinct_orders = int(sales["order_id"].nunique())
    latest_month = len(dims["months"]) - 1
    latest_stock = sum(r[latest_month] for r in inventory if r[latest_month] is not None)

    # Cross-check: cents total equals the float total of the revenue column.
    if abs(revenue_cents / 100 - round(float(t["sales"]["revenue"].sum()), 2)) > 0.005:
        fail("cents total does not match revenue column total")

    built = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    products = dims["products"]
    data = {
        "period": dims["period"],
        "built": built,
        "source": args.mart.replace("\\", "/"),
        "months": dims["months"],
        "countries": [{"code": r.country_code, "name": r.country_name}
                      for r in dims["countries"].itertuples()],
        "channels": [{"code": c, "name": c.capitalize()} for c in dims["channels"]],
        "categories": dims["categories"],
        "products": {
            "sku": products["sku"].tolist(),
            "name": products["product_name"].tolist(),
            "cat": products["category"].map(dims["category_index"]).tolist(),
        },
        "inventory": inventory,
        **encoded,
    }

    # JSON inside a <script> tag: escape "</" so the data can never close the tag.
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__DATA__", blob).replace("__PERIOD__", dims["period"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    size_mb = out.stat().st_size / 1024 / 1024

    # Console output is kept plain ASCII (EUR, "-") so it prints on any Windows terminal.
    eur = f"EUR {revenue_cents // 100:,}.{revenue_cents % 100:02d}"
    print("NORDA dashboard build")
    print(f"  rows read       fact_sales {len(t['sales']):,} | fact_inventory {len(t['inventory']):,} | "
          f"products {len(products)} | countries {len(dims['countries'])} | channels {len(dims['channels'])} | "
          f"months {len(dims['months'])}")
    print(f"  period          {dims['period'].replace(chr(0x2013), '-')}")
    print(f"  revenue         {eur}")
    print(f"  distinct orders {distinct_orders:,}")
    print(f"  stock on hand   {latest_stock:,} units ({dims['months'][latest_month]['label']})")
    print(f"  inventory gaps  {missing_inv} sku-months have no stock record (kept as empty, not 0)")
    print(f"  file            {out.resolve()} ({size_mb:.2f} MB)")

    # Build log for this run (same idea as runs/<run>/3-mart/mart-log.md).
    eur_log = f"€{revenue_cents // 100:,}.{revenue_cents % 100:02d}"
    log = [
        f"# Dashboard build log - run {args.run}", "",
        f"Built: {built} · Script: `.claude/skills/html-dashboard/dashboard.py`", "",
        "| Item | Value |", "|---|---|",
        f"| Source | `{data['source']}` |",
        f"| Rows read | fact_sales {len(t['sales']):,} · fact_inventory {len(t['inventory']):,} · "
        f"products {len(products)} · countries {len(dims['countries'])} · channels {len(dims['channels'])} · "
        f"months {len(dims['months'])} |",
        f"| Period | {dims['period']} |",
        f"| Total revenue | {eur_log} |",
        f"| Orders (distinct) | {distinct_orders:,} |",
        f"| Stock on hand | {latest_stock:,} units ({dims['months'][latest_month]['label']}) |",
        f"| Inventory gaps | {missing_inv} sku-months with no stock record (shown as 'no stock data', not 0) |",
        f"| Output | `{args.out}` ({size_mb:.2f} MB) |",
    ]
    log_path = Path("runs") / args.run / "5-html-dashboard" / "html-dashboard-log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"  log             {log_path}")


# ---------------------------------------------------------------------------
# 6. HTML template (CSS + JavaScript). __DATA__ is replaced by the JSON blob.
# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NORDA Sales Dashboard</title>
<style>
:root{
  --bg:#0e1117; --panel:#161b22; --panel-2:#1e252e; --border:#232a33;
  --grid:#262d37; --axis:#3a434f; --faint:#262e39;
  --text:#e6e9ee; --text-2:#b4bcc7; --muted:#8c96a3;
  --calm:#5f87b4;   /* one calm colour for all marks */
  --hi:#f0a73a;     /* one highlight colour */
  --hover:rgba(255,255,255,.045);
}
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{margin:0;background:var(--bg);color:var(--text)}
body{font:13px/1.4 "Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif;overflow-x:hidden}
td,th,.tick,.hval,.xl,.tmeta,#tip{font-variant-numeric:tabular-nums}
.page{max-width:1680px;margin:0 auto;padding:12px 16px 10px}
button{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--text);outline-offset:1px}

/* Rule: nothing on the page changes height when a filter changes.
   Every line that can change text has a fixed height and does not wrap. */

/* top bar */
.top{display:flex;align-items:baseline;gap:14px;height:24px;margin-bottom:8px;white-space:nowrap;overflow:hidden}
.top h1{font-size:18px;font-weight:600;margin:0}
.top .meta{color:var(--text-2)}
.top .meta b{color:var(--text);font-weight:600}
.slicers{display:flex;align-items:center;gap:8px;height:30px;margin-bottom:10px}
.slicer{position:relative;flex:none}
.sl-btn{display:flex;align-items:center;gap:6px;width:190px;height:30px;padding:0 10px;background:var(--panel);
  border:1px solid var(--axis);border-radius:4px;cursor:pointer;text-align:left}
.sl-btn:hover{background:var(--panel-2)}
.sl-btn.on{border-color:var(--text-2)}
.sl-name{color:var(--muted);flex:none}
.sl-val{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sl-caret{color:var(--muted);flex:none;font-size:10px}
.sl-panel{position:absolute;top:34px;left:0;z-index:20;min-width:190px;max-height:420px;overflow:auto;background:var(--panel-2);
  border:1px solid var(--axis);border-radius:4px;padding:4px 0}
.sl-panel label{display:flex;align-items:center;gap:8px;padding:4px 10px;cursor:pointer;white-space:nowrap}
.sl-panel label:hover{background:var(--hover)}
.sl-panel input{accent-color:var(--calm);margin:0}
.sl-panel .sl-all{border-bottom:1px solid var(--axis);margin-bottom:4px;padding-bottom:6px}
.clear{flex:none;height:30px;padding:0 12px;background:transparent;border:1px solid var(--axis);border-radius:4px;cursor:pointer}
.clear:hover{background:var(--panel-2)}
.clear:disabled{opacity:.45;cursor:default}
.summary{flex:1;min-width:0;padding-left:6px;color:var(--text-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* one 12-column grid: KPIs 4/4/4, month 8 + country 4, best sellers 4 + table 8 */
.dash{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:12px}
.s4{grid-column:span 4}
.s8{grid-column:span 8}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:10px 14px;min-width:0}
.ph{display:flex;align-items:baseline;gap:10px;height:18px;margin-bottom:8px;white-space:nowrap;overflow:hidden}
.ph h2{font-size:13px;font-weight:600;margin:0;flex:none}
.ph .sub{color:var(--muted);font-size:12px;flex:none}
.caveat{font-size:12px;line-height:16px;color:var(--text-2);border-left:3px solid var(--muted);padding-left:7px;white-space:nowrap}
.ph .caveat{margin-left:auto;line-height:14px}

/* KPI tiles */
.kpi .label{color:var(--text-2);height:18px}
.kpi .vrow{display:flex;align-items:center;gap:16px;height:46px}
.kpi .value{font-size:38px;font-weight:600;line-height:46px;cursor:default;flex:none}
.kpi .cap{color:var(--muted);font-size:12px;height:17px;white-space:nowrap}

/* month chart (SVG) */
#chart-month{user-select:none}
#chart-month svg{display:block}
.grid line{stroke:var(--grid);stroke-width:1;shape-rendering:crispEdges}
.baseline{stroke:var(--axis);stroke-width:1;shape-rendering:crispEdges}
.tick{fill:var(--muted);font-size:11px}
.xl{fill:var(--muted);font-size:11px}
.xl.sel{fill:var(--text);font-weight:600}
.vlab{fill:var(--text);font-size:11px;font-variant-numeric:tabular-nums}
.hit{fill:transparent;cursor:pointer;outline:none}
.hit:focus-visible{stroke:var(--text);stroke-width:2}
.col{pointer-events:none}

/* horizontal bars (HTML) */
.hbars{user-select:none;overflow:hidden}
.hrow{display:grid;align-items:center;height:32px;cursor:pointer;border-radius:3px}
.hrow:focus-visible{outline-offset:-2px}
#chart-country .hrow{grid-template-columns:92px minmax(0,1fr)}
#chart-product .hrow{grid-template-columns:minmax(0,46%) minmax(0,1fr)}
.hlabel{color:var(--text-2);min-width:0;overflow:hidden;padding:0 8px 0 4px}
.hlabel.sel{color:var(--text);font-weight:600}
.htrack{display:flex;align-items:center;min-width:0;border-left:1px solid var(--axis);height:100%}
.hbar{display:block;height:14px;background:var(--calm);border-radius:0 4px 4px 0;flex:none}
.hbar.hi{background:var(--hi)}
.hval{color:var(--text-2);font-size:12px;padding-left:6px;white-space:nowrap}
.empty{color:var(--muted);padding:24px 4px}
.note2{color:var(--muted);font-size:12px;height:18px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* product names: cut in the middle, keep the end (6.7in vs 6.1in stay readable) */
.nm{display:flex;min-width:0;white-space:pre}
.nm .nh{min-width:0;overflow:hidden;text-overflow:ellipsis}
.nm .nt{flex:none}

/* product table */
.tpanel{display:flex;flex-direction:column}
.tmeta{color:var(--text-2);font-size:12px;height:18px;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tlegend{display:flex;gap:14px;color:var(--muted);font-size:12px;height:18px;margin-top:6px;white-space:nowrap;overflow:hidden}
.tlegend i{display:inline-block;width:8px;height:12px;border-radius:2px;vertical-align:-2px;margin-right:5px}
.tlegend i.dot{width:8px;height:8px;border-radius:50%;vertical-align:0}
.tw{flex:1 1 0;min-height:0;overflow:auto;border-top:1px solid var(--axis);
  scrollbar-color:var(--axis) var(--panel);scrollbar-width:thin}
.tw::-webkit-scrollbar,.sl-panel::-webkit-scrollbar{width:10px}
.tw::-webkit-scrollbar-track,.sl-panel::-webkit-scrollbar-track{background:var(--panel)}
.tw::-webkit-scrollbar-thumb,.sl-panel::-webkit-scrollbar-thumb{background:var(--axis);border-radius:5px;border:2px solid var(--panel)}
.sl-panel{scrollbar-color:var(--axis) var(--panel-2);scrollbar-width:thin}
table{width:100%;border-collapse:collapse;table-layout:fixed}
th{position:sticky;top:0;z-index:2;background:var(--panel);color:var(--text-2);font-weight:600;font-size:12px;text-align:left;
  height:28px;padding:0 6px;border-bottom:1px solid var(--axis);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
th.sort{cursor:pointer}
th.sort:hover{color:var(--text)}
th:focus-visible{outline-offset:-2px}
th.r,td.r{text-align:right}
th .ar{color:var(--muted);font-size:10px;margin-left:3px}
td{padding:0 6px;height:27px;border-bottom:1px solid var(--grid);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
tbody tr{cursor:pointer}
tbody tr:focus-visible{outline:2px solid var(--text);outline-offset:-2px}
tbody tr.spacer{cursor:default}
tbody tr.spacer td{padding:0;border:0}
tbody tr.sel td:first-child{box-shadow:inset 3px 0 0 var(--hi)}
td.pn{color:var(--text)}
td.ct{color:var(--text-2)}
.db{display:grid;grid-template-columns:44px 40px;justify-content:end;align-items:center;gap:6px}
.db .n{text-align:right}
.db .t{height:8px;display:flex;align-items:center}
.db .b{height:8px;background:var(--calm);border-radius:0 4px 4px 0}
.db .z{width:8px;height:8px;border-radius:50%;background:var(--hi)}
.strip{display:flex;gap:2px;align-items:center}
.strip s{display:block;width:8px;height:12px;border-radius:2px;text-decoration:none}
.strip s.ok{background:var(--faint)}
.strip s.z{background:var(--calm)}
.strip s.na{background:transparent;box-shadow:inset 0 0 0 1px var(--grid)}
.strip s.off{opacity:.28}
.strip.sh b{display:block;width:8px;text-align:center;font-size:10px;font-weight:600;color:var(--muted)}
.strip.sh b.sel{color:var(--text)}
.strip.sh b.off{opacity:.45}

/* footer + tooltip */
.foot{color:var(--muted);font-size:11.5px;height:17px;margin-top:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#tip{position:fixed;left:0;top:0;z-index:50;pointer-events:none;background:#232a34;border:1px solid var(--axis);border-radius:4px;
  padding:6px 9px;font-size:12px;color:var(--text-2);white-space:nowrap;display:none}
#tip b{color:var(--text);font-weight:600}
#tip .x{color:var(--muted);margin-top:2px}
</style>
</head>
<body>
<div class="page">
  <header>
    <div class="top">
      <h1>NORDA Sales Dashboard</h1>
      <span class="meta"><b id="period">__PERIOD__</b> &nbsp;·&nbsp; Revenue before returns</span>
    </div>
    <div class="slicers" id="slicers">
      <button class="clear" id="clear-all" type="button">Clear all</button>
      <div class="summary" id="summary"></div>
    </div>
  </header>

  <main class="dash">
    <div class="panel kpi s4">
      <div class="label">Total revenue</div>
      <div class="vrow"><div class="value" id="kpi-rev"></div></div>
      <div class="cap">before returns</div>
    </div>
    <div class="panel kpi s4">
      <div class="label">Orders</div>
      <div class="vrow"><div class="value" id="kpi-ord"></div></div>
      <div class="cap">distinct orders</div>
    </div>
    <div class="panel kpi s4">
      <div class="label">Stock on hand</div>
      <div class="vrow">
        <div class="value" id="kpi-stock"></div>
        <div class="caveat" id="kpi-stock-note" style="visibility:hidden">Not filtered by country/channel –<br>stock has no country/channel</div>
      </div>
      <div class="cap" id="kpi-stock-cap"></div>
    </div>

    <div class="panel s8">
      <div class="ph"><h2>Sales per month</h2><span class="sub">Revenue</span></div>
      <div id="chart-month"></div>
    </div>
    <div class="panel s4">
      <div class="ph"><h2>Sales per country</h2><span class="sub">Revenue</span></div>
      <div id="chart-country" class="hbars"></div>
    </div>

    <div class="panel s4">
      <div class="ph"><h2>Best-selling products</h2><span class="sub">Top 10 by revenue</span></div>
      <div id="chart-product" class="hbars"></div>
      <div class="note2" id="product-note"></div>
    </div>
    <div class="panel s8 tpanel">
      <div class="ph"><h2>Stock and sales per product</h2><span class="sub">Units sold · revenue · month-end stock</span>
        <span class="caveat" id="table-stock-note" style="visibility:hidden">Stock not filtered by country/channel</span></div>
      <div class="tmeta" id="table-count"></div>
      <div class="tw" id="table-wrap">
        <table>
          <colgroup><col><col style="width:118px"><col style="width:104px"><col style="width:96px"><col style="width:104px"><col style="width:132px"></colgroup>
          <thead><tr id="thead"></tr></thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
      <div class="tlegend">
        <span><i style="background:var(--calm)"></i><span id="lg-zero">stock 0 at month end</span></span>
        <span><i class="dot" style="background:var(--hi)"></i>ran out (stock 0 now)</span>
        <span><i style="background:var(--faint)"></i>in stock</span>
        <span><i style="box-shadow:inset 0 0 0 1px var(--grid)"></i>no stock data</span>
      </div>
    </div>
  </main>

  <footer class="foot" id="foot"></footer>
</div>
<div id="tip"></div>

<script type="application/json" id="norda-data">__DATA__</script>
<script>
(function () {
'use strict';

/* ------------------------------------------------------------------ *
 * 1. Load the data blob into typed arrays (fast integer columns)      *
 * ------------------------------------------------------------------ */
var D = JSON.parse(document.getElementById('norda-data').textContent);
var MONTHS = D.months, NM = MONTHS.length;
var COUNTRIES = D.countries, NC = COUNTRIES.length;
var CHANNELS = D.channels, NCH = CHANNELS.length;
var CATS = D.categories, NCAT = CATS.length;
var P = D.products, NP = P.sku.length;
var pCat = Uint8Array.from(P.cat);
var INV = D.inventory;                      // [product][month] = units or null (no stock data)

var oMonth = Uint8Array.from(D.orders.month);
var oCountry = Uint8Array.from(D.orders.country);
var oChannel = Uint8Array.from(D.orders.channel);
var NO = oMonth.length;

var NL = D.lines.qty.length;
var lOrder = new Int32Array(NL), lMonth = new Uint8Array(NL), lCountry = new Uint8Array(NL), lChannel = new Uint8Array(NL);
var lSku = Uint16Array.from(D.lines.sku), lQty = Int32Array.from(D.lines.qty), lCents = Int32Array.from(D.lines.cents);
(function () {
  var o = 0, delta = D.lines.orderDelta;
  for (var i = 0; i < NL; i++) {
    o += delta[i]; lOrder[i] = o;
    lMonth[i] = oMonth[o]; lCountry[i] = oCountry[o]; lChannel[i] = oChannel[o];
  }
})();
var stamp = new Int32Array(NO), stampNow = 0;   // for distinct order counting

/* Fixed sizes, so nothing changes height when filters change */
var HROW = 32, TOPN = 10, ROWH = 27, OVERSCAN = 12, BARPX = 40;

/* ------------------------------------------------------------------ *
 * 2. Filter state (one global state, like Power BI)                    *
 * ------------------------------------------------------------------ */
var S = { month: new Set(), cat: new Set(), country: new Set(), channel: new Set(), product: new Set() };
function range(n) { var a = []; for (var i = 0; i < n; i++) a.push(i); return a; }
function byName(names) { return range(names.length).sort(function (a, b) { return names[a].localeCompare(names[b]); }); }
var countryNames = COUNTRIES.map(function (c) { return c.name; });
var DIMS = [   // items = names by index; order = display order in the slicer and filter line
  { key: 'month',   title: 'Month',    items: MONTHS.map(function (m) { return m.label; }), order: range(NM) },
  { key: 'cat',     title: 'Category', items: CATS.slice(), order: range(NCAT) },
  { key: 'country', title: 'Country',  items: countryNames, order: byName(countryNames) },
  { key: 'channel', title: 'Channel',  items: CHANNELS.map(function (c) { return c.name; }), order: range(NCH) }
];
var sortKey = null, sortDir = -1;   // null = default sort (stock 0 first, then units desc)

function mask(set, n) {
  var a = new Uint8Array(n);
  if (set.size === 0) a.fill(1); else set.forEach(function (i) { a[i] = 1; });
  return a;
}

/* ------------------------------------------------------------------ *
 * 3. Compute everything in ONE pass over the order lines               *
 *    Each chart ignores its own dimension (Power BI behaviour).        *
 * ------------------------------------------------------------------ */
function compute() {
  var mOK = mask(S.month, NM), cOK = mask(S.country, NC), chOK = mask(S.channel, NCH),
      catOK = mask(S.cat, NCAT), pOK = mask(S.product, NP);
  var monthRev = new Float64Array(NM), countryRev = new Float64Array(NC),
      skuRev = new Float64Array(NP), skuUnits = new Float64Array(NP);
  var total = 0, orders = 0, cur = ++stampNow;
  for (var i = 0; i < NL; i++) {
    var s = lSku[i];
    if (!catOK[pCat[s]] || !chOK[lChannel[i]]) continue;
    var m = lMonth[i], c = lCountry[i], r = lCents[i];
    var mo = mOK[m], co = cOK[c], po = pOK[s];
    if (co && po) monthRev[m] += r;               // month chart: all filters except month
    if (mo && po) countryRev[c] += r;             // country chart: all except country
    if (mo && co) {
      skuRev[s] += r; skuUnits[s] += lQty[i];     // products: all except product
      if (po) {                                   // KPIs: all filters
        total += r;
        var o = lOrder[i];
        if (stamp[o] !== cur) { stamp[o] = cur; orders++; }
      }
    }
  }
  // Stock: latest selected month; filtered by category + product only.
  var latest = NM - 1;
  if (S.month.size) { latest = -1; S.month.forEach(function (x) { if (x > latest) latest = x; }); }
  var stock = 0;
  for (var p = 0; p < NP; p++) {
    if (!catOK[pCat[p]] || !pOK[p]) continue;
    var v = INV[p][latest];
    if (v !== null) stock += v;
  }
  return { mOK: mOK, catOK: catOK, monthRev: monthRev, countryRev: countryRev, skuRev: skuRev,
           skuUnits: skuUnits, total: total, orders: orders, latest: latest, stock: stock };
}

/* ------------------------------------------------------------------ *
 * 4. Number and text formatting (cents -> text, no float drift)        *
 * ------------------------------------------------------------------ */
var nf = new Intl.NumberFormat('en-US');
function eurExact(c) {                       // €33,506,864.27 (tooltips)
  c = Math.round(c); var e = Math.floor(c / 100), ct = c % 100;
  return '€' + nf.format(e) + '.' + (ct < 10 ? '0' : '') + ct;
}
function eurWhole(c) { return '€' + nf.format(Math.round(c / 100)); }   // €33,506,864 (KPI, table)
function trimNum(x) { var s = x >= 100 ? x.toFixed(0) : x.toFixed(1); return s.replace(/\.0$/, ''); }
function eurCompact(c) {                     // €15.9M / €2.4M / €1.3K (bar labels, axis)
  var v = c / 100;
  if (v >= 1e6) return '€' + trimNum(v / 1e6) + 'M';
  if (v >= 1e3) return '€' + trimNum(v / 1e3) + 'K';
  return '€' + Math.round(v);
}
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function tipAttr(label, value, extra) {
  return ' data-tl="' + esc(label) + '" data-tv="' + esc(value) + '"' + (extra ? ' data-tx="' + esc(extra) + '"' : '');
}
/* Product name that is cut in the middle when too long: the last word
   (e.g. "6.7in", "256GB") always stays visible. */
function nameHTML(name) {
  var k = name.lastIndexOf(' ');
  if (k > 0 && name.length - k <= 3) { var k2 = name.lastIndexOf(' ', k - 1); if (k2 > 0) k = k2; }
  if (k <= 0) return '<span class="nm"><span class="nh">' + esc(name) + '</span></span>';
  return '<span class="nm"><span class="nh">' + esc(name.slice(0, k)) + '</span><span class="nt">' + esc(name.slice(k)) + '</span></span>';
}
function $(id) { return document.getElementById(id); }

/* Highlight rule: selection in own dimension -> selected items; else the top item. */
function highlightSet(dimKey, values, idxList) {
  if (S[dimKey].size) return new Set(S[dimKey]);
  var best = -1, bestV = 0;
  idxList.forEach(function (i) { if (values[i] > bestV) { bestV = values[i]; best = i; } });
  return best >= 0 ? new Set([best]) : new Set();
}

/* Header period: follows the month filter ("Oct–Dec 2025", "Mar, Jul 2025"). */
function periodText() {
  if (!S.month.size) return D.period;
  var idx = range(NM).filter(function (i) { return S.month.has(i); });
  var runs = [];
  idx.forEach(function (i) { var r = runs[runs.length - 1]; if (r && r[1] === i - 1) r[1] = i; else runs.push([i, i]); });
  var years = {}; idx.forEach(function (i) { years[MONTHS[i].key.slice(0, 4)] = 1; });
  var oneYear = Object.keys(years).length === 1;
  var parts = runs.map(function (r) {
    var a = MONTHS[r[0]], b = MONTHS[r[1]];
    if (oneYear) return r[0] === r[1] ? a.short : a.short + '–' + b.short;
    return r[0] === r[1] ? a.label : a.label + '–' + b.label;
  });
  return parts.join(', ') + (oneYear ? ' ' + Object.keys(years)[0] : '');
}

/* ------------------------------------------------------------------ *
 * 5. Renderers                                                        *
 * ------------------------------------------------------------------ */
function renderKPIs(R) {
  var rev = $('kpi-rev'), ord = $('kpi-ord'), st = $('kpi-stock');
  rev.textContent = eurWhole(R.total);
  rev.setAttribute('data-tl', 'Total revenue'); rev.setAttribute('data-tv', eurExact(R.total));
  ord.textContent = nf.format(R.orders);
  ord.setAttribute('data-tl', 'Orders'); ord.setAttribute('data-tv', nf.format(R.orders));
  st.textContent = nf.format(R.stock);
  st.setAttribute('data-tl', 'Stock on hand, ' + MONTHS[R.latest].long); st.setAttribute('data-tv', nf.format(R.stock) + ' units');
  $('kpi-stock-cap').textContent = 'units at month end, ' + MONTHS[R.latest].label;
  var cc = (S.country.size || S.channel.size) ? 'visible' : 'hidden';   // space is always reserved
  $('kpi-stock-note').style.visibility = cc;
  $('table-stock-note').style.visibility = cc;
}

function niceTicks(max) {
  if (max <= 0) return [0, 100000];
  var raw = max / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
  var step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
  var ticks = [];
  for (var v = 0; v < max + step * 0.999; v += step) ticks.push(v);
  return ticks;
}
function colPath(x, yTop, w, yBase) {        // column with 4px rounded top, square at baseline
  var h = yBase - yTop; if (h <= 0.5) return '';
  var r = Math.min(4, h, w / 2);
  return 'M' + x + ',' + yBase + 'V' + (yTop + r) + 'A' + r + ',' + r + ' 0 0 1 ' + (x + r) + ',' + yTop +
         'H' + (x + w - r) + 'A' + r + ',' + r + ' 0 0 1 ' + (x + w) + ',' + (yTop + r) + 'V' + yBase + 'Z';
}

/* Month axis: "Jan", "Feb", ... When the data spans more than one year, January shows its year
   ("Jan 2026") so the years stay apart. */
function axisLabel(i) {
  var multiYear = MONTHS[0].key.slice(0, 4) !== MONTHS[NM - 1].key.slice(0, 4);
  return MONTHS[i].short + (multiYear && MONTHS[i].key.slice(5) === '01' ? ' ' + MONTHS[i].key.slice(0, 4) : '');
}
function renderMonth(R) {
  var el = $('chart-month');
  var W = Math.max(300, el.clientWidth), H = NC * HROW;
  var m = { l: 48, r: 6, t: 20, b: 22 }, pw = W - m.l - m.r, ph = H - m.t - m.b;
  var vals = R.monthRev, max = 0;
  for (var i = 0; i < NM; i++) if (vals[i] > max) max = vals[i];
  var ticks = niceTicks(max), top = ticks[ticks.length - 1];
  function y(v) { return m.t + ph - (v / top) * ph; }
  var band = pw / NM, cw = Math.min(24, band * 0.6);
  var hi = highlightSet('month', vals, range(NM));
  var out = ['<svg width="' + W + '" height="' + H + '" role="img" aria-label="Revenue per month"><g class="grid">'];
  ticks.forEach(function (t) {
    var yy = Math.round(y(t)) + 0.5;
    if (t > 0) out.push('<line x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + yy + '" y2="' + yy + '"/>');
    out.push('<text class="tick" x="' + (m.l - 6) + '" y="' + (yy + 4) + '" text-anchor="end">' + eurCompact(t) + '</text>');
  });
  out.push('</g><line class="baseline" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + (m.t + ph + 0.5) + '" y2="' + (m.t + ph + 0.5) + '"/>');
  for (i = 0; i < NM; i++) {
    var x0 = m.l + band * i, cx = x0 + band / 2, isHi = hi.has(i);
    out.push('<rect class="hit" tabindex="0" role="button" data-dim="month" data-i="' + i + '" x="' + x0 + '" y="' + m.t +
             '" width="' + band + '" height="' + (ph + m.b) + '"' + tipAttr(MONTHS[i].long, eurExact(vals[i])) +
             ' aria-label="' + esc(MONTHS[i].long + ' ' + eurExact(vals[i])) + '"/>');
    out.push('<path class="col" fill="' + (isHi ? 'var(--hi)' : 'var(--calm)') + '" d="' + colPath(cx - cw / 2, y(vals[i]), cw, m.t + ph) + '"/>');
    out.push('<text class="xl' + (S.month.has(i) ? ' sel' : '') + '" x="' + cx + '" y="' + (H - 6) + '" text-anchor="middle" pointer-events="none">' + esc(axisLabel(i)) + '</text>');
    if (isHi && vals[i] > 0)
      out.push('<text class="vlab" x="' + cx + '" y="' + (y(vals[i]) - 6) + '" text-anchor="middle" pointer-events="none">' + eurCompact(vals[i]) + '</text>');
  }
  if (max === 0) out.push('<text class="tick" x="' + (m.l + pw / 2) + '" y="' + (m.t + ph / 2) + '" text-anchor="middle">No sales for this selection</text>');
  out.push('</svg>');
  el.innerHTML = out.join('');
}

function hbarsHTML(dimKey, order, vals, names, hi, selSet, extraFn, asProduct) {
  var max = 0; order.forEach(function (i) { if (vals[i] > max) max = vals[i]; });
  return order.map(function (i) {
    var frac = max > 0 ? vals[i] / max : 0;
    return '<div class="hrow" tabindex="0" role="button" data-dim="' + dimKey + '" data-i="' + i + '"' +
      tipAttr(names[i], eurExact(vals[i]), extraFn ? extraFn(i) : '') + ' aria-label="' + esc(names[i] + ' ' + eurExact(vals[i])) + '">' +
      '<span class="hlabel' + (selSet.has(i) ? ' sel' : '') + '">' + (asProduct ? nameHTML(names[i]) : esc(names[i])) + '</span>' +
      '<span class="htrack"><span class="hbar' + (hi.has(i) ? ' hi' : '') + '" style="width:calc((100% - 56px) * ' + frac.toFixed(5) + ')"></span>' +
      '<span class="hval">' + eurCompact(vals[i]) + '</span></span></div>';
  }).join('');
}

function renderCountry(R) {
  var order = range(NC);
  order.sort(function (a, b) { return R.countryRev[b] - R.countryRev[a] || a - b; });
  var hi = highlightSet('country', R.countryRev, order);
  $('chart-country').innerHTML = hbarsHTML('country', order, R.countryRev, countryNames, hi, S.country);
}

function productRanking(R) {
  var order = [];
  for (var p = 0; p < NP; p++) if (R.catOK[pCat[p]] && R.skuRev[p] > 0) order.push(p);
  order.sort(function (a, b) { return R.skuRev[b] - R.skuRev[a] || a - b; });
  return order;
}
function renderProduct(R) {
  var ranked = productRanking(R), top = ranked.slice(0, TOPN);
  var hi = highlightSet('product', R.skuRev, top);
  var el = $('chart-product');
  el.innerHTML = top.length ? hbarsHTML('product', top, R.skuRev, P.name, hi, S.product, function (p) {
    return nf.format(R.skuUnits[p]) + ' units sold · ' + CATS[pCat[p]];
  }, true) : '<div class="empty">No sales for this selection</div>';
  // Selected products outside the top 10: say where they rank (the table shows them).
  var notes = [];
  S.product.forEach(function (p) {
    if (top.indexOf(p) < 0) {
      var rank = ranked.indexOf(p);
      notes.push(P.name[p] + (rank >= 0 ? ' ranks #' + (rank + 1) : ' has no sales in this selection'));
    }
  });
  var note = $('product-note');
  note.textContent = notes.length ? 'Selected, not in top 10: ' + notes.join(' · ') : '';
  note.title = note.textContent;
}

var COLS = [
  { key: 'name',  label: 'Product',       cls: '' },
  { key: 'cat',   label: 'Category',      cls: '' },
  { key: 'units', label: 'Units sold',    cls: 'r' },
  { key: 'rev',   label: 'Revenue',       cls: 'r' },
  { key: 'stock', label: 'Stock on hand', cls: 'r' },
  { key: null,    label: '',              cls: '' }      // month strip, letters filled by renderStripHead
];
function renderHead() {
  $('thead').innerHTML = COLS.map(function (c) {
    if (!c.key) return '<th id="strip-head"></th>';
    var arrow = c.key === sortKey ? '<span class="ar">' + (sortDir > 0 ? '▲' : '▼') + '</span>' : '';
    return '<th tabindex="0" class="' + c.cls + ' sort" data-sort="' + c.key + '">' + c.label + arrow + '</th>';
  }).join('');
}
function renderStripHead() {      // J F M A M J J A S O N D, selected months emphasised
  var f = S.month.size > 0, h = '<div class="strip sh">';
  for (var i = 0; i < NM; i++)
    h += '<b class="' + (f ? (S.month.has(i) ? 'sel' : 'off') : '') + '" title="' + esc(MONTHS[i].long) + '">' + esc(MONTHS[i].short.charAt(0)) + '</b>';
  $('strip-head').innerHTML = h + '</div>';
  $('strip-head').title = f ? 'Stock 0 at month end, selected months bright' : 'Stock 0 at month end, by month';
  $('lg-zero').textContent = f ? 'stock 0 at month end (selected months bright)' : 'stock 0 at month end';
}

function renderTable(R) {
  var L = R.latest, monthFiltered = S.month.size > 0, rows = [];
  for (var p = 0; p < NP; p++) {
    if (!R.catOK[pCat[p]]) continue;
    var inv = INV[p], m0 = 0;
    for (var i = 0; i < NM; i++) if (R.mOK[i] && inv[i] === 0) m0++;
    rows.push({ p: p, name: P.name[p], cat: CATS[pCat[p]], units: R.skuUnits[p], rev: R.skuRev[p], stock: inv[L], m0: m0 });
  }
  if (sortKey === null) {
    rows.sort(function (a, b) {
      return ((a.stock === 0 ? 0 : 1) - (b.stock === 0 ? 0 : 1)) || (b.units - a.units) || (a.p - b.p);
    });
  } else {
    rows.sort(function (a, b) {
      var x = a[sortKey], y = b[sortKey];
      if (x === null && y === null) return a.p - b.p;
      if (x === null) return 1;            // no stock data: always last
      if (y === null) return -1;
      var d = typeof x === 'string' ? x.localeCompare(y) : x - y;
      return d * sortDir || (a.p - b.p);
    });
  }
  var maxU = 0, maxS = 0, ranOut = 0, hitZero = 0;
  rows.forEach(function (r) {
    if (r.units > maxU) maxU = r.units;
    if (r.stock !== null && r.stock > maxS) maxS = r.stock;
    if (r.stock === 0) ranOut++;
    if (r.m0 > 0) hitZero++;
  });
  var mLabel = MONTHS[L].label;
  T = { rows: rows, maxU: maxU, maxS: maxS, monthFiltered: monthFiltered, mOK: R.mOK, mLabel: mLabel };
  renderStripHead();
  renderRows(true);
  $('table-count').textContent = nf.format(rows.length) + ' products, ' + ranOut + ' ran out (stock 0 at end of ' + mLabel + ') · ' +
    hitZero + ' were at 0 in at least one ' + (monthFiltered ? 'selected ' : '') + 'month';
  return { rows: rows.length, ranOut: ranOut, hitZero: hitZero };
}

/* The table only puts the rows you can see (plus a margin) into the page.
   Two spacer rows keep the scrollbar the same as with all rows. This keeps
   every filter click fast. */
var T = null, lastWindow = '';
function barHTML(value, max) {    // inline data bar in px; bars under 2px are not drawn
  var w = max > 0 ? Math.round(value / max * BARPX) : 0;
  return w >= 2 ? '<span class="b" style="width:' + w + 'px"></span>' : '';
}
function rowHTML(r) {
  var sel = S.product.has(r.p);
  var stockCell;
  if (r.stock === null) stockCell = '<span class="n">–</span><span class="t"></span>';
  else if (r.stock === 0) stockCell = '<span class="n">0</span><span class="t"><span class="z"></span></span>';   // ran out: amber dot
  else stockCell = '<span class="n">' + nf.format(r.stock) + '</span><span class="t">' + barHTML(r.stock, T.maxS) + '</span>';
  var strip = '', inv = INV[r.p];
  for (var i = 0; i < NM; i++) {
    var v = inv[i], cls = v === null ? 'na' : v === 0 ? 'z' : 'ok';   // stock 0 = always the calm colour
    if (T.monthFiltered && !T.mOK[i]) cls += ' off';
    var txt = v === null ? 'no stock data' : v === 0 ? '0 units (out of stock)' : nf.format(v) + ' units';
    strip += '<s class="' + cls + '"' + tipAttr(MONTHS[i].long + ' month end', txt, r.name) + '></s>';
  }
  return '<tr tabindex="0" data-dim="product" data-i="' + r.p + '"' + (sel ? ' class="sel"' : '') + '>' +
    '<td class="pn"' + tipAttr(r.name, eurExact(r.rev), nf.format(r.units) + ' units sold · stock ' +
      (r.stock === null ? 'no stock data' : nf.format(r.stock)) + ' (' + T.mLabel + ')') + '>' + nameHTML(r.name) + '</td>' +
    '<td class="ct">' + esc(r.cat) + '</td>' +
    '<td class="r"><div class="db"><span class="n">' + nf.format(r.units) + '</span><span class="t">' + barHTML(r.units, T.maxU) + '</span></div></td>' +
    '<td class="r"' + tipAttr(r.name, eurExact(r.rev)) + '>' + eurWhole(r.rev) + '</td>' +
    '<td class="r"><div class="db">' + stockCell + '</div></td>' +
    '<td><div class="strip">' + strip + '</div></td></tr>';
}
function renderRows(force) {
  var wrap = $('table-wrap'), n = T.rows.length;
  // fewer rows than before: use the scroll position the browser is about to clamp to
  var st = Math.min(wrap.scrollTop, Math.max(0, n * ROWH + $('thead').offsetHeight - wrap.clientHeight));
  var first = Math.max(0, Math.floor(st / ROWH) - OVERSCAN);
  var last = Math.min(n, Math.ceil((st + wrap.clientHeight) / ROWH) + OVERSCAN);
  var key = first + ':' + last;
  if (!force && key === lastWindow) return;
  lastWindow = key;
  var html = '<tr class="spacer"><td colspan="6" style="height:' + first * ROWH + 'px"></td></tr>';
  for (var k = first; k < last; k++) html += rowHTML(T.rows[k]);
  html += '<tr class="spacer"><td colspan="6" style="height:' + (n - last) * ROWH + 'px"></td></tr>';
  $('tbody').innerHTML = html;
}
/* Scroll a product's row into view (only if it is not already visible). */
function revealRow(p) {
  var k = -1;
  for (var j = 0; j < T.rows.length; j++) if (T.rows[j].p === p) { k = j; break; }
  if (k < 0) return;
  var wrap = $('table-wrap'), head = $('thead').offsetHeight;
  var top = head + k * ROWH, viewTop = wrap.scrollTop + head, viewBot = wrap.scrollTop + wrap.clientHeight;
  if (top >= viewTop && top + ROWH <= viewBot) return;
  wrap.scrollTop = Math.max(0, top - head - (wrap.clientHeight - head - ROWH) / 2);
  renderRows(true);
}
var scrollQueued = false;
$('table-wrap').addEventListener('scroll', function () {
  if (scrollQueued) return; scrollQueued = true;
  requestAnimationFrame(function () { scrollQueued = false; if (T) renderRows(false); });
});

/* Slicers: multi-select dropdowns with checkbox lists */
function buildSlicers() {
  var host = $('slicers'), clear = $('clear-all');
  DIMS.forEach(function (d) {
    var wrap = document.createElement('div'); wrap.className = 'slicer'; wrap.setAttribute('data-slicer', d.key);
    var btn = document.createElement('button'); btn.type = 'button'; btn.className = 'sl-btn';
    btn.innerHTML = '<span class="sl-name"></span><span class="sl-val"></span><span class="sl-caret">▾</span>';
    btn.firstChild.textContent = d.title;
    var panel = document.createElement('div'); panel.className = 'sl-panel'; panel.hidden = true;
    var allLab = document.createElement('label'); allLab.className = 'sl-all';
    var allBox = document.createElement('input'); allBox.type = 'checkbox'; allBox.setAttribute('data-all', '1');
    allLab.appendChild(allBox); allLab.appendChild(document.createTextNode('All'));
    panel.appendChild(allLab);
    d.order.forEach(function (i) {
      var lab = document.createElement('label'), box = document.createElement('input');
      box.type = 'checkbox'; box.setAttribute('data-i', i);
      lab.appendChild(box); lab.appendChild(document.createTextNode(d.items[i]));
      panel.appendChild(lab);
    });
    panel.addEventListener('change', function (e) {
      var t = e.target;
      if (t.hasAttribute('data-all')) S[d.key].clear();
      else { var i = +t.getAttribute('data-i'); if (t.checked) S[d.key].add(i); else S[d.key].delete(i); }
      update();
    });
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = panel.hidden; closePanels(); panel.hidden = !open;
    });
    wrap.appendChild(btn); wrap.appendChild(panel);
    host.insertBefore(wrap, clear);
  });
}
function closePanels() {
  var ps = document.querySelectorAll('.sl-panel');
  for (var i = 0; i < ps.length; i++) ps[i].hidden = true;
}
function selectedNames(d) {      // selected items in display order (months in date order)
  return d.order.filter(function (i) { return S[d.key].has(i); }).map(function (i) { return d.items[i]; });
}
function renderSlicers() {
  DIMS.forEach(function (d) {
    var wrap = document.querySelector('[data-slicer="' + d.key + '"]'), set = S[d.key];
    var txt = set.size ? selectedNames(d).join(', ') : 'All';
    var val = wrap.querySelector('.sl-val'); val.textContent = txt; val.title = txt;
    wrap.querySelector('.sl-btn').classList.toggle('on', set.size > 0);
    var boxes = wrap.querySelectorAll('input[data-i]');
    for (var i = 0; i < boxes.length; i++) boxes[i].checked = set.has(+boxes[i].getAttribute('data-i'));
    wrap.querySelector('input[data-all]').checked = set.size === 0;
  });
  var any = Object.keys(S).some(function (k) { return S[k].size > 0; });
  $('clear-all').disabled = !any && sortKey === null;   // also active when the table is sorted
  var parts = [];
  DIMS.forEach(function (d) { if (S[d.key].size) parts.push(d.title + ': ' + selectedNames(d).join(', ')); });
  if (S.product.size) {
    var pn = []; S.product.forEach(function (p) { pn.push(P.name[p]); });
    parts.push('Product: ' + (pn.length > 2 ? pn.slice(0, 2).join(', ') + ' +' + (pn.length - 2) + ' more' : pn.join(', ')));
  }
  var sum = $('summary');
  sum.textContent = parts.length ? parts.join('  ·  ') : 'All data';
  sum.title = sum.textContent;
  $('period').textContent = periodText();
}

/* ------------------------------------------------------------------ *
 * 6. Update cycle                                                     *
 * ------------------------------------------------------------------ */
var lastR = null, revealProduct = -1;
function update() {
  // remember keyboard focus, so it survives the re-render
  var a = document.activeElement, fDim = a && a.getAttribute && a.getAttribute('data-dim'), fI = fDim ? a.getAttribute('data-i') : null;
  var R = compute();
  renderKPIs(R); renderMonth(R); renderCountry(R); renderProduct(R);
  renderTable(R); renderSlicers();
  lastR = R;
  if (revealProduct >= 0) { revealRow(revealProduct); revealProduct = -1; }
  hideTip();
  if (fDim) {
    var el = document.querySelector('[data-dim="' + fDim + '"][data-i="' + fI + '"]');
    if (el) el.focus({ preventScroll: true });
  }
}

/* Click / keyboard selection (Power BI style cross-filter) */
function select(dim, i, additive) {
  var set = S[dim];
  if (additive) { if (set.has(i)) set.delete(i); else set.add(i); }
  else if (set.size === 1 && set.has(i)) set.clear();
  else { set.clear(); set.add(i); }
  if (dim === 'product' && set.has(i)) revealProduct = i;
  update();
}
function sortBy(k) {
  if (sortKey === k) sortDir = -sortDir;
  else { sortKey = k; sortDir = (k === 'name' || k === 'cat') ? 1 : -1; }
  renderHead(); renderTable(lastR);
  $('clear-all').disabled = false;  // a sorted table can always be reset with Clear all
}
document.addEventListener('click', function (e) {
  var th = e.target.closest('th[data-sort]');
  if (th) { sortBy(th.getAttribute('data-sort')); return; }
  if (!e.target.closest('.slicer')) closePanels();
  var t = e.target.closest('[data-dim][data-i]');
  if (t) select(t.getAttribute('data-dim'), +t.getAttribute('data-i'), e.ctrlKey || e.metaKey || e.shiftKey);
});
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    var open = document.querySelector('.sl-panel:not([hidden])');
    if (open) { closePanels(); return; }
    clearAll(); return;
  }
  if (e.key !== 'Enter' && e.key !== ' ') return;
  var th = e.target.closest && e.target.closest('th[data-sort]');
  if (th) { e.preventDefault(); sortBy(th.getAttribute('data-sort')); return; }
  var t = e.target.closest && e.target.closest('[data-dim][data-i]');
  if (t) { e.preventDefault(); select(t.getAttribute('data-dim'), +t.getAttribute('data-i'), e.ctrlKey || e.metaKey || e.shiftKey); }
});
function clearAll() {             // clears every filter and resets the table sort
  Object.keys(S).forEach(function (k) { S[k].clear(); });
  sortKey = null; sortDir = -1; renderHead();
  closePanels(); update();
}
$('clear-all').addEventListener('click', function (e) { e.stopPropagation(); clearAll(); });
document.addEventListener('mousedown', function (e) { if (e.shiftKey && e.target.closest('[data-dim]')) e.preventDefault(); });

/* Tooltip: floats, never moves anything else. Hover shows only the tooltip. */
var tip = $('tip'), tipEl = null;
function showTip(el, x, y) {
  if (el !== tipEl) {
    tipEl = el; tip.textContent = '';
    var line = document.createElement('div');
    line.appendChild(document.createTextNode(el.getAttribute('data-tl') + ' · '));
    var b = document.createElement('b'); b.textContent = el.getAttribute('data-tv'); line.appendChild(b);
    tip.appendChild(line);
    if (el.getAttribute('data-tx')) {
      var x2 = document.createElement('div'); x2.className = 'x'; x2.textContent = el.getAttribute('data-tx'); tip.appendChild(x2);
    }
    tip.style.display = 'block';
  }
  var w = tip.offsetWidth, h = tip.offsetHeight, px = x + 14, py = y + 16;
  if (px + w > window.innerWidth - 8) px = x - w - 14;
  if (py + h > window.innerHeight - 8) py = y - h - 12;
  tip.style.transform = 'translate(' + Math.max(4, px) + 'px,' + Math.max(4, py) + 'px)';
}
function hideTip() { tipEl = null; tip.style.display = 'none'; }
document.addEventListener('pointermove', function (e) {
  var el = e.target.closest && e.target.closest('[data-tl]');
  if (el) showTip(el, e.clientX, e.clientY); else if (tipEl) hideTip();
});
document.addEventListener('focusin', function (e) {
  var el = e.target.closest && (e.target.closest('[data-tl]') || (e.target.querySelector && e.target.querySelector('[data-tl]')));
  if (el) { var r = el.getBoundingClientRect(); showTip(el, r.left + r.width / 2, r.top + r.height / 2); }
});
document.addEventListener('focusout', hideTip);
window.addEventListener('resize', function () { if (lastR) renderMonth(lastR); });

/* ------------------------------------------------------------------ *
 * 7. Start                                                            *
 * ------------------------------------------------------------------ */
$('chart-month').style.height = NC * HROW + 'px';       // month chart as tall as the country list
$('chart-country').style.height = NC * HROW + 'px';
$('chart-product').style.height = TOPN * HROW + 'px';
$('foot').textContent = 'Source: ' + D.source + ' · Built ' + D.built +
  ' · Revenue = qty × price × (1 − discount), before returns · Orders = distinct order numbers · Stock = month-end units, latest selected month';
buildSlicers(); renderHead(); update();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
