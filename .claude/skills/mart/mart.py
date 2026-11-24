"""
Build the NORDA sales data model (star schema) from the combined clean history.

    data/clean/all/orders.csv, products.csv, inventory.csv   (every delivery, built by /clean)
        ->  data/mart/fact_sales.csv, fact_inventory.csv,
            dim_date.csv, dim_product.csv, dim_country.csv, dim_channel.csv
        +   data/mart/model.html (diagram, generated from the design below on every build)
        +   runs/<run>/3-mart/mart-log.md

Design: knowledge/data-model.md
Metrics: knowledge/metrics.md
Never modifies data/clean. Overwrites only the six model CSVs and model.html (Power BI reads a fixed folder).

Run from the project root (--run names the log folder; the source is always data/clean/all/):
    python .claude/skills/mart/mart.py --run 2026-08
Then validate:
    python .claude/skills/mart/check.py --run 2026-08
"""
import sys

sys.dont_write_bytecode = True  # no __pycache__ folder next to the scripts

import argparse
import calendar
import html
import json
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

# ===========================================================================
# RULES (also used by check.py). Business lists come from knowledge/rules.json.
# ===========================================================================
def load_rules():
    """Business lists are shared by all scripts: knowledge/rules.json (found by walking up from here)."""
    for folder in Path(__file__).resolve().parents:
        f = folder / "knowledge" / "rules.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    raise FileNotFoundError("knowledge/rules.json not found")


RULES = load_rules()
CORE_MARKETS = set(RULES["core_markets"])
COUNTRY_NAMES = dict(RULES["country_names"])   # code -> name
CHANNELS = set(RULES["channels"])

# Fixed English names, so the result never depends on the computer's language
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

CENT = Decimal("0.01")  # money is rounded half-up to the cent (decision 2026-11-24)

# Output tables: column names AND order are fixed (knowledge/data-model.md)
COLUMNS = {
    "fact_sales": ["order_id", "date_key", "sku", "country_code", "channel",
                   "quantity", "unit_price", "discount_rate", "revenue", "discount_amount"],
    "fact_inventory": ["date_key", "sku", "qty_on_hand"],
    "dim_date": ["date_key", "date", "year", "quarter", "month_no", "month_name",
                 "year_month", "weekday", "is_weekend", "month_label"],
    "dim_product": ["sku", "product_name", "brand", "category", "latest_list_price"],
    "dim_country": ["country_code", "country_name", "is_core_market"],
    "dim_channel": ["channel"],
}
DIM_KEYS = {"dim_date": "date_key", "dim_product": "sku",
            "dim_country": "country_code", "dim_channel": "channel"}

# Relationships: (fact, fact column, dimension, dimension key) - one dimension row -> many fact rows
RELATIONSHIPS = [
    ("fact_sales", "date_key", "dim_date", "date_key"),
    ("fact_sales", "sku", "dim_product", "sku"),
    ("fact_sales", "country_code", "dim_country", "country_code"),
    ("fact_sales", "channel", "dim_channel", "channel"),
    ("fact_inventory", "date_key", "dim_date", "date_key"),
    ("fact_inventory", "sku", "dim_product", "sku"),
]

# For the diagram (data/mart/model.html): column types, table labels, and layout
COLUMN_TYPES = {
    "fact_sales": {"order_id": "text", "date_key": "int", "sku": "text", "country_code": "text",
                   "channel": "text", "quantity": "int", "unit_price": "decimal", "discount_rate": "decimal",
                   "revenue": "decimal", "discount_amount": "decimal"},
    "fact_inventory": {"date_key": "int", "sku": "text", "qty_on_hand": "int"},
    "dim_date": {"date_key": "int", "date": "date", "year": "int", "quarter": "int", "month_no": "int",
                 "month_name": "text", "year_month": "text", "weekday": "text", "is_weekend": "bool",
                 "month_label": "text"},
    "dim_product": {"sku": "text", "product_name": "text", "brand": "text", "category": "text",
                    "latest_list_price": "decimal"},
    "dim_country": {"country_code": "text", "country_name": "text", "is_core_market": "bool"},
    "dim_channel": {"channel": "text"},
}
TABLE_LABELS = {
    "fact_sales": "fact · one order line",
    "fact_inventory": "fact · sku × month end",
    "dim_date": "dimension · one day",
    "dim_product": "dimension",
    "dim_country": "dimension",
    "dim_channel": "dimension",
}
# Diagram columns, left to right: sales-only dims | fact_sales | shared dims | fact_inventory
DIAGRAM_LAYOUT = [["dim_channel", "dim_country"], ["fact_sales"], ["dim_date", "dim_product"], ["fact_inventory"]]


