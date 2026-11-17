#!/usr/bin/env python3
"""Read-only scanner: turns existing run folders into index.jsonl records.

- Reads ONLY the roots you pass (default: natural-lab and genesis-pattern-lab).
- Never edits, moves or deletes any source file.
- Writes to a NEW folder ~/records-scan/scan-<timestamp>/ each time.
- Standard library only. Records that break a rule are reported, not fixed.

Usage:
    python3 scan_records.py
    python3 scan_records.py ~/natural-lab ~/genesis-pattern-lab
"""
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SOURCES = {"natural-lab": "natural-lab", "genesis-pattern-lab": "pattern-lab"}
VERIFIED_ON = {"sandbox", "termux"}
STATUS = {"complete", "partial", "unknown"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
METRIC_KEYS = ("current_regime_accuracy", "next_grid_accuracy",
               "next_grid_accuracy_all", "wrong_switch_count")
REQUIRED = ("source", "algo", "seed", "params", "metrics", "artifact_path",
            "sha256", "device_profile_ref", "verified_on", "status")


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(rec):
    errs = []
    missing = [k for k in REQUIRED if rec.get(k) is None]
    if missing:
        errs.append("missing: " + ", ".join(missing))
    if rec.get("source") not in SOURCES.values():
        errs.append("source not allowed")
    if not isinstance(rec.get("seed"), int) or isinstance(rec.get("seed"), bool) or rec.get("seed", -1) < 0:
        errs.append("seed must be integer >= 0")
    if not HEX64.match(str(rec.get("sha256", ""))):
        errs.append("sha256 malformed")
    if rec.get("status") not in STATUS:
        errs.append("status not allowed")
    if not set(rec.get("verified_on") or []) <= VERIFIED_ON:
        errs.append("verified_on not allowed")
    return errs


def manifest_check(run):
    """Return (ok, problems) by re-hashing every file listed in manifest.sha256."""
    mf = run / "manifest.sha256"
    if not mf.is_file():
        return None, ["no manifest.sha256"]
    problems = []
    for line in mf.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, name = line.split(maxsplit=1)
        target = run / name.strip()
        if not target.is_file():
            problems.append(f"listed file missing: {name.strip()}")
        elif sha256_file(target) != expected:
            problems.append(f"hash mismatch: {name.strip()}")
    return not problems, problems


def source_of(path):
    for part in path.parts:
        if part in SOURCES:
            return SOURCES[part]
    return None


def main():
    roots = [Path(p).expanduser() for p in sys.argv[1:]] or [
        Path.home() / "natural-lab", Path.home() / "genesis-pattern-lab"]
    out = Path.home() / "records-scan" / f"scan-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=False)
    records, skipped, problems = [], [], []

    for root in roots:
        if not root.exists():
            skipped.append(f"{root}: folder not found")
            continue
        for summary in sorted(root.rglob("summary.json")):
            run = summary.parent
            src = source_of(summary)
            if src is None:
                skipped.append(f"{summary}: no adapter for this folder")
                continue
            try:
                data = json.loads(summary.read_text(encoding="utf-8"))
            except Exception as e:
                problems.append(f"{summary}: unreadable JSON ({e})")
                continue
            ok, why = manifest_check(run)
            rec = {
                "source": src,
                "algo": data.get("algo"),
                "seed": data.get("seed"),
                "params": data.get("drawn", {}),
                "metrics": {k: data[k] for k in METRIC_KEYS if k in data},
                "artifact_path": "summary.json",
                "sha256": sha256_file(summary),
                "device_profile_ref": "none",
                "verified_on": ["termux"],
                "status": "complete" if ok else ("partial" if ok is False else "unknown"),
            }
            errs = check(rec)
            if ok is False:
                errs += why
            if errs:
                problems.append(f"{run}: " + "; ".join(errs))
                rec["status"] = "partial"
            records.append(rec)

    with (out / "index.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    report = [
        f"scanned roots: {[str(r) for r in roots]}",
        f"records written: {len(records)}",
        f"skipped: {len(skipped)}", *[f"  - {s}" for s in skipped],
        f"problems: {len(problems)}", *[f"  - {p}" for p in problems],
    ]
    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print("OUTPUT:", out)


if __name__ == "__main__":
    main()
