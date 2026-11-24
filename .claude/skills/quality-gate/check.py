"""
Quality gate for the NORDA data project: one section per rule in knowledge/quality-rules.md.

  Rule 1  Code computes, Claude understands  -> process rule: this script computes and writes
                                                 every number in the report (not machine-checkable)
  Rule 2  Two roads, one number              -> G01-G10: every dashboard number computed twice
                                                 Road A = SQL on data/mart (what Power BI sees)
                                                 Road B = pandas straight from every delivery in
                                                          data/raw/<month>/, cleaning decisions and the
                                                          monthly-delivery rules re-applied independently
                                                          (orders + stock appended, newest price per product)
  Rule 3  Trace orders                       -> T01-T10: 10 random orders of this run's delivery
                                                 followed raw -> clean -> model
  Rule 4  What must always be true           -> Q01-Q04

Every check is PASS or FAIL. Any FAIL -> exit code 1. Read-only on all data.

Run from the project root:
    python .claude/skills/quality-gate/check.py --run 2026-08
    python .claude/skills/quality-gate/check.py --run 2026-08 --seed 12345   (replay a previous trace sample)
Writes runs/<run>/4-quality-gate/quality-gate-checks.md
"""
import sys

sys.dont_write_bytecode = True

import argparse
import json
import random
import re
import sqlite3
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

CENT = Decimal("0.01")
results = []    # one dict per check


def check(rule, cid, name, failed, detail=""):
    results.append({"rule": rule, "id": cid, "name": name, "status": "FAIL" if failed else "PASS",
                    "failed": int(failed), "detail": detail})


def load_rules():
    """Business lists shared by all scripts: knowledge/rules.json (found by walking up from here)."""
    for folder in Path(__file__).resolve().parents:
        f = folder / "knowledge" / "rules.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    raise FileNotFoundError("knowledge/rules.json not found")


def read_text(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def to_cents(value):
    """Decimal euros -> whole cents (int), so both roads compare exactly."""
    return int((value * 100).to_integral_value())


def eur(cents):
    return f"€{Decimal(cents) / 100:,.2f}"


def line_cents(q, p, d):
    """metrics.md, exact decimal maths, rounded half-up to the cent: (revenue, discount amount) in cents."""
    gross = Decimal(q) * Decimal(p)
    rev = (gross * (1 - Decimal(d))).quantize(CENT, ROUND_HALF_UP)
    disc = (gross * Decimal(d)).quantize(CENT, ROUND_HALF_UP)
    return to_cents(rev), to_cents(disc)


# ===========================================================================
# Road B: straight from raw, cleaning decisions re-applied independently
# ===========================================================================
def deliveries(raw_root):
    """Every delivery folder data/raw/<YYYY-MM>/ with the 3 files, oldest first."""
    return sorted((d for d in raw_root.iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}", d.name)
                   and all((d / f"{n}.csv").exists() for n in ("orders", "products", "inventory"))),
                  key=lambda d: d.name)