# ===========================================================================
# FACTS
# ===========================================================================
def build_fact_sales(orders):
    """One row per clean order line, same order as the input.

    revenue         = quantity x unit_price x (1 - discount_rate)
    discount_amount = quantity x unit_price x discount_rate
    Exact Decimal maths from the TEXT values, each rounded half-up to the cent on its own
    (so revenue + discount_amount can differ from quantity x unit_price by 1 cent).
    """
    revenues, discounts = [], []
    for qty_txt, price_txt, rate_txt in zip(orders["quantity"], orders["unit_price"], orders["discount_rate"]):
        gross = Decimal(qty_txt) * Decimal(price_txt)
        rate = Decimal(rate_txt)
        revenues.append(float((gross * (Decimal("1") - rate)).quantize(CENT, rounding=ROUND_HALF_UP)))
        discounts.append(float((gross * rate).quantize(CENT, rounding=ROUND_HALF_UP)))

    fact = pd.DataFrame({
        "order_id": orders["order_id"],
        "date_key": orders["order_date"].str.replace("-", "", regex=False).astype("int64"),  # 2025-01-31 -> 20250131
        "sku": orders["sku"],
        "country_code": orders["country_code"],
        "channel": orders["channel"],
        "quantity": orders["quantity"].astype("int64"),
        "unit_price": orders["unit_price"].astype("float64"),
        "discount_rate": orders["discount_rate"].astype("float64"),
        "revenue": revenues,
        "discount_amount": discounts,
    })
    return fact[COLUMNS["fact_sales"]].reset_index(drop=True)


def last_day_key(stock_month):
    """'2025-02' -> 20250228 (last calendar day of that month, as yyyymmdd)."""
    year, month = int(stock_month[:4]), int(stock_month[5:7])
    return year * 10000 + month * 100 + calendar.monthrange(year, month)[1]


def build_fact_inventory(inventory):
    """One row per clean inventory row, same order. A month's stock is keyed to its LAST day."""
    fact = pd.DataFrame({
        "date_key": [last_day_key(m) for m in inventory["stock_month"]],
        "sku": inventory["sku"],
        "qty_on_hand": inventory["qty_on_hand"].astype("int64"),
    })
    fact["date_key"] = fact["date_key"].astype("int64")
    return fact[COLUMNS["fact_inventory"]].reset_index(drop=True)


# ===========================================================================
# DIMENSIONS
# ===========================================================================
def date_attributes(day):
    """All dim_date columns for one datetime.date."""
    return {
        "date_key": day.year * 10000 + day.month * 100 + day.day,
        "date": day.isoformat(),
        "year": day.year,
        "quarter": (day.month - 1) // 3 + 1,
        "month_no": day.month,
        "month_name": MONTH_NAMES[day.month - 1],
        "year_month": f"{day.year}-{day.month:02d}",
        "weekday": WEEKDAY_NAMES[day.weekday()],
        "is_weekend": day.weekday() >= 5,
        "month_label": f"{MONTH_NAMES[day.month - 1][:3]} {day.year}",   # Jan 2025: tells years apart
    }


