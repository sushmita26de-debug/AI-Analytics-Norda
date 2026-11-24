"""
Monthly pass/fail checks on the raw NORDA shop export.

FAIL = the case is present in the data. Every check has a label:
  known   - understood and decided. Reported every month; does not stop the run.
  blocker - new or unsafe; stop and ask before going further.

Exit code 1 if any blocker fails (or a check could not run), else 0.
Read-only: never modifies the raw folder.

Each delivery is its own folder: data/raw/<run>/ (orders, products, inventory). Earlier deliveries
(data/raw/<earlier month>/) are the history: orders and stock rows are appended to it, products are
added or get a new price. The H checks compare the new delivery with that history.

Business lists (markets, countries, channels, brands, categories) come from knowledge/rules.json.
The RULES section below (incl. columns and limits) is also used by profile.py.

Run from the project root:
    python .claude/skills/profile/check.py --run 2026-08                 (reads data/raw/2026-08/)
    python .claude/skills/profile/check.py --run 2026-09 --expect-month 2026-08
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# ===========================================================================
# RULES - what "normal" looks like (knowledge/company.md, knowledge/metadata.md)
# ===========================================================================

# Exact column lists as the shop system delivers them (the file, not the PDF, is the truth)
COLUMNS = {
    "orders": ["ORD_NO", "CRTD_DT", "CHNL", "CTRY", "CUST_REF", "ART_NO", "QTY", "UNIT_PRC", "DISC_PCT"],
    "products": ["sku", "product_name", "brand", "category", "list_price"],
    "inventory": ["art_no", "stk_month", "qty_hand", "reserved_qty"],
}

# Order columns that must never be blank
ORDER_KEY_FIELDS = ["ORD_NO", "CRTD_DT", "CHNL", "CTRY", "ART_NO", "QTY", "UNIT_PRC", "DISC_PCT"]

def load_rules():
    """Business lists are shared by all scripts: knowledge/rules.json (found by walking up from here)."""
    for folder in Path(__file__).resolve().parents:
        f = folder / "knowledge" / "rules.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    raise FileNotFoundError("knowledge/rules.json not found")


RULES = load_rules()
MARKETS = set(RULES["core_markets"])             # the four markets in the company overview
EXTRA_COUNTRIES = set(RULES["extra_countries"])  # decision: kept for now (not removed), FAIL reported every month
COUNTRY_NAMES = {name: code for code, name in RULES["country_names"].items()}  # full name in raw file -> code
CHANNELS = set(RULES["channels"])
BRANDS = set(RULES["brands"])
CATEGORIES = set(RULES["categories"])

DISC_MAX = 0.5                                # DISC_PCT is a fraction (0.15 = 15%); highest seen in 2025
PRICE_RATIO_MIN, PRICE_RATIO_MAX = 0.5, 1.5   # UNIT_PRC / list_price outside this = suspicious

# Date formats seen in CRTD_DT. Slash dates are DD/MM (proven on 2025 data).
DATE_FORMATS = {
    "YYYY-MM-DD": ("%Y-%m-%d", r"^\d{4}-\d{2}-\d{2}$"),
    "DD/MM/YYYY": ("%d/%m/%Y", r"^\d{2}/\d{2}/\d{4}$"),
}


def parse_dates(s):
    """Parse each known format separately. Returns (dates, format label per row)."""
    s = s.str.strip()
    parsed = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    used = pd.Series("unknown", index=s.index)
    for label, (fmt, rx) in DATE_FORMATS.items():
        m = s.str.match(rx)
        parsed[m] = pd.to_datetime(s[m], format=fmt, errors="coerce")
        used[m] = label
    return parsed, used


def norm_case(s, allowed):
    """Map 'NODO' / 'nodo' -> 'Nodo' using the allowed list. Unknown values stay as they are."""
    lookup = {a.lower(): a for a in allowed}
    return s.str.strip().map(lambda v: lookup.get(v.lower(), v))


# ===========================================================================
# CHECKS
# ===========================================================================
results = []   # one dict per check


def check(cid, label, name, count, total=None, detail=""):
    """Record one check. count > 0 means the case is present -> FAIL."""
    status = "FAIL" if count > 0 else "PASS"
    share = f" ({count / total:.2%})" if total and count else ""
    results.append({"id": cid, "label": label, "name": name, "status": status,
                    "found": f"{count:,}{share}", "detail": detail})


def not_run(cid, label, name, reason):
    results.append({"id": cid, "label": label, "name": name, "status": "NOT RUN",
                    "found": "-", "detail": reason})


def num(s):
    return pd.to_numeric(s.str.strip(), errors="coerce")


def examples(values, n=5):
    v = list(pd.Series(values).unique()[:n])
    return f"e.g. {v}" if v else ""


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
def check_structure(raw):
    files = {}
    missing = [n for n in COLUMNS if not (raw / f"{n}.csv").exists()]
    check("S01", "blocker", "File missing (orders/products/inventory)", len(missing), detail=", ".join(missing))
    for i, (name, cols) in enumerate(COLUMNS.items(), start=2):
        cid = f"S0{i}"
        if name in missing:
            not_run(cid, "blocker", f"{name}: columns differ from expected", "file missing")
            continue
        df = pd.read_csv(raw / f"{name}.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
        new = [c for c in df.columns if c not in cols]
        gone = [c for c in cols if c not in df.columns]
        detail = "; ".join(x for x in [f"new: {new}" if new else "", f"missing: {gone}" if gone else ""] if x)
        check(cid, "blocker", f"{name}: columns differ from expected", len(new) + len(gone), detail=detail)
        files[name] = df
    empty = [n for n, df in files.items() if len(df) == 0]
    check("S05", "blocker", "File has no rows", len(empty), detail=", ".join(empty))
    return files


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def check_orders(o, products, expect_month):
    n = len(o)
    raw_dt = o["CRTD_DT"].str.strip()
    dt, used = parse_dates(o["CRTD_DT"])

    check("O01", "known", "Dates in DD/MM/YYYY instead of YYYY-MM-DD",
          int((used == "DD/MM/YYYY").sum()), n)
    bad = dt.isna()
    check("O02", "blocker", "Date in unknown format or not a real date", int(bad.sum()), n,
          examples(raw_dt[bad]))

    slash = used == "DD/MM/YYYY"
    parts = raw_dt[slash].str.split("/", expand=True).astype(int) if slash.any() else pd.DataFrame({0: [], 1: []})
    mmdd = parts[1] > 12
    check("O03", "blocker", "Slash date only valid as MM/DD (DD/MM rule broken)", int(mmdd.sum()), n,
          examples(raw_dt[slash][mmdd.values]))

    ordn = pd.to_numeric(o["ORD_NO"].str.strip().str[2:], errors="coerce")
    seq = pd.DataFrame({"n": ordn, "dt": dt}).dropna().groupby("n")["dt"].first().sort_index()
    back = seq.diff().dt.days < 0
    check("O04", "blocker", "Order dated earlier than the previous order number", int(back.sum()), len(seq),
          examples([f"SO{int(k)}" for k in seq[back].index]))

    if expect_month:
        m = pd.Period(expect_month, "M")
        outside = dt.notna() & (dt.dt.to_period("M") != m)
        check("O05", "blocker", f"Order dated outside {expect_month}", int(outside.sum()), n,
              f"range {dt.min().date()} -> {dt.max().date()}")
    else:
        not_run("O05", "blocker", "Order dated outside expected month",
                f"no --expect-month given; data range {dt.min().date()} -> {dt.max().date()}")

    dup = o.duplicated(keep="first")
    check("O06", "known", "Completely identical rows (extra copies)", int(dup.sum()), n)

    blank = (o[ORDER_KEY_FIELDS].apply(lambda c: c.str.strip() == "")).any(axis=1)
    cols = [c for c in ORDER_KEY_FIELDS if (o[c].str.strip() == "").any()]
    check("O07", "blocker", "Blank key field", int(blank.sum()), n, f"columns: {cols}" if cols else "")

    ctry = o["CTRY"].str.strip()
    ctry_n = ctry.replace(COUNTRY_NAMES)
    extra = ctry_n.isin(EXTRA_COUNTRIES)
    check("O08", "known", f"Rows for countries outside the 4 markets {sorted(EXTRA_COUNTRIES)} (kept for now)",
          int(extra.sum()), n, f"by country: { {k: int(v) for k, v in ctry_n[extra].value_counts().items()} }")
    check("O09", "known", "Full country name instead of code", int((ctry != ctry_n).sum()), n)
    unknown = ~ctry_n.isin(MARKETS | EXTRA_COUNTRIES)
    check("O10", "blocker", "Unknown country value", int(unknown.sum()), n, examples(ctry[unknown]))

    chn = o["CHNL"].str.strip()
    check("O11", "blocker", "Unknown channel value", int((~chn.isin(CHANNELS)).sum()), n,
          examples(chn[~chn.isin(CHANNELS)]))
    mk = (chn == "marketplace") & (o["CUST_REF"].str.strip() != "")
    check("O12", "known", "Marketplace row with CUST_REF", int(mk.sum()), n)

    g = pd.DataFrame({"o": o["ORD_NO"], "dt": dt, "ch": chn, "ct": ctry_n, "cu": o["CUST_REF"]}).groupby("o")
    multi = (g.nunique(dropna=False) > 1).any(axis=1)
    check("O13", "blocker", "Order with >1 date, channel, country or customer", int(multi.sum()), len(multi),
          examples(multi[multi].index))

    disc = num(o["DISC_PCT"])
    bad_d = disc.isna() | (disc < 0) | (disc > DISC_MAX)
    check("O14", "blocker", f"DISC_PCT not a number in 0..{DISC_MAX} (fraction)", int(bad_d.sum()), n,
          examples(o.loc[bad_d, "DISC_PCT"]))

    qty = num(o["QTY"])
    bad_q = qty.isna() | (qty <= 0) | (qty % 1 != 0)
    check("O15", "blocker", "QTY missing, <= 0 or not a whole number", int(bad_q.sum()), n,
          examples(o.loc[bad_q, "QTY"]))

    prc = num(o["UNIT_PRC"])
    bad_p = prc.isna() | (prc <= 0)
    check("O16", "blocker", "UNIT_PRC missing or <= 0", int(bad_p.sum()), n, examples(o.loc[bad_p, "UNIT_PRC"]))

    art = o["ART_NO"].str.strip()
    sku = products["sku"].str.strip() if products is not None else pd.Series(dtype=str)
    not_cat = ~art.isin(sku)
    check("O17", "blocker", "ART_NO not in products", int(not_cat.sum()), n, examples(art[not_cat]))

    if products is not None:
        lp = art.map(pd.Series(num(products["list_price"]).values, index=sku))
        ratio = prc / lp
        far = (ratio < PRICE_RATIO_MIN) | (ratio > PRICE_RATIO_MAX)
        check("O18", "blocker", f"UNIT_PRC outside {PRICE_RATIO_MIN}x-{PRICE_RATIO_MAX}x of list_price",
              int(far.sum()), n, examples(o.loc[far, "ORD_NO"] + " " + art[far]))
    else:
        not_run("O18", "blocker", "UNIT_PRC far from list_price", "products file missing")
    return dt


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
def check_products(p):
    n = len(p)
    brand, cat = p["brand"].str.strip(), p["category"].str.strip()
    miscased = (~brand.isin(BRANDS) & norm_case(brand, BRANDS).isin(BRANDS)) | \
               (~cat.isin(CATEGORIES) & norm_case(cat, CATEGORIES).isin(CATEGORIES))
    check("P01", "known", "Brand or category in wrong case", int(miscased.sum()), n)
    unk = ~norm_case(brand, BRANDS).isin(BRANDS) | ~norm_case(cat, CATEGORIES).isin(CATEGORIES)
    check("P02", "blocker", "Unknown brand or category (after case fix)", int(unk.sum()), n,
          examples((brand + " / " + cat)[unk]))
    sku = p["sku"].str.strip()
    dup = sku.str.upper().duplicated(keep=False)
    check("P03", "blocker", "Duplicate sku", int(dup.sum()), n, examples(sku[dup]))
    lp = num(p["list_price"])
    bad = lp.isna() | (lp <= 0)
    check("P04", "blocker", "list_price missing or <= 0", int(bad.sum()), n, examples(sku[bad]))


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
def check_inventory(inv, products, orders, order_dates, stock_keys=None):
    n = len(inv)
    m = inv["stk_month"].str.strip()
    short = m.str.match(r"^\d{4}-\d$")
    check("I01", "known", "stk_month written as YYYY-M (no leading zero)", int(short.sum()), n)
    ok = m.str.match(r"^\d{4}-\d{1,2}$")
    month = pd.Series(pd.NaT, index=m.index, dtype="period[M]")
    month[ok] = pd.PeriodIndex(m[ok], freq="M")
    check("I04", "blocker", "stk_month in unknown format", int((~ok).sum()), n, examples(m[~ok]))

    r = inv["reserved_qty"].str.strip()
    check("I02", "known", "reserved_qty empty (dropped from export)", int((r == "").sum()), n)
    check("I03", "blocker", "reserved_qty has values (was dropped, now back?)", int((r != "").sum()), n)

    q = num(inv["qty_hand"])
    bad_q = q.isna() | (q < 0)
    check("I05", "blocker", "qty_hand missing or negative", int(bad_q.sum()), n)

    art = inv["art_no"].str.strip()
    dup = pd.DataFrame({"a": art, "m": month}).duplicated(keep=False)
    check("I06", "blocker", "Duplicate art_no + month", int(dup.sum()), n, examples(art[dup]))

    if products is not None:
        not_cat = ~art.isin(products["sku"].str.strip())
        check("I07", "blocker", "art_no not in products", int(not_cat.sum()), n, examples(art[not_cat]))
    else:
        not_run("I07", "blocker", "art_no not in products", "products file missing")

    if orders is not None and order_dates is not None:
        sold = pd.DataFrame({"a": orders["ART_NO"].str.strip(),
                             "m": order_dates.dt.to_period("M")}).dropna().drop_duplicates()
        have = stock_keys if stock_keys is not None else set(zip(art, month))   # history + this delivery
        missing = [f"{a} {mm}" for a, mm in zip(sold["a"], sold["m"]) if (a, mm) not in have]
        check("I08", "blocker", "Article sold in a month with no stock row", len(missing), len(sold),
              examples(missing))
    else:
        not_run("I08", "blocker", "Article sold in a month with no stock row", "orders file missing")


# ---------------------------------------------------------------------------
# History: earlier deliveries (data/raw/<earlier month>/)
# ---------------------------------------------------------------------------
H_CHECKS = [
    ("H01", "blocker", "Order number already loaded in an earlier delivery (would count twice)"),
    ("H02", "blocker", "Stock row (art_no + month) already loaded in an earlier delivery"),
    ("H03", "blocker", "Existing sku with a different product_name, brand or category than loaded"),
    ("H04", "known", "Existing sku with a new list_price (updated in the products table)"),
    ("H05", "known", "New sku (added to the products table)"),
]


def earlier_deliveries(raw, run):
    """Delivery folders next to this one, named YYYY-MM and before the run, oldest first."""
    root = raw.resolve().parent
    return sorted((d for d in root.iterdir()
                   if d.is_dir() and len(d.name) == 7 and d.name[4] == "-" and d.name.replace("-", "").isdigit()
                   and d.name < run and all((d / f"{n}.csv").exists() for n in COLUMNS)),
                  key=lambda d: d.name)


def read_history(folders):
    """Orders, products (newest delivery wins per sku) and stock rows of all earlier deliveries."""
    def rd(d, n):
        df = pd.read_csv(d / f"{n}.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
        return df.apply(lambda c: c.str.strip())
    orders = pd.concat([rd(d, "orders") for d in folders], ignore_index=True)
    products = pd.concat([rd(d, "products").assign(_d=d.name) for d in folders], ignore_index=True)
    products = products.sort_values("_d", kind="stable").drop_duplicates("sku", keep="last").drop(columns="_d")
    inv = pd.concat([rd(d, "inventory") for d in folders], ignore_index=True)
    return orders, products, inv


def month_keys(inv):
    """{(art_no, Period)} for stock rows with a readable month."""
    m = inv["stk_month"].str.strip()
    ok = m.str.match(r"^\d{4}-\d{1,2}$")
    return set(zip(inv.loc[ok, "art_no"].str.strip(), pd.PeriodIndex(m[ok], freq="M")))


def check_history(o, p, inv, hist):
    """H checks: the new delivery against everything loaded before."""
    if hist is None:
        for cid, label, name in H_CHECKS:
            check(cid, label, name, 0, detail="first delivery - no history yet")
        return
    h_orders, h_products, h_inv = hist
    (c1, l1, n1), (c2, l2, n2), (c3, l3, n3), (c4, l4, n4), (c5, l5, n5) = H_CHECKS

    new_ids = set(o["ORD_NO"].str.strip())
    again = sorted(new_ids & set(h_orders["ORD_NO"]))
    check(c1, l1, n1, len(again), len(new_ids), examples(again))

    keys = month_keys(inv)
    loaded = sorted(f"{a} {mm}" for a, mm in keys & month_keys(h_inv))
    check(c2, l2, n2, len(loaded), len(keys), examples(loaded))

    cur = p.apply(lambda c: c.str.strip())
    both = cur.merge(h_products, on="sku", suffixes=("", "_old"))
    changed = (both["product_name"] != both["product_name_old"]) | \
              (norm_case(both["brand"], BRANDS) != norm_case(both["brand_old"], BRANDS)) | \
              (norm_case(both["category"], CATEGORIES) != norm_case(both["category_old"], CATEGORIES))
    check(c3, l3, n3, int(changed.sum()), len(both),
          examples(both.loc[changed, "sku"] + ": " + both.loc[changed, "product_name_old"] + " / "
                   + both.loc[changed, "category_old"] + " -> " + both.loc[changed, "product_name"] + " / "
                   + both.loc[changed, "category"]))
    price = (num(both["list_price"]) - num(both["list_price_old"])).abs() > 0.005
    check(c4, l4, n4, int(price.sum()), len(both),
          examples(both.loc[price, "sku"] + " " + both.loc[price, "list_price_old"] + " -> " + both.loc[price, "list_price"]))
    new_skus = cur.loc[~cur["sku"].isin(h_products["sku"]), "sku"]
    check(c5, l5, n5, len(new_skus), len(cur), examples(new_skus))


def catalogue(p, hist):
    """Products the new orders and stock rows may use: history, updated by this delivery (newest wins)."""
    if p is None:
        return None
    cur = p.apply(lambda c: c.str.strip())
    if hist is None:
        return cur
    return pd.concat([hist[1][~hist[1]["sku"].isin(cur["sku"])], cur], ignore_index=True)


# ---------------------------------------------------------------------------
def report(run, raw, expect_month):
    order = {"S": 0, "O": 1, "P": 2, "I": 3, "H": 4}
    rows = sorted(results, key=lambda r: (order[r["id"][0]], r["id"]))
    blockers = [r for r in rows if r["label"] == "blocker" and r["status"] == "FAIL"]
    not_ran = [r for r in rows if r["status"] == "NOT RUN" and not r["id"] == "O05"]
    known = [r for r in rows if r["label"] == "known" and r["status"] == "FAIL"]
    verdict = "STOP - blockers found" if blockers or not_ran else "OK - no blockers"

    md = [f"# Raw data check - run {run}", "",
          f"Data: `{raw}`" + (f" · expected month: {expect_month}" if expect_month else ""), "",
          f"**Verdict: {verdict}**  ·  blockers failing: {len(blockers)}  ·  "
          f"known issues present: {len(known)}  ·  checks: {len(rows)}", "",
          "FAIL = the case is present. *known* = decided, reported, run continues. *blocker* = stop and ask.", "",
          "| ID | Label | Check | Result | Found | Detail |", "|---|---|---|---|---|---|"]
    for r in rows:
        res = f"**{r['status']}**" if r["status"] == "FAIL" and r["label"] == "blocker" else r["status"]
        md.append(f"| {r['id']} | {r['label']} | {r['name']} | {res} | {r['found']} | {r['detail']} |")

    print(f"Raw data check - run {run}   ({raw})")
    print(f"{'ID':<4} {'label':<8} {'result':<8} {'found':>18}  check")
    for r in rows:
        print(f"{r['id']:<4} {r['label']:<8} {r['status']:<8} {r['found']:>18}  {r['name']}"
              + (f"  [{r['detail']}]" if r["detail"] else ""))
    print(f"\nVerdict: {verdict}  (blockers failing: {len(blockers)}, known issues present: {len(known)})")

    out = Path("runs") / run / "1-profile" / "profile-checks.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Saved to {out}")
    return 1 if blockers or not_ran else 0


def main():
    ap = argparse.ArgumentParser(description="Pass/fail checks on the raw shop export.")
    ap.add_argument("--run", required=True, help="Run folder name, e.g. 2026-08")
    ap.add_argument("--raw", help="Delivery folder with orders/products/inventory .csv (default: data/raw/<run>)")
    ap.add_argument("--expect-month", help="Month the orders should cover, e.g. 2026-08 (optional)")
    args = ap.parse_args()
    raw = Path(args.raw) if args.raw else Path("data/raw") / args.run

    files = check_structure(raw)
    struct_ok = all(r["status"] == "PASS" for r in results)
    o, p, inv = files.get("orders"), files.get("products"), files.get("inventory")

    if not struct_ok:
        # Column checks below would give misleading results on a changed file layout
        for cid, name in [("O", "orders checks"), ("P", "products checks"), ("I", "inventory checks")]:
            not_run(f"{cid}00", "blocker", name, "structure check failed - fix structure first")
    else:
        earlier = earlier_deliveries(raw, args.run)
        hist = read_history(earlier) if earlier else None
        cat = catalogue(p, hist)          # orders and stock may use products loaded in earlier deliveries
        dates = check_orders(o, cat, args.expect_month)
        check_products(p)
        check_inventory(inv, cat, o, dates, stock_keys=month_keys(inv) | (month_keys(hist[2]) if hist else set()))
        check_history(o, p, inv, hist)
        if earlier:
            print(f"History (earlier deliveries): {', '.join(d.name for d in earlier)}")

    return report(args.run, raw, args.expect_month)


if __name__ == "__main__":
    sys.exit(main())
