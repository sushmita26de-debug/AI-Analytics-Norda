---
name: pipeline
description: Orchestrate the whole NORDA monthly analytical process for a run month, in a fixed order - profile, clean, mart, quality-gate, html-dashboard, ppt-review, powerbi (quality always before any report). Called with nothing, it shows a friendly overview of every step (what it does, when it last ran, green or red) and asks what to run - everything, from one step, or one step only. Every run is logged in runs/<month>/pipeline-log.md with the date and result of every step. If a step fails it stops, says which step and why, and restores the last good data and reports. Uses the existing skills as they are. Use when the user asks to run the pipeline, the monthly process, or "everything".
---

# Pipeline: the whole monthly process

Usage: `/pipeline` (overview, then ask) · `/pipeline <run-month>` · `/pipeline <run-month> everything | from <step> | only <step>`.
If no month is given, use the newest folder in `data/raw/` and say which one you picked.

Follow CLAUDE.md throughout: tag load-bearing claims [high]/[med]/[guess], don't guess about the business, keep it short.

## The order (fixed)

| # | Step | Skill | What it does |
|---|---|---|---|
| 1 | profile | `/profile` | Checks the new raw delivery for known and new data issues |
| 2 | clean | `/clean` | Cleans the delivery and rebuilds the combined history |
| 3 | mart | `/mart` | Builds the star schema in `data/mart/` (what Power BI reads) |
| 4 | quality-gate | `/quality-gate` | Computes every number twice, traces 10 orders |
| 5 | html-dashboard | `/html-dashboard` | Builds and checks `reports/html/dashboard.html` |
| 6 | ppt-review | `/ppt-review` | Builds and checks the monthly review deck (every month) |
| 7 | powerbi | `/powerbi` | Refreshes and checks the Power BI report |

**Quality always runs before any report.** "From html-dashboard" or "only powerbi" is allowed only when step 4 is green for that month; the report skills' own gate checks this too.

## Files in this folder

| File | What it is |
|---|---|
| `status.py` | Read-only overview: every step, what it does, last ran (date of its checks file), green/red (its verdict line), and the last pipeline run. |
| `guard.py` | `start` / `begin` / `end` / `finish`: writes `runs/<run>/pipeline-log.md`, backs up what a step overwrites into `runs/<run>/.last-good/`, decides PASS/FAIL from the step's checks file, restores on FAIL, deletes the backup at the end. |

The step list and the "green" verdict texts live in `STEPS` in `status.py`; `guard.py` reads them from there.

## Steps

1. **Overview** (always, also when the user gave a mode):
   `python .claude/skills/pipeline/status.py [--run <run>]`
   Show the table as printed. Add one short line on what it means (e.g. "steps 1–4 green from 25 Nov, 5–7 not run yet for 2026-09").
   If it warns that `.last-good/` exists, stop and tell the user: an earlier run did not finish.

2. **Ask what to run** (skip if the user already said): use AskUserQuestion with
   - **Everything** (1 → 7)
   - **From one step** (then ask which)
   - **One step only** (then ask which)

   Recommend the option that fits the overview: a new month with nothing run → everything; a step red → from that step.
   If the last pipeline run restored data (its result line says so), "from" must start at clean or earlier.
   Before starting, say the pauses that will come: profile blockers and `findings.md`; ppt-review overwrites any hand edits in the deck; Power BI Desktop must be closed for powerbi.

3. **Open the run:**
   `python .claude/skills/pipeline/guard.py start --run <run> --mode everything|from|only [--step <step>]`

4. **For every selected step, in order:**
   1. `python .claude/skills/pipeline/guard.py begin --run <run> --step <step>`
   2. Invoke the skill with the Skill tool (`<step>`, args `<run>`) and follow its SKILL.md exactly as written, including its gates, its pauses and its questions to the user. Don't skip, shorten or change any of its steps. Its report to the user can be 1–2 lines here; the full summary comes at the end.
   3. `python .claude/skills/pipeline/guard.py end --run <run> --step <step>`
      - If the skill stopped (a `STOPPED`/`ERROR`, a blocker, the user said no, a script failed twice) add `--stopped "<short reason>"`.
      - `PASS` → next step.
      - `STOP` (exit 1) → go to step 5. Never start the next step.

5. **Close the run:** `python .claude/skills/pipeline/guard.py finish --run <run>` (also after a failure).

6. **Report to the user:** short, result first.
   - All PASS: one line per step with its verdict, then the key points from the skills' reports (headline numbers as the checks files print them, the deck's answers, "open Power BI and click Refresh").
   - A failure: **which step failed and why** (the failing checks, from its checks file), what was restored (as `guard.py` printed it), which steps did not run, and a proposed fix. Make the fix only after a yes.
   - The log path: `runs/<run>/pipeline-log.md`.

## Protecting the last good outputs

The report skills build first and check afterwards, so on their own a failed build would already have replaced the last good file. `guard.py` closes that gap without changing those skills:

| Step | Backed up before it runs | Restored if it fails |
|---|---|---|
| profile | nothing (writes only `runs/`) | - |
| clean, mart, quality-gate | `data/clean/all/`, `data/clean/<run>/`, `data/mart/` (once, before the first of these) | all three, if any of the three fails (a failed quality gate means Power BI must not refresh from that mart) |
| html-dashboard | `reports/html/dashboard.html` | that file |
| ppt-review | `reports/ppt/` | that folder |
| powerbi | nothing (it never saves the project) | - |

A failed step's own `runs/<run>/<n>-<step>/` folder is **kept**: it is the evidence of why it failed. Steps after a failure never start, so their reports stay as they were.

## Rules

- **Use the existing skills as they are.** Never edit another skill's files from this skill. If a skill needs a change, propose it first.
- **Never skip the quality gate before a report**, and never continue after a FAIL, even if the user's choice was "everything".
- **Never restore or delete by hand.** Only `guard.py` touches the backup. If it errors twice the same way, stop and tell the user what's blocking you; don't delete `.last-good/` yourself.
- **Code computes every number.** Quote verdicts and numbers exactly as the checks files and scripts print them.
- **Clean up.** `finish` deletes `.last-good/`; delete any other temporary files you created.
