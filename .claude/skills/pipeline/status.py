"""Pipeline overview (read-only).

Usage (from the project root):
    python .claude/skills/pipeline/status.py [--run YYYY-MM]

Shows every pipeline step, what it does, when it last ran (date of its checks
file) and whether it was green (the verdict line in that file), plus the last
pipeline run from runs/<run>/pipeline-log.md. Writes nothing.
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path.cwd()

# The pipeline order. Quality gate always runs before any report.
# (n, skill, what it does, checks file, verdict text that means green)
STEPS = [
    (1, "profile", "Checks the new raw delivery for known and new data issues",
     "1-profile/profile-checks.md", "OK - no blockers"),
    (2, "clean", "Cleans the delivery and rebuilds the combined history",
     "2-clean/clean-checks.md", "PASS - clean layer OK"),
    (3, "mart", "Builds the star schema in data/mart/ (what Power BI reads)",
     "3-mart/mart-checks.md", "PASS - mart OK"),
    (4, "quality-gate", "Computes every number twice, traces 10 orders",
     "4-quality-gate/quality-gate-checks.md", "PASS - all quality rules hold"),
    (5, "html-dashboard", "Builds and checks reports/html/dashboard.html",
     "5-html-dashboard/html-dashboard-checks.md", "PASS - dashboard OK"),
    (6, "ppt-review", "Builds and checks the monthly review deck",
     "6-ppt-review/ppt-review-checks.md", "PASS - deck OK"),
    (7, "powerbi", "Refreshes and checks the Power BI report",
     "7-powerbi/powerbi-checks.md", "PASS - Power BI OK"),
]
STEP_NAMES = [s[1] for s in STEPS]


def months(folder):
    p = ROOT / folder
    if not p.is_dir():
        return []
    return sorted(d.name for d in p.iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}", d.name))


def verdict_line(path):
    """The first bold line of a checks file, e.g. '**PASS - mart OK** (43 checks)'."""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("**"):
            return line.strip()
    return ""


def step_state(run, step):
    """(state, last_ran, verdict) for one step. state: GREEN / RED / NOT RUN."""
    n, name, _, rel, green = step
    path = ROOT / "runs" / run / rel
    if not path.is_file():
        return "NOT RUN", None, ""
    v = verdict_line(path)
    ran = dt.datetime.fromtimestamp(path.stat().st_mtime)
    return ("GREEN" if green in v else "RED"), ran, re.sub(r"\*", "", v)


def last_pipeline_run(run):
    log = ROOT / "runs" / run / "pipeline-log.md"
    if not log.is_file():
        return None
    sections = log.read_text(encoding="utf-8").split("\n## ")
    return sections[-1] if len(sections) > 1 else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="run month YYYY-MM (default: newest folder in data/raw)")
    a = ap.parse_args()

    raw = months("data/raw")
    if not raw:
        sys.exit("STOPPED: no delivery folder in data/raw/")
    run = a.run or raw[-1]
    print(f"Run month: {run}   (deliveries in data/raw: {', '.join(raw)}; "
          f"run folders in runs/: {', '.join(months('runs')) or 'none'})")
    if run not in raw:
        print(f"WARNING: data/raw/{run}/ does not exist")
    print()
    print(f"| # | Step | What it does | Last ran | Status | Verdict |")
    print(f"|---|---|---|---|---|---|")
    for step in STEPS:
        state, ran, v = step_state(run, step)
        mark = {"GREEN": "🟢 green", "RED": "🔴 red", "NOT RUN": "⚪ not run"}[state]
        when = ran.strftime("%Y-%m-%d %H:%M") if ran else "-"
        print(f"| {step[0]} | {step[1]} | {step[2]} | {when} | {mark} | {v or '-'} |")

    last = last_pipeline_run(run)
    print()
    if last is None:
        print(f"Last pipeline run: none yet (runs/{run}/pipeline-log.md does not exist)")
    else:
        print("Last pipeline run:")
        print("## " + last.strip())
    if (ROOT / "runs" / run / ".last-good").exists():
        print()
        print(f"WARNING: runs/{run}/.last-good/ exists - a pipeline run did not finish. "
              f"Run `guard.py finish --run {run}` after checking what happened.")


if __name__ == "__main__":
    main()
