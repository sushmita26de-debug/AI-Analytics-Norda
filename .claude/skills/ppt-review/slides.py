"""
NORDA monthly review deck
=========================

Answers the Purchasing team's three monthly questions
(knowledge/inbox/december-questions.pdf) as a PowerPoint, built from data/mart/.

Run from the project root (or use /ppt-review <run>):
    python .claude/skills/ppt-review/slides.py --run 2026-08                   # latest month in the data
    python .claude/skills/ppt-review/slides.py --run 2026-08 --month 2025-12   # a chosen month
    python .claude/skills/ppt-review/check.py  --run 2026-08
    -> reports/ppt/<month name>-review.pptx   (e.g. december-review.pptx)
    +  runs/<run>/6-ppt-review/ppt-review-log.md  (every number on the slides)

One slide per question, the answer in one sentence, one big number in the
highlight colour, one chart or table. The last slide lists what must be said
out loud before the deck is shown.

How it works (in SQL terms):
  1. Load the 6 mart CSVs into an in-memory SQLite database.
  2. Every number is a SQL query (section 3). Revenue is summed in whole cents.
  3. The sentences are filled in from those numbers (section 4), so the deck
     says the right thing again next month.
  4. python-pptx writes the slides (section 5). Charts are native PowerPoint
     charts, so they stay editable.

Definitions agreed with Sushmita (2026-11-24):
  - Compare the review month with the month before (only 2025 data exists).
  - Ran out        = stock 0 at the end of the month (fact_inventory).
  - Lost sales     = for each product that ran out: its average monthly units in
                     the 3 months before, minus what it sold this month (never
                     below 0), times its average selling price in those 3 months.
                     Lost revenue, not lost profit (no cost prices).
  - Order more     = months of stock left = month-end stock / average monthly
                     units in the last 3 months (incl. this month); under 1 month
                     is flagged, ranked by revenue in those 3 months.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_TICK_MARK
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt


# ---------------------------------------------------------------------------
# 1. Look (same as the dashboard) and settings
# ---------------------------------------------------------------------------
BG = RGBColor(0x0E, 0x11, 0x17)        # page background
TEXT = RGBColor(0xE6, 0xE9, 0xEE)      # main text
TEXT2 = RGBColor(0xB4, 0xBC, 0xC7)     # secondary text
MUTED = RGBColor(0x8C, 0x96, 0xA3)     # labels
CALM = RGBColor(0x5F, 0x87, 0xB4)      # the one calm colour (all marks)
HI = RGBColor(0xF0, 0xA7, 0x3A)        # the one highlight colour (only the big number)
FONT = "Segoe UI"

TABLES = ["fact_sales", "fact_inventory", "dim_date", "dim_product", "dim_country", "dim_channel"]
MAIN_SHARE = 0.01      # slide 2: a product gets its own row if it is >= 1% of the total loss
FIRST_SHARE = 0.90     # slide 3: "order first" = biggest sellers that make up 90% of the flagged revenue
NO_TABLE_STYLE = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"   # PowerPoint's "No Style, No Grid"
WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def parse_args():
    ap = argparse.ArgumentParser(description="Build the NORDA monthly review deck.")
    ap.add_argument("--run", required=True, help="run month, e.g. 2026-08 (for the log folder)")
    ap.add_argument("--month", default=None, help="review month yyyy-mm (default: latest month with sales)")
    ap.add_argument("--mart", default="data/mart")
    ap.add_argument("--out", default=None, help="default: reports/ppt/<month name>-review.pptx")
    return ap.parse_args()


def fail(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Small helpers: database and number formats
# ---------------------------------------------------------------------------
def load_db(mart):
    db = sqlite3.connect(":memory:")
    for t in TABLES:
        p = Path(mart) / f"{t}.csv"
        if not p.exists():
            fail(f"missing {p}")
        pd.read_csv(p, dtype=str, keep_default_na=False).to_sql(t, db, index=False)
    return db


def q(db, sql, params=()):
    return db.execute(sql, params).fetchall()


CENTS = "CAST(ROUND(CAST(f.revenue AS REAL) * 100) AS INTEGER)"
UNITS = "CAST(f.quantity AS INTEGER)"
SALES = "FROM fact_sales f JOIN dim_date d ON d.date_key = f.date_key JOIN dim_product p ON p.sku = f.sku "


def word(n):
    return WORDS[n] if 0 <= n < len(WORDS) else f"{n:,}"


def pct(x):
    """0.2412 -> '+24%', -0.133 -> '−13%' (real minus sign)."""
    v = round(x * 100)
    return f"+{v}%" if v > 0 else (f"−{abs(v)}%" if v < 0 else "0%")


def eur_k(cents):
    """Estimates: rounded to thousands. 61234567 -> '€612K'."""
    e = cents / 100
    if e < 1000:
        return "under €1K"
    if e >= 1_000_000:
        return f"€{e / 1_000_000:.1f}M"
    return f"€{round(e / 1000):,}K"


def eur(cents):
    return f"€{cents // 100:,}.{cents % 100:02d}"


def month_range(ms):
    return f"{ms[0]['short']}–{ms[-1]['short']}" if len(ms) > 1 else ms[0]["short"]


# ---------------------------------------------------------------------------
# 3. The numbers (all SQL on data/mart)
# ---------------------------------------------------------------------------
def months(db):
    rows = q(db, "SELECT year_month, MIN(month_name), MIN(year) FROM dim_date GROUP BY 1 ORDER BY 1")
    return [{"ym": r[0], "name": r[1], "short": r[1][:3], "yyyymm": r[0].replace("-", ""),
             "label": f"{r[1]} {r[2]}"} for r in rows]


def revenue_by(db, col, ym, extra="", params=()):
    return dict(q(db, f"SELECT {col}, SUM({CENTS}) {SALES}WHERE d.year_month = ? {extra}GROUP BY 1", (ym, *params)))


def units_by_sku(db, yms):
    ph = ",".join("?" * len(yms))
    return {r[0]: (r[1], r[2]) for r in
            q(db, f"SELECT f.sku, SUM({UNITS}), SUM({CENTS}) {SALES}WHERE d.year_month IN ({ph}) GROUP BY 1", yms)}


def stock_at(db, m):
    """{sku: qty} at the end of month m (only products with a stock record)."""
    return {r[0]: int(r[1]) for r in
            q(db, "SELECT sku, qty_on_hand FROM fact_inventory WHERE substr(date_key, 1, 6) = ?", (m["yyyymm"],))}


def compute(db, ms, i):
    M, P = ms[i], ms[i - 1]
    base = ms[i - 3:i]                  # 3 months before the review month (lost sales)
    cover = ms[i - 2:i + 1]             # last 3 months incl. the review month (months of stock left)
    names = dict(q(db, "SELECT sku, product_name FROM dim_product"))
    cat_of = dict(q(db, "SELECT sku, category FROM dim_product"))
    cats = [r[0] for r in q(db, "SELECT DISTINCT category FROM dim_product ORDER BY 1")]
    out = {"M": M, "P": P, "base": base, "cover": cover}

    # --- Q1: was every part up? -------------------------------------------
    total_m = q(db, f"SELECT SUM({CENTS}) {SALES}WHERE d.year_month = ?", (M["ym"],))[0][0] or 0
    total_p = q(db, f"SELECT SUM({CENTS}) {SALES}WHERE d.year_month = ?", (P["ym"],))[0][0] or 0
    cm, cp = revenue_by(db, "p.category", M["ym"]), revenue_by(db, "p.category", P["ym"])
    chg = {c: (cm.get(c, 0) / cp[c] - 1) for c in cats if cp.get(c)}
    worst = min(chg, key=chg.get)
    # Products of the worst category that sold last month, ended last month at 0 stock and sold nothing now.
    u_p, u_m = units_by_sku(db, [P["ym"]]), units_by_sku(db, [M["ym"]])
    s_p = stock_at(db, P)
    cause = [s for s in names if cat_of[s] == worst and u_p.get(s, (0, 0))[0] > 0
             and s_p.get(s) == 0 and u_m.get(s, (0, 0))[0] == 0]
    base_rev = units_by_sku(db, [m["ym"] for m in base])
    rank = sorted([s for s in names if cat_of[s] == worst], key=lambda s: -base_rev.get(s, (0, 0))[1])
    cause_best = bool(cause) and all(s in rank[:5] for s in cause)
    # Countries / channels that fell, and how they did without the worst category.
    parts_down = []
    for col, label in (("f.country_code", "country"), ("f.channel", "channel")):
        a, b = revenue_by(db, col, M["ym"]), revenue_by(db, col, P["ym"])
        a2 = revenue_by(db, col, M["ym"], "AND p.category <> ? ", (worst,))
        b2 = revenue_by(db, col, P["ym"], "AND p.category <> ? ", (worst,))
        for k in b:
            if a.get(k, 0) < b[k]:
                parts_down.append((label, k, a.get(k, 0) / b[k] - 1, (a2.get(k, 0) / b2[k] - 1) if b2.get(k) else None))
    country_names = dict(q(db, "SELECT country_code, country_name FROM dim_country"))
    out["q1"] = {"total_m": total_m, "total_p": total_p, "cm": cm, "cp": cp, "chg": chg, "worst": worst,
                 "cause": [(names[s], u_p[s][0], u_p[s][1]) for s in cause], "cause_best": cause_best,
                 "parts_down": [(l, country_names.get(k, k), x, y) for l, k, x, y in parts_down]}

    # --- Q2: what ran out, and what did it cost? ----------------------------
    s_m = stock_at(db, M)
    ran_out = [s for s, v in s_m.items() if v == 0]
    rows = []
    for s in ran_out:
        bu, br = base_rev.get(s, (0, 0))
        avg = bu / len(base)
        sold = u_m.get(s, (0, 0))[0]
        price = br / bu if bu else 0                    # cents per unit, average selling price
        lost_units = max(0.0, avg - sold)
        rows.append({"sku": s, "name": names[s], "avg": avg, "sold": sold, "loss": round(lost_units * price)})
    rows.sort(key=lambda r: (-r["loss"], r["name"]))
    total_loss = sum(r["loss"] for r in rows)
    main = [r for r in rows if total_loss and r["loss"] > 0 and r["loss"] >= MAIN_SHARE * total_loss]
    rest = [r for r in rows if r not in main]
    out["q2"] = {"rows": rows, "main": main, "rest": rest, "total_loss": total_loss,
                 "no_record": len(names) - len(s_m)}

    # --- Q3: what should we order more of? ----------------------------------
    cov = units_by_sku(db, [m["ym"] for m in cover])
    flagged = []
    for s, (u, r) in cov.items():
        avg = u / len(cover)
        if avg <= 0 or s not in s_m:
            continue                                     # no sales, or no stock record: no rule possible
        left = s_m[s] / avg
        if left < 1:
            flagged.append({"sku": s, "name": names[s], "stock": s_m[s], "avg": avg, "left": left, "rev": r})
    flagged.sort(key=lambda x: (-x["rev"], x["name"]))
    tot, run, first = sum(x["rev"] for x in flagged), 0, []
    for x in flagged:
        if tot and run >= FIRST_SHARE * tot:
            break
        first.append(x)
        run += x["rev"]
    sellers_no_record = sum(1 for s, (u, _) in cov.items() if u > 0 and s not in s_m)
    out["q3"] = {"flagged": flagged, "first": first, "first_share": (run / tot) if tot else 0,
                 "sellers_no_record": sellers_no_record}

    # --- For the last slide ---------------------------------------------------
    by_month = dict(q(db, f"SELECT d.year_month, SUM({CENTS}) {SALES}GROUP BY 1"))
    out["is_biggest"] = by_month.get(M["ym"], 0) == max(by_month.values())
    out["missing_year"] = len(names) * len([m for m in ms if m["ym"][:4] == M["ym"][:4] and m["ym"] <= M["ym"]]) - \
        q(db, "SELECT COUNT(*) FROM fact_inventory WHERE substr(date_key, 1, 4) = ? AND substr(date_key, 1, 6) <= ?",
          (M["ym"][:4], M["yyyymm"]))[0][0]
    out["next"] = (pd.Period(M["ym"], freq="M") + 1).strftime("%B")    # e.g. January (calendar may end in Dec)
    # Data range (months with sales) and whether the same month last year is in the data
    first, last = min(by_month), max(by_month)
    label = {m["ym"]: f"{m['short']} {m['ym'][:4]}" for m in ms}
    out["data_range"] = f"{label[first]}–{label[last]}"
    out["has_last_year"] = by_month.get(str(pd.Period(M["ym"], freq="M") - 12), 0) > 0
    return out


# ---------------------------------------------------------------------------
# 4. The story: one sentence and one big number per slide
# ---------------------------------------------------------------------------
QUESTIONS = [
    "Was every part of the business up, or is something hiding under the number?",
    "Which products ran out, and what did it cost us?",
    "What should we order more of?",
]


def story(n):
    M, P = n["M"], n["P"]
    s = []

    # Slide 1
    a = n["q1"]
    down = [c for c, x in a["chg"].items() if x < 0]
    if not down:
        head = f"Yes. Every category grew in {M['name']}."
        big, big_label = pct(a["total_m"] / a["total_p"] - 1), f"all sales, {M['name']} vs {P['name']}"
    else:
        w = a["worst"]
        why = ""
        if a["cause"]:
            k = len(a["cause"])
            why = f", because {word(k)} of its best sellers ran out" if a["cause_best"] else \
                  f", because {word(k)} of its products ran out"
        head = (f"No. Every category grew except {w}{why}." if len(down) == 1 else
                f"No. {len(down)} categories fell, {w} the most{why}.")
        big, big_label = pct(a["chg"][w]), f"{w}, {M['name']} vs {P['name']}"
    notes = [f"All sales: {eur(a['total_p'])} in {P['name']}, {eur(a['total_m'])} in {M['name']} "
             f"({pct(a['total_m'] / a['total_p'] - 1)}).", "Per category, {P} -> {M}:".format(P=P['short'], M=M['short'])]
    notes += [f"  {c}: {eur(a['cp'][c])} -> {eur(a['cm'].get(c, 0))} ({pct(x)})" for c, x in sorted(a["chg"].items(), key=lambda t: t[1])]
    if a["cause"]:
        notes.append(f"Ran out at the end of {P['name']} and sold nothing in {M['name']}: " +
                     "; ".join(f"{nm} ({u:,} units, {eur(r)} in {P['name']})" for nm, u, r in a["cause"]) + ".")
    for label, k, x, y in a["parts_down"]:
        extra = f" Without {a['worst']} it was {pct(y)}." if y is not None else ""
        notes.append(f"Also down: {label} {k} {pct(x)}.{extra}")
    notes.append("Source: data/mart, revenue before returns, all 6 countries.")
    s.append({"q": QUESTIONS[0], "head": head, "big": big, "big_label": big_label, "notes": notes})

    # Slide 2
    b = n["q2"]
    n_out, k = len(b["rows"]), len(b["main"])
    base_txt = month_range(n["base"])
    if n_out == 0:
        head = f"Nothing ran out in {M['name']}."
    elif k == 0:
        head = f"{n_out} products ran out in {M['name']}, but they hardly sold before, so it cost us little."
    else:
        head = (f"{n_out} products ran out in {M['name']}, and the {word(k)} that sell well cost us about "
                f"{eur_k(b['total_loss'])} in sales.")
    notes = [f"Ran out = stock 0 at the end of {M['name']}.",
             f"Lost sales = average units per month in {base_txt}, minus units sold in {M['name']} (not below 0), "
             f"times the average selling price in {base_txt}. Estimate. Lost sales, not lost profit (we have no cost prices).",
             f"Total {eur(b['total_loss'])}. Rows are rounded to thousands, so they may not add up exactly.",
             f"A product gets its own row if it is at least {MAIN_SHARE:.0%} of the total loss."]
    notes += [f"  {r['name']}: {r['avg']:.1f} per month before, {r['sold']} in {M['short']}, {eur(r['loss'])}" for r in b["rows"]]
    s.append({"q": QUESTIONS[1], "head": head, "big": eur_k(b["total_loss"]) if n_out else "0",
              "big_label": f"estimated lost sales in {M['name']}", "notes": notes})

    # Slide 3
    c = n["q3"]
    cov_txt = month_range(n["cover"])
    if not c["flagged"]:
        head = "Nothing is running low: every product has at least a month of stock."
    else:
        head = (f"Order these {word(len(c['first']))} first: they sell the most and have less than a month of stock left."
                if len(c["first"]) > 1 else
                f"Order {c['first'][0]['name']} first: it sells the most and has less than a month of stock left.")
    notes = [f"Months of stock left = stock at the end of {M['name']} / average units sold per month in {cov_txt}.",
             f"{len(c['flagged'])} products have less than 1 month left. Ranked by revenue in {cov_txt}.",
             f"The first {len(c['first'])} make up {c['first_share']:.0%} of the revenue of those {len(c['flagged'])} products."]
    if c["sellers_no_record"]:
        notes.append(f"{c['sellers_no_record']} products that sold have no stock record for {M['name']}; they are not in this list.")
    notes += [f"  {x['name']}: stock {x['stock']:,}, {x['avg']:.1f} per month, {x['left']:.1f} months left, {eur(x['rev'])}"
              for x in c["flagged"]]
    s.append({"q": QUESTIONS[2], "head": head, "big": f"{len(c['first'])}", "big_label": "products to order first",
              "notes": notes})

    # Last slide
    rows = [("Revenue is before returns.", "Returns are in another system. The real number is lower."),
            (f"The {eur_k(b['total_loss'])} is an estimate.",
             f"It is what these products sold per month in {base_txt}, times their price. It is lost sales, not lost profit."),
            (f"Our data covers {n['data_range']}.",
             f"I compare {M['name']} with {P['name']}, the month before" +
             ("." if n["has_last_year"] else f"; there is no data for {M['name']} last year.")),
            ("Stock has no country or channel.", "Stock numbers are always for all of NORDA."),
            (f"{n['missing_year']} product-months have no stock record.",
             f"They are left out, not counted as 0 ({b['no_record']} of them in {M['name']})."),
            (f"The order list uses {cov_txt} sales.",
             (f"{M['name']} is our biggest month. " if n["is_biggest"] else "") +
             (f"If {n['next']} sells less, we need less." if n["next"] else "If next month sells less, we need less."))]
    if n_out == 0:
        rows.pop(1)
    s.append({"q": "Before the meeting", "head": f"Before I show this, I must say these {word(len(rows))} things out loud.",
              "big": None, "rows": rows, "notes": ["Say these before slide 1, so nobody finds them later."]})
    return s


# ---------------------------------------------------------------------------
# 5. Writing the slides
# ---------------------------------------------------------------------------
def text(slide, x, y, w, h, s, size, color, bold=False, anchor=MSO_ANCHOR.TOP, name=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap, tf.vertical_anchor = True, anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    run = tf.paragraphs[0].add_run()
    run.text = s
    f = run.font
    f.name, f.size, f.bold, f.color.rgb = FONT, Pt(size), bold, color
    return tb


def frame(prs, s):
    """Background, question label and the one-sentence answer (as the slide title)."""
    slide = prs.slides.add_slide(prs.slide_layouts[5])          # "Title Only": the answer is the real title
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = BG
    text(slide, 0.6, 0.45, 12.1, 0.35, s["q"], 14, MUTED, name="Question")
    t = slide.shapes.title
    t.left, t.top, t.width, t.height = Inches(0.6), Inches(0.9), Inches(12.1), Inches(1.3)
    tf = t.text_frame
    tf.word_wrap, tf.vertical_anchor = True, MSO_ANCHOR.TOP
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run()
    r.text = s["head"]
    r.font.name, r.font.size, r.font.bold, r.font.color.rgb = FONT, Pt(30), True, TEXT
    slide.notes_slide.notes_text_frame.text = "\n".join(s["notes"])
    return slide


def big_number(slide, s):
    text(slide, 0.6, 2.75, 3.9, 1.2, s["big"], 66, HI, bold=True, anchor=MSO_ANCHOR.BOTTOM, name="Big number")
    text(slide, 0.6, 4.05, 3.6, 1.0, s["big_label"], 16, TEXT2, name="Big number label")


def table(slide, x, y, w, header, rows, widths, right_cols, row_h=0.5):
    shape = slide.shapes.add_table(len(rows) + 1, len(header), Inches(x), Inches(y), Inches(w),
                                   Inches(row_h * (len(rows) + 1)))
    tbl = shape.table
    shape._element.graphic.graphicData.tbl.tblPr.find(qn("a:tableStyleId")).text = NO_TABLE_STYLE
    tbl.first_row = tbl.horz_banding = False
    for j, cw in enumerate(widths):
        tbl.columns[j].width = Inches(cw)
    for i, vals in enumerate([header] + rows):
        tbl.rows[i].height = Inches(row_h)
        for j, v in enumerate(vals):
            cell = tbl.cell(i, j)
            cell.fill.background()
            cell.margin_left = Inches(0 if j == 0 else 0.1)
            cell.margin_right = Inches(0.1 if j < len(header) - 1 else 0)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.RIGHT if j in right_cols else PP_ALIGN.LEFT
            cell.text_frame.word_wrap = True
            r = p.add_run()
            r.text = str(v)
            r.font.name, r.font.size = FONT, Pt(13 if i == 0 else 15)
            r.font.bold = i == 0
            r.font.color.rgb = MUTED if i == 0 else TEXT
    return shape


def slide_q1(prs, s, n):
    slide = frame(prs, s)
    big_number(slide, s)
    chg = sorted(n["q1"]["chg"].items(), key=lambda t: t[1])           # lowest first = at the top
    data = CategoryChartData()
    data.categories = [c for c, _ in chg]
    data.add_series(f"Revenue change, {n['M']['short']} vs {n['P']['short']}", [round(v, 4) for _, v in chg])
    gf = slide.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(4.9), Inches(2.5), Inches(7.8), Inches(4.4), data)
    gf.name = "Chart: change per category"
    ch = gf.chart
    ch.has_legend = False
    ch.has_title = False
    ch.font.name, ch.font.size, ch.font.color.rgb = FONT, Pt(15), TEXT2
    plot = ch.plots[0]
    plot.gap_width = 70
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format, dl.number_format_is_linked = '+0%;−0%;0%', False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.name, dl.font.size, dl.font.color.rgb = FONT, Pt(15), TEXT
    ser = plot.series[0]
    ser.invert_if_negative = False
    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = CALM
    cat = ch.category_axis
    cat.reverse_order = True                                            # first category at the top
    cat.format.line.color.rgb = MUTED                                  # thin zero line, no tick marks
    cat.major_tick_mark = cat.minor_tick_mark = XL_TICK_MARK.NONE
    cat.has_major_gridlines = False
    cat.tick_labels.font.color.rgb = TEXT2
    cat.tick_labels.font.size = Pt(15)
    # labels on the left edge, also for negative bars
    cat._element.get_or_add_tickLblPos().set("val", "low")
    val = ch.value_axis
    val.visible = False
    val.has_major_gridlines = False
    lo = min(v for _, v in chg)
    hi = max(v for _, v in chg)
    val.minimum_scale = min(0, lo) * 1.35
    val.maximum_scale = max(0, hi) * 1.25
    return slide


def slide_q2(prs, s, n):
    slide = frame(prs, s)
    big_number(slide, s)
    b, M = n["q2"], n["M"]
    base_txt = month_range(n["base"])
    rows = [[r["name"], f"{r['avg']:,.0f}", f"{r['sold']:,}", eur_k(r["loss"])] for r in b["main"]]
    if b["rest"]:
        rows.append([f"{len(b['rest'])} other products", f"{sum(r['avg'] for r in b['rest']):,.0f}",
                     f"{sum(r['sold'] for r in b['rest']):,}", eur_k(sum(r["loss"] for r in b["rest"]))])
    if not rows:
        rows = [["–", "–", "–", "–"]]
    shape = table(slide, 4.9, 2.6, 7.8,
                  ["Product", f"Sold per month, {base_txt}", f"Sold in {M['short']}", "Lost sales"],
                  rows, [3.0, 1.9, 1.35, 1.55], right_cols={1, 2, 3})
    shape.name = "Table: products that ran out"
    return slide


def slide_q3(prs, s, n):
    slide = frame(prs, s)
    big_number(slide, s)
    c, M = n["q3"], n["M"]
    cov_txt = month_range(n["cover"])
    rows = [[x["name"], f"{x['stock']:,}", f"{x['avg']:,.0f}", "0" if x["stock"] == 0 else f"{x['left']:.1f}"]
            for x in c["first"]]
    rest = c["flagged"][len(c["first"]):]
    if rest:
        rows.append([f"{len(rest)} more, smaller sellers", f"{sum(x['stock'] for x in rest):,}",
                     f"{sum(x['avg'] for x in rest):,.0f}", ""])
    if not rows:
        rows = [["–", "–", "–", "–"]]
    shape = table(slide, 4.9, 2.6, 7.8,
                  ["Product", f"Stock end of {M['short']}", f"Sold per month, {cov_txt}", "Months of stock left"],
                  rows, [3.0, 1.45, 1.8, 1.55], right_cols={1, 2, 3})
    shape.name = "Table: what to order first"
    return slide


def slide_last(prs, s):
    slide = frame(prs, s)
    shape = table(slide, 0.6, 2.4, 12.1, ["What I say", "Why"], [list(r) for r in s["rows"]],
                  [4.6, 7.5], right_cols=set(), row_h=0.62)
    shape.name = "Table: say this out loud"
    return slide


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    db = load_db(args.mart)
    ms = months(db)
    with_sales = {r[0] for r in q(db, f"SELECT DISTINCT d.year_month {SALES}")}
    month = args.month or max(with_sales)
    idx = next((k for k, m in enumerate(ms) if m["ym"] == month), None)
    if idx is None or month not in with_sales:
        fail(f"no sales for month {month} in {args.mart}")
    if idx < 3:
        fail("need at least 3 months before the review month (for lost sales)")

    n = compute(db, ms, idx)
    slides = story(n)

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide_q1(prs, slides[0], n)
    slide_q2(prs, slides[1], n)
    slide_q3(prs, slides[2], n)
    slide_last(prs, slides[3])

    out = Path(args.out or f"reports/ppt/{n['M']['name'].lower()}-review.pptx")
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out)

    # Every number on the slides, printed (plain ASCII for the Windows terminal).
    def a(t):
        return t.replace("€", "EUR ").replace("−", "-").replace("–", "-")
    print(f"NORDA review deck - {n['M']['label']} vs {n['P']['label']}")
    for k, s in enumerate(slides, 1):
        print(f"\nSlide {k}: {a(s['head'])}")
        if s.get("big"):
            print(f"  big number: {a(s['big'])} ({a(s['big_label'])})")
        for line in s["notes"]:
            print("  " + a(line))
        for r in s.get("rows", []):
            print("  - " + a(" | ".join(r)))
    print(f"\nFile: {out.resolve()}")

    # Build log for this run: every sentence, big number, table row and note on the slides.
    log = [f"# Review deck build log - run {args.run}", "",
           f"Review month: **{n['M']['label']}** (compared with {n['P']['label']}) · "
           f"Script: `.claude/skills/ppt-review/slides.py` · Source: `{args.mart}` · Output: `{out.as_posix()}`", ""]
    for k, s in enumerate(slides, 1):
        log += [f"## Slide {k}: {s['q']}", "", f"**{s['head']}**", ""]
        if s.get("big"):
            log += [f"Big number: **{s['big']}** ({s['big_label']})", ""]
        for r in s.get("rows", []):
            log.append(f"- {r[0]} {r[1]}")
        log += ["Speaker notes:", "```"] + s["notes"] + ["```", ""]
    log_path = Path("runs") / args.run / "6-ppt-review" / "ppt-review-log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"Log: {log_path}")


if __name__ == "__main__":
    main()
