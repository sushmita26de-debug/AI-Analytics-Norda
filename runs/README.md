# runs/: what every file is

There is one folder per run month (e.g. `runs/2026-08/`), the month a delivery arrived. Inside it there's one subfolder per pipeline step, numbered in the order the steps run. Each step only starts if the step before it passed.

```
runs/<month>/
  1-profile/          /profile         - is the new delivery (data/raw/<month>/) safe to clean?
  2-clean/            /clean           - delivery -> data/clean/<month>/, history -> data/clean/all/
  3-mart/             /mart            - data/clean/all/ -> data/mart/ (star schema)
  4-quality-gate/     /quality-gate    - are the numbers safe to show stakeholders?
  5-html-dashboard/   /html-dashboard  - data/mart/ -> reports/html/dashboard.html (interactive, offline)
  6-ppt-review/       /ppt-review      - data/mart/ -> reports/ppt/<month>-review.pptx (only when there are questions)
  7-powerbi/          /powerbi         - reports/powerbi/NORDA Sales.pbip refreshed from data/mart/ and checked
```

Naming rule: `<n>-<skill>/<skill>-checks.md` (pass/fail checks) and `<skill>-log.md` (what was built). The script that verifies is always `check.py` in `.claude/skills/<skill>/`.

| File | What it holds | Written by | Read it when |
|---|---|---|---|
| `1-profile/profile-checks.md` | 40 PASS/FAIL checks on the new delivery, incl. H01–H05 against earlier deliveries. Each is labelled *known* (decided; the run continues) or *blocker* (stop and ask). Verdict at the top. | `profile/check.py` | You want to know if the new delivery has anything new or broken |
| `1-profile/profile-output.txt` | The full column-by-column profile of the delivery: counts, formats, value lists, money impact. Long, technical. | `profile/profile.py` | You need the detail behind a finding |
| `1-profile/findings.md` | The data quality findings in plain language, with rows affected, EUR impact and questions for you. | Claude, from the two files above | **Start here** for "what's wrong with the raw data" |
| `2-clean/clean-log.md` | Rows in, changed and removed per cleaning step, the column renames, and the combined history per delivery. | `clean/clean.py` | You want to know what cleaning did |
| `2-clean/clean-checks.md` | 49 PASS/FAIL checks on the clean delivery and the combined history, including reconciliation with raw. | `clean/check.py` | You want proof that cleaning lost nothing |
| `3-mart/mart-log.md` | Tables built, row counts, columns, and the diagram path. | `mart/mart.py` | You want to know what's in `data/mart/` |
| `3-mart/mart-checks.md` | 43 PASS/FAIL checks on the star schema, plus the **dashboard headline numbers**. | `mart/check.py` | You want proof the model is correct, or the headline numbers |
| `4-quality-gate/quality-gate-checks.md` | The quality rules 1–4 from `knowledge/quality-rules.md`: two roads per number (25 checks), 10 traced orders of the new delivery (with the seed), always-true rules. | `quality-gate/check.py` | **Before any number goes to a meeting** |
| `5-html-dashboard/html-dashboard-log.md` | Rows read, period, headline numbers, inventory gaps, and the path and size of the HTML dashboard. | `html-dashboard/dashboard.py` | You want to know what went into the dashboard |
| `5-html-dashboard/html-dashboard-checks.md` | 16 PASS/FAIL checks: the real page is opened in headless Edge, clicked through like a user, and every number shown is compared with SQL on `data/mart/`. | `html-dashboard/check.py` | **Before you share the dashboard** |
| `6-ppt-review/ppt-review-log.md` | Every sentence, big number, table row and speaker note on the review deck, with the review month. | `ppt-review/slides.py` | You want the story in text, or to compare it with last month |
| `6-ppt-review/ppt-review-checks.md` | ~39 PASS/FAIL checks: the design rules read from the deck, and every number on the slides recomputed from every delivery in `data/raw/`. | `ppt-review/check.py` | **Before you present the deck** |
| `7-powerbi/powerbi-checks.md` | 22 PASS/FAIL checks: the Power BI project refreshed from `data/mart/`, every measure compared with SQL. | `powerbi/check.py` | **Before you share the Power BI report** |
| `7-powerbi/powerbi.png` | Screenshot of the Power BI window after the refresh. | `powerbi/check.py` | You want to see what the report looked like |
| `pipeline-log.md` | One section per `/pipeline` run: date, what was run (everything / from a step / one step), and each step's start, finish, PASS/FAIL and verdict, plus what was restored after a failure. | `pipeline/guard.py` | You want the history of runs for this month |

**Everything except `findings.md` is generated.** Don't edit those files; rerun the step instead. Rerunning a step overwrites its own subfolder only.

All scripts live in `.claude/skills/<skill>/`.
