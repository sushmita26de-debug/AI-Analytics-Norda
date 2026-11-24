"""
NORDA Power BI checks
=====================

Opens the Power BI project (reports/powerbi/NORDA Sales.pbip) in Power BI Desktop, refreshes it from
data/mart/ through its own local engine, and compares every measure with SQL on data/mart/ (the same
second road as the HTML dashboard check). Captures the Power BI window as evidence.

    python .claude/skills/powerbi/check.py --run 2026-09

Writes runs/<run>/7-powerbi/powerbi-checks.md and powerbi.png. Any FAIL -> exit code 1.
Safety: refuses to start if any Power BI Desktop is already open (so it never touches the user's work),
and closes only the Power BI it started. It never saves the project: the user opens it and clicks Refresh.

Checks
  B01-B04  the project: data paths point to this mart, model loads with no measure errors, refresh works,
           row counts = the mart CSVs
  P01-P07  measures vs SQL for the dashboard's filter states (KPIs, 12+ months, countries, top 10,
           ran out, at 0, stock note, period text)
  D01-D10  display measures (top 10, months at 0, summary text, caption, colours) vs SQL
  S01      screenshot of the Power BI window
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
HI, CALM = "#F0A73A", "#5F87B4"
NOTE = "Not filtered by country/channel – stock has no country/channel"
COLS = {"month": "dim_date[year_month]", "cat": "dim_product[category]", "country": "dim_country[country_code]",
        "channel": "dim_channel[channel]"}
TABLES = ["dim_date", "dim_product", "dim_country", "dim_channel", "fact_sales", "fact_inventory"]


def parse_args():
    ap = argparse.ArgumentParser(description="Check the Power BI project against data/mart.")
    ap.add_argument("--run", required=True, help="run month, e.g. 2026-09")
    ap.add_argument("--pbip", default="reports/powerbi/NORDA Sales.pbip")
    ap.add_argument("--mart", default="data/mart")
    return ap.parse_args()


def load_dashboard_model():
    """Road B: the SQL model of the mart used by the HTML dashboard check (same definitions)."""
    p = HERE.parent / "html-dashboard" / "check.py"
    spec = importlib.util.spec_from_file_location("dash_check", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ps(*args):
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "pbi.ps1"), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "").strip()


def filters(st, skip=None):
    out = []
    for k, col in COLS.items():
        if k != skip and st.get(k):
            out.append("TREATAS ( { " + ", ".join(f'"{v}"' for v in st[k]) + f" }}, {col} )")
    return out


def cents(v):
    return int((Decimal(str(v)) * 100).to_integral_value()) if v is not None else 0


def val(row, key):
    return next((v for k, v in row.items() if k.strip("[]").split("[")[-1].strip("]") == key or k.endswith(f"[{key}]")), None)


def main():
    args = parse_args()
    pbip, mart = Path(args.pbip).resolve(), Path(args.mart).resolve()
    out_dir = Path("runs") / args.run / "7-powerbi"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []

    def add(cid, name, ok, detail=""):
        res.append((cid, name, bool(ok), str(detail)))

    # B01: every table reads its CSV from this mart (absolute paths in Power Query)
    tdir = pbip.parent / (pbip.stem + ".SemanticModel") / "definition" / "tables"
    wrong = []
    for t in TABLES:
        text = (tdir / f"{t}.tmdl").read_text(encoding="utf-8")
        m = re.search(r'File\.Contents\("([^"]+)"\)', text)
        if not m or Path(m.group(1)).resolve() != mart / f"{t}.csv":
            wrong.append(f"{t}: {m.group(1) if m else 'no path'}")
    add("B01", "Every table reads its CSV from this mart", not wrong, f"{mart}" if not wrong else "; ".join(wrong))

    code, out = ps("-Action", "open", "-Pbip", str(pbip))
    if code == 2:
        print("STOPPED: Power BI Desktop is already open. Close it (save your work first) and run again.")
        return 2
    info = json.loads(out.splitlines()[-1]) if out else {"error": "no output"}
    if "error" in info:
        add("B02", "Model loads", False, info["error"])
        ps("-Action", "close", "-ProcId", str(info.get("pid", 0)), "-EngineId", str(info.get("engine", 0)))
        return finish(args, res, out_dir)
    pid, engine, port = info["pid"], info["engine"], info["port"]
    tmp = Path(tempfile.mkdtemp(prefix="norda-pbi-"))
    try:
        def query(items):
            (tmp / "in.json").write_text(json.dumps(items), encoding="utf-8")
            ps("-Action", "query", "-Port", str(port), "-InFile", str(tmp / "in.json"), "-OutFile", str(tmp / "out.json"))
            return {r["id"]: r for r in json.loads((tmp / "out.json").read_text(encoding="utf-8-sig"))["results"]}

        R = query([{"id": "measures", "kind": "dmv", "text": "SELECT [Name], [State], [ErrorMessage] FROM $SYSTEM.TMSCHEMA_MEASURES"},
                   {"id": "refresh", "kind": "tmsl", "text": '{"refresh":{"type":"full","objects":[{"database":"__DB__"}]}}'},
                   {"id": "rows", "kind": "dax", "text": "EVALUATE { " + ", ".join(f'("{t}", COUNTROWS({t}))' for t in TABLES) + " }"}])
        bad = [f"{val(r, 'Name')}: {val(r, 'ErrorMessage')}" for r in R["measures"]["rows"] if str(val(r, "State")) != "1"]
        add("B02", "Model loads, no measure errors", R["measures"]["ok"] and not bad,
            f"{len(R['measures']['rows'])} measures" if not bad else "; ".join(bad)[:300])
        add("B03", "Refresh from data/mart works", R["refresh"]["ok"], "ok" if R["refresh"]["ok"] else (R["refresh"]["error"] or "")[:300])
        got_rows = {list(r.values())[0]: int(list(r.values())[1]) for r in R["rows"]["rows"]} if R["rows"]["ok"] else {}
        csv_rows = {t: sum(1 for _ in open(mart / f"{t}.csv", encoding="utf-8")) - 1 for t in TABLES}
        add("B04", "Row counts = the mart CSVs", got_rows == csv_rows,
            " · ".join(f"{t} {csv_rows[t]:,}" for t in TABLES) if got_rows == csv_rows else f"model {got_rows} vs csv {csv_rows}")

        # P: measures vs SQL for the dashboard's filter states
        dc = load_dashboard_model()
        db = dc.load_db(str(mart))
        m = dc.Model(db)
        states, _ = dc.pick_states(m, db)
        sm = m.sales_months
        if len(sm) >= 7:
            states.append(("P07", f"Months {sm[2]} + {sm[6]} (period text)", {"month": [sm[2], sm[6]]}))
        lab = {x["ym"]: x for x in m.months}
        items = []
        for sid, _, st in states:
            f = filters(st)
            row = ('ROW ( "rev", [Total Revenue], "ord", [Orders], "stock", [Stock on Hand], "smonth", [Stock Month], '
                   '"ranout", [Products Ran Out], "hit0", [Products at 0 in Selection], "note", [Stock Note], "period", [Selected Period] )')
            items.append({"id": f"{sid}-kpi", "kind": "dax", "text": "EVALUATE CALCULATETABLE ( " + ", ".join([row] + f) + " )"})
            items.append({"id": f"{sid}-months", "kind": "dax", "text": "EVALUATE SUMMARIZECOLUMNS ( dim_date[year_month], "
                          + ", ".join(filters(st, "month") + ['"rev", [Total Revenue]']) + " )"})
            items.append({"id": f"{sid}-countries", "kind": "dax", "text": "EVALUATE SUMMARIZECOLUMNS ( dim_country[country_name], "
                          + ", ".join(filters(st, "country") + ['"rev", [Total Revenue]']) + " )"})
            items.append({"id": f"{sid}-top", "kind": "dax", "text": "EVALUATE TOPN ( 10, SUMMARIZECOLUMNS ( dim_product[product_name], "
                          + ", ".join(f + ['"rev", [Total Revenue]']) + " ), [rev], DESC ) ORDER BY [rev] DESC"})
        Q = query(items)
        for sid, name, st in states:
            e = m.expected(st)
            errs = [f"{q}: {Q[f'{sid}-{q}']['error'][:120]}" for q in ("kpi", "months", "countries", "top") if not Q[f"{sid}-{q}"]["ok"]]
            if errs:
                add(sid, name, False, "; ".join(errs))
                continue
            k = Q[f"{sid}-kpi"]["rows"][0]
            bad = []
            if cents(val(k, "rev")) != e["rev"]: bad.append(f"revenue {val(k, 'rev')} vs {e['rev'] / 100}")
            if int(val(k, "ord") or 0) != e["orders"]: bad.append(f"orders {val(k, 'ord')} vs {e['orders']}")
            if int(val(k, "stock") or 0) != e["stock"]: bad.append(f"stock {val(k, 'stock')} vs {e['stock']}")
            if val(k, "smonth") != e["stock_label"]: bad.append(f"stock month {val(k, 'smonth')} vs {e['stock_label']}")
            if int(val(k, "ranout")) != e["ran_out"]: bad.append(f"ran out {val(k, 'ranout')} vs {e['ran_out']}")
            if int(val(k, "hit0")) != e["hit_zero"]: bad.append(f"at 0 {val(k, 'hit0')} vs {e['hit_zero']}")
            want_note = NOTE if (st.get("country") or st.get("channel")) else ""
            if (val(k, "note") or "") != want_note: bad.append(f"stock note {val(k, 'note')!r}")
            if st.get("month"):
                ms = sorted(st["month"])
                one_year = len({x[:4] for x in ms}) == 1
                want_p = (", ".join(lab[x]["short"] for x in ms) + " " + ms[0][:4]) if one_year else ", ".join(lab[x]["label"] for x in ms)
            else:
                want_p = m.period
            if val(k, "period") != want_p: bad.append(f"period {val(k, 'period')!r} vs {want_p!r}")
            ym_long = {x["ym"]: x["long"] for x in m.months}
            pm = {ym_long.get(val(r, "year_month")): cents(val(r, "rev")) for r in Q[f"{sid}-months"]["rows"]}
            bad += [f"month {mo}" for mo, v in e["months"].items() if pm.get(mo, 0) != v]
            pc = {val(r, "country_name"): cents(val(r, "rev")) for r in Q[f"{sid}-countries"]["rows"]}
            bad += [f"country {c}" for c, v in e["countries"] if pc.get(c, 0) != v]
            pt = [(val(r, "product_name"), cents(val(r, "rev"))) for r in Q[f"{sid}-top"]["rows"]]
            if pt != e["top"]: bad.append("top 10 differs")
            add(sid, name, not bad, "; ".join(bad[:4]) if bad else
                f"revenue {val(k, 'rev')} · orders {val(k, 'ord')} · stock {val(k, 'stock')} ({val(k, 'smonth')}) · "
                f"ran out {val(k, 'ranout')} · period '{val(k, 'period')}' · {len(e['months'])} months, countries, top 10")

        # D: display measures, no filter (and Accessories for two of them)
        e0, ea = m.expected({}), m.expected({"cat": [m.cats[0]]})
        D = query([
            {"id": "top10", "kind": "dax", "text": 'EVALUATE FILTER ( SUMMARIZECOLUMNS ( dim_product[product_name], "v", [Top 10 Revenue] ), NOT ISBLANK ( [v] ) )'},
            {"id": "top10_c", "kind": "dax", "text": f'EVALUATE FILTER ( SUMMARIZECOLUMNS ( dim_product[product_name], TREATAS ( {{ "{m.cats[0]}" }}, dim_product[category] ), "v", [Top 10 Revenue] ), NOT ISBLANK ( [v] ) )'},
            {"id": "m0", "kind": "dax", "text": 'EVALUATE SUMMARIZECOLUMNS ( dim_product[sku], "m0", [Months at 0] )'},
            {"id": "kpis", "kind": "dax", "text": 'EVALUATE ROW ( "products", [Products in Selection], "summary", [Table Summary], "caption", [Stock Caption] )'},
            {"id": "c_month", "kind": "dax", "text": 'EVALUATE SUMMARIZECOLUMNS ( dim_date[month_label], dim_date[year_month], "c", [Colour Month] )'},
            {"id": "c_country", "kind": "dax", "text": 'EVALUATE SUMMARIZECOLUMNS ( dim_country[country_name], "c", [Colour Country] )'},
            {"id": "c_product", "kind": "dax", "text": 'EVALUATE FILTER ( SUMMARIZECOLUMNS ( dim_product[product_name], "c", [Colour Product], "v", [Top 10 Revenue] ), NOT ISBLANK ( [v] ) )'},
            {"id": "c_stock", "kind": "dax", "text": 'EVALUATE SUMMARIZECOLUMNS ( dim_product[sku], "c", [Colour Stock] )'},
        ])
        for kq, r in D.items():
            if not r["ok"]:
                add("D00", f"display query {kq}", False, r["error"][:200])
        if all(r["ok"] for r in D.values()):
            got = sorted(((val(r, "product_name"), cents(val(r, "v"))) for r in D["top10"]["rows"]), key=lambda t: -t[1])
            add("D01", "Top 10 Revenue: same 10 products and values", got == e0["top"], f"#1 {got[0][0]}" if got else "")
            got = sorted(((val(r, "product_name"), cents(val(r, "v"))) for r in D["top10_c"]["rows"]), key=lambda t: -t[1])
            add("D02", f"Top 10 Revenue, {m.cats[0]}", got == ea["top"])
            sql_m0 = dict(db.execute("SELECT sku, COUNT(*) FROM fact_inventory WHERE CAST(qty_on_hand AS INTEGER) = 0 GROUP BY sku").fetchall())
            got = {val(r, "sku"): int(val(r, "m0")) for r in D["m0"]["rows"] if val(r, "m0") is not None}
            add("D03", "Months at 0 per product", got == sql_m0, f"{len(sql_m0)} products with a month at 0")
            k = D["kpis"]["rows"][0]
            want = (f"{e0['products']} products, {e0['ran_out']} ran out (stock 0 at end of {e0['stock_label']}) · "
                    f"{e0['hit_zero']} were at 0 in at least one month")
            add("D04", "Products in Selection", int(val(k, "products")) == e0["products"], val(k, "products"))
            add("D05", "Table Summary text", val(k, "summary") == want, val(k, "summary"))
            add("D06", "Stock Caption text", val(k, "caption") == f"units at month end, {e0['stock_label']}", val(k, "caption"))
            top_ym = max((x for x in m.months), key=lambda x: e0["months"].get(x["long"], 0))
            amb = [val(r, "month_label") for r in D["c_month"]["rows"] if val(r, "c") == HI]
            add("D07", f"Colour Month: amber only on {top_ym['label']}", amb == [top_ym["label"]], amb)
            amb = [val(r, "country_name") for r in D["c_country"]["rows"] if val(r, "c") == HI]
            add("D08", f"Colour Country: amber only on {e0['countries'][0][0]}", amb == [e0["countries"][0][0]], amb)
            amb = [val(r, "product_name") for r in D["c_product"]["rows"] if val(r, "c") == HI]
            add("D09", f"Colour Product: amber only on {e0['top'][0][0]}", amb == [e0["top"][0][0]], amb)
            latest = max(r[0] for r in db.execute("SELECT DISTINCT substr(date_key, 1, 6) FROM fact_inventory"))
            sql_out = {r[0] for r in db.execute(f"SELECT sku FROM fact_inventory WHERE substr(date_key,1,6) = '{latest}' AND CAST(qty_on_hand AS INTEGER) = 0")}
            amb = {val(r, "sku") for r in D["c_stock"]["rows"] if val(r, "c") == HI}
            add("D10", f"Colour Stock: amber on exactly the {len(sql_out)} products that ran out", amb == sql_out)

        code, out = ps("-Action", "shot", "-ProcId", str(pid), "-Shot", str((out_dir / "powerbi.png").resolve()))
        add("S01", "Screenshot of the Power BI window", code == 0, (out_dir / "powerbi.png").as_posix() if code == 0 else out)
    finally:
        ps("-Action", "close", "-ProcId", str(pid), "-EngineId", str(engine))
        for f in tmp.glob("*"):
            f.unlink()
        tmp.rmdir()
    return finish(args, res, out_dir)


def finish(args, res, out_dir):
    fails = [r for r in res if not r[2]]
    verdict = "PASS - Power BI OK" if not fails else f"FAIL - {len(fails)} checks failed"
    lines = [f"# Power BI checks - run {args.run}", "",
             f"Script: `.claude/skills/powerbi/check.py` · Project: `{args.pbip}` · Road B: SQL on `{args.mart}`", "",
             f"**{verdict}**", "", "| ID | Check | Result | Detail |", "|---|---|---|---|"]
    lines += [f"| {c} | {n} | {'PASS' if ok else '**FAIL**'} | {d.replace('|', '/')} |" for c, n, ok, d in res]
    (out_dir / "powerbi-checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for c, n, ok, _ in res:
        print(f"{c}  {'PASS' if ok else 'FAIL'}  {n.encode('ascii', 'replace').decode()}")
    print(verdict)
    print(f"Report: {out_dir / 'powerbi-checks.md'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
