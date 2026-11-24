"""
Validate the NORDA sales data model (data/mart) against the design and the clean layer.

Every check must PASS. Any FAIL -> exit code 1.
  F01-F19  fact tables (columns, values, revenue recomputed independently, reconciliation with clean)
  D01-D16  dimension tables (columns, keys, calendar, consistency with clean)
  X01-X07  relationships between facts and dimensions (every key found, no orphans)
  M01      the diagram data/mart/model.html shows every table, column and relationship
Also prints the dashboard headline numbers so they can be eyeballed before Power BI.

Reads the model files back as TEXT: the checks look at what is really in the files.

Run from the project root (after mart.py):
    python .claude/skills/mart/check.py --run 2026-08
Writes runs/<run>/3-mart/mart-checks.md
"""
import sys

sys.dont_write_bytecode = True  # no __pycache__ folder next to the scripts

import argparse
import datetime as dt
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

# Rules and the table design live in mart.py (one place to change them)
from mart import CHANNELS, COLUMNS, CORE_MARKETS, COUNTRY_NAMES, DIM_KEYS, RELATIONSHIPS

CENT = Decimal("0.01")
WHOLE_NUMBER = re.compile(r"^\d+$")
EIGHT_DIGITS = re.compile(r"^\d{8}$")
results = []


def check(cid, name, failed, detail=""):
    """failed = number of offending rows/items. 0 -> PASS."""
    results.append({"id": cid, "name": name, "status": "FAIL" if failed else "PASS",
                    "failed": f"{int(failed):,}", "detail": detail})


def to_decimal(text):
    try:
        return Decimal(text)
    except Exception:
        return None


