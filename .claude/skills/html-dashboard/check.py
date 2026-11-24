"""
NORDA dashboard checks
======================

Opens the real dashboard (reports/html/dashboard.html) in headless Edge, uses it
like a person would (slicer checkboxes, clicks on bars, sorting, Clear all) and
compares what the page SHOWS with SQL on data/mart/ (the second road).

    python .claude/skills/html-dashboard/check.py --run 2026-08

Writes runs/<run>/5-html-dashboard/html-dashboard-checks.md. Any FAIL -> exit code 1.
Read-only on data/ and on the dashboard; temporary files live in a temp folder
that is deleted automatically.

Checks
  H01-H04  the file: exists, self-contained, no test hook, newer than the mart
  P01-P06  the numbers, page vs SQL, in whole cents, for 6 filter states
  I01-I06  behaviour: click twice clears, nothing moves, Clear all resets sort,
           stock ignores country/channel, header period, no script errors
"""

import argparse
import html
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# 1. Settings
# ---------------------------------------------------------------------------
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]
WINDOW = "1440,1100"
TABLES = ["fact_sales", "fact_inventory", "dim_date", "dim_product", "dim_country", "dim_channel"]


def parse_args():
    ap = argparse.ArgumentParser(description="Check the NORDA HTML dashboard against data/mart.")
    ap.add_argument("--run", required=True, help="run month, e.g. 2026-08")
    ap.add_argument("--mart", default="data/mart")
    ap.add_argument("--html", default="reports/html/dashboard.html")
    ap.add_argument("--browser", default=None, help="path to msedge.exe / chrome.exe (optional)")
    return ap.parse_args()