def road_b(folders, rules):
    # Orders: per delivery, identical rows -> keep one (decision); then every delivery appended
    parts = []
    for d in folders:
        raw = read_text(d / "orders.csv")
        parts.append(raw[~raw.duplicated(keep="first")])
    o = pd.concat(parts, ignore_index=True).apply(lambda c: c.str.strip())

    iso = o["CRTD_DT"].str.match(r"^\d{4}-\d{2}-\d{2}$")
    dates = pd.to_datetime(o["CRTD_DT"].where(iso), format="%Y-%m-%d", errors="coerce")
    dates = dates.fillna(pd.to_datetime(o["CRTD_DT"].where(~iso), format="%d/%m/%Y", errors="coerce"))  # DD/MM

    name_to_code = {name: code for code, name in rules["country_names"].items()}
    money = [line_cents(q, p, d) for q, p, d in zip(o["QTY"], o["UNIT_PRC"], o["DISC_PCT"])]
    lines = pd.DataFrame({
        "order": o["ORD_NO"], "month": dates.dt.strftime("%Y-%m"), "country": o["CTRY"].replace(name_to_code),
        "sku": o["ART_NO"], "qty": o["QTY"].astype(int),
        "rev": [m[0] for m in money], "disc": [m[1] for m in money],
    })

    inv = pd.concat([read_text(d / "inventory.csv") for d in folders], ignore_index=True).apply(lambda c: c.str.strip())
    inv["month"] = pd.PeriodIndex(inv["stk_month"], freq="M").strftime("%Y-%m")   # 2025-4 -> 2025-04
    inv["qty"] = inv["qty_hand"].astype(int)
    latest = inv["month"].max()
    stock = inv[inv["month"] == latest].groupby("art_no")["qty"].sum()

    # Products: new skus added, existing skus get the newest delivery's price
    newest = {}
    for d in folders:
        for sku, price in zip(read_text(d / "products.csv")["sku"].str.strip(), read_text(d / "products.csv")["list_price"].str.strip()):
            newest[sku] = to_cents(Decimal(price))
    skus = pd.Series(sorted(newest))
    by_sku = lines.groupby("sku").agg(units=("qty", "sum"), rev=("rev", "sum"))
    per_product = {s: (int(by_sku["units"].get(s, 0)), int(by_sku["rev"].get(s, 0)), int(stock.get(s, 0)))
                   for s in skus}
    top = by_sku.reset_index().sort_values(["rev", "sku"], ascending=[False, True]).head(10)

    return {
        "unparsed_dates": int(dates.isna().sum()),
        "total_revenue": int(lines["rev"].sum()),
        "orders": int(lines["order"].nunique()),
        "stock_month": latest,
        "stock": int(stock.sum()),
        "per_month": {k: int(v) for k, v in lines.groupby("month")["rev"].sum().items()},
        "per_country": {k: int(v) for k, v in lines.groupby("country")["rev"].sum().items()},
        "top10": [(s, int(r)) for s, r in zip(top["sku"], top["rev"])],
        "per_product": per_product,
        "units": int(lines["qty"].sum()),
        "discount": int(lines["disc"].sum()),
        "prices": newest,
    }


# ===========================================================================
# Road A: SQL on the model (what Power BI sees)
# ===========================================================================
def road_a(model_dir):
    con = sqlite3.connect(":memory:")
    for t in ["fact_sales", "fact_inventory", "dim_date", "dim_product", "dim_country"]:
        pd.read_csv(model_dir / f"{t}.csv", dtype={"sku": str, "order_id": str}).to_sql(t, con, index=False)
    q = lambda sql: con.execute(sql).fetchall()
    cents = "SUM(CAST(ROUND(f.revenue * 100) AS INTEGER))"          # exact cents, no float drift
    latest = "(SELECT MAX(date_key) FROM fact_inventory)"

    per_product = {s: (u, r, st) for s, u, r, st in q(f"""
        SELECT p.sku, COALESCE(s.units, 0), COALESCE(s.rev, 0), COALESCE(i.stock, 0)
        FROM dim_product p
        LEFT JOIN (SELECT f.sku, SUM(f.quantity) AS units, {cents} AS rev FROM fact_sales f GROUP BY f.sku) s
               ON s.sku = p.sku
        LEFT JOIN (SELECT sku, SUM(qty_on_hand) AS stock FROM fact_inventory
                   WHERE date_key = {latest} GROUP BY sku) i
               ON i.sku = p.sku""")}
    stock_key = q(f"SELECT {latest}")[0][0]
    a = {
        "total_revenue": q(f"SELECT {cents} FROM fact_sales f")[0][0],
        "orders": q("SELECT COUNT(DISTINCT order_id) FROM fact_sales")[0][0],
        "stock_month": f"{str(stock_key)[:4]}-{str(stock_key)[4:6]}",
        "stock": q(f"SELECT SUM(qty_on_hand) FROM fact_inventory WHERE date_key = {latest}")[0][0],
        "per_month": dict(q(f"""SELECT d.year_month, {cents} FROM fact_sales f
                               JOIN dim_date d ON d.date_key = f.date_key GROUP BY d.year_month""")),
        "per_country": dict(q(f"""SELECT c.country_code, {cents} FROM fact_sales f
                                 JOIN dim_country c ON c.country_code = f.country_code GROUP BY c.country_code""")),
        "top10": q(f"SELECT f.sku, {cents} AS rev FROM fact_sales f GROUP BY f.sku ORDER BY rev DESC, f.sku LIMIT 10"),
        "per_product": per_product,
        "units": q("SELECT SUM(quantity) FROM fact_sales")[0][0],
        "discount": q("SELECT SUM(CAST(ROUND(discount_amount * 100) AS INTEGER)) FROM fact_sales")[0][0],
        "negative_lines": q("SELECT COUNT(*) FROM fact_sales WHERE revenue < 0")[0][0],
        "prices": dict(q("SELECT sku, CAST(ROUND(latest_list_price * 100) AS INTEGER) FROM dim_product")),
    }
    con.close()
    return a