def build_dim_date(dates):
    """One row per day, no gaps, from 1 January of the first year to 31 December of the last year
    found in `dates` (any list of 'YYYY-MM-DD' strings)."""
    distinct = set(dates)
    if not distinct:
        raise ValueError("build_dim_date: no dates were passed in.")
    parsed = []
    for text in distinct:
        try:
            parsed.append(dt.date.fromisoformat(text))
        except (TypeError, ValueError):
            raise ValueError(f"build_dim_date: '{text}' is not a valid YYYY-MM-DD date.")
    day, last_day = dt.date(min(parsed).year, 1, 1), dt.date(max(parsed).year, 12, 31)
    rows = []
    while day <= last_day:
        rows.append(date_attributes(day))
        day += dt.timedelta(days=1)
    return pd.DataFrame(rows, columns=COLUMNS["dim_date"])


def build_dim_product(products):
    """One row per clean product, same order."""
    dim = products[COLUMNS["dim_product"]].copy().reset_index(drop=True)
    dim["latest_list_price"] = pd.to_numeric(dim["latest_list_price"], errors="raise").round(2)
    return dim


def build_dim_country(orders):
    """One row per country code found in orders, sorted. Unknown code -> stop (no guessing)."""
    codes = sorted(orders["country_code"].unique())
    unknown = [c for c in codes if c not in COUNTRY_NAMES]
    if unknown:
        raise ValueError(f"Unknown country code(s) in orders: {unknown}. Add them to COUNTRY_NAMES first.")
    return pd.DataFrame({
        "country_code": codes,
        "country_name": [COUNTRY_NAMES[c] for c in codes],
        "is_core_market": [c in CORE_MARKETS for c in codes],
    })


def build_dim_channel(orders):
    """One row per channel found in orders, sorted. Unknown channel -> stop."""
    channels = sorted(orders["channel"].unique())
    unknown = [c for c in channels if c not in CHANNELS]
    if unknown:
        raise ValueError(f"Unknown channel(s) in orders: {unknown}. Add them to CHANNELS first.")
    return pd.DataFrame({"channel": channels})


# ===========================================================================
# DIAGRAM: data/mart/model.html, generated from the design above on every build
# ===========================================================================
DIAGRAM_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sales Data Model</title>
<style>
  :root {
    --bg: #0e1318; --surface: #151c23; --surface-2: #1a232c; --line-soft: #243039;
    --text: #cdd6de; --muted: #7d8b97;
    --calm: #6f93b6; --calm-dim: rgba(111, 147, 182, 0.38);   /* the one calm colour */
    --key: #e5b45a; --key-soft: rgba(229, 180, 90, 0.10);     /* join keys */
    --mono: ui-monospace, "Cascadia Mono", "SF Mono", Consolas, monospace;
    --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--bg); color: var(--text); font-family: var(--sans); }
  body { padding: 32px 16px 48px; }
  .page { max-width: 1240px; margin: 0 auto; }
  header.top h1 { font-size: 22px; font-weight: 600; margin: 0 0 6px; letter-spacing: 0.2px; }
  header.top p { margin: 0; color: var(--muted); font-size: 14px; }
  code { font-family: var(--mono); font-size: 12.5px; }
  .legend { display: flex; flex-wrap: wrap; gap: 18px; margin: 18px 0 8px; font-size: 13px; color: var(--muted); }
  .legend span { display: inline-flex; align-items: center; gap: 8px; }
  .sw-key, .sw-line { display: inline-block; }
  .sw-key { width: 10px; height: 10px; border-radius: 2px; background: var(--key); }
  .sw-line { width: 26px; height: 2px; background: var(--calm); opacity: 0.6; }
  .scroll { overflow-x: auto; margin-top: 18px; border: 1px solid var(--line-soft); border-radius: 10px; background: #0b1015; }
  .diagram { position: relative; min-width: 1120px; padding: 40px 36px; display: grid;
             grid-template-columns: 210px 250px 240px 210px; column-gap: 104px; justify-content: center; align-items: center; }
  .col { display: flex; flex-direction: column; gap: 40px; position: relative; z-index: 1; }
  svg.links { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 0; overflow: visible; }
  .table { background: var(--surface); border: 1px solid var(--line-soft); border-radius: 8px; outline: none; cursor: default; transition: border-color .18s ease; }
  .table:hover, .table:focus-visible { border-color: var(--calm); }
  .table header { padding: 10px 12px 9px; border-bottom: 1px solid var(--line-soft); background: var(--surface-2); border-radius: 8px 8px 0 0; }
  .t-name { font-family: var(--mono); font-size: 14px; font-weight: 600; color: var(--calm); }
  .t-meta { display: flex; justify-content: space-between; gap: 8px; margin-top: 4px; font-size: 11.5px; color: var(--muted); }
  .t-kind { text-transform: uppercase; letter-spacing: 0.8px; }
  .table ul { list-style: none; margin: 0; padding: 6px 0; }
  .table li { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; padding: 4px 12px; font-family: var(--mono); font-size: 12.5px; }
  .table li .ty { color: var(--muted); font-size: 11px; }
  .table li.key { color: var(--key); background: var(--key-soft); }
  .table li.key .ty { color: var(--key); opacity: .75; }
  path.link { fill: none; stroke: var(--calm-dim); stroke-width: 1.6; transition: stroke .18s ease; }
  path.link.lit { stroke: var(--key); }
  text.card { fill: var(--muted); font: 11px var(--mono); transition: fill .18s ease; }
  text.card.lit { fill: var(--key); }
  circle.end { fill: var(--calm-dim); transition: fill .18s ease; }
  circle.end.lit { fill: var(--key); }
  .notes { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-top: 24px; }
  .note-box { background: var(--surface); border: 1px solid var(--line-soft); border-radius: 8px; padding: 14px 16px; }
  .note-box h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--calm); margin: 0 0 10px; font-weight: 600; }
  .note-box dl { margin: 0; font-size: 13px; line-height: 1.45; }
  .note-box dt { font-weight: 600; margin-top: 8px; }
  .note-box dt:first-child { margin-top: 0; }
  .note-box dd { margin: 2px 0 0; color: var(--muted); }
  footer { margin-top: 22px; font-size: 12px; color: var(--muted); }
