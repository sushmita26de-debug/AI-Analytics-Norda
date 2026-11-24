"""Pipeline guard: run log + protection of the last good outputs.

Usage (from the project root), in this order:
    python .claude/skills/pipeline/guard.py start  --run M --mode everything
    python .claude/skills/pipeline/guard.py start  --run M --mode from --step mart
    python .claude/skills/pipeline/guard.py start  --run M --mode only --step ppt-review
    python .claude/skills/pipeline/guard.py begin  --run M --step <step>     # before a step
    python .claude/skills/pipeline/guard.py end    --run M --step <step> [--stopped "reason"]
    python .claude/skills/pipeline/guard.py finish --run M

start   opens a new section in runs/<M>/pipeline-log.md and creates runs/<M>/.last-good/.
begin   notes the start time and backs up what the step will overwrite:
          clean / mart / quality-gate -> data/clean/all, data/clean/<M>, data/mart (once per run)
          html-dashboard              -> reports/html/dashboard.html
          ppt-review                  -> reports/ppt/
          profile, powerbi            -> nothing (they never overwrite data or reports)
end     reads the step's checks file and decides PASS/FAIL itself. A checks file older than
        `begin` means the step stopped before its checks ran -> FAIL. --stopped forces FAIL.
        On FAIL it restores the backup and prints STOP. Exit code 1 on FAIL.
finish  marks the steps that did not run, writes the result line, deletes .last-good/.
"""
import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from status import STEPS, STEP_NAMES, verdict_line  # noqa: E402

ROOT = Path.cwd()
DATA_STEPS = {"clean", "mart", "quality-gate"}
REPORT_TARGETS = {"html-dashboard": "reports/html/dashboard.html", "ppt-review": "reports/ppt"}


def now():
    return dt.datetime.now()


def paths(run):
    rd = ROOT / "runs" / run
    return rd, rd / "pipeline-log.md", rd / ".last-good", rd / ".last-good" / "state.json"


def load(run):
    _, _, _, sf = paths(run)
    if not sf.is_file():
        sys.exit(f"STOPPED: no pipeline run open for {run} (call start first)")
    return json.loads(sf.read_text(encoding="utf-8"))


def save(run, state):
    _, _, _, sf = paths(run)
    sf.write_text(json.dumps(state, indent=2), encoding="utf-8")


def log(run, text):
    _, lf, _, _ = paths(run)
    with lf.open("a", encoding="utf-8") as f:
        f.write(text)


def copy(src, dst):
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def put_back(backup, target):
    """Replace target with backup (or remove target if there was nothing before)."""
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    if backup.exists():
        copy(backup, target)


def data_targets(run):
    return {"clean_all": ROOT / "data/clean/all", "clean_run": ROOT / "data/clean" / run,
            "mart": ROOT / "data/mart"}


def cmd_start(a):
    rd, lf, lg, _ = paths(a.run)
    if lg.exists():
        sys.exit(f"STOPPED: runs/{a.run}/.last-good/ exists - an earlier run did not finish. "
                 f"Check it, then run finish.")
    if a.mode == "everything":
        sel, label = STEP_NAMES, "everything"
    else:
        if a.step not in STEP_NAMES:
            sys.exit(f"STOPPED: --step must be one of {', '.join(STEP_NAMES)}")
        i = STEP_NAMES.index(a.step)
        sel = STEP_NAMES[i:] if a.mode == "from" else [a.step]
        label = f"from {a.step}" if a.mode == "from" else f"only {a.step}"
    rd.mkdir(parents=True, exist_ok=True)
    lg.mkdir()
    started = now()
    save(a.run, {"started": started.isoformat(), "mode": label, "steps": sel, "done": {},
                 "step_start": {}, "data_backup": False, "failed": None, "restored": []})
    if not lf.exists():
        log(a.run, f"# Pipeline log - run {a.run}\n\nOne section per pipeline run, newest last. "
                   f"Written by `.claude/skills/pipeline/guard.py`.\n")
    log(a.run, f"\n## {started:%Y-%m-%d %H:%M} · {label} ({' → '.join(sel)})\n\n"
               f"| # | Step | Started | Finished | Result | Verdict |\n|---|---|---|---|---|---|\n")
    print(f"OK - pipeline run opened for {a.run}: {label} ({' → '.join(sel)})")