# ===========================================================================
# Rule 2: two roads, one number
# ===========================================================================
def rule_2(a, b):
    rows = []   # for the report table

    def same(cid, name, va, vb, show):
        ok = va == vb
        check(2, cid, name, 0 if ok else 1, "" if ok else f"A={show(va)} B={show(vb)}")
        rows.append((name, show(va), show(vb), "PASS" if ok else "FAIL"))

    def same_map(cid, name, ma, mb, label):
        keys = sorted(set(ma) | set(mb))
        bad = [k for k in keys if ma.get(k) != mb.get(k)]
        check(2, cid, name, len(bad), f"differ: {bad[:5]}" if bad else f"{len(keys)} {label} compared")
        rows.append((name, f"{len(keys) - len(bad)}/{len(keys)} {label} equal", "", "PASS" if not bad else "FAIL"))

    check(2, "G00", "Road B could read every raw date", b["unparsed_dates"])
    same("G01", "Total revenue", a["total_revenue"], b["total_revenue"], eur)
    same("G02", "Number of orders", a["orders"], b["orders"], lambda v: f"{v:,}")
    same("G03", f"Stock on hand, latest month ({a['stock_month']})", (a["stock_month"], a["stock"]),
         (b["stock_month"], b["stock"]), lambda v: f"{v[1]:,} units ({v[0]})")
    same_map("G04", "Sales per month", a["per_month"], b["per_month"], "months")
    same_map("G05", "Sales per country", a["per_country"], b["per_country"], "countries")
    same("G06", "Best-selling products (top 10 by revenue)", [tuple(t) for t in a["top10"]],
         [tuple(t) for t in b["top10"]], lambda v: f"{len(v)} products, #1 {v[0][0]} {eur(v[0][1])}" if v else "none")
    same_map("G07", "Stock and sales per product (units, revenue, stock)", a["per_product"], b["per_product"], "products")
    same("G08", "Units sold", a["units"], b["units"], lambda v: f"{v:,}")
    same("G09", "Discount amount", a["discount"], b["discount"], eur)
    same_map("G10", "Product prices (newest delivery per product)", a["prices"], b["prices"], "products")
    return rows


