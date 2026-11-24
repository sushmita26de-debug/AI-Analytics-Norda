"""
Profile the raw NORDA shop export: every column of every file, plus business checks.

Read-only: never modifies the raw folder.
Output: printed to screen and saved to runs/<run>/1-profile/profile-output.txt

Run from the project root:
    python .claude/skills/profile/profile.py --run 2026-08
    python .claude/skills/profile/profile.py --run 2026-09 --raw data/raw/2026-09
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True   # no __pycache__ folder next to the scripts
# The rules live in check.py so both scripts stay in sync
from check import (BRANDS, CATEGORIES, CHANNELS, COUNTRY_NAMES, EXTRA_COUNTRIES,
                   MARKETS, parse_dates)

EXPECTED_COUNTRIES = MARKETS
EXPECTED_CHANNELS = CHANNELS
EXPECTED_CATEGORIES = CATEGORIES
EXPECTED_BRANDS = BRANDS
EXCL = sorted(EXTRA_COUNTRIES)
EXCL_LABEL = "+".join(EXCL)

lines = []


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def out(text=""):
    print(text)
    lines.append(str(text))


def section(title):
    out()
    out("=" * 80)
    out(title)
    out("=" * 80)


def pct(n, total):
    return f"{n:,} ({n / total:.2%})" if total else f"{n:,}"


def d(counts):
    """Value counts as a plain dict, so the printout has no numpy types."""
    return {str(k): int(v) for k, v in counts.items()}


def by_group(mask_or_values, groups, fmt="{:.1%}"):
    """One line: share/value per group, e.g. 'app=5.0%, web=3.1%'."""
    s = pd.Series(mask_or_values).groupby(groups).mean()
    return ", ".join(f"{k}={fmt.format(v)}" for k, v in s.items())


def table(df):
    return "      " + df.to_string().replace("\n", "\n      ")


def shape_of(value):
    """Turn a value into a pattern: digits -> 9, letters -> A. '01/01/2025' -> '99/99/9999'."""
    s = re.sub(r"[0-9]", "9", value)
    return re.sub(r"[A-Za-z]", "A", s)


def to_number(series):
    """Convert text to numbers; return (numbers, values that could not be converted)."""
    num = pd.to_numeric(series.str.strip(), errors="coerce")
    bad = series[(series.str.strip() != "") & num.isna()]
    return num, bad


# ---------------------------------------------------------------------------
# 1. Generic profile: every column of every file, raw text as delivered
# ---------------------------------------------------------------------------
def profile_file(name, df):
    section(f"FILE: {name}.csv")
    total = len(df)
    out(f"Rows: {total:,}   Columns: {len(df.columns)}")
    out(f"Columns: {list(df.columns)}")
    out(f"Fully duplicated rows: {pct(int(df.duplicated().sum()), total)}")

    for col in df.columns:
        s = df[col]
        out()
        out(f"--- {name}.{col}")
        blank = s.str.strip() == ""
        out(f"  blank/empty:            {pct(int(blank.sum()), total)}")
        filled = s[~blank]
        out(f"  distinct values:        {filled.nunique():,}")
        out(f"  leading/trailing space: {pct(int((filled != filled.str.strip()).sum()), total)}")

        # Same value written in different case / spacing
        norm = filled.str.strip().str.lower()
        variants = filled.groupby(norm).nunique()
        variants = variants[variants > 1]
        if len(variants):
            out(f"  case/space variants:    {len(variants)} values written >1 way:")
            for key in variants.index:
                out(f"      {d(filled[norm == key].value_counts())}")

        # Formats
        shapes_all = filled.map(shape_of)
        shapes = shapes_all.value_counts()
        out(f"  formats (top 6 of {len(shapes)}):")
        for shp, n in shapes.head(6).items():
            example = filled[shapes_all == shp].iloc[0]
            out(f"      {shp!r:<22} {pct(int(n), total):<22} e.g. {example!r}")

        # Numeric summary if mostly numeric, else top values
        num, bad = to_number(s)
        if num.notna().sum() > 0.5 * max(len(filled), 1):
            out(f"  numeric: min={num.min()}  max={num.max()}  mean={num.mean():.2f}  "
                f"median={num.median()}")
            out(f"  zero: {pct(int((num == 0).sum()), total)}   "
                f"negative: {pct(int((num < 0).sum()), total)}   "
                f"not a number: {pct(len(bad), total)}")
            if len(bad):
                out(f"      non-numeric examples: {list(bad.unique()[:8])}")
        else:
            out("  top values:")
            for v, n in filled.value_counts().head(10).items():
                out(f"      {v!r:<35} {pct(int(n), total)}")


# ---------------------------------------------------------------------------
# 2. Orders
# ---------------------------------------------------------------------------
def check_orders(o, products):
    section("CHECKS: orders")
    total = len(o)
    raw_cols = list(o.columns)

    # --- Dates
    out("Dates (CRTD_DT):")
    dt, used = parse_dates(o["CRTD_DT"])
    for label, n in used.value_counts().items():
        out(f"  format {label:<12} {pct(int(n), total)}")
    out(f"  could not parse: {pct(int(dt.isna().sum()), total)}")
    if dt.isna().any():
        out(f"      examples: {list(o.loc[dt.isna(), 'CRTD_DT'].unique()[:8])}")
    out(f"  range: {dt.min().date()} -> {dt.max().date()}")

    # Slash dates: DD/MM or MM/DD?
    raw_dt = o["CRTD_DT"].str.strip()
    slash = raw_dt.str.match(r"^\d{2}/\d{2}/\d{4}$")
    parts = raw_dt[slash].str.split("/", expand=True).astype(int)
    out(f"  slash dates with first part > 12 (only possible as DD/MM):  {pct(int((parts[0] > 12).sum()), total)}")
    out(f"  slash dates with second part > 12 (only possible as MM/DD): {pct(int((parts[1] > 12).sum()), total)}")
    ambiguous = pd.Series(False, index=o.index)
    ambiguous[parts.index] = (parts[0] <= 12) & (parts[1] <= 12) & (parts[0] != parts[1])
    out(f"  slash dates ambiguous (both <= 12, day != month):           {pct(int(ambiguous.sum()), total)}")

    # Cross-check with order numbers: they are sequential, so dates should rise with them
    ordn = pd.to_numeric(o["ORD_NO"].str[2:], errors="coerce")
    first_dt = pd.DataFrame({"n": ordn, "dt": dt}).groupby("n")["dt"].first().sort_index()
    out(f"  orders dated earlier than the previous order number (reading DD/MM): "
        f"{int((first_dt.diff().dt.days < 0).sum()):,} of {len(first_dt):,}")
    alt_dt = dt.copy()
    alt_dt[ambiguous] = pd.to_datetime(raw_dt[ambiguous], format="%m/%d/%Y")
    alt_first = pd.DataFrame({"n": ordn, "dt": alt_dt}).groupby("n")["dt"].first().sort_index()
    out(f"  same check if ambiguous dates were read as MM/DD:                  "
        f"{int((alt_first.diff().dt.days < 0).sum()):,} of {len(alt_first):,}")

    o = o.assign(_date=dt, _month=dt.dt.to_period("M"))
    out("  rows per month:")
    for m, n in o["_month"].value_counts().sort_index().items():
        out(f"      {m}  {n:,}")
    out("  date format per month:")
    out(table(pd.crosstab(o["_month"], used)))

    alldays = pd.date_range(dt.min(), dt.max(), freq="D")
    daily = dt.dt.normalize().value_counts().reindex(alldays, fill_value=0)
    out(f"  calendar days with no order rows: {int((daily == 0).sum())}  "
        f"{[str(x.date()) for x in daily[daily == 0].index[:40]]}")
    out(f"  rows per day: min={daily.min()} median={daily.median():.0f} max={daily.max()}")
    out(f"  lowest 10 days:  {[(str(k.date()), int(v)) for k, v in daily.nsmallest(10).items()]}")
    out(f"  highest 10 days: {[(str(k.date()), int(v)) for k, v in daily.nlargest(10).items()]}")
    out("  average rows per day by month: "
        + ", ".join(f"{k}={v:.0f}" for k, v in daily.groupby(daily.index.to_period('M')).mean().items()))

    # --- Channel / country
    out()
    chn = o["CHNL"].str.strip()
    out(f"Channel values not in {sorted(EXPECTED_CHANNELS)}: "
        f"{pct(int((~chn.isin(EXPECTED_CHANNELS)).sum()), total)}")
    ctry = o["CTRY"].str.strip()
    out(f"Country values not in {sorted(EXPECTED_COUNTRIES)}: "
        f"{pct(int((~ctry.isin(EXPECTED_COUNTRIES)).sum()), total)}")
    out(f"  {d(ctry[~ctry.isin(EXPECTED_COUNTRIES)].value_counts())}")
    ctry_n = ctry.replace(COUNTRY_NAMES)
    o = o.assign(_ctry=ctry_n)
    full_name = ctry != ctry_n
    out(f"  full country names instead of codes: {pct(int(full_name.sum()), total)}")
    out(f"  after mapping names to codes: {d(ctry_n.value_counts())}")
    out(f"  full names by channel: {d(chn[full_name].value_counts())}")
    out(f"  {EXCL_LABEL} (outside the 4 markets) share of rows by month: {by_group(ctry_n.isin(EXCL), o['_month'])}")
    out(f"  {EXCL_LABEL} share of rows by channel: {by_group(ctry_n.isin(EXCL), chn)}")
    out("  rows by channel x country (mapped):")
    out(table(pd.crosstab(chn, ctry_n, margins=True)))

    # --- Customer ref
    out()
    has_cust = o["CUST_REF"].str.strip() != ""
    out("Customer ref filled, by channel:")
    for ch, g in o.groupby(chn):
        out(f"  {ch:<14} {pct(int(has_cust[g.index].sum()), len(g))} of {len(g):,} rows")
    out(f"  marketplace rows with customer ref, by month: "
        f"{by_group(has_cust[chn == 'marketplace'], o.loc[chn == 'marketplace', '_month'])}")
    mk_cust = set(o.loc[(chn == "marketplace") & has_cust, "CUST_REF"])
    own_cust = set(o.loc[(chn != "marketplace") & has_cust, "CUST_REF"])
    out(f"  marketplace customer refs also seen on web/app: {len(mk_cust & own_cust):,} of {len(mk_cust):,}")

    # --- Quantity / price / discount
    out()
    qty, _ = to_number(o["QTY"])
    prc, _ = to_number(o["UNIT_PRC"])
    disc, _ = to_number(o["DISC_PCT"])
    out(f"QTY <= 0: {pct(int((qty <= 0).sum()), total)}   non-integer: "
        f"{pct(int((qty.notna() & (qty % 1 != 0)).sum()), total)}   max={qty.max()}")
    out(f"  QTY distribution: {d(qty.value_counts().sort_index())}")
    out(f"UNIT_PRC <= 0: {pct(int((prc <= 0).sum()), total)}")
    out(f"DISC_PCT range: {disc.min()} -> {disc.max()}   values: {d(disc.value_counts().sort_index())}")
    out(f"  rows with discount > 0: {pct(int((disc > 0).sum()), total)}")
    out(f"  by channel: {by_group(disc > 0, chn)}")
    out(f"  by month:   {by_group(disc > 0, o['_month'])}")

    # --- Price vs catalogue list price
    out()
    art = o["ART_NO"].str.strip()
    sku = products["sku"].str.strip()
    list_price = pd.to_numeric(products["list_price"].str.strip(), errors="coerce")
    lp = art.map(pd.Series(list_price.values, index=sku))
    ratio = prc / lp
    r = ratio.dropna()
    out("UNIT_PRC / catalogue list_price:")
    out(f"  rows compared: {len(r):,}")
    out("  quantiles: " + ", ".join(f"p{int(q*100)}={r.quantile(q):.3f}"
                                    for q in [0, .01, .05, .25, .5, .75, .95, .99, 1]))
    out(f"  equal to list (within 0.1%): {pct(int(((r >= 0.999) & (r <= 1.001)).sum()), total)}")
    out(f"  above list:                   {pct(int((r > 1.001).sum()), total)}")
    out(f"  below list:                   {pct(int((r < 0.999).sum()), total)}")
    out(f"  far off (>1.5x or <0.5x):     {pct(int(((r > 1.5) | (r < 0.5)).sum()), total)}")
    out(f"  share above list, by channel: {by_group(ratio > 1.001, chn)}")
    out(f"  share below list, by channel: {by_group(ratio < 0.999, chn)}")
    out(f"  median ratio by channel:      {by_group(ratio, chn, '{:.3f}')}")
    out(f"  share above list, by month:   {by_group(ratio > 1.001, o['_month'])}")

    pa = pd.DataFrame({"art": art, "prc": prc, "chn": chn})
    nprices = pa.groupby("art")["prc"].nunique()
    out(f"Distinct unit prices per article: median={nprices.median()}, max={nprices.max()}, "
        f"articles with >1 price: {int((nprices > 1).sum())} of {len(nprices)}")
    per_chn = pa.groupby(["art", "chn"])["prc"].nunique()
    out(f"  article+channel combinations with >1 price: {int((per_chn > 1).sum())} of {len(per_chn)}")
    for a in nprices[nprices > 1].index[:3]:
        t = pa[pa["art"] == a].groupby(["chn", "prc"]).size()
        out(f"  e.g. {a} (list {lp[art == a].iloc[0]}): "
            f"{[(c, float(p_), int(n)) for (c, p_), n in t.items()]}")

    # --- Duplicates
    out()
    raw_dup_all = o[raw_cols].duplicated(keep=False)
    raw_dup_extra = o[raw_cols].duplicated(keep="first")
    key_dup = o.duplicated(subset=["ORD_NO", "ART_NO"], keep=False)
    out(f"Rows sharing ORD_NO+ART_NO with another row: {pct(int(key_dup.sum()), total)}")
    out(f"Rows that are exact copies of another row:   {pct(int(raw_dup_all.sum()), total)}")
    out(f"  extra copies (rows to drop if they are true duplicates): {int(raw_dup_extra.sum()):,}")
    norm = o[raw_cols].assign(CRTD_DT=o["_date"].astype(str), CTRY=o["_ctry"])
    out(f"  extra copies after normalising date + country: {int(norm.duplicated().sum()):,}")
    out(f"  extra copies by month:   {d(o.loc[raw_dup_extra, '_month'].value_counts().sort_index())}")
    out(f"  extra copies by channel: {d(chn[raw_dup_extra].value_counts())}")
    out(f"  copies per duplicated line: {d(o[raw_dup_all].groupby(raw_cols).size().value_counts())}")

    # --- Order-level consistency
    out()
    lines_per_order = o.groupby("ORD_NO").size()
    out(f"Distinct orders: {o['ORD_NO'].nunique():,}   lines per order: "
        f"mean={lines_per_order.mean():.2f} max={lines_per_order.max()}")
    for col, label in [("_date", "date"), ("CTRY", "country (raw)"), ("_ctry", "country (mapped)"),
                       ("CHNL", "channel"), ("CUST_REF", "customer")]:
        n = o.groupby("ORD_NO")[col].nunique(dropna=False)
        out(f"  orders with >1 {label:<17}: {pct(int((n > 1).sum()), len(n))}")
    out(f"ORD_NO number range: {ordn.min():.0f} -> {ordn.max():.0f}  "
        f"(numbers in range not present: {int(ordn.max() - ordn.min() + 1 - ordn.nunique()):,})")

    # --- Articles vs catalogue
    out()
    out(f"Order rows whose ART_NO is not in products: {pct(int((~art.isin(sku)).sum()), total)}")

    # --- Money: what the issues are worth
    # DISC_PCT is 0..0.5 in the file, so it is treated as a fraction here (assumption)
    gross = qty * prc
    net = gross * (1 - disc.fillna(0))
    out()
    out("Line value by month (EUR). 'after disc' assumes DISC_PCT is a fraction (0.15 = 15%):")
    t = pd.DataFrame({
        "m": o["_month"], "qty_x_price": gross, "after_disc": net,
        "dup_copies": net.where(raw_dup_extra, 0),
        "extra_ctry": net.where(ctry_n.isin(EXCL), 0),
        "above_list_uplift": (qty * (prc - lp)).where(ratio > 1.001, 0),
    }).groupby("m").sum()
    t.loc["total"] = t.sum()
    out(table(t.round(0).astype("int64").map(lambda v: f"{v:,}")))

    out("  top 5 single lines by value:")
    top = o.assign(_value=net).nlargest(5, "_value")[["ORD_NO", "CRTD_DT", "CHNL", "ART_NO", "QTY", "UNIT_PRC", "_value"]]
    out(table(top))
    return o


# ---------------------------------------------------------------------------
# 3. Products
# ---------------------------------------------------------------------------
def check_products(p):
    section("CHECKS: products")
    total = len(p)
    sku = p["sku"].str.strip()
    out(f"Duplicate sku: {pct(int(sku.duplicated(keep=False).sum()), total)}   "
        f"ignoring case: {int(sku.str.upper().duplicated().sum())}")

    brand = p["brand"].str.strip()
    catg = p["category"].str.strip()
    bad_b = ~brand.isin(EXPECTED_BRANDS)
    bad_c = ~catg.isin(EXPECTED_CATEGORIES)
    out(f"Brand not written exactly as expected:    {pct(int(bad_b.sum()), total)}  {d(brand[bad_b].value_counts())}")
    out(f"Category not written exactly as expected: {pct(int(bad_c.sum()), total)}  {d(catg[bad_c].value_counts())}")
    out(f"Either miscased: {pct(int((bad_b | bad_c).sum()), total)}")
    out(f"Unknown brand/category even after fixing case: "
        f"{int((~brand.str.title().isin(EXPECTED_BRANDS)).sum())} / "
        f"{int((~catg.str.title().str.replace('And', 'and').isin(EXPECTED_CATEGORIES)).sum())}")
    out("Brand x category (case-normalised):")
    out(table(pd.crosstab(brand.str.title(), catg.str.title())))
    out("SKU prefix x brand (case-normalised):")
    out(table(pd.crosstab(sku.str[:2], brand.str.title())))

    starts = [n.strip().lower().startswith(b.lower()) for n, b in zip(p["product_name"], brand)]
    out(f"product_name does not start with brand: {total - sum(starts)}")
    out(f"Same product_name on more than one sku: {int(p['product_name'].str.strip().duplicated().sum())}")

    lp, _ = to_number(p["list_price"])
    out(f"list_price <= 0: {int((lp <= 0).sum())}   blank/non-numeric: {int(lp.isna().sum())}")
    out("list_price by category (case-normalised):")
    out(table(pd.DataFrame({"c": catg.str.title(), "p": lp}).groupby("c")["p"].describe().round(2)))


# ---------------------------------------------------------------------------
# 4. Inventory
# ---------------------------------------------------------------------------
def check_inventory(inv, products, orders):
    section("CHECKS: inventory")
    total = len(inv)
    art = inv["art_no"].str.strip()
    shapes = inv["stk_month"].map(shape_of)
    out(f"stk_month formats: {d(shapes.value_counts())}")
    out(f"  short-format rows: {inv[shapes == '9999-9'].values.tolist()}")
    month = pd.PeriodIndex(inv["stk_month"].str.strip(), freq="M").astype(str)
    inv = inv.assign(_m=month)
    out(f"stk_month range (normalised): {min(month)} -> {max(month)}")
    out(f"Rows per month (normalised): {d(inv['_m'].value_counts().sort_index())}")
    dup = inv.duplicated(subset=["art_no", "_m"], keep=False)
    out(f"Duplicate art_no+month after normalising: {pct(int(dup.sum()), total)}")

    q, _ = to_number(inv["qty_hand"])
    r, _ = to_number(inv["reserved_qty"])
    out(f"qty_hand negative: {int((q < 0).sum())}   zero: {pct(int((q == 0).sum()), total)}   "
        f"blank: {int(q.isna().sum())}")
    out(f"reserved_qty filled: {pct(int(r.notna().sum()), total)}")

    sku = products["sku"].str.strip()
    out(f"Inventory art_no not in products: {art[~art.isin(sku)].nunique()}")
    out(f"Products with no inventory rows: {list(sku[~sku.isin(art)])}")

    first_stock = inv.assign(a=art).groupby("a")["_m"].min()
    last_stock = inv.assign(a=art).groupby("a")["_m"].max()
    n_months = inv.assign(a=art).groupby("a")["_m"].nunique()
    span = [pd.Period(l, "M").ordinal - pd.Period(f, "M").ordinal + 1 for f, l in zip(first_stock, last_stock)]
    out(f"Articles with a stock row every month {min(month)}..{max(month)}: "
        f"{int((n_months == n_months.max()).sum())} of {len(n_months)}")
    out(f"Articles with a missing month between first and last row: "
        f"{int((pd.Series(span, index=n_months.index) > n_months).sum())}")
    out(f"Articles whose last row is before {max(month)}: {int((last_stock < max(month)).sum())}")
    out(f"First stock month per article: {d(first_stock.value_counts().sort_index())}")

    oart = orders["ART_NO"].str.strip()
    odt, _ = parse_dates(orders["CRTD_DT"])
    sold = pd.DataFrame({"art": oart, "m": odt.dt.to_period("M").astype(str)}).drop_duplicates()
    have = set(zip(art, inv["_m"]))
    no_row = [(a, m) for a, m in zip(sold["art"], sold["m"]) if (a, m) not in have]
    out(f"Article-months with sales but no stock row: {len(no_row)}  e.g. {no_row[:8]}")
    first_sale = sold.groupby("art")["m"].min()
    out(f"Articles first sold before their first stock row: "
        f"{int((first_sale.reindex(first_stock.index) < first_stock).sum())}")
    out(f"Articles first sold in the same month as their first stock row: "
        f"{int((first_sale.reindex(first_stock.index) == first_stock).sum())}")
    zs = set(zip(art[q == 0], inv.loc[q == 0, "_m"]))
    out(f"Article-months with month-end stock 0 that also had sales: "
        f"{sum((a, m) in zs for a, m in zip(sold['art'], sold['m']))} of {len(zs)}")


def check_catalogue_coverage(orders, products):
    section("CHECKS: catalogue coverage")
    sku = products["sku"].str.strip()
    oart = orders["ART_NO"].str.strip()
    never = sku[~sku.isin(oart)]
    out(f"Catalogue articles never sold: {never.nunique()} of {sku.nunique()}")
    if len(never):
        out(table(products[sku.isin(never)]))


def main():
    ap = argparse.ArgumentParser(description="Profile the raw shop export.")
    ap.add_argument("--run", required=True, help="Run folder name, e.g. 2026-08")
    ap.add_argument("--raw", help="Delivery folder with orders/products/inventory .csv (default: data/raw/<run>)")
    args = ap.parse_args()
    raw = Path(args.raw) if args.raw else Path("data/raw") / args.run   # one folder per delivery
    out_file = Path("runs") / args.run / "1-profile" / "profile-output.txt"

    files = {}
    for name in ["orders", "products", "inventory"]:
        path = raw / f"{name}.csv"
        raw_bytes = path.read_bytes()
        bom = "UTF-8 BOM" if raw_bytes.startswith(b"\xef\xbb\xbf") else "no BOM"
        # Read everything as text: we want to see what was delivered, not what pandas guesses
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        files[name] = df
        out(f"{name}.csv: {path.stat().st_size:,} bytes, {bom}, CRLF line endings: {raw_bytes.count(b'\r\n'):,}")

    for name, df in files.items():
        profile_file(name, df)

    check_orders(files["orders"], files["products"])
    check_products(files["products"])
    check_inventory(files["inventory"], files["products"], files["orders"])
    check_catalogue_coverage(files["orders"], files["products"])

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSaved to {out_file}")


if __name__ == "__main__":
    sys.exit(main())
