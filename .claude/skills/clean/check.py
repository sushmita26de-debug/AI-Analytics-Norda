"""
Checks on the clean layer (data/clean/<run>/). Separate from the /profile skill, which checks raw.

Every check must PASS. Any FAIL -> exit code 1.
Part A checks the clean files on their own (format, allowed values, keys).
Part B reconciles clean against raw: re-reads data/raw/<run>/ independently and proves
that the only rows removed are the identical copies and that nothing else was lost.
Part C checks the combined history data/clean/all/ against every delivery folder, re-derived here
independently: orders and stock rows appended exactly once, products = newest delivery per sku.
No business calculations here (no amounts): those are defined later, outside the clean layer.

Run from the project root (after clean.py):
    python .claude/skills/clean/check.py --run 2026-08
Writes runs/<run>/2-clean/clean-checks.md
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True   # no __pycache__ folder next to the scripts
from clean import (BRANDS, CATEGORIES, CHANNELS, CLEAN_COLUMNS, COUNTRY_NAMES, DISC_MAX,
                   EXTRA_COUNTRIES, MARKETS)

results = []


def check(cid, name, failed, detail=""):
    """failed = number of rows/items that break the rule. 0 -> PASS."""
    results.append({"id": cid, "name": name, "status": "FAIL" if failed else "PASS",
                    "failed": f"{failed:,}", "detail": detail})


def ex(values, n=5):
    v = list(pd.Series(values).unique()[:n])
    return f"e.g. {v}" if v else ""


def read(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


# ===========================================================================
# A. Clean files on their own
# ===========================================================================
def check_all_files(files):
    for i, (name, df) in enumerate(files.items(), start=1):
        cols = list(df.columns)
        check(f"A0{i}", f"{name}: columns exactly {CLEAN_COLUMNS[name]}",
              int(cols != CLEAN_COLUMNS[name]), "" if cols == CLEAN_COLUMNS[name] else f"found {cols}")
    spaces = sum(int((df[c] != df[c].str.strip()).sum()) for df in files.values() for c in df.columns)
    check("A04", "No leading/trailing spaces in any value", spaces)
    dups = {n: int(df.duplicated().sum()) for n, df in files.items()}
    check("A05", "No completely identical rows in any file", sum(dups.values()), str(dups))


def check_orders(o, p):
    n = "orders"
    blank = o[["order_id", "order_date", "channel", "country_code", "is_core_market", "sku",
               "quantity", "unit_price", "discount_rate"]].eq("").any(axis=1)
    check("O01", f"{n}: no blank values (except customer_id)", int(blank.sum()))
    check("O02", f"{n}: order_id format SO + 6 digits", int((~o["order_id"].str.match(r"^SO\d{6}$")).sum()),
          ex(o.loc[~o["order_id"].str.match(r"^SO\d{6}$"), "order_id"]))

    fmt = o["order_date"].str.match(r"^\d{4}-\d{2}-\d{2}$")
    real = pd.to_datetime(o["order_date"], format="%Y-%m-%d", errors="coerce").notna()
    check("O03", f"{n}: order_date is a real date in YYYY-MM-DD", int((~(fmt & real)).sum()),
          ex(o.loc[~(fmt & real), "order_date"]))

    check("O04", f"{n}: channel in {sorted(CHANNELS)}", int((~o["channel"].isin(CHANNELS)).sum()),
          ex(o.loc[~o["channel"].isin(CHANNELS), "channel"]))
    allowed = MARKETS | EXTRA_COUNTRIES
    check("O05", f"{n}: country_code in {sorted(allowed)}", int((~o["country_code"].isin(allowed)).sum()),
          ex(o.loc[~o["country_code"].isin(allowed), "country_code"]))
    expect_flag = o["country_code"].isin(MARKETS).map({True: "True", False: "False"})
    check("O06", f"{n}: is_core_market = True exactly for {sorted(MARKETS)}",
          int((o["is_core_market"] != expect_flag).sum()))

    mk = (o["channel"] == "marketplace") & (o["customer_id"] != "")
    check("O07", f"{n}: customer_id empty on marketplace rows", int(mk.sum()))
    filled = o["customer_id"] != ""
    bad_c = filled & ~o["customer_id"].str.match(r"^C\d{6}$")
    check("O08", f"{n}: customer_id format C + 6 digits when filled", int(bad_c.sum()), ex(o.loc[bad_c, "customer_id"]))

    q = pd.to_numeric(o["quantity"], errors="coerce")
    check("O09", f"{n}: quantity whole number >= 1",
          int((q.isna() | (q < 1) | ~o["quantity"].str.match(r"^\d+$")).sum()))
    pr = pd.to_numeric(o["unit_price"], errors="coerce")
    check("O10", f"{n}: unit_price > 0 with 2 decimals",
          int((pr.isna() | (pr <= 0) | ~o["unit_price"].str.match(r"^\d+\.\d{2}$")).sum()))
    d = pd.to_numeric(o["discount_rate"], errors="coerce")
    check("O11", f"{n}: discount_rate between 0 and {DISC_MAX}", int((d.isna() | (d < 0) | (d > DISC_MAX)).sum()),
          ex(o.loc[d.isna() | (d < 0) | (d > DISC_MAX), "discount_rate"]))
    not_cat = ~o["sku"].isin(p["sku"])
    check("O12", f"{n}: every sku exists in products (this delivery + history)", int(not_cat.sum()), ex(o.loc[not_cat, "sku"]))
    multi = (o.groupby("order_id")[["order_date", "channel", "country_code", "customer_id"]].nunique() > 1).any(axis=1)
    check("O13", f"{n}: one date, channel, country and customer per order", int(multi.sum()), ex(multi[multi].index))


def check_products(p):
    n = "products"
    check("P01", f"{n}: sku unique", int(p["sku"].duplicated().sum()), ex(p.loc[p["sku"].duplicated(), "sku"]))
    check("P02", f"{n}: sku format AA-99999", int((~p["sku"].str.match(r"^[A-Z]{2}-\d{5}$")).sum()))
    check("P03", f"{n}: brand exactly one of {sorted(BRANDS)}", int((~p["brand"].isin(BRANDS)).sum()),
          ex(p.loc[~p["brand"].isin(BRANDS), "brand"]))
    check("P04", f"{n}: category exactly one of the 5 categories", int((~p["category"].isin(CATEGORIES)).sum()),
          ex(p.loc[~p["category"].isin(CATEGORIES), "category"]))
    lp = pd.to_numeric(p["latest_list_price"], errors="coerce")
    check("P05", f"{n}: latest_list_price > 0 with 2 decimals",
          int((lp.isna() | (lp <= 0) | ~p["latest_list_price"].str.match(r"^\d+\.\d{2}$")).sum()))
    check("P06", f"{n}: no blank product_name", int((p["product_name"] == "").sum()))


def check_inventory(i, p):
    n = "inventory"
    check("I01", f"{n}: stock_month in YYYY-MM", int((~i["stock_month"].str.match(r"^\d{4}-(0[1-9]|1[0-2])$")).sum()),
          ex(i.loc[~i["stock_month"].str.match(r"^\d{4}-(0[1-9]|1[0-2])$"), "stock_month"]))
    check("I02", f"{n}: sku + stock_month unique", int(i.duplicated(subset=["sku", "stock_month"]).sum()))
    qh = pd.to_numeric(i["qty_on_hand"], errors="coerce")
    check("I03", f"{n}: qty_on_hand whole number >= 0",
          int((qh.isna() | (qh < 0) | ~i["qty_on_hand"].str.match(r"^\d+$")).sum()))
    not_cat = ~i["sku"].isin(p["sku"])
    check("I04", f"{n}: every sku exists in products (this delivery + history)", int(not_cat.sum()), ex(i.loc[not_cat, "sku"]))


# ===========================================================================
# B. Reconciliation: clean vs raw (raw re-read independently)
# ===========================================================================
def reconcile(raw, o, p, i):
    ro = read(raw / "orders.csv")
    dup = ro.duplicated(keep="first")
    rk = ro[~dup].apply(lambda c: c.str.strip())   # raw minus identical copies = what clean should hold

    check("R01", "orders: clean rows = raw rows - identical copies",
          abs(len(o) - len(rk)), f"raw {len(ro):,} - copies {int(dup.sum()):,} = {len(rk):,}; clean {len(o):,}")
    missing = set(ro["ORD_NO"].str.strip()) - set(o["order_id"])
    check("R02", "orders: every raw order_id is in clean", len(missing), ex(sorted(missing)))

    # Same order lines, ignoring format: order + sku + quantity + price + discount
    def key(df, cols):
        return df[cols].astype(str).agg("|".join, axis=1).value_counts()
    k_raw = key(rk.assign(q=pd.to_numeric(rk["QTY"]).astype(int).astype(str),
                          pr=pd.to_numeric(rk["UNIT_PRC"]).map("{:.2f}".format),
                          d=pd.to_numeric(rk["DISC_PCT"]).map("{:.2f}".format)),
                ["ORD_NO", "ART_NO", "q", "pr", "d"])
    k_cln = key(o, ["order_id", "sku", "quantity", "unit_price", "discount_rate"])
    diff = k_raw.sub(k_cln, fill_value=0)
    check("R03", "orders: every raw line (order, sku, qty, price, discount) is in clean, same count",
          int((diff != 0).sum()), ex(diff[diff != 0].index))

    # Dates: raw parsed independently (ISO, else DD/MM)
    s = rk["CRTD_DT"]
    rdt = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce").fillna(
        pd.to_datetime(s, format="%d/%m/%Y", errors="coerce"))
    if len(rk) == len(o):
        date_off = int((rdt.dt.strftime("%Y-%m-%d").values != o["order_date"].values).sum())
    else:
        date_off = len(o)   # row counts differ -> cannot compare row by row (R01 fails too)
    check("R04", "orders: each order_date equals the raw date read as DD/MM (row by row)", date_off)

    # Units per month: sum of quantity (no business calculation)
    raw_q = pd.to_numeric(rk["QTY"]).groupby(rdt.dt.strftime("%Y-%m")).sum()
    cln_q = pd.to_numeric(o["quantity"]).groupby(o["order_date"].str[:7]).sum()
    gap = raw_q.sub(cln_q, fill_value=0)
    bad_months = gap[gap != 0]
    check("R05", "orders: sum of quantity per month = raw minus identical copies",
          len(bad_months), ex(bad_months.index))

    # Rows per channel and per country (names mapped)
    rc = rk["CTRY"].replace(COUNTRY_NAMES)
    by_c = rc.value_counts().sub(o["country_code"].value_counts(), fill_value=0)
    by_ch = rk["CHNL"].value_counts().sub(o["channel"].value_counts(), fill_value=0)
    check("R06", "orders: rows per country and per channel match raw", int((by_c != 0).sum() + (by_ch != 0).sum()))
    cust_raw = rk.loc[rk["CHNL"] != "marketplace", "CUST_REF"]
    cust_cln = o.loc[o["channel"] != "marketplace", "customer_id"]
    check("R07", "orders: customer_id unchanged on web/app rows",
          int(cust_raw.value_counts().sub(cust_cln.value_counts(), fill_value=0).ne(0).sum()))

    rp_ = read(raw / "products.csv").apply(lambda c: c.str.strip())
    check("R08", "products: same skus as raw", len(set(rp_["sku"]) ^ set(p["sku"])), f"raw {len(rp_)}, clean {len(p)}")
    m = rp_.merge(p, on="sku", suffixes=("_raw", ""))
    bad = (m["brand_raw"].str.lower() != m["brand"].str.lower()) | \
          (m["category_raw"].str.lower() != m["category"].str.lower()) | \
          (pd.to_numeric(m["list_price"]) - pd.to_numeric(m["latest_list_price"])).abs().gt(0.005) | \
          (m["product_name_raw"] != m["product_name"])
    check("R09", "products: only the case of brand/category changed vs raw", int(bad.sum()), ex(m.loc[bad, "sku"]))

    ri = read(raw / "inventory.csv").apply(lambda c: c.str.strip())
    ri["m"] = pd.PeriodIndex(ri["stk_month"], freq="M").strftime("%Y-%m")
    check("R10", "inventory: same rows as raw", abs(len(ri) - len(i)), f"raw {len(ri):,}, clean {len(i):,}")
    rkey = set(zip(ri["art_no"], ri["m"], ri["qty_hand"]))
    ckey = set(zip(i["sku"], i["stock_month"], i["qty_on_hand"]))
    check("R11", "inventory: same sku, month and qty_on_hand as raw", len(rkey ^ ckey), ex(sorted(rkey ^ ckey)))


# ===========================================================================
# C. Combined history: data/clean/all/ vs every delivery folder (re-derived independently)
# ===========================================================================
def deliveries_on_disk(root):
    return sorted((d for d in root.iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}", d.name)
                   and all((d / f"{n}.csv").exists() for n in CLEAN_COLUMNS)), key=lambda d: d.name)


def check_combined(root):
    a_dir = root / "all"
    if not all((a_dir / f"{n}.csv").exists() for n in CLEAN_COLUMNS):
        check("C01", "all: the 3 combined files exist", 1, f"missing in {a_dir}")
        return None
    A = {n: read(a_dir / f"{n}.csv") for n in CLEAN_COLUMNS}
    D = [(d.name, {n: read(d / f"{n}.csv") for n in CLEAN_COLUMNS}) for d in deliveries_on_disk(root)]
    bad_cols = [n for n in CLEAN_COLUMNS if list(A[n].columns) != CLEAN_COLUMNS[n]]
    check("C01", "all: the 3 combined files exist with the clean columns", len(bad_cols), ", ".join(bad_cols))
    if bad_cols:
        return None
    names = [d for d, _ in D]

    def multiset(df):
        return df.astype(str).agg("|".join, axis=1).value_counts()
    for cid, n, label in [("C02", "orders", "order line"), ("C04", "inventory", "stock row")]:
        stacked = pd.concat([f[n] for _, f in D], ignore_index=True)
        diff = multiset(stacked).sub(multiset(A[n]), fill_value=0)
        check(cid, f"all/{n}: every delivery's {label}s exactly once ({' + '.join(names)})", int((diff != 0).sum()),
              f"deliveries {len(stacked):,} rows, all {len(A[n]):,}")
    owner = {}
    twice = []
    for d, f in D:
        for oid in set(f["orders"]["order_id"]):
            if oid in owner:
                twice.append(oid)
            owner[oid] = d
    check("C03", "all/orders: no order number in two deliveries", len(twice), ex(twice))
    check("C05", "all/inventory: sku + stock_month unique", int(A["inventory"].duplicated(subset=["sku", "stock_month"]).sum()))

    newest = {}
    for d, f in D:                                   # oldest -> newest: later deliveries overwrite
        for r in f["products"].itertuples(index=False):
            newest[r.sku] = r
    ap_ = A["products"].set_index("sku")
    check("C06", "all/products: exactly the skus of all deliveries", len(set(newest) ^ set(ap_.index)),
          f"deliveries {len(newest)}, all {len(ap_)}")
    off = [s for s, r in newest.items() if s in ap_.index and (
        ap_.at[s, "latest_list_price"] != r.latest_list_price or ap_.at[s, "product_name"] != r.product_name
        or ap_.at[s, "brand"] != r.brand or ap_.at[s, "category"] != r.category)]
    check("C07", "all/products: price, name, brand, category = the newest delivery's row", len(off), ex(off))
    first = {}
    for d, f in D:
        for r in f["products"].itertuples(index=False):
            first.setdefault(r.sku, r)
    moved = [s for s, r in first.items() if (r.product_name, r.brand, r.category) !=
             (newest[s].product_name, newest[s].brand, newest[s].category)]
    check("C08", "all/products: no sku changed name, brand or category between deliveries", len(moved), ex(moved))
    for cid, n in [("C09", "orders"), ("C10", "inventory")]:
        miss = ~A[n]["sku"].isin(ap_.index)
        check(cid, f"all/{n}: every sku exists in all/products", int(miss.sum()), ex(A[n].loc[miss, "sku"]))
    return A


# ===========================================================================
def main():
    ap = argparse.ArgumentParser(description="Check the clean layer.")
    ap.add_argument("--run", required=True)
    ap.add_argument("--raw", help="Delivery folder (default: data/raw/<run>)")
    ap.add_argument("--clean-root", default="data/clean", help="Clean layer root (delivery folders + all/)")
    args = ap.parse_args()
    raw = Path(args.raw) if args.raw else Path("data/raw") / args.run
    root = Path(args.clean_root)
    clean = root / args.run

    missing = [n for n in CLEAN_COLUMNS if not (clean / f"{n}.csv").exists()]
    if missing:
        print(f"FAIL - clean files missing in {clean}: {missing}. Run clean.py first.")
        return 1
    files = {n: read(clean / f"{n}.csv") for n in CLEAN_COLUMNS}
    o, p, i = files["orders"], files["products"], files["inventory"]

    check_all_files(files)
    if all(r["status"] == "PASS" for r in results[:3]):   # columns OK -> column checks are meaningful
        A = check_combined(root)
        catalogue = A["products"] if A is not None else p   # skus may come from an earlier delivery
        check_orders(o, catalogue)
        check_products(p)
        check_inventory(i, catalogue)
        reconcile(raw, o, p, i)

    fails = [r for r in results if r["status"] == "FAIL"]
    verdict = "PASS - clean layer OK" if not fails else f"FAIL - {len(fails)} checks failed"
    for r in results:
        print(f"{r['id']:<4} {r['status']:<5} {r['failed']:>8}  {r['name']}" + (f"  [{r['detail']}]" if r["detail"] else ""))
    print(f"\n{verdict}  ({len(results)} checks)")

    md = [f"# Clean layer check - run {args.run}", "",
          f"Clean: `{clean}` · reconciled against raw: `{raw}` · combined history: `{root / 'all'}`", "",
          f"**{verdict}** ({len(results)} checks)", "",
          "| ID | Check | Result | Failing | Detail |", "|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['name']} | {'**FAIL**' if r['status'] == 'FAIL' else 'PASS'} | {r['failed']} | {r['detail']} |"
           for r in results]
    out = Path("runs") / args.run / "2-clean" / "clean-checks.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Saved to {out}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