def cmd_begin(a):
    st = load(a.run)
    _, _, lg, _ = paths(a.run)
    if a.step not in st["steps"]:
        sys.exit(f"STOPPED: {a.step} is not part of this run ({', '.join(st['steps'])})")
    if st["failed"]:
        sys.exit(f"STOPPED: {st['failed']} failed in this run - no further steps")
    if a.step in DATA_STEPS and not st["data_backup"]:
        st["data_had"] = {}
        for key, p in data_targets(a.run).items():
            st["data_had"][key] = p.exists()
            if p.exists():
                copy(p, lg / "data" / key)
        st["data_backup"] = True
        print("Backed up: data/clean/all, data/clean/" + a.run + ", data/mart")
    if a.step in REPORT_TARGETS:
        src = ROOT / REPORT_TARGETS[a.step]
        dst = lg / "reports" / a.step
        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        if src.exists():
            copy(src, dst / src.name if src.is_file() else dst)
        print(f"Backed up: {REPORT_TARGETS[a.step]}" if src.exists()
              else f"Nothing to back up: {REPORT_TARGETS[a.step]} does not exist yet")
    st["step_start"][a.step] = now().isoformat()
    save(a.run, st)
    print(f"OK - {a.step} may start")


def cmd_end(a):
    st = load(a.run)
    _, _, lg, _ = paths(a.run)
    if a.step not in st["step_start"]:
        sys.exit(f"STOPPED: begin was not called for {a.step}")
    began = dt.datetime.fromisoformat(st["step_start"][a.step])
    step = STEPS[STEP_NAMES.index(a.step)]
    checks = ROOT / "runs" / a.run / step[3]

    if a.stopped:
        result, verdict = "FAIL", f"stopped: {a.stopped}"
    elif not checks.is_file() or dt.datetime.fromtimestamp(checks.stat().st_mtime) < began:
        result, verdict = "FAIL", "no new checks file - the step stopped before its checks ran"
    else:
        verdict = verdict_line(checks).replace("*", "")
        result = "PASS" if step[4] in verdict else "FAIL"

    finished = now()
    log(a.run, f"| {step[0]} | {a.step} | {began:%H:%M:%S} | {finished:%H:%M:%S} | "
               f"{'✅ PASS' if result == 'PASS' else '❌ FAIL'} | {verdict.replace('|', '/')} |\n")
    st["done"][a.step] = result

    if result == "PASS":
        if a.step in REPORT_TARGETS and (lg / "reports" / a.step).exists():
            shutil.rmtree(lg / "reports" / a.step)
        save(a.run, st)
        print(f"PASS - {a.step}: {verdict}")
        return

    st["failed"] = a.step
    restored = []
    if a.step in DATA_STEPS and st["data_backup"]:
        for key, p in data_targets(a.run).items():
            put_back(lg / "data" / key, p)
            restored.append(str(p.relative_to(ROOT)).replace("\\", "/")
                            + ("" if st["data_had"][key] else " (removed, did not exist before)"))
    if a.step in REPORT_TARGETS:
        target = ROOT / REPORT_TARGETS[a.step]
        b = lg / "reports" / a.step
        put_back(b / target.name if target.suffix else b, target)
        restored.append(REPORT_TARGETS[a.step])
    st["restored"] = restored
    save(a.run, st)
    print(f"STOP - {a.step} FAILED: {verdict}")
    print(f"Checks: runs/{a.run}/{step[3]}")
    print("Restored last good: " + (", ".join(restored) if restored else "nothing to restore"))
    sys.exit(1)


def cmd_finish(a):
    st = load(a.run)
    _, _, lg, _ = paths(a.run)
    for name in st["steps"]:
        if name not in st["done"]:
            n = STEPS[STEP_NAMES.index(name)][0]
            log(a.run, f"| {n} | {name} | - | - | ⚪ not run | - |\n")
    if st["failed"]:
        line = (f"**Result: STOPPED at {st['failed']}.** Restored: "
                f"{', '.join(st['restored']) or 'nothing'}.")
        if st["restored"] and st["failed"] in DATA_STEPS:
            line += " Data was put back, so the next run must start from clean (or profile)."
    elif len(st["done"]) < len(st["steps"]):
        missing = [s for s in st["steps"] if s not in st["done"]]
        line = (f"**Result: NOT FINISHED - closed before {missing[0]}.** "
                f"{len(st['done'])} of {len(st['steps'])} step(s) ran, all PASS.")
    else:
        line = f"**Result: all {len(st['steps'])} step(s) PASS.**"
    log(a.run, f"\n{line} Finished {now():%Y-%m-%d %H:%M}.\n")
    shutil.rmtree(lg)
    print(line.replace("*", ""))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["start", "begin", "end", "finish"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--mode", choices=["everything", "from", "only"])
    ap.add_argument("--step")
    ap.add_argument("--stopped")
    a = ap.parse_args()
    if a.command == "start" and not a.mode:
        sys.exit("STOPPED: start needs --mode")
    if a.command in ("begin", "end") and a.step not in STEP_NAMES:
        sys.exit(f"STOPPED: --step must be one of {', '.join(STEP_NAMES)}")
    {"start": cmd_start, "begin": cmd_begin, "end": cmd_end, "finish": cmd_finish}[a.command](a)


if __name__ == "__main__":
    main()
