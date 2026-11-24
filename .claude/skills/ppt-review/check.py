"""
NORDA review deck checks
========================

Reads the finished deck (reports/ppt/<month>-review.pptx) back and checks it two ways:
  - the design rules, straight from the file (colours, shapes, fonts, sentences)
  - every number on the slides, recomputed with pandas from every delivery in data/raw/<month>/
    (road B: the cleaning decisions and the delivery rules re-applied - orders and stock appended,
    newest price per product - independent of slides.py and data/mart)

    python .claude/skills/ppt-review/check.py --run 2026-08
    python .claude/skills/ppt-review/check.py --run 2026-08 --month 2025-12

Writes runs/<run>/6-ppt-review/ppt-review-checks.md. Any FAIL -> exit code 1.
Read-only on data/ and on the deck.

Checks
  F01-F04  the file: opens, 4 slides, speaker notes, built from the current mart
  D01-D07  design: dark, one amber item per question slide, one chart or table,
           no decoration shapes, Segoe UI >= 13pt, one-sentence answers, only
           the dashboard colours
  N..      the numbers, deck vs data/raw
"""

import argparse
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.util import Pt


# ---------------------------------------------------------------------------
# 1. Settings: the agreed look (same as the dashboard) and rules
# ---------------------------------------------------------------------------
BG, CALM, HI = "0E1117", "5F87B4", "F0A73A"
TEXT_COLOURS = {"E6E9EE", "B4BCC7", "8C96A3", HI}
FONT, MIN_PT = "Segoe UI", 13
MAX_HEAD_CHARS = 120             # about two lines at 30pt across the slide
MAIN_SHARE, FIRST_SHARE = 0.01, 0.90   # same grouping thresholds as slides.py
TABLES = ["fact_sales", "fact_inventory", "dim_date", "dim_product", "dim_country", "dim_channel"]


def parse_args():
    ap = argparse.ArgumentParser(description="Check the NORDA review deck.")
    ap.add_argument("--run", required=True, help="run month, e.g. 2026-08")
    ap.add_argument("--month", default=None, help="review month yyyy-mm (default: latest month with sales in raw)")
    ap.add_argument("--raw", default="data/raw", help="folder with one subfolder per delivery")
    ap.add_argument("--mart", default="data/mart")
    ap.add_argument("--deck", default=None, help="default: reports/ppt/<month name>-review.pptx")
    return ap.parse_args()