def stop(msg):
    print("STOPPED: " + msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Road B: SQL on data/mart (what Power BI would compute)
# ---------------------------------------------------------------------------
def load_db(mart):
    db = sqlite3.connect(":memory:")
    for t in TABLES:
        p = Path(mart) / f"{t}.csv"
        if not p.exists():
            stop(f"missing {p}")
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        df["_row"] = range(len(df))                 # keeps the file order (used for tie-breaks)
        df.to_sql(t, db, index=False)
    return db


def q(db, sql, params=()):
    return db.execute(sql, params).fetchall()


CENTS = "CAST(ROUND(CAST(f.revenue AS REAL) * 100) AS INTEGER)"
SALES = ("FROM fact_sales f JOIN dim_date d ON d.date_key = f.date_key "
         "JOIN dim_product p ON p.sku = f.sku JOIN dim_country c ON c.country_code = f.country_code ")
FILTER_COLS = {"month": "d.year_month", "cat": "p.category", "country": "f.country_code", "channel": "f.channel"}


def where(state, skip=None):
    parts, params = [], []
    for dim, col in FILTER_COLS.items():
        vals = state.get(dim) or []
        if dim == skip or not vals:
            continue
        parts.append(f"{col} IN ({','.join('?' * len(vals))})")
        params += vals
    return ("WHERE " + " AND ".join(parts) + " ") if parts else "", params


class Model:
    """Everything the checks need to know about the mart, computed with SQL."""

    def __init__(self, db):
        self.db = db
        # Months from the first to the last month WITH DATA (sales or stock); dim_date holds whole calendar years.
        ym = "substr(date_key, 1, 4) || '-' || substr(date_key, 5, 2)"
        with_data = {r[0] for r in q(db, f"SELECT DISTINCT {ym} FROM fact_sales UNION SELECT DISTINCT {ym} FROM fact_inventory")}
        rows = [r for r in q(db, "SELECT year_month, MIN(month_name), MIN(year) FROM dim_date GROUP BY year_month ORDER BY year_month")
                if min(with_data) <= r[0] <= max(with_data)]
        self.months = [{"ym": r[0], "short": r[1][:3], "label": f"{r[1][:3]} {r[2]}", "long": f"{r[1]} {r[2]}"} for r in rows]
        self.cats = [r[0] for r in q(db, "SELECT DISTINCT category FROM dim_product ORDER BY category")]
        self.countries = q(db, "SELECT country_code, country_name FROM dim_country ORDER BY _row")
        self.channels = [r[0] for r in q(db, "SELECT channel FROM dim_channel ORDER BY _row")]
        sales_ym = [r[0] for r in q(db, f"SELECT DISTINCT d.year_month {SALES} ORDER BY 1")]
        first = next(m for m in self.months if m["ym"] == sales_ym[0])
        last = next(m for m in self.months if m["ym"] == sales_ym[-1])
        self.sales_months = sales_ym
        self.period = (f"{first['short']}–{last['short']} {last['ym'][:4]}" if first["ym"][:4] == last["ym"][:4]
                       else f"{first['label']}–{last['label']}")

    def expected(self, st):
        db, out = self.db, {}
        w, p = where(st)
        rev, orders = q(db, f"SELECT COALESCE(SUM({CENTS}),0), COUNT(DISTINCT f.order_id) {SALES}{w}", p)[0]
        out["rev"], out["orders"] = rev, orders

        w, p = where(st, skip="month")
        by_m = dict(q(db, f"SELECT d.year_month, SUM({CENTS}) {SALES}{w}GROUP BY 1", p))
        out["months"] = {m["long"]: by_m.get(m["ym"], 0) for m in self.months}

        w, p = where(st, skip="country")
        by_c = dict(q(db, f"SELECT f.country_code, SUM({CENTS}) {SALES}{w}GROUP BY 1", p))
        order = sorted(range(len(self.countries)), key=lambda i: (-by_c.get(self.countries[i][0], 0), i))
        out["countries"] = [(self.countries[i][1], by_c.get(self.countries[i][0], 0)) for i in order]

        w, p = where(st)
        top = q(db, f"SELECT p.product_name, SUM({CENTS}) AS v, MIN(p._row) {SALES}{w}"
                    f"GROUP BY p.sku HAVING v > 0 ORDER BY v DESC, MIN(p._row) LIMIT 10", p)
        out["top"] = [(r[0], r[1]) for r in top]

        # Stock: latest selected month (or latest month), category filter only.
        latest = max(st["month"]) if st.get("month") else self.months[-1]["ym"]
        yyyymm = latest.replace("-", "")
        cat_sql, cat_p = ("AND p.category IN (" + ",".join("?" * len(st["cat"])) + ") ", st["cat"]) if st.get("cat") else ("", [])
        inv = ("FROM fact_inventory i JOIN dim_product p ON p.sku = i.sku "
               "WHERE substr(i.date_key, 1, 6) = ? " + cat_sql)
        out["stock"] = q(db, f"SELECT COALESCE(SUM(CAST(i.qty_on_hand AS INTEGER)),0) {inv}", [yyyymm] + cat_p)[0][0]
        out["stock_label"] = next(m["label"] for m in self.months if m["ym"] == latest)
        out["ran_out"] = q(db, f"SELECT COUNT(DISTINCT i.sku) {inv}AND CAST(i.qty_on_hand AS INTEGER) = 0", [yyyymm] + cat_p)[0][0]
        sel = [m.replace("-", "") for m in (st.get("month") or [m["ym"] for m in self.months])]
        out["hit_zero"] = q(db, "SELECT COUNT(DISTINCT i.sku) FROM fact_inventory i JOIN dim_product p ON p.sku = i.sku "
                                f"WHERE substr(i.date_key, 1, 6) IN ({','.join('?' * len(sel))}) "
                                f"AND CAST(i.qty_on_hand AS INTEGER) = 0 " + cat_sql, sel + cat_p)[0][0]
        out["products"] = q(db, "SELECT COUNT(*) FROM dim_product p WHERE 1=1 " + cat_sql, cat_p)[0][0]
        return out


# ---------------------------------------------------------------------------
# 3. The filter states to test (picked from the data, so they work every month)
# ---------------------------------------------------------------------------
def pick_states(m, db):
    top_country = q(db, f"SELECT f.country_code {SALES}GROUP BY 1 ORDER BY SUM({CENTS}) DESC LIMIT 1")[0][0]
    top_channel = q(db, f"SELECT f.channel {SALES}GROUP BY 1 ORDER BY SUM({CENTS}) DESC LIMIT 1")[0][0]
    # Two categories that share the most orders: proves orders are counted once, not summed.
    pair = q(db, "SELECT a.category, b.category, COUNT(*) FROM "
                 "(SELECT DISTINCT f.order_id, p.category FROM fact_sales f JOIN dim_product p ON p.sku = f.sku) a JOIN "
                 "(SELECT DISTINCT f.order_id, p.category FROM fact_sales f JOIN dim_product p ON p.sku = f.sku) b "
                 "ON a.order_id = b.order_id AND a.category < b.category GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 1")
    sm = m.sales_months
    states = [
        ("P01", "Default (no filters)", {}),
        ("P02", f"Month = {sm[-1]}", {"month": [sm[-1]]}),
        ("P03", f"Country {top_country} + channel {top_channel}", {"country": [top_country], "channel": [top_channel]}),
        ("P04", f"Category = {m.cats[0]}", {"cat": [m.cats[0]]}),
        ("P05", f"Months {sm[min(2, len(sm)-1)]}+{sm[min(3, len(sm)-1)]}, category {m.cats[-1]}",
         {"month": sorted({sm[min(2, len(sm)-1)], sm[min(3, len(sm)-1)]}), "cat": [m.cats[-1]]}),
    ]
    if pair:
        states.append(("P06", f"Categories {pair[0][0]} + {pair[0][1]} ({pair[0][2]:,} orders have both)",
                       {"cat": [pair[0][0], pair[0][1]]}))
    return states, pair


def to_page_labels(m, st):
    """Turn a state into the labels the page's slicers show."""
    ym_label = {x["ym"]: x["label"] for x in m.months}
    names = dict(m.countries)
    return {
        "month": [ym_label[v] for v in st.get("month", [])],
        "cat": st.get("cat", []),
        "country": [names[v] for v in st.get("country", [])],
        "channel": [v.capitalize() for v in st.get("channel", [])],
    }


# ---------------------------------------------------------------------------
# 4. Road A: the page itself, driven in headless Edge
# ---------------------------------------------------------------------------
ERR_HOOK = """<script>window.__errs=[];window.addEventListener('error',function(e){__errs.push(String(e.message))});
(function(){var ce=console.error;console.error=function(){__errs.push([].join.call(arguments,' '));ce.apply(console,arguments)}})();</script>"""

DRIVER = r"""<pre id="__check__" hidden></pre><script>
window.addEventListener('load', function () { setTimeout(run, 50); });
function run() {
  var SPEC = __SPEC__, out = { states: {}, i: {} };
  function q(s) { return document.querySelector(s); }
  function qa(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function clearAll() { var b = q('#clear-all'); if (!b.disabled) b.click(); }
  function pick(key, names) {
    names.forEach(function (n) {
      var lab = qa('[data-slicer="' + key + '"] .sl-panel label').filter(function (l) { return l.textContent.trim() === n; })[0];
      if (!lab) throw new Error('slicer ' + key + ' has no item "' + n + '"');
      var box = lab.querySelector('input'); if (!box.checked) box.click();
    });
  }
  function setState(s) { clearAll(); ['month', 'cat', 'country', 'channel'].forEach(function (k) { pick(k, s[k] || []); }); }
  function pair(e) { return [e.getAttribute('data-tl'), e.getAttribute('data-tv')]; }
  function read() {
    return {
      rev: q('#kpi-rev').getAttribute('data-tv'), revBig: q('#kpi-rev').textContent,
      orders: q('#kpi-ord').textContent, stock: q('#kpi-stock').textContent, stockCap: q('#kpi-stock-cap').textContent,
      months: qa('rect.hit[data-dim="month"]').map(pair),
      countries: qa('.hrow[data-dim="country"]').map(pair),
      top: qa('.hrow[data-dim="product"]').map(pair),
      table: q('#table-count').textContent, period: q('#period').textContent, summary: q('#summary').textContent,
      notes: [q('#kpi-stock-note').style.visibility, q('#table-stock-note').style.visibility]
    };
  }
  function layout() {
    return qa('header, .panel, footer, #chart-month, #chart-country, #chart-product, #table-wrap').map(function (e) {
      var r = e.getBoundingClientRect(); return [Math.round(r.left * 2) / 2, Math.round(r.top * 2) / 2, Math.round(r.width * 2) / 2, Math.round(r.height * 2) / 2];
    }).concat([[document.documentElement.scrollHeight]]);
  }
  function clickAt(x, y) {
    var el = document.elementFromPoint(x, y); if (!el) return;
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y, view: window }));
  }
  function rowIds() { return qa('#tbody tr[data-i]').slice(0, 10).map(function (r) { return r.getAttribute('data-i'); }); }
  try {
    // P: numbers for every state
    SPEC.states.forEach(function (s) { setState(s.labels); out.states[s.id] = read(); });
    clearAll();
    // I01: click the same screen point twice -> filter on, then off (every country row + first month column)
    var base = layout(), i01 = [];
    qa('.hrow[data-dim="country"]').forEach(function (row, k) {
      var r = qa('.hrow[data-dim="country"]')[k].getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
      var name = row.getAttribute('data-tl');
      clickAt(x, y); var s1 = q('#summary').textContent;
      clickAt(x, y); var s2 = q('#summary').textContent;
      i01.push([name, s1, s2]);
    });
    var mr = q('rect.hit[data-dim="month"]').getBoundingClientRect(), mx = mr.left + mr.width / 2, my = mr.top + mr.height / 2;
    clickAt(mx, my); var m1 = q('#summary').textContent; clickAt(mx, my); i01.push(['first month column', m1, q('#summary').textContent]);
    out.i.i01 = i01;
    // I02: nothing moves when filters change
    var moved = [];
    setState(SPEC.busy); if (JSON.stringify(layout()) !== JSON.stringify(base)) moved.push('country+channel+month+category');
    var pr = q('.hrow[data-dim="product"]'); if (pr) { pr.click(); if (JSON.stringify(layout()) !== JSON.stringify(base)) moved.push('+ product'); }
    clearAll(); if (JSON.stringify(layout()) !== JSON.stringify(base)) moved.push('after Clear all');
    out.i.i02 = moved;
    // I03: sort, then Clear all -> default order back
    var def = rowIds(), th = q('th[data-sort="rev"]');
    th.click();
    out.i.i03 = { enabledAfterSort: !q('#clear-all').disabled, changed: JSON.stringify(rowIds()) !== JSON.stringify(def) };
    q('#clear-all').click();
    out.i.i03.disabledAfterClear = q('#clear-all').disabled;
    out.i.i03.backToDefault = JSON.stringify(rowIds()) === JSON.stringify(def);
    // I05: header period follows the month filter
    out.i.i05 = SPEC.periods.map(function (p) { setState({ month: p.labels }); return [p.labels.join(' + ') || '(none)', q('#period').textContent, p.want]; });
    clearAll();
  } catch (e) { out.fatal = String(e && e.stack || e); }
  out.errors = window.__errs || [];
  document.getElementById('__check__').textContent = JSON.stringify(out);
}
</script>"""


def find_browser(arg):
    for c in ([arg] if arg else []) + BROWSERS + [shutil.which("msedge"), shutil.which("chrome")]:
        if c and Path(c).exists():
            return c
    stop("no Microsoft Edge or Chrome found. Install Edge, or pass --browser <path to msedge.exe>.")


def run_page(page_html, spec, browser):
    with tempfile.TemporaryDirectory(prefix="norda-dash-check-") as tmp:
        test = page_html.replace("<head>", "<head>" + ERR_HOOK, 1)
        test = test.replace("</body>", DRIVER.replace("__SPEC__", json.dumps(spec).replace("</", "<\\/")) + "</body>", 1)
        page = Path(tmp) / "page.html"
        page.write_text(test, encoding="utf-8")
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
               f"--user-data-dir={Path(tmp) / 'profile'}", f"--window-size={WINDOW}",
               "--virtual-time-budget=30000", "--dump-dom", page.as_uri()]
        res = subprocess.run(cmd, capture_output=True, timeout=300)
        dom = res.stdout.decode("utf-8", errors="replace")
    m = re.search(r'<pre id="__check__" hidden="">(.*?)</pre>', dom, re.S)
    if not m or not m.group(1).strip():
        stop("the browser returned no test result (page did not load or the driver did not run).")
    return json.loads(html.unescape(m.group(1)))


