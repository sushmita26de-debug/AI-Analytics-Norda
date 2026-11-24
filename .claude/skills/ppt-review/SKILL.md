---
name: ppt-review
description: Build and check the NORDA monthly review deck, a PowerPoint (reports/ppt/<month>-review.pptx) generated from data/mart/ that answers the Purchasing team's three questions (knowledge/inbox/december-questions.pdf). Was every part of the business up or is something hiding; which products ran out and what did it cost; what should we order more of. Plus a last slide with what must be said out loud. One slide per question, the answer in one sentence, one big amber number, one chart or table, dashboard look. A check script reads the deck back and verifies the design rules and every number against data/raw (about 39 pass/fail checks). Use after /quality-gate has passed, or when the user asks to build/rebuild/check the review deck or the monthly presentation.
---

# Build the monthly review deck

Usage: `/ppt-review <run-month>`, e.g. `/ppt-review 2026-09`. If no run month is given, ask for it.
The review month is the latest month in the data by default (e.g. December 2025 in run 2026-08). To review another month, add `--month <yyyy-mm>` to both scripts.

Pipeline: `/profile` → `/clean` → `/mart` → `/quality-gate` → `/html-dashboard` and `/powerbi` (every month) · **`/ppt-review`** (when there are questions). This skill is step 6.

Follow CLAUDE.md throughout: tag load-bearing claims [high]/[med]/[guess], don't guess about the business, keep it short.

**This is the opposite of the dashboard. Nobody clicks here.** It is a story Sushmita presents in a meeting, one message per slide.

## Files in this folder

| File | What it is |
|---|---|
| `slides.py` | `data/mart/` → `reports/ppt/<month name>-review.pptx` (e.g. `december-review.pptx`, overwritten each build), plus `runs/<run>/6-ppt-review/ppt-review-log.md` (every sentence, big number, table row and speaker note). Every number is a SQL query on the mart (section 3). The sentences are filled in from those numbers (section 4), so the deck tells the right story again next month. Charts are native PowerPoint charts, so they stay editable. Needs `python-pptx`. |
| `check.py` | Reads the deck back and writes `runs/<run>/6-ppt-review/ppt-review-checks.md`. Any FAIL → exit code 1. Road B is pandas straight from `data/raw/`, with the cleaning decisions re-applied; it shares no code with `slides.py`. |

Run both scripts from the project root. Neither ever modifies `data/`.

## The checks

| ID | Check |
|---|---|
| F01–F04 | The deck opens; it has 4 slides; every slide has speaker notes; it is newer than every mart CSV. |
| D01 | Dark background on every slide. |
| D02 | Exactly one amber item per question slide (the big number) and none on the last slide. |
| D03 | Exactly one chart or table on every slide. |
| D04 | No lines or decoration shapes: only the title, text boxes and the chart or table. |
| D05 | Segoe UI everywhere, nothing under 13pt. |
| D06 | Each answer is one sentence (an opening "Yes." or "No." is allowed), at most 120 characters. |
| D07 | Only the dashboard colours. |
| N01–N28 | Every number on the slides, deck vs `data/raw`:<br>• the chart values, the big numbers and the table rows;<br>• the exact totals in the speaker notes;<br>• countries and channels that fell, and how they did without the weakest category;<br>• the missing stock records;<br>• "biggest month" is said only when it is true.<br>The count changes with the data, e.g. more rows when more products run out. |

Every D check and a changed table number were shown to FAIL on a deliberately broken copy (2026-11-25).

## Steps

1. **Gate: the quality gate must have passed.**
   Read `runs/<run>/4-quality-gate/quality-gate-checks.md` (written by `/quality-gate`).
   - Missing → stop and ask the user to run `/quality-gate <run>` first.
   - Not "PASS - all quality rules hold" → stop, show the failing rules, and ask.

2. **Build**
   `python .claude/skills/ppt-review/slides.py --run <run> [--month <yyyy-mm>]`
   If it prints `ERROR`, report the reason and ask. If `python-pptx` is missing, ask before running `pip install python-pptx`.

3. **Check**
   `python .claude/skills/ppt-review/check.py --run <run> [--month <yyyy-mm>]`
   - All PASS → go on to step 4.
   - Any FAIL → the deck must not be shown. Show the failing checks with their details, find the cause, and propose a fix. Only make the fix after a yes. Never weaken a check to make it pass.