# ===========================================================================
# Rule 3: trace 10 random orders raw -> clean -> model
# ===========================================================================
def rule_3(raw_dir, clean_dir, model_dir, rules, seed):
    raw = read_text(raw_dir / "orders.csv")
    raw_copy = raw.duplicated(keep="first")
    raw = raw.apply(lambda c: c.str.strip())
    clean = read_text(clean_dir / "orders.csv")
    model = read_text(model_dir / "fact_sales.csv")
    name_to_code = {name: code for code, name in rules["country_names"].items()}

    ids = sorted(raw["ORD_NO"].unique())
    sample = random.Random(seed).sample(ids, 10)
    tables = []

    for n, oid in enumerate(sample, start=1):
        r_all = raw[raw["ORD_NO"] == oid]
        r = r_all[~raw_copy[r_all.index]]
        c = clean[clean["order_id"] == oid]
        m = model[model["order_id"] == oid]
        problems = []

        # Lines: raw minus identical copies = clean = model, same sku / qty / price / discount
        if not (len(r) == len(c) == len(m)):
            problems.append(f"lines raw {len(r)} / clean {len(c)} / model {len(m)}")
        key_r = sorted((s, int(q), f"{Decimal(p):.2f}", f"{Decimal(d):.2f}")
                       for s, q, p, d in zip(r["ART_NO"], r["QTY"], r["UNIT_PRC"], r["DISC_PCT"]))
        key_c = sorted(zip(c["sku"], c["quantity"].astype(int), c["unit_price"], c["discount_rate"]))
        key_m = sorted(zip(m["sku"], m["quantity"].astype(int), m["unit_price"], m["discount_rate"]))
        if not (key_r == key_c == key_m):
            problems.append("line values differ")

        # Date: raw read as DD/MM -> clean ISO -> model yyyymmdd
        raw_d = {datetime.strptime(v, "%Y-%m-%d" if "-" in v else "%d/%m/%Y").strftime("%Y-%m-%d") for v in r["CRTD_DT"]}
        cln_d = set(c["order_date"])
        mdl_d = {f"{k[:4]}-{k[4:6]}-{k[6:]}" for k in m["date_key"]}
        if not (raw_d == cln_d == mdl_d):
            problems.append("date differs")

        raw_c = set(r["CTRY"].replace(name_to_code))
        if not (raw_c == set(c["country_code"]) == set(m["country_code"])):
            problems.append("country differs")
        raw_ch = set(r["CHNL"])
        if not (raw_ch == set(c["channel"]) == set(m["channel"])):
            problems.append("channel differs")
        exp_cust = {"" if ch == "marketplace" else cu for ch, cu in zip(r["CHNL"], r["CUST_REF"])}
        if exp_cust != set(c["customer_id"]):
            problems.append("customer_id differs")

        # Revenue: model per line = recalculated from raw
        rev_r = sorted((s, line_cents(q, p, d)[0]) for s, q, p, d in zip(r["ART_NO"], r["QTY"], r["UNIT_PRC"], r["DISC_PCT"]))
        rev_m = sorted((s, to_cents(Decimal(v))) for s, v in zip(m["sku"], m["revenue"]))
        if rev_r != rev_m:
            problems.append("revenue differs")

        check(3, f"T{n:02d}", f"Order {oid} traced raw -> clean -> model", len(problems), "; ".join(problems))
        n_copies = int(raw_copy[r_all.index].sum())
        tables.append({
            "order": oid, "status": "FAIL" if problems else "PASS", "problems": problems,
            "rows": [
                ("raw", f"{len(r_all)}" + (f" ({n_copies} identical cop{'y' if n_copies == 1 else 'ies'})" if n_copies else ""),
                 " / ".join(sorted(set(r_all["CRTD_DT"]))), " / ".join(sorted(set(r_all["CTRY"]))),
                 " / ".join(sorted(raw_ch)), " / ".join(sorted(set(r_all["CUST_REF"]))) or "(blank)",
                 eur(sum(v for _, v in rev_r)) + " (recalculated)"),
                ("clean", str(len(c)), " / ".join(sorted(cln_d)), " / ".join(sorted(set(c["country_code"]))),
                 " / ".join(sorted(set(c["channel"]))), " / ".join(sorted(set(c["customer_id"]))) or "(blank)", "-"),
                ("model", str(len(m)), " / ".join(sorted(set(m["date_key"]))), " / ".join(sorted(set(m["country_code"]))),
                 " / ".join(sorted(set(m["channel"]))), "(not in model)", eur(sum(v for _, v in rev_m))),
            ],
        })
    return tables