# ---------------------------------------------------------------------------
# 5. Compare
# ---------------------------------------------------------------------------
def cents(text):
    """'€33,506,864.27' -> 3350686427"""
    return int(re.sub(r"[^\d]", "", text or "0") or 0)


def whole(text):
    return int(re.sub(r"[^\d]", "", text or "0") or 0)


def eur(c):
    return f"€{c // 100:,}.{c % 100:02d}"


def compare_state(page, exp):
    """Returns a list of mismatch strings (empty = PASS)."""
    bad = []
    if cents(page["rev"]) != exp["rev"]:
        bad.append(f"revenue page {page['rev']} vs SQL {eur(exp['rev'])}")
    if whole(page["revBig"]) != (exp["rev"] + 50) // 100:
        bad.append(f"big revenue {page['revBig']} is not the exact value rounded to whole euros")
    if whole(page["orders"]) != exp["orders"]:
        bad.append(f"orders page {page['orders']} vs SQL {exp['orders']:,}")
    if whole(page["stock"]) != exp["stock"]:
        bad.append(f"stock page {page['stock']} vs SQL {exp['stock']:,}")
    if not page["stockCap"].endswith(exp["stock_label"]):
        bad.append(f"stock month '{page['stockCap']}' vs SQL {exp['stock_label']}")
    pm = {k: cents(v) for k, v in page["months"]}
    for k, v in exp["months"].items():
        if pm.get(k) != v:
            bad.append(f"month {k}: page {eur(pm[k]) if k in pm else 'missing'} vs SQL {eur(v)}")
    pc = [(k, cents(v)) for k, v in page["countries"]]
    if pc != exp["countries"]:
        bad.append(f"countries page {pc} vs SQL {exp['countries']}")
    pt = [(k, cents(v)) for k, v in page["top"]]
    if pt != exp["top"]:
        first = next((i for i, (a, b) in enumerate(zip(pt, exp["top"])) if a != b), min(len(pt), len(exp["top"])))
        bad.append(f"top 10 differs at #{first + 1}: page {pt[first:first + 1]} vs SQL {exp['top'][first:first + 1]}")
    m = re.match(r"([\d,]+) products, (\d+) ran out \(stock 0 at end of (.+?)\) · (\d+) were at 0", page["table"])
    if not m:
        bad.append(f"table line not readable: '{page['table']}'")
    else:
        got = (whole(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4)))
        want = (exp["products"], exp["ran_out"], exp["stock_label"], exp["hit_zero"])
        if got != want:
            bad.append(f"table line page {got} vs SQL {want} (products, ran out, month, at 0 in some month)")
    return bad


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    page_path = Path(args.html)
    results = []                       # (id, name, ok, detail)

    def add(cid, name, ok, detail=""):
        results.append((cid, name, bool(ok), detail))

    # H: the file
    exists = page_path.exists() and page_path.stat().st_size > 0
    add("H01", "Dashboard file exists", exists,
        f"{page_path} ({page_path.stat().st_size / 1024 / 1024:.2f} MB)" if exists else f"{page_path} missing or empty")
    if not exists:
        return finish(args, results, None)
    text = page_path.read_text(encoding="utf-8")
    external = re.findall(r"https?://[^\s\"'<>)]{0,60}|<link\b[^>]*>|<script[^>]*\bsrc=|@import", text)
    add("H02", "Self-contained (no internet links, no external scripts/styles)", not external,
        "none found" if not external else f"found: {external[:3]}")
    add("H03", "No test hook left in the page", "#test" not in text, "none" if "#test" not in text else "'#test' found")
    newest = max((Path(args.mart) / f"{t}.csv").stat().st_mtime for t in TABLES)
    add("H04", "Built from the current mart (page newer than every mart CSV)", page_path.stat().st_mtime >= newest,
        "ok" if page_path.stat().st_mtime >= newest else "the mart changed after the page was built: rebuild with dashboard.py")

    # Road B and the states
    db = load_db(args.mart)
    m = Model(db)
    states, pair = pick_states(m, db)
    exps = {sid: m.expected(st) for sid, _, st in states}
    sm = m.sales_months
    lab = {x["ym"]: x for x in m.months}
    yr = sm[-1][:4]
    periods = [{"labels": [], "want": m.period}]
    if len(sm) >= 7 and sm[2][:4] == sm[6][:4] == yr:
        periods.append({"labels": [lab[sm[2]]["label"], lab[sm[6]]["label"]],
                        "want": f"{lab[sm[2]]['short']}, {lab[sm[6]]['short']} {yr}"})
    if len(sm) >= 3 and sm[-3][:4] == yr:
        periods.append({"labels": [lab[x]["label"] for x in sm[-3:]],
                        "want": f"{lab[sm[-3]]['short']}–{lab[sm[-1]]['short']} {yr}"})
    busy = to_page_labels(m, states[2][2])                     # top country + top channel ...
    busy["month"] = [lab[sm[-1]]["label"]]                     # ... + a month + a category
    busy["cat"] = [m.cats[0]]
    spec = {"states": [{"id": sid, "labels": to_page_labels(m, st)} for sid, _, st in states],
            "busy": busy, "periods": periods}

    # Road A
    page = run_page(text, spec, find_browser(args.browser))
    if page.get("fatal"):
        add("I00", "Test driver ran through", False, page["fatal"][:300])

    # P: numbers
    for sid, name, st in states:
        got = page["states"].get(sid)
        bad = ["state not reached"] if got is None else compare_state(got, exps[sid])
        detail = "; ".join(bad[:4]) if bad else (
            f"revenue {eur(exps[sid]['rev'])} · orders {exps[sid]['orders']:,} · stock {exps[sid]['stock']:,} "
            f"({exps[sid]['stock_label']}) · 12 months, {len(exps[sid]['countries'])} countries, top 10, table line")
        if sid == "P06" and pair and not bad:
            a = m.expected({"cat": [pair[0][0]]})["orders"]
            b = m.expected({"cat": [pair[0][1]]})["orders"]
            detail += f" · orders {exps[sid]['orders']:,} = union, not the sum {a + b:,}"
        add(sid, name, not bad, detail)

    # I: behaviour
    i = page.get("i", {})
    i01 = i.get("i01", [])
    bad01 = [r[0] for r in i01 if r[1] == "All data" or r[2] != "All data"]
    add("I01", "Click a bar twice at the same spot: filters, then clears", i01 and not bad01,
        f"{len(i01)} bars tested" if i01 and not bad01 else f"failed for: {bad01 or 'nothing tested'}")
    moved = i.get("i02")
    add("I02", "Nothing moves or resizes when filters change", moved == [],
        "all panels identical" if moved == [] else f"layout changed: {moved}")
    i03 = i.get("i03", {})
    ok03 = all(i03.get(k) for k in ("enabledAfterSort", "changed", "disabledAfterClear", "backToDefault"))
    add("I03", "Sort the table, then Clear all: default order back", ok03, "ok" if ok03 else json.dumps(i03))
    p3 = page["states"].get("P03", {})
    ok04 = (p3 and whole(p3.get("stock")) == exps["P01"]["stock"] and p3.get("notes") == ["visible", "visible"]
            and page["states"].get("P01", {}).get("notes") == ["hidden", "hidden"])
    add("I04", "Stock ignores country/channel, and both notes say so", ok04,
        "stock unchanged under P03, notes shown only when country/channel filtered" if ok04 else
        f"P03 stock {p3.get('stock')} notes {p3.get('notes')}")
    i05 = i.get("i05", [])
    bad05 = [r for r in i05 if r[1] != r[2]]
    add("I05", "Header period follows the month filter", i05 and not bad05,
        " · ".join(f"{r[0]} -> '{r[1]}'" for r in i05) if i05 and not bad05 else f"wrong: {bad05}")
    errs = page.get("errors", [])
    add("I06", "No script errors on the page", not errs, "none" if not errs else "; ".join(errs[:3]))

    return finish(args, results, exps.get("P01"))


