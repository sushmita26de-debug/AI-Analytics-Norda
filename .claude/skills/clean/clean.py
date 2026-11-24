"""
Clean one monthly NORDA delivery and combine it with the history.

    data/raw/<run>/  ->  data/clean/<run>/      this delivery, cleaned
    data/clean/<every delivery>/  ->  data/clean/all/   the combined history the model is built from:
        orders     appended (every delivery's orders, once)
        inventory  appended (every delivery's stock rows, once)
        products   new skus added; existing skus get the newest delivery's latest_list_price

Applies the decisions in knowledge/metadata.md. Never modifies data/raw.
Stops and writes nothing if the raw data contains something the rules below don't cover
(new date format, unknown country, ...), or if the delivery overlaps the history (an order number
or a stock row already loaded, or an existing sku with a new name, brand or category).
Run the /profile skill first: it reports the same cases as blockers.

Run from the project root:
    python .claude/skills/clean/clean.py --run 2026-08
Writes:
    data/clean/<run>/orders.csv, products.csv, inventory.csv
    data/clean/all/orders.csv, products.csv, inventory.csv   (rebuilt from all delivery folders)
    runs/<run>/2-clean/clean-log.md
"""
import re
import argparse
import json
import sys
from datetime import datetime
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
MARKETS = set(RULES["core_markets"])             # core markets -> is_core_market = True
EXTRA_COUNTRIES = set(RULES["extra_countries"])  # kept for now, is_core_market = False
COUNTRY_NAMES = {name: code for code, name in RULES["country_names"].items()}  # full name in raw file -> code
CHANNELS = set(RULES["channels"])
BRANDS = set(RULES["brands"])
CATEGORIES = set(RULES["categories"])
DISC_MAX = 0.5

RAW_COLUMNS = {
    "orders": ["ORD_NO", "CRTD_DT", "CHNL", "CTRY", "CUST_REF", "ART_NO", "QTY", "UNIT_PRC", "DISC_PCT"],
    "products": ["sku", "product_name", "brand", "category", "list_price"],
    "inventory": ["art_no", "stk_month", "qty_hand", "reserved_qty"],
}

# Clean layer: raw name -> clean name, in output order. New columns are added in clean_*().
CLEAN_COLUMNS = {
    "orders": ["order_id", "order_date", "channel", "country_code", "is_core_market", "customer_id",
               "sku", "quantity", "unit_price", "discount_rate"],
    "products": ["sku", "product_name", "brand", "category", "latest_list_price"],
    "inventory": ["sku", "stock_month", "qty_on_hand"],
}


class RawDataError(Exception):
    """Raw data contains something the cleaning rules do not cover."""


def stop_if(mask, what, values):
    if mask.any():
        ex = list(pd.Series(values[mask]).unique()[:5])
        raise RawDataError(f"{what}: {int(mask.sum())} rows, e.g. {ex}. Run /profile and decide first.")