# ===========================================================================
# F. Facts
# ===========================================================================
def check_facts(fs, fi, orders, inventory):
    ok_s, ok_i = list(fs.columns) == COLUMNS["fact_sales"], list(fi.columns) == COLUMNS["fact_inventory"]
    check("F01", "fact_sales columns exact and in order", 0 if ok_s else 1, "" if ok_s else f"got {list(fs.columns)}")
    check("F02", "fact_inventory columns exact and in order", 0 if ok_i else 1, "" if ok_i else f"got {list(fi.columns)}")
    if not (ok_s and ok_i):
        check("F00", "remaining fact checks not run (columns wrong)", 1)
        return

    blank_s = int((fs.apply(lambda c: c.str.strip() == "")).sum().sum())
    blank_i = int((fi.apply(lambda c: c.str.strip() == "")).sum().sum())
    check("F03", "fact_sales has no blank values", blank_s)
    check("F04", "fact_inventory has no blank values", blank_i)

    same_s, same_i = len(fs) == len(orders), len(fi) == len(inventory)
    check("F05", "fact_sales rows = clean orders rows", abs(len(fs) - len(orders)), f"{len(fs):,} vs {len(orders):,}")
    check("F06", "fact_inventory rows = clean inventory rows", abs(len(fi) - len(inventory)), f"{len(fi):,} vs {len(inventory):,}")

    # Row by row: date_key = order_date without dashes
    if same_s:
        expected = orders["order_date"].str.replace("-", "", regex=False)
        bad = int((~fs["date_key"].str.match(EIGHT_DIGITS.pattern) | (fs["date_key"].values != expected.values)).sum())
    else:
        bad = len(fs)
    check("F07", "sales date_key = order_date (yyyymmdd)", bad)

    check("F08", "quantity is a whole number >= 1",
          sum(1 for q in fs["quantity"] if not WHOLE_NUMBER.match(q) or int(q) < 1))
    check("F09", "unit_price > 0", sum(1 for p in fs["unit_price"] if (to_decimal(p) is None or to_decimal(p) <= 0)))
    check("F10", "discount_rate between 0 and 0.5",
          sum(1 for r in fs["discount_rate"] if (d := to_decimal(r)) is None or d < 0 or d > Decimal("0.5")))

    # Revenue and discount recomputed from the CLEAN text (not from the fact), compared as 2-dp text
    if same_s:
        bad_rev = bad_disc = 0
        first_rev = first_disc = ""
        for i, (q, p, r, rev, disc) in enumerate(zip(orders["quantity"], orders["unit_price"],
                                                     orders["discount_rate"], fs["revenue"], fs["discount_amount"])):
            line = Decimal(q) * Decimal(p)
            exp_rev = str((line - line * Decimal(r)).quantize(CENT, ROUND_HALF_UP))
            exp_disc = str((line * Decimal(r)).quantize(CENT, ROUND_HALF_UP))
            if rev != exp_rev:
                bad_rev += 1
                first_rev = first_rev or f"first at row {i}: got {rev}, expected {exp_rev}"
            if disc != exp_disc:
                bad_disc += 1
                first_disc = first_disc or f"first at row {i}: got {disc}, expected {exp_disc}"
    else:
        bad_rev = bad_disc = len(fs)
        first_rev = first_disc = "row counts differ"
    check("F11", "revenue = quantity x unit_price x (1 - discount_rate), half-up", bad_rev, first_rev)
    check("F12", "discount_amount = quantity x unit_price x discount_rate, half-up", bad_disc, first_disc)

    bad = 0
    for q, p, rev in zip(fs["quantity"], fs["unit_price"], fs["revenue"]):
        qd, pd_, rd = to_decimal(q), to_decimal(p), to_decimal(rev)
        if None in (qd, pd_, rd) or rd < 0 or rd > qd * pd_:
            bad += 1
    check("F13", "revenue between 0 and quantity x unit_price", bad)

    fm = pd.to_numeric(fs["quantity"], errors="coerce").groupby(fs["date_key"].str[:6]).sum()
    cm = orders["quantity"].astype("int64").groupby(orders["order_date"].str[:7].str.replace("-", "", regex=False)).sum()
    diff = fm.sub(cm, fill_value=0)
    check("F14", "units per month = clean orders", int((diff != 0).sum()), f"{len(diff)} months compared")

    nf, nc = fs["order_id"].nunique(), orders["order_id"].nunique()
    check("F15", "distinct order_id = clean orders", abs(nf - nc), f"{nf:,} vs {nc:,}")

    bad = 0
    months = inventory["stock_month"].tolist() if same_i else [None] * len(fi)
    for key, month in zip(fi["date_key"], months):
        try:
            d = dt.datetime.strptime(key, "%Y%m%d").date()
        except ValueError:
            bad += 1
            continue
        if (d + dt.timedelta(days=1)).day != 1 or month is None or d.strftime("%Y-%m") != month:
            bad += 1
    check("F16", "inventory date_key = last day of stock_month", bad)

    check("F17", "inventory sku + date_key unique", int(fi.duplicated(subset=["sku", "date_key"], keep=False).sum()))
    check("F18", "qty_on_hand is a whole number >= 0", sum(1 for q in fi["qty_on_hand"] if not WHOLE_NUMBER.match(q)))

    fm = pd.to_numeric(fi["qty_on_hand"], errors="coerce").groupby(fi["date_key"].str[:6]).sum()
    cm = inventory["qty_on_hand"].astype("int64").groupby(inventory["stock_month"].str.replace("-", "", regex=False)).sum()
    diff = fm.sub(cm, fill_value=0)
    check("F19", "stock per month = clean inventory", int((diff != 0).sum()), f"{len(diff)} months compared")