4. **Look at every slide.** The checks can't see layout. Export the slides with the installed PowerPoint into the scratchpad and read each image: look for text cut off, overlaps, a headline wrapping to 3 lines, and a table running into the bottom edge. Only do this when PowerPoint is **not** already open (check `Get-Process POWERPNT`), because the script closes PowerPoint at the end:
   ```powershell
   $ppt = New-Object -ComObject PowerPoint.Application
   try { $p = $ppt.Presentations.Open("<full path to deck>", $true, $false, $false)
         $i = 1; foreach ($s in $p.Slides) { $s.Export("<scratchpad>\slide$i.png", "PNG", 1600, 900); $i++ }
         $p.Close() } finally { $ppt.Quit() }
   ```
   Delete the images when done.

5. **Report to the user:** short, result first.
   - the verdict (e.g. 39/39 PASS) and the deck path
   - the answer on each slide, as written in `ppt-review-log.md`
   - what changed in the story compared with the previous run (read the previous `runs/*/6-ppt-review/ppt-review-log.md`). For example, a different weakest category, new products running out, or a bigger loss.
   - anything she should know before the meeting that isn't on slide 4 already

## Story and design rules (agreed with Sushmita, 2026-11-24)

**The deck:**
- 4 slides, 16:9, no title slide.
- One slide per question: the question as a small grey label, the answer in one sentence as the slide title (30pt bold).
- The last slide is "Before I show this, I must say these N things out loud": a table of what I say and why, with no big number.
- Speaker notes on every slide say where each number comes from, with exact euro amounts.

**Design:**
- Same look as the dashboard: background `#0e1117`, text `#e6e9ee` / `#b4bcc7` / `#8c96a3`, calm blue `#5f87b4` for every bar, amber `#f0a73a` only on the big number.
- One big number per question slide.
- Every slide has one chart or one table, never only text.
- No lines under titles, no decoration, no logos, no footers.
- Segoe UI.
- Her words: short sentences, no jargon.

**Definitions (business decisions, don't change without a yes):**

| Topic | Decision |
|---|---|
| Comparison | The review month vs the month before. Slide 4 states the data range and, only when true, that there is no data for the same month last year. Road B in `check.py` reads every delivery in `data/raw/<month>/` (orders and stock appended, newest price per product). |
| "Every part up" | Revenue change per category on the chart. The weakest category is the big number. Ran-out products in that category are named as the cause (sold last month, stock 0 at the end of last month, nothing sold this month). Countries and channels that fell go in the speaker notes, with their change without the weakest category. |
| Ran out | `qty_on_hand = 0` at the end of the review month. |
| What it cost | For each product that ran out: average monthly units in the 3 months before, minus units sold this month (not below 0), × its average selling price in those 3 months. Lost sales, not lost profit (no cost prices). Shown rounded to thousands. |
| Order more | Months of stock left = month-end stock ÷ average monthly units in the last 3 months (including the review month). Under 1 month is flagged, ranked by revenue in those 3 months. Products with no sales or no stock record are left out. |
| Grouping (layout choices, in the notes) | Slide 2: a product gets its own row at ≥ 1% of the total loss; the rest becomes one "N other products" row. Slide 3: "order first" = the biggest sellers that together make up 90% of the flagged revenue; the rest becomes "N more, smaller sellers". |

**Last slide, always:** revenue before returns; the loss is an estimate; only one year of data; stock has no country or channel; missing stock records are left out, not 0; the order list uses the last 3 months of sales ("is our biggest month" only when true).

## Rules

- **Never modify `data/`.** Only overwrite the deck in `reports/ppt/` and `runs/<run>/6-ppt-review/`.
- **Never hand-edit the deck.** It's regenerated on every build; change `slides.py` instead. If Sushmita edits the deck in PowerPoint, the next build overwrites her edits. Say so before rebuilding.
- **Code computes every number.** Quote numbers exactly as `ppt-review-log.md` or `ppt-review-checks.md` show them. Never type a number into a sentence by hand.
- **Business definitions belong to the user.** The definitions above are hers. A new definition, a new question or a different method is proposed first and made only after a yes. Then update `slides.py`, `check.py` and this file together.
- **A script failure is a blocker.** If a script errors twice the same way, stop and tell the user what's blocking you.
- **Clean up.** Delete any temporary files when done (slide images, test copies, `__pycache__`).