</style>
</head>
<body>
<div class="page">
  <header class="top">
    <h1>NORDA sales data model · star schema</h1>
    <p>__SUBTITLE__</p>
  </header>
  <div class="legend">
    <span><i class="sw-key"></i>Join key</span>
    <span><i class="sw-line"></i>Relationship: 1 dimension row → many fact rows</span>
    <span>Hover a table to light up its relationships</span>
  </div>
  <div class="scroll">
    <div class="diagram" id="diagram">
      <svg class="links" id="links" aria-hidden="true"></svg>
__COLUMNS__
    </div>
  </div>
  <div class="notes">
    <div class="note-box"><h2>Measures</h2><dl>
      <dt>Total revenue</dt><dd>Sum of <code>revenue</code>. Per line: quantity × unit_price × (1 − discount_rate), rounded half-up to the cent.</dd>
      <dt>Orders</dt><dd>Distinct count of <code>order_id</code>. Orders, not lines.</dd>
      <dt>Units sold</dt><dd>Sum of <code>quantity</code>.</dd>
      <dt>Discount amount</dt><dd>Sum of <code>discount_amount</code> = quantity × unit_price × discount_rate.</dd>
      <dt>Stock on hand</dt><dd>Sum of <code>qty_on_hand</code> at the latest month in the selection. Never summed across months.</dd>
    </dl></div>
    <div class="note-box"><h2>Definitions</h2><dl>
      <dt>Best-selling products</dt><dd>Ranked by revenue.</dd>
      <dt>Ran out</dt><dd><code>qty_on_hand = 0</code> at month end.</dd>
      <dt>Countries</dt><dd>All shown by default. Use <code>is_core_market</code> to filter to the core markets.</dd>
      <dt>Stock date</dt><dd>Inventory is keyed to the month-end date, so one month filter works on both facts.</dd>
    </dl></div>
    <div class="note-box"><h2>Limits</h2><dl>
      <dt>Stock vs. country and channel</dt><dd>The inventory data has no country or channel, so these filters don't change stock on hand.</dd>
      <dt>Returns</dt><dd>Revenue is before returns. Returns are handled in a separate system.</dd>
      <dt>Cost of running out</dt><dd>Needs a lost-sales estimate, which isn't in the data yet.</dd>
    </dl></div>
  </div>
  <footer>Generated by the <code>/mart</code> skill (<code>mart.py</code>) on every build. Details in <code>knowledge/data-model.md</code>.</footer>