# ===========================================================================
# D. Dimensions
# ===========================================================================
def check_dims(dims, products, orders):
    dim_names = list(DIM_KEYS)
    wrong = [n for n in dim_names if list(dims[n].columns) != COLUMNS[n]]
    check("D01", "dimension columns exact and in order", len(wrong), f"wrong: {wrong}" if wrong else "")
    if wrong:
        check("D00", "remaining dimension checks not run (columns wrong)", 1)
        return

    dups = {n: int(dims[n][k].str.strip().duplicated().sum()) for n, k in DIM_KEYS.items()}
    blank_keys = {n: int((dims[n][k].str.strip() == "").sum()) for n, k in DIM_KEYS.items()}
    check("D02", "dimension keys unique", sum(dups.values()), str({k: v for k, v in dups.items() if v}) if any(dups.values()) else "")
    check("D03", "dimension keys never blank", sum(blank_keys.values()))
    blanks = sum(int((dims[n].apply(lambda c: c.str.strip()) == "").sum().sum()) for n in dim_names)
    check("D04", "no blank values in any dimension column", blanks)

    dd = dims["dim_date"]
    days = pd.to_datetime(dd["date"], format="%Y-%m-%d", errors="coerce")
    steps = days.diff().dt.days.iloc[1:]
    check("D05", "dim_date has no missing days", int((steps != 1).sum() + days.isna().sum()))
    first_ok = len(days) and days.iloc[0] is not pd.NaT and (days.iloc[0].month, days.iloc[0].day) == (1, 1)
    last_ok = len(days) and days.iloc[-1] is not pd.NaT and (days.iloc[-1].month, days.iloc[-1].day) == (12, 31)
    check("D06", "dim_date starts on 1 Jan and ends on 31 Dec", int(not first_ok) + int(not last_ok),
          f"{dd['date'].iloc[0]} .. {dd['date'].iloc[-1]}" if len(dd) else "empty")
    missing = sorted(set(orders["order_date"]) - set(dd["date"]))
    check("D07", "dim_date covers every order date", len(missing), f"e.g. {missing[:5]}" if missing else "")
    check("D08", "date_key = date without dashes", int((dd["date_key"] != dd["date"].str.replace("-", "", regex=False)).sum()))

    # Recompute the attributes independently with pandas (not the builder's helper)
    ok = days.notna()
    v = days[ok]
    expected = pd.DataFrame({
        "year": v.dt.year.astype(int).astype(str),
        "quarter": v.dt.quarter.astype(int).astype(str),
        "month_no": v.dt.month.astype(int).astype(str),
        "month_name": v.dt.month_name(),
        "year_month": v.dt.strftime("%Y-%m"),
        "weekday": v.dt.day_name(),
        "is_weekend": (v.dt.dayofweek >= 5).map({True: "True", False: "False"}),
        "month_label": v.dt.month_name().str[:3] + " " + v.dt.year.astype(int).astype(str),
    })
    wrong_rows = (dd.loc[ok, expected.columns] != expected).any(axis=1)
    check("D09", "dim_date attributes match the date", int(wrong_rows.sum() + (~ok).sum()),
          f"e.g. {list(dd.loc[wrong_rows[wrong_rows].index, 'date'][:3])}" if wrong_rows.any() else "")

    dp = dims["dim_product"]
    only = set(dp["sku"]) ^ set(products["sku"])
    row_diff = abs(len(dp) - len(products))
    check("D10", "dim_product has the same skus as clean products", len(only) + row_diff, f"{len(dp)} vs {len(products)}")
    n = min(len(dp), len(products))
    differs = (dp[COLUMNS["dim_product"]].iloc[:n].reset_index(drop=True)
               != products[COLUMNS["dim_product"]].iloc[:n].reset_index(drop=True)).any(axis=1)
    check("D11", "dim_product rows identical to clean products", int(differs.sum()) + row_diff)

    dc = dims["dim_country"]
    check("D12", "dim_country codes = country codes in orders", len(set(dc["country_code"]) ^ set(orders["country_code"])))
    check("D13", "country_name matches the country list",
          sum(COUNTRY_NAMES.get(c) != nm for c, nm in zip(dc["country_code"], dc["country_name"])))
    check("D14", f"is_core_market True exactly for {sorted(CORE_MARKETS)}",
          int((dc["is_core_market"] != dc["country_code"].map(lambda c: str(c in CORE_MARKETS))).sum()))

    dch = dims["dim_channel"]
    check("D15", "dim_channel = channels in orders", len(set(dch["channel"]) ^ set(orders["channel"])))
    check("D16", f"all channels allowed {sorted(CHANNELS)}", len(set(dch["channel"]) - CHANNELS))


# ===========================================================================
# X. Relationships (star schema joins)
# ===========================================================================
def check_relationships(tables, orders):
    for i, (fact, fcol, dim, dkey) in enumerate(RELATIONSHIPS, start=1):
        orphans = ~tables[fact][fcol].isin(set(tables[dim][dkey]))
        check(f"X0{i}", f"every {fact}.{fcol} exists in {dim}.{dkey}", int(orphans.sum()),
              f"e.g. {list(tables[fact].loc[orphans, fcol].unique()[:5])}" if orphans.any() else "")
    # The clean layer's flag must agree with the dimension (one definition of "core market")
    flag = dict(zip(tables["dim_country"]["country_code"], tables["dim_country"]["is_core_market"]))
    disagree = orders["is_core_market"] != orders["country_code"].map(flag)
    check("X07", "clean orders is_core_market agrees with dim_country", int(disagree.sum()))