def stop(msg):
    print("STOPPED: " + msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Road B: data/raw with the cleaning decisions re-applied
# ---------------------------------------------------------------------------
def load_rules():
    for folder in Path(__file__).resolve().parents:
        f = folder / "knowledge" / "rules.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    stop("knowledge/rules.json not found")


def read_raw(raw, rules):
    """Every delivery folder raw/<YYYY-MM>/, oldest first: orders and stock appended, newest product row per sku."""
    folders = sorted(d for d in Path(raw).iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}", d.name)
                     and all((d / f"{n}.csv").exists() for n in ("orders", "products", "inventory")))
    if not folders:
        stop(f"no delivery folders in {raw}")

    def txt(p):
        return pd.concat([pd.read_csv(d / p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
                          .apply(lambda c: c.str.strip())
                          .pipe(lambda df: df.drop_duplicates() if p == "orders.csv" else df)   # identical rows -> keep one, per delivery
                          .assign(_delivery=d.name) for d in folders], ignore_index=True)
    o = txt("orders.csv").drop(columns="_delivery")
    iso = o["CRTD_DT"].str.match(r"^\d{4}-\d{2}-\d{2}$")
    d = pd.to_datetime(o["CRTD_DT"].where(iso), format="%Y-%m-%d", errors="coerce").fillna(
        pd.to_datetime(o["CRTD_DT"].where(~iso), format="%d/%m/%Y", errors="coerce"))   # DD/MM
    if d.isna().any():
        stop(f"{int(d.isna().sum())} order dates could not be read")
    o["m"] = d.dt.strftime("%Y-%m")
    o["ctry"] = o["CTRY"].replace({v: k for k, v in rules["country_names"].items()})
    o["chnl"] = o["CHNL"].str.lower()
    o["q"] = o["QTY"].astype(int)
    o["c"] = [int((Decimal(q) * Decimal(p) * (1 - Decimal(x))).quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)
              for q, p, x in zip(o["QTY"], o["UNIT_PRC"], o["DISC_PCT"])]
    pr = txt("products.csv").sort_values("_delivery", kind="stable").drop_duplicates("sku", keep="last")  # newest wins
    canon = {c.lower(): c for c in rules["categories"]}
    pr["cat"] = pr["category"].str.lower().map(canon)
    if pr["cat"].isna().any():
        stop("unknown category in products.csv")
    o = o.merge(pr[["sku", "product_name", "cat"]], left_on="ART_NO", right_on="sku")
    inv = txt("inventory.csv").drop(columns="_delivery")
    inv["m"] = pd.PeriodIndex(inv["stk_month"], freq="M").strftime("%Y-%m")   # 2025-4 -> 2025-04
    inv["q"] = inv["qty_hand"].astype(int)
    return o, pr, inv


def pct(x):
    v = round(x * 100)
    return f"+{v}%" if v > 0 else (f"−{abs(v)}%" if v < 0 else "0%")


def eurk(c):
    e = c / 100
    if e < 1000:
        return "under €1K"
    return f"€{e / 1_000_000:.1f}M" if e >= 1_000_000 else f"€{round(e / 1000):,}K"


def eur(c):
    return f"€{c // 100:,}.{c % 100:02d}"


WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def word(n):
    return WORDS[n] if 0 <= n < len(WORDS) else f"{n:,}"


# ---------------------------------------------------------------------------
# 3. Read the deck
# ---------------------------------------------------------------------------
def runs_of(shape):
    """Every text run in a shape (text boxes, titles, table cells)."""
    if shape.has_text_frame:
        for p in shape.text_frame.paragraphs:
            yield from p.runs
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            for cell in row.cells:
                for p in cell.text_frame.paragraphs:
                    yield from p.runs


def colour(font):
    try:
        return str(font.color.rgb) if font.color and font.color.type is not None else None
    except AttributeError:
        return None


def read_deck(path):
    prs = Presentation(path)
    slides = []
    for s in prs.slides:
        x = {"slide": s, "title": s.shapes.title.text_frame.text if s.shapes.title else "",
             "notes": s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""}
        for sh in s.shapes:
            if sh.name == "Big number":
                x["big"] = sh.text_frame.text
            if sh.has_table:
                x["table"] = [[c.text for c in r.cells] for r in sh.table.rows]
            if sh.has_chart:
                pl = sh.chart.plots[0]
                x["chart"] = dict(zip(pl.categories, pl.series[0].values))
        slides.append(x)
    return slides


# ---------------------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    rules = load_rules()
    o, pr, inv = read_raw(args.raw, rules)
    M = args.month or o["m"].max()
    per = pd.Period(M, freq="M")
    P = str(per - 1)
    BASE = [str(per - k) for k in (3, 2, 1)]
    COV = [str(per - k) for k in (2, 1, 0)]
    mname = per.strftime("%B")
    deck_path = Path(args.deck or f"reports/ppt/{mname.lower()}-review.pptx")
    res = []

    def add(cid, name, ok, detail=""):
        res.append((cid, name, bool(ok), detail))

    # --- F: the file -----------------------------------------------------------
    if not deck_path.exists():
        add("F01", "Deck exists and opens", False, f"{deck_path} missing")
        return finish(args, res, M)
    try:
        S = read_deck(deck_path)
        add("F01", "Deck exists and opens", True, f"{deck_path.as_posix()} ({deck_path.stat().st_size / 1024:.0f} KB)")
    except Exception as e:                                   # noqa: BLE001 - report any read error as a FAIL
        add("F01", "Deck exists and opens", False, str(e)[:200])
        return finish(args, res, M)
    add("F02", "4 slides: 3 questions + what to say out loud", len(S) == 4, f"{len(S)} slides")
    if len(S) != 4:
        return finish(args, res, M)
    no_notes = [k + 1 for k, x in enumerate(S) if not x["notes"].strip()]
    add("F03", "Every slide has speaker notes", not no_notes, "ok" if not no_notes else f"missing on slide {no_notes}")
    newest = max((Path(args.mart) / f"{t}.csv").stat().st_mtime for t in TABLES)
    fresh = deck_path.stat().st_mtime >= newest
    add("F04", "Built from the current mart (deck newer than every mart CSV)", fresh,
        "ok" if fresh else "the mart changed after the deck was built: rebuild with slides.py")

    # --- D: design rules, from the file ---------------------------------------
    bad_bg = [k + 1 for k, x in enumerate(S) if str(x["slide"].background.fill.fore_color.rgb) != BG]
    add("D01", "Dark background on every slide", not bad_bg, "ok" if not bad_bg else f"slides {bad_bg}")

    amber, one_vis, deco, fonts, colours = [], [], [], [], []
    for k, x in enumerate(S, 1):
        n_hi, n_vis = 0, 0
        for sh in x["slide"].shapes:
            for r in runs_of(sh):
                if colour(r.font) == HI:
                    n_hi += 1 if sh.name == "Big number" else 100   # amber outside the big number = fail
                if r.font.name != FONT or r.font.size is None or r.font.size < Pt(MIN_PT):
                    fonts.append(f"s{k} '{r.text[:20]}' {r.font.name} {r.font.size.pt if r.font.size else None}pt")
                if colour(r.font) not in TEXT_COLOURS:
                    colours.append(f"s{k} '{r.text[:20]}' {colour(r.font)}")
            if sh.has_chart:
                n_vis += 1
                ch = sh.chart
                if ch.font.name != FONT:
                    fonts.append(f"s{k} chart font {ch.font.name}")
                for ser in ch.plots[0].series:
                    fill = str(ser.format.fill.fore_color.rgb)
                    if fill == HI:
                        n_hi += 100
                    elif fill != CALM:
                        colours.append(f"s{k} chart bars {fill}")
            elif sh.has_table:
                n_vis += 1
            elif sh.shape_type == MSO_SHAPE_TYPE.TEXT_BOX:
                pass
            elif sh.is_placeholder and sh.placeholder_format.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE):
                pass
            else:
                deco.append(f"s{k} {sh.shape_type} '{sh.name}'")
        want = 0 if k == len(S) else 1
        if n_hi != want:
            amber.append(f"slide {k}: {'amber outside the big number' if n_hi >= 100 else n_hi} (want {want})")
        if n_vis != 1:
            one_vis.append(f"slide {k}: {n_vis}")
    add("D02", "One amber item per question slide (the big number), none on the last", not amber,
        "ok" if not amber else "; ".join(amber))
    add("D03", "Every slide has exactly one chart or table", not one_vis, "ok" if not one_vis else "; ".join(one_vis))
    add("D04", "No lines or decoration shapes", not deco, "only title, text boxes, chart/table" if not deco else "; ".join(deco[:5]))
    add("D05", f"Font {FONT}, nothing under {MIN_PT}pt", not fonts, "ok" if not fonts else "; ".join(fonts[:5]))
    long_or_many = []
    for k, x in enumerate(S, 1):
        h = re.sub(r"^(Yes|No)\.\s+", "", x["title"].strip())
        n_sent = len(re.findall(r"[.!?](\s|$)", h))
        if n_sent != 1 or len(x["title"]) > MAX_HEAD_CHARS:
            long_or_many.append(f"slide {k}: {n_sent} sentences, {len(x['title'])} chars")
    add("D06", f"Each answer is one sentence (after Yes./No.), at most {MAX_HEAD_CHARS} characters", not long_or_many,
        "ok" if not long_or_many else "; ".join(long_or_many))
    add("D07", "Only the dashboard colours (text tokens, calm bars, amber)", not colours,
        "ok" if not colours else "; ".join(colours[:5]))

    # --- N: numbers, deck vs data/raw ------------------------------------------
    nid = [0]

    def num(name, ok, deck_val="", raw_val=""):
        nid[0] += 1
        add(f"N{nid[0]:02d}", name, ok, f"deck {deck_val} = raw {raw_val}" if ok else f"deck {deck_val} vs raw {raw_val}")

    names = pr.set_index("sku")["product_name"]
    cat_of = pr.set_index("sku")["cat"]

    def stock(m):
        return inv[inv["m"] == m].groupby("art_no")["q"].sum()

    sm, sp = stock(M), stock(P)
    u = o.groupby(["m", "sku"])["q"].sum()
    tot = o.groupby("m")["c"].sum()

    # Slide 1
    cat = o.groupby(["m", "cat"])["c"].sum()
    chg = {c: cat.get((M, c), 0) / cat[(P, c)] - 1 for c in rules["categories"] if cat.get((P, c))}
    worst = min(chg, key=chg.get)
    for c, v in chg.items():
        got = S[0].get("chart", {}).get(c)
        num(f"S1 chart: {c}", got is not None and round(got, 4) == round(v, 4), pct(got) if got is not None else "missing", pct(v))
    down = [c for c, v in chg.items() if v < 0]
    want_big = pct(chg[worst]) if down else pct(tot[M] / tot[P] - 1)
    num("S1 big number", S[0].get("big") == want_big, S[0].get("big"), want_big)
    if down:
        num("S1 answer names the weakest category", worst in S[0]["title"], "'" + S[0]["title"][:60] + "…'", worst)
        cause = [s for s in pr["sku"] if cat_of[s] == worst and u.get((P, s), 0) > 0
                 and sp.get(s) == 0 and u.get((M, s), 0) == 0]
        if cause:
            num("S1 number of best sellers that ran out", f" {word(len(cause))} of its" in S[0]["title"], "in answer", word(len(cause)))
    num("S1 notes: all sales previous month", eur(int(tot[P])) in S[0]["notes"], "notes", eur(int(tot[P])))
    num("S1 notes: all sales review month", eur(int(tot[M])) in S[0]["notes"], "notes", eur(int(tot[M])))
    for col, label, nm in (("ctry", "country", rules["country_names"]), ("chnl", "channel", {})):
        a = o.groupby(["m", col])["c"].sum()
        b = o[o["cat"] != worst].groupby(["m", col])["c"].sum()
        for k in sorted(o[col].unique()):
            if a.get((P, k)) and a.get((M, k), 0) < a[(P, k)]:
                t = f"{label} {nm.get(k, k)} {pct(a.get((M, k), 0) / a[(P, k)] - 1)}."
                if b.get((P, k)):
                    t += f" Without {worst} it was {pct(b.get((M, k), 0) / b[(P, k)] - 1)}."
                num(f"S1 notes: {label} {nm.get(k, k)} down", t in S[0]["notes"], "notes", t)

    # Slide 2
    out = [s for s, v in sm.items() if v == 0]
    bb = o[o["m"].isin(BASE)].groupby("sku").agg(u=("q", "sum"), c=("c", "sum"))
    loss = {}
    for s in out:
        bu, bc = int(bb["u"].get(s, 0)), int(bb["c"].get(s, 0))
        loss[s] = round(max(0, bu / len(BASE) - u.get((M, s), 0)) * (bc / bu if bu else 0))
    total = sum(loss.values())
    num("S2 number of products that ran out", S[1]["title"].startswith(f"{len(out)} products") or (not out and "Nothing" in S[1]["title"]),
        S[1]["title"].split(" ")[0], len(out))
    if out:
        num("S2 big number", S[1].get("big") == eurk(total), S[1].get("big"), eurk(total))
        num("S2 notes: exact total", eur(total) in S[1]["notes"], "notes", eur(total))
        main_ = sorted([s for s in out if total and loss[s] > 0 and loss[s] >= MAIN_SHARE * total], key=lambda s: (-loss[s], names[s]))
        rest = [s for s in out if s not in main_]
        rows = S[1].get("table", [[]])[1:]
        for k, s in enumerate(main_):
            want = [names[s], f"{bb['u'].get(s, 0) / len(BASE):,.0f}", f"{u.get((M, s), 0):,}", eurk(loss[s])]
            got = rows[k] if k < len(rows) else None
            num(f"S2 row: {names[s]}", got == want, got, want)
        if rest:
            want = [f"{len(rest)} other products", f"{sum(bb['u'].get(s, 0) for s in rest) / len(BASE):,.0f}",
                    f"{sum(u.get((M, s), 0) for s in rest):,}", eurk(sum(loss[s] for s in rest))]
            got = rows[len(main_)] if len(main_) < len(rows) else None
            num("S2 row: other products", got == want, got, want)

    # Slide 3
    cv = o[o["m"].isin(COV)].groupby("sku").agg(u=("q", "sum"), c=("c", "sum"))
    fl = [(s, int(r.c)) for s, r in cv.iterrows() if r.u > 0 and s in sm and sm[s] / (r.u / len(COV)) < 1]
    fl.sort(key=lambda t: (-t[1], names[t[0]]))
    T, run, first = sum(c for _, c in fl), 0, []
    for s, c in fl:
        if T and run >= FIRST_SHARE * T:
            break
        first.append(s)
        run += c
    if fl:
        num("S3 big number (products to order first)", S[2].get("big") == str(len(first)), S[2].get("big"), len(first))
        rows = S[2].get("table", [[]])[1:]
        for k, s in enumerate(first):
            a = cv["u"][s] / len(COV)
            want = [names[s], f"{int(sm[s]):,}", f"{a:,.0f}", "0" if sm[s] == 0 else f"{sm[s] / a:.1f}"]
            got = rows[k] if k < len(rows) else None
            num(f"S3 row: {names[s]}", got == want, got, want)
        if len(fl) > len(first):
            got = rows[len(first)][0] if len(first) < len(rows) else ""
            num("S3 row: the rest", got.startswith(f"{len(fl) - len(first)} more"), got, f"{len(fl) - len(first)} more")

    # Slide 4
    rows4 = S[3].get("table", [[]])[1:]
    year = M[:4]
    yms = [str(p) for p in pd.period_range(f"{year}-01", M, freq="M")]
    have = inv[inv["m"].isin(yms)].groupby("m")["art_no"].nunique()
    missing = len(pr) * len(yms) - int(have.sum())
    r_miss = next((r for r in rows4 if "product-months" in r[0]), None)
    num("S4 product-months without a stock record", r_miss is not None and r_miss[0].startswith(f"{missing} "),
        r_miss[0] if r_miss else "missing", missing)
    m_miss = len(pr) - int(have.get(M, 0))
    num(f"S4 of them in {mname}", r_miss is not None and f"({m_miss} of them in {mname})" in r_miss[1],
        r_miss[1] if r_miss else "missing", m_miss)
    if out:
        r_est = next((r for r in rows4 if "estimate" in r[0]), None)
        num("S4 estimate repeats the big number", r_est is not None and r_est[0] == f"The {eurk(total)} is an estimate.",
            r_est[0] if r_est else "missing", eurk(total))
    biggest = tot.idxmax() == M
    said = any(f"{mname} is our biggest month" in r[1] for r in rows4)
    num(f"S4 '{mname} is our biggest month' said only when true", said == biggest, said, biggest)

    return finish(args, res, M, deck_path)


def finish(args, res, month, deck_path=None):
    fails = [r for r in res if not r[2]]
    verdict = "PASS - deck OK" if not fails else f"FAIL - {len(fails)} checks failed"
    lines = [f"# Review deck checks - run {args.run}", "",
             f"Script: `.claude/skills/ppt-review/check.py` · Review month: {month} · "
             f"Deck: `{deck_path.as_posix() if deck_path else args.deck}` · Road B: pandas on `{args.raw}`", "",
             f"**{verdict}**", "",
             "| ID | Check | Result | Detail |", "|---|---|---|---|"]
    lines += [f"| {cid} | {name} | {'PASS' if ok else '**FAIL**'} | {str(detail).replace('|', '/')} |"
              for cid, name, ok, detail in res]
    out = Path("runs") / args.run / "6-ppt-review" / "ppt-review-checks.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for cid, name, ok, _ in res:
        print(f"{cid}  {'PASS' if ok else 'FAIL'}  {name.encode('ascii', 'replace').decode()}")
    print(verdict)
    print(f"Report: {out}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