</div>
<script id="rels" type="application/json">__RELS__</script>
<script>
  // [fact table, fact column, dimension table, dimension column], generated from mart.py
  const RELS = JSON.parse(document.getElementById("rels").textContent);
  const NS = "http://www.w3.org/2000/svg";
  const diagram = document.getElementById("diagram");
  const svg = document.getElementById("links");

  function row(table, col) { return document.querySelector(`#${table} li[data-col="${col}"]`); }
  function el(tag, attrs) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function draw() {
    const box = diagram.getBoundingClientRect();
    svg.replaceChildren();
    for (const [ft, fc, dt, dc] of RELS) {
      const a = row(ft, fc).getBoundingClientRect();
      const b = row(dt, dc).getBoundingClientRect();
      const right = a.left < b.left;           // is the dimension to the right of the fact?
      const x1 = (right ? a.right : a.left) - box.left, x2 = (right ? b.left : b.right) - box.left;
      const y1 = a.top + a.height / 2 - box.top, y2 = b.top + b.height / 2 - box.top;
      const bend = Math.max(40, Math.abs(x2 - x1) * 0.5), dir = right ? 1 : -1;
      const tags = { "data-a": ft, "data-b": dt };
      svg.append(el("path", { d: `M ${x1} ${y1} C ${x1 + dir * bend} ${y1}, ${x2 - dir * bend} ${y2}, ${x2} ${y2}`, class: "link", ...tags }));
      svg.append(el("circle", { cx: x1, cy: y1, r: 2.6, class: "end", ...tags }));
      svg.append(el("circle", { cx: x2, cy: y2, r: 2.6, class: "end", ...tags }));
      const many = el("text", { x: x1 + dir * 8, y: y1 - 5, "text-anchor": right ? "start" : "end", class: "card", ...tags });
      many.textContent = "*";
      const one = el("text", { x: x2 - dir * 8, y: y2 - 5, "text-anchor": right ? "end" : "start", class: "card", ...tags });
      one.textContent = "1";
      svg.append(many, one);
    }
  }
  // Hover / focus a table: its relationship lines light up. Only colours change; nothing moves.
  function light(id, on) {
    svg.querySelectorAll(`[data-a="${id}"], [data-b="${id}"]`).forEach(n => n.classList.toggle("lit", on));
  }
  document.querySelectorAll(".table").forEach(t => {
    t.addEventListener("mouseenter", () => light(t.id, true));
    t.addEventListener("mouseleave", () => light(t.id, false));
    t.addEventListener("focus", () => light(t.id, true));
    t.addEventListener("blur", () => light(t.id, false));
  });
  new ResizeObserver(draw).observe(diagram);
  window.addEventListener("load", draw);
  draw();