# ===========================================================================
# Rule 4: what must always be true
# ===========================================================================
def rule_4(a, folders):
    months = a["per_month"]
    if months:
        expected = [str(p) for p in pd.period_range(min(months), max(months), freq="M")]
        bad = [m for m in expected if months.get(m, 0) <= 0]
        check(4, "Q01", "Every month has sales", len(bad),
              f"missing/zero: {bad}" if bad else f"{len(expected)} months, {expected[0]} .. {expected[-1]}")
    else:
        check(4, "Q01", "Every month has sales", 1, "no sales at all")

    empty, checked = [], 0
    for folder in folders:
        for f in sorted(folder.glob("*.csv")):
            checked += 1
            if f.stat().st_size == 0 or len(read_text(f)) == 0:
                empty.append(str(f))
    check(4, "Q02", "No empty files", len(empty) + (0 if checked else 1),
          f"empty: {empty}" if empty else f"{checked} CSV files in {', '.join(str(x) for x in folders)}")

    check(4, "Q03", "No revenue is negative", a["negative_lines"], f"{a['negative_lines']} negative lines in fact_sales")

    y2025 = {m: v for m, v in months.items() if m.startswith("2025-")}
    if "2025-12" not in y2025:
        check(4, "Q04", "December is the biggest month of 2025 by revenue", 1, "no December 2025 in the data")
    else:
        dec = y2025["2025-12"]
        others = {m: v for m, v in y2025.items() if m != "2025-12"}
        runner = max(others, key=others.get) if others else None
        beaten = [m for m, v in others.items() if v >= dec]
        detail = (f"Dec {eur(dec)} vs runner-up {runner} {eur(others[runner])} (margin {eur(dec - others[runner])})"
                  if runner else f"Dec {eur(dec)}, no other month")
        check(4, "Q04", "December is the biggest month of 2025 by revenue", len(beaten),
              detail + (f"; not bigger than {beaten}" if beaten else ""))
    return {m: months[m] for m in sorted(months)}


# ===========================================================================
def write_report(path, run, seed, data_line, g_rows, traces, month_rev):
    fails = [r for r in results if r["status"] == "FAIL"]
    verdict = "PASS - all quality rules hold" if not fails else f"FAIL - {len(fails)} checks failed"
    by_rule = {k: [r for r in results if r["rule"] == k] for k in (2, 3, 4)}

    def summary(k):
        rs = by_rule[k]
        return f"{sum(r['status'] == 'PASS' for r in rs)}/{len(rs)} PASS"

    md = [f"# Quality gate - run {run}", "",
          f"Rules: `knowledge/quality-rules.md` · Script: `.claude/skills/quality-gate/check.py` · Run: {datetime.now():%Y-%m-%d %H:%M}",
          f"{data_line} · trace seed **{seed}**", "",
          f"**{verdict}**", "",
          "| Rule | Result |", "|---|---|",
          "| 1. Code computes, Claude understands | Process rule (not a data test): every number in this report was computed and written by this script |",
          f"| 2. Two roads, one number | {summary(2)} |",
          f"| 3. Trace orders | {summary(3)} |",
          f"| 4. What must always be true | {summary(4)} |", ""]

    md += ["## Rule 1 - Code computes, Claude understands", "",
           "This is a working rule, not a property of the data, so it can't be tested here. It is followed by design: "
           "this file is generated by `check.py`; no number in it was typed by hand.", ""]

    md += ["## Rule 2 - Two roads, one number", "",
           "Road A = SQL on `data/mart/` (what Power BI sees). Road B = pandas straight from every delivery in "
           "`data/raw/<month>/`, re-applying the cleaning decisions independently (identical rows removed, DD/MM dates, "
           "country names mapped), the delivery rules (orders and stock appended, newest price per product) "
           "and revenue per `knowledge/metrics.md`. Compared in whole cents.", "",
           "| Dashboard number | Road A (model) | Road B (raw) | Result |", "|---|---|---|---|"]
    md += [f"| {n} | {va} | {vb} | {'**FAIL**' if s == 'FAIL' else s} |" for n, va, vb, s in g_rows]
    md += ["", "| ID | Check | Result | Detail |", "|---|---|---|---|"]
    md += [f"| {r['id']} | {r['name']} | {'**FAIL**' if r['status'] == 'FAIL' else 'PASS'} | {r['detail']} |" for r in by_rule[2]]

    md += ["", "## Rule 3 - Trace orders", "",
           f"10 random orders of this run's delivery (seed {seed}; replay with `--seed {seed}`), "
           "followed raw -> clean -> model.", ""]
    for t in traces:
        md += [f"**{t['order']}: {t['status']}**" + (f" - {'; '.join(t['problems'])}" if t["problems"] else ""), "",
               "| Step | Lines | Date | Country | Channel | Customer | Revenue |", "|---|---|---|---|---|---|---|"]
        md += [f"| {' | '.join(row)} |" for row in t["rows"]] + [""]

    md += ["## Rule 4 - What must always be true", "",
           "| ID | Check | Result | Detail |", "|---|---|---|---|"]
    md += [f"| {r['id']} | {r['name']} | {'**FAIL**' if r['status'] == 'FAIL' else 'PASS'} | {r['detail']} |" for r in by_rule[4]]
    md += ["", "Revenue per month (Road A, model):", "", "| Month | Revenue |", "|---|---|"]
    md += [f"| {m} | {eur(v)} |" for m, v in month_rev.items()]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return verdict