def finish(args, results, default):
    fails = [r for r in results if not r[2]]
    verdict = "PASS - dashboard OK" if not fails else f"FAIL - {len(fails)} checks failed"
    lines = [f"# Dashboard checks - run {args.run}", "",
             f"Script: `.claude/skills/html-dashboard/check.py` · Page: `{args.html}` · Road B: SQL on `{args.mart}`", "",
             f"**{verdict}**", ""]
    if default:
        lines += ["Headline numbers (page = SQL):",
                  f"- Total revenue {eur(default['rev'])}",
                  f"- Orders {default['orders']:,}",
                  f"- Stock on hand {default['stock']:,} units ({default['stock_label']})",
                  f"- {default['ran_out']} products ran out (stock 0 at end of {default['stock_label']})", ""]
    lines += ["| ID | Check | Result | Detail |", "|---|---|---|---|"]
    lines += [f"| {cid} | {name} | {'PASS' if ok else '**FAIL**'} | {detail.replace('|', '/')} |" for cid, name, ok, detail in results]
    out = Path("runs") / args.run / "5-html-dashboard" / "html-dashboard-checks.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for cid, name, ok, detail in results:
        print(f"{cid}  {'PASS' if ok else 'FAIL'}  {name}")
    print(verdict.replace("–", "-"))
    print(f"Report: {out}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