</script>
</body>
</html>
"""


def diagram_card(name, rows):
    """One table card: header (name, kind, rows) + one line per column. Keys get the highlight colour."""
    missing = [c for c in COLUMNS[name] if c not in COLUMN_TYPES[name]]
    if missing:
        raise ValueError(f"COLUMN_TYPES has no type for {name}: {missing}")
    fks = {fc for f, fc, _, _ in RELATIONSHIPS if f == name}
    lines = []
    for col in COLUMNS[name]:
        typ = COLUMN_TYPES[name][col]
        if col == DIM_KEYS.get(name):
            cls, tag = ' class="key"', f"{typ} · PK"
        elif col in fks:
            cls, tag = ' class="key"', f"{typ} · FK"
        else:
            cls, tag = "", typ
        lines.append(f'            <li{cls} data-col="{col}"><span>{html.escape(col)}</span><span class="ty">{tag}</span></li>')
    return (f'        <section class="table" id="{name}" tabindex="0">\n'
            f'          <header><div class="t-name">{name}</div>\n'
            f'            <div class="t-meta"><span class="t-kind">{html.escape(TABLE_LABELS[name])}</span>'
            f'<span>{rows:,} rows</span></div></header>\n'
            f'          <ul>\n' + "\n".join(lines) + "\n          </ul>\n        </section>")


def write_diagram(tables, path, run, clean):
    """Write data/mart/model.html from the design (COLUMNS, keys, RELATIONSHIPS) and the real row counts."""
    placed = [t for col in DIAGRAM_LAYOUT for t in col]
    if sorted(placed) != sorted(COLUMNS):
        raise ValueError(f"DIAGRAM_LAYOUT must place every table exactly once: {placed}")
    columns = "\n".join(
        '      <div class="col">\n' + "\n".join(diagram_card(t, len(tables[t])) for t in col) + "\n      </div>"
        for col in DIAGRAM_LAYOUT)
    subtitle = (f"For the Power BI sales dashboard. {sum(t.startswith('fact_') for t in COLUMNS)} facts, "
                f"{sum(t.startswith('dim_') for t in COLUMNS)} dimensions. Built from <code>{html.escape(str(clean))}</code> "
                f"(run {html.escape(run)}) into <code>data/mart/</code> on {dt.datetime.now():%Y-%m-%d %H:%M}.")
    page = (DIAGRAM_TEMPLATE.replace("__SUBTITLE__", subtitle)
            .replace("__COLUMNS__", columns)
            .replace("__RELS__", json.dumps([list(r) for r in RELATIONSHIPS])))
    path.write_text(page, encoding="utf-8")


# ===========================================================================
def read_text(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


def month_end_date(stock_month):
    """'2025-02' -> '2025-02-28'"""
    year, month = int(stock_month[:4]), int(stock_month[5:7])
    return dt.date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def main():
    ap = argparse.ArgumentParser(description="Build the star-schema sales data model from the clean layer.")
    ap.add_argument("--run", required=True, help="Run month for the log folder, e.g. 2026-08")
    ap.add_argument("--clean", default="data/clean/all", help="Combined clean history (default: data/clean/all)")
    ap.add_argument("--out", default="data/mart", help="Mart folder (default: data/mart)")
    args = ap.parse_args()
    clean = Path(args.clean)
    out = Path(args.out)

    missing = [n for n in ("orders", "products", "inventory") if not (clean / f"{n}.csv").exists()]
    if missing:
        print(f"STOPPED - clean files missing in {clean}: {missing}. Run /clean {args.run} first.")
        return 1
    orders = read_text(clean / "orders.csv")
    products = read_text(clean / "products.csv")
    inventory = read_text(clean / "inventory.csv")

    try:
        inventory_dates = [month_end_date(m) for m in inventory["stock_month"].unique()]
        tables = {
            "fact_sales": build_fact_sales(orders),
            "fact_inventory": build_fact_inventory(inventory),
            "dim_date": build_dim_date(list(orders["order_date"]) + inventory_dates),
            "dim_product": build_dim_product(products),
            "dim_country": build_dim_country(orders),
            "dim_channel": build_dim_channel(orders),
        }
    except ValueError as e:
        print(f"STOPPED - nothing written. {e}")
        return 1

    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", index=False, encoding="utf-8", float_format="%.2f", lineterminator="\n")
        print(f"{name:<15} {len(df):>8,} rows -> {out / (name + '.csv')}")
    write_diagram(tables, out / "model.html", args.run, clean)
    print(f"{'diagram':<15} {'':>8}      -> {out / 'model.html'}")

    log = [f"# Mart build log - run {args.run}", "",
           f"- Source: `{clean}`  ->  Mart: `{out}`",
           f"- Built: {dt.datetime.now():%Y-%m-%d %H:%M}",
           "- Design: `knowledge/data-model.md` · Metrics: `knowledge/metrics.md`", "",
           "| Table | Rows | Columns |", "|---|---|---|"]
    log += [f"| {n} | {len(df):,} | {', '.join(df.columns)} |" for n, df in tables.items()]
    log += ["", f"Diagram: `{out / 'model.html'}` (generated from the design in mart.py)"]
    log_path = Path("runs") / args.run / "3-mart" / "mart-log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"Log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