def read_raw(raw, name):
    df = pd.read_csv(raw / f"{name}.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if list(df.columns) != RAW_COLUMNS[name]:
        raise RawDataError(f"{name}.csv columns changed: {list(df.columns)}")
    return df


def parse_order_dates(s):
    """YYYY-MM-DD and DD/MM/YYYY -> datetime. Anything else stops the run."""
    iso = s.str.match(r"^\d{4}-\d{2}-\d{2}$")
    slash = s.str.match(r"^\d{2}/\d{2}/\d{4}$")
    stop_if(~(iso | slash), "Unknown date format", s)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out[iso] = pd.to_datetime(s[iso], format="%Y-%m-%d", errors="coerce")
    out[slash] = pd.to_datetime(s[slash], format="%d/%m/%Y", errors="coerce")
    stop_if(out.isna(), "Date that does not exist", s)
    return out


def norm_case(s, allowed):
    lookup = {a.lower(): a for a in allowed}
    return s.map(lambda v: lookup.get(v.lower(), v))


# ===========================================================================
# CLEANING
# ===========================================================================
def clean_orders(raw_df, log):
    o = raw_df.apply(lambda c: c.str.strip())
    log.append(("orders", "rows in (raw)", len(o)))

    # 1. Completely identical rows: keep one copy (decision 2026-11-24)
    dup = raw_df.duplicated(keep="first")
    o = o[~dup].copy()
    log.append(("orders", "removed: completely identical rows (extra copies)", int(dup.sum())))

    # 2. Dates -> YYYY-MM-DD (slash dates are DD/MM)
    n_slash = int(o["CRTD_DT"].str.contains("/").sum())
    o["order_date"] = parse_order_dates(o["CRTD_DT"]).dt.strftime("%Y-%m-%d")
    log.append(("orders", "changed: DD/MM/YYYY dates converted to YYYY-MM-DD", n_slash))

    # 3. Country names -> codes, flag core markets
    ctry = o["CTRY"].replace(COUNTRY_NAMES)
    log.append(("orders", "changed: full country name -> code", int((ctry != o["CTRY"]).sum())))
    stop_if(~ctry.isin(MARKETS | EXTRA_COUNTRIES), "Unknown country", ctry)
    o["country_code"] = ctry
    o["is_core_market"] = ctry.isin(MARKETS)
    log.append(("orders", "flagged: is_core_market = False (ES/AT, rows kept)", int((~o["is_core_market"]).sum())))

    # 4. Channel
    stop_if(~o["CHNL"].isin(CHANNELS), "Unknown channel", o["CHNL"])
    o["channel"] = o["CHNL"]

    # 5. Marketplace customer refs are ignored -> cleared (decision 2026-11-24)
    mk = (o["CHNL"] == "marketplace") & (o["CUST_REF"] != "")
    o["customer_id"] = o["CUST_REF"].where(~mk, "")
    log.append(("orders", "changed: customer_id cleared on marketplace rows", int(mk.sum())))

    # 6. Numbers
    o["quantity"] = pd.to_numeric(o["QTY"], errors="coerce")
    stop_if(o["quantity"].isna() | (o["quantity"] < 1) | (o["quantity"] % 1 != 0), "Bad quantity", o["QTY"])
    o["quantity"] = o["quantity"].astype("int64")
    o["unit_price"] = pd.to_numeric(o["UNIT_PRC"], errors="coerce")
    stop_if(o["unit_price"].isna() | (o["unit_price"] <= 0), "Bad unit price", o["UNIT_PRC"])
    o["discount_rate"] = pd.to_numeric(o["DISC_PCT"], errors="coerce")
    stop_if(o["discount_rate"].isna() | (o["discount_rate"] < 0) | (o["discount_rate"] > DISC_MAX),
            "Discount outside 0..0.5", o["DISC_PCT"])

    o["order_id"] = o["ORD_NO"]
    o["sku"] = o["ART_NO"]
    o = o[CLEAN_COLUMNS["orders"]].reset_index(drop=True)
    log.append(("orders", "rows out (clean)", len(o)))
    return o


def clean_products(raw_df, log):
    p = raw_df.apply(lambda c: c.str.strip())
    log.append(("products", "rows in (raw)", len(p)))
    for col, allowed in [("brand", BRANDS), ("category", CATEGORIES)]:
        fixed = norm_case(p[col], allowed)
        stop_if(~fixed.isin(allowed), f"Unknown {col}", p[col])
        log.append(("products", f"changed: {col} case fixed", int((fixed != p[col]).sum())))
        p[col] = fixed
    stop_if(p["sku"].duplicated(), "Duplicate sku", p["sku"])
    p["latest_list_price"] = pd.to_numeric(p["list_price"], errors="coerce")
    stop_if(p["latest_list_price"].isna() | (p["latest_list_price"] <= 0), "Bad list price", p["list_price"])
    p = p[CLEAN_COLUMNS["products"]]
    log.append(("products", "rows out (clean)", len(p)))
    return p


def clean_inventory(raw_df, log):
    i = raw_df.apply(lambda c: c.str.strip())
    log.append(("inventory", "rows in (raw)", len(i)))

    # reserved_qty was dropped from the export (decision 2026-11-24)
    stop_if(i["reserved_qty"] != "", "reserved_qty has values again", i["reserved_qty"])
    log.append(("inventory", "removed column: reserved_qty (always empty)", 0))

    ok = i["stk_month"].str.match(r"^\d{4}-\d{1,2}$")
    stop_if(~ok, "Unknown stock month format", i["stk_month"])
    month = pd.PeriodIndex(i["stk_month"], freq="M").strftime("%Y-%m")
    log.append(("inventory", "changed: stock month YYYY-M -> YYYY-MM", int((month != i["stk_month"]).sum())))
    i["stock_month"] = month

    i["qty_on_hand"] = pd.to_numeric(i["qty_hand"], errors="coerce")
    stop_if(i["qty_on_hand"].isna() | (i["qty_on_hand"] < 0) | (i["qty_on_hand"] % 1 != 0),
            "Bad qty on hand", i["qty_hand"])
    i["qty_on_hand"] = i["qty_on_hand"].astype("int64")
    i["sku"] = i["art_no"]
    stop_if(i.duplicated(subset=["sku", "stock_month"]), "Duplicate sku + month", i["sku"])
    i = i[CLEAN_COLUMNS["inventory"]]
    log.append(("inventory", "rows out (clean)", len(i)))
    return i


# ===========================================================================
# COMBINE: all delivery folders -> data/clean/all/
# ===========================================================================
ALL = "all"


def is_delivery(name):
    return re.fullmatch(r"\d{4}-\d{2}", name) is not None


def delivery_folders(clean_root):
    return sorted((d for d in clean_root.iterdir()
                   if d.is_dir() and is_delivery(d.name) and all((d / f"{n}.csv").exists() for n in CLEAN_COLUMNS)),
                  key=lambda d: d.name)


def read_clean(folder, name):
    return pd.read_csv(folder / f"{name}.csv", dtype=str, keep_default_na=False, encoding="utf-8")


def combine(deliveries, log):
    """deliveries: [(name, {file: DataFrame as text})], oldest first. Returns the combined files."""
    orders, inv, prods = [], [], []
    seen_orders, seen_stock = {}, {}
    for name, files in deliveries:
        o, i, p = files["orders"], files["inventory"], files["products"]
        again = sorted(set(o["order_id"]) & set(seen_orders))
        if again:
            raise RawDataError(f"Delivery {name}: {len(again)} order numbers already loaded in delivery "
                               f"{seen_orders[again[0]]}, e.g. {again[:5]}")
        keys = list(zip(i["sku"], i["stock_month"]))
        twice = [k for k in keys if k in seen_stock]
        if twice:
            raise RawDataError(f"Delivery {name}: {len(twice)} stock rows (sku + month) already loaded, e.g. {twice[:5]}")
        seen_orders.update({k: name for k in set(o["order_id"])})
        seen_stock.update({k: name for k in keys})
        orders.append(o)
        inv.append(i)
        prods.append(p.assign(_delivery=name))
        log.append(("all", f"delivery {name}: order rows / stock rows / product rows",
                    f"{len(o):,} / {len(i):,} / {len(p):,}"))

    p_all = pd.concat(prods, ignore_index=True)
    first = p_all.drop_duplicates("sku", keep="first").set_index("sku")
    last = p_all.drop_duplicates("sku", keep="last").set_index("sku")
    attr = ["product_name", "brand", "category"]
    moved = (first[attr] != last.loc[first.index, attr]).any(axis=1)
    if moved.any():
        raise RawDataError(f"{int(moved.sum())} existing skus changed name, brand or category between deliveries, "
                           f"e.g. {list(moved[moved].index[:5])}")
    n_price = int((first["latest_list_price"] != last.loc[first.index, "latest_list_price"]).sum())
    products = last.reset_index()[CLEAN_COLUMNS["products"]]       # newest delivery wins per sku (price)
    out = {"orders": pd.concat(orders, ignore_index=True)[CLEAN_COLUMNS["orders"]],
           "products": products,
           "inventory": pd.concat(inv, ignore_index=True)[CLEAN_COLUMNS["inventory"]]}
    log.append(("all", "orders: rows (appended)", len(out["orders"])))
    log.append(("all", "inventory: rows (appended)", len(out["inventory"])))
    log.append(("all", "products: skus (new skus added)", len(products)))
    log.append(("all", "products: skus whose latest_list_price changed across deliveries", n_price))
    return out


def as_text(df):
    """The same text a clean CSV holds (2-decimal money), so combined files equal what is on disk."""
    tmp = df.copy()
    for c in tmp.columns:
        if pd.api.types.is_float_dtype(tmp[c]):
            tmp[c] = tmp[c].map("{:.2f}".format)
        else:
            tmp[c] = tmp[c].astype(str)
    return tmp


def write_csvs(folder, files):
    folder.mkdir(parents=True, exist_ok=True)
    for name, df in files.items():
        df.to_csv(folder / f"{name}.csv", index=False, encoding="utf-8", float_format="%.2f", lineterminator="\n")
        print(f"{name}: {len(df):,} rows -> {folder / (name + '.csv')}")


# ===========================================================================
def write_log(path, raw, clean, log, started):
    md = [f"# Clean log - run {path.parent.name}", "",
          f"- Raw: `{raw}`  ->  Clean: `{clean}`",
          f"- Run: {started:%Y-%m-%d %H:%M}",
          "- Rules: decisions in `knowledge/metadata.md`", "",
          "| File | Step | Rows |", "|---|---|---|"]
    md += [f"| {f} | {step} | {n:,} |" if isinstance(n, int) else f"| {f} | {step} | {n} |" for f, step, n in log]
    md += ["", "Column renames:", "",
           "| File | Raw | Clean |", "|---|---|---|",
           "| orders | ORD_NO, CRTD_DT, CHNL, CTRY, CUST_REF, ART_NO, QTY, UNIT_PRC, DISC_PCT "
           "| order_id, order_date, channel, country_code, customer_id, sku, quantity, unit_price, discount_rate |",
           "| orders | (new) | is_core_market |",
           "| products | list_price | latest_list_price |",
           "| inventory | art_no, stk_month, qty_hand, reserved_qty | sku, stock_month, qty_on_hand, (removed) |"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(md) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Clean raw shop export into the clean layer.")
    ap.add_argument("--run", required=True, help="Run folder name, e.g. 2026-08")
    ap.add_argument("--raw", help="Delivery folder (default: data/raw/<run>)")
    ap.add_argument("--clean-root", default="data/clean", help="Clean layer root (delivery folders + all/)")
    args = ap.parse_args()
    if not is_delivery(args.run):
        print(f"STOPPED - run must be a month folder name YYYY-MM, got {args.run}")
        return 1
    raw = Path(args.raw) if args.raw else Path("data/raw") / args.run
    root = Path(args.clean_root)
    clean = root / args.run
    started = datetime.now()
    log = []

    try:
        out = {
            "orders": clean_orders(read_raw(raw, "orders"), log),
            "products": clean_products(read_raw(raw, "products"), log),
            "inventory": clean_inventory(read_raw(raw, "inventory"), log),
        }
        # Combine: every other delivery folder from disk, this run from memory (nothing written yet).
        others = [(d.name, {n: read_clean(d, n) for n in CLEAN_COLUMNS})
                  for d in (delivery_folders(root) if root.exists() else []) if d.name != args.run]
        deliveries = sorted(others + [(args.run, {n: as_text(df) for n, df in out.items()})], key=lambda t: t[0])
        combined = combine(deliveries, log)
    except RawDataError as e:
        print(f"STOPPED - nothing written. {e}")
        return 1

    write_csvs(clean, out)
    write_csvs(root / ALL, combined)
    log_path = Path("runs") / args.run / "2-clean" / "clean-log.md"
    write_log(log_path, raw, clean, log, started)
    print(f"Log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