# ===========================================================================
# M. The diagram (data/mart/model.html) matches the design
# ===========================================================================
def check_diagram(folder):
    name = "model.html shows every table, column and relationship"
    path = folder / "model.html"
    if not path.exists():
        check("M01", name, 1, "model.html missing - run mart.py")
        return
    page = path.read_text(encoding="utf-8")
    problems = []
    for table, cols in COLUMNS.items():
        card = re.search(rf'<section class="table" id="{table}".*?</section>', page, re.S)
        if not card:
            problems.append(f"{table} missing")
        elif re.findall(r'data-col="([^"]+)"', card.group(0)) != cols:
            problems.append(f"{table} columns differ")
    rels = re.search(r'<script id="rels" type="application/json">(.*?)</script>', page, re.S)
    shown = sorted(tuple(r) for r in json.loads(rels.group(1))) if rels else []
    if shown != sorted(RELATIONSHIPS):
        problems.append("relationships differ")
    check("M01", name, len(problems), "; ".join(problems))


# ===========================================================================
def headline(tables):
    """The dashboard's three big numbers, plus a split, for eyeballing (not pass/fail)."""
    fs, fi, dc = tables["fact_sales"], tables["fact_inventory"], tables["dim_country"]
    rev = fs["revenue"].map(Decimal)
    core = dict(zip(dc["country_code"], dc["is_core_market"]))
    is_core = fs["country_code"].map(core) == "True"
    last = fi["date_key"].max()
    stock = int(fi.loc[fi["date_key"] == last, "qty_on_hand"].astype(int).sum())
    return [
        f"Total revenue: EUR {sum(rev):,.2f}  (core markets EUR {sum(rev[is_core]):,.2f} · ES/AT EUR {sum(rev[~is_core]):,.2f})",
        f"Number of orders: {fs['order_id'].nunique():,}",
        f"Stock on hand (latest month, {last[:4]}-{last[4:6]}): {stock:,} units",
        f"Discount amount: EUR {sum(fs['discount_amount'].map(Decimal)):,.2f} · Units sold: {fs['quantity'].astype(int).sum():,}",
    ]


def main():
    ap = argparse.ArgumentParser(description="Validate the star-schema sales data model.")
    ap.add_argument("--run", required=True, help="Run month for the report folder, e.g. 2026-08")
    ap.add_argument("--clean", default="data/clean/all", help="Combined clean history (default: data/clean/all)")
    ap.add_argument("--data", default="data/mart", help="Mart folder (default: data/mart)")
    args = ap.parse_args()
    clean = Path(args.clean)
    data = Path(args.data)

    def read(path):
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")

    missing = [n for n in COLUMNS if not (data / f"{n}.csv").exists()]
    if missing:
        print(f"FAIL - mart files missing in {data}: {missing}. Run mart.py first.")
        return 1
    missing = [n for n in ("orders", "products", "inventory") if not (clean / f"{n}.csv").exists()]
    if missing:
        print(f"FAIL - clean files missing in {clean}: {missing}. Check --run / --clean.")
        return 1
    tables = {n: read(data / f"{n}.csv") for n in COLUMNS}
    orders, products, inventory = (read(clean / f"{n}.csv") for n in ("orders", "products", "inventory"))

    check_facts(tables["fact_sales"], tables["fact_inventory"], orders, inventory)
    check_dims({n: tables[n] for n in DIM_KEYS}, products, orders)
    columns_ok = not any(r["id"] in ("F00", "D00") for r in results)
    if columns_ok:
        check_relationships(tables, orders)
    check_diagram(data)

    fails = [r for r in results if r["status"] == "FAIL"]
    verdict = "PASS - mart OK" if not fails else f"FAIL - {len(fails)} checks failed"
    for r in results:
        print(f"{r['id']:<4} {r['status']:<5} {r['failed']:>8}  {r['name']}" + (f"  [{r['detail']}]" if r["detail"] else ""))
    print(f"\n{verdict}  ({len(results)} checks)")
    heads = headline(tables) if columns_ok else []
    if heads:
        print("\nDashboard headline numbers:\n  " + "\n  ".join(heads))

    md = [f"# Mart check - run {args.run}", "", f"Mart: `{data}` · reconciled against clean: `{clean}`", "",
          f"**{verdict}** ({len(results)} checks)", ""]
    if heads:
        md += ["Dashboard headline numbers:", ""] + [f"- {h}" for h in heads] + [""]
    md += ["| ID | Check | Result | Failing | Detail |", "|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['name']} | {'**FAIL**' if r['status'] == 'FAIL' else 'PASS'} | {r['failed']} | {r['detail']} |"
           for r in results]
    out = Path("runs") / args.run / "3-mart" / "mart-checks.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Saved to {out}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