def main():
    ap = argparse.ArgumentParser(description="Quality gate: knowledge/quality-rules.md")
    ap.add_argument("--run", required=True, help="Run month, e.g. 2026-08")
    ap.add_argument("--raw-root", default="data/raw", help="Folder with one subfolder per delivery")
    ap.add_argument("--clean-root", default="data/clean", help="Clean layer root (delivery folders + all/)")
    ap.add_argument("--mart", default="data/mart")
    ap.add_argument("--seed", type=int, help="Seed for the 10 traced orders (default: new random seed)")
    args = ap.parse_args()
    raw_root, clean_root, model = Path(args.raw_root), Path(args.clean_root), Path(args.mart)
    raw, clean = raw_root / args.run, clean_root / args.run        # this run's delivery (traced orders)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1, 1_000_000)

    needed = [raw / "orders.csv", raw / "products.csv", raw / "inventory.csv", clean / "orders.csv",
              clean_root / "all" / "orders.csv",
              model / "fact_sales.csv", model / "fact_inventory.csv", model / "dim_date.csv",
              model / "dim_product.csv", model / "dim_country.csv"]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        print(f"FAIL - files missing: {missing}")
        return 1
    folders = deliveries(raw_root)

    rules = load_rules()
    a, b = road_a(model), road_b(folders, rules)
    g_rows = rule_2(a, b)
    traces = rule_3(raw, clean, model, rules, seed)
    month_rev = rule_4(a, folders + [clean, clean_root / "all", model])

    out = Path("runs") / args.run / "4-quality-gate" / "quality-gate-checks.md"
    data_line = (f"Data: raw deliveries {', '.join(f'`{d.as_posix()}`' for d in folders)} · clean `{clean.as_posix()}` "
                 f"+ `{(clean_root / 'all').as_posix()}` · model `{model.as_posix()}`")
    verdict = write_report(out, args.run, seed, data_line, g_rows, traces, month_rev)
    for r in results:
        print(f"R{r['rule']} {r['id']:<4} {r['status']:<5} {r['name']}" + (f"  [{r['detail']}]" if r["detail"] else ""))
    print(f"\n{verdict}  ({len(results)} checks, trace seed {seed})")
    print(f"Saved to {out}")
    return 0 if verdict.startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
