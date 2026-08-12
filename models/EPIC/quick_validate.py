#!/usr/bin/env python3
"""Quick validation: run (or verify) the shipped umstead example and report JSON.

Usage:
    python3 quick_validate.py              # use existing outputs if available
    python3 quick_validate.py --rerun      # force a fresh Wine execution
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

KI_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(KI_DIR, "templates")
TOOLS_DIR = os.path.join(KI_DIR, "tools")
sys.path.insert(0, TOOLS_DIR)

# The binary and the example workspace used to be hard-coded to the transient
# dissection scratch tree (_work_v2/EPIC/epic_workspace). SKILL.md already says
# that path "is a transient dissection scratch dir and no longer exists" and
# that the binary must be resolved via tools/_common.resolve_binary() -- but
# this file bypassed it, so `quick_validate.py --rerun` died with
# "[Errno 2] No such file or directory: .../_work_v2/.../epic1102-official_release.exe"
# and the no-`--rerun` path reported "Missing umstead_0.ANN". Resolve both
# against durable locations instead.
from _common import resolve_binary  # noqa: E402  (TOOLS_DIR added to sys.path above)

DEFAULT_BINARY = resolve_binary()
MODEL_DIR = os.path.abspath(os.path.join(KI_DIR, ".."))
# Durable locations that hold the shipped umstead_0.* outputs, most-preferred
# first; the scratch tree stays last so an old checkout still resolves.
WORKSPACE_CANDIDATES = [
    os.path.join(KI_DIR, "runs", "umstead_quick_validate"),
    os.path.join(MODEL_DIR, "outputs"),
    os.path.join(MODEL_DIR, "source", "repo"),
    "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent"
    "/_work_v2/EPIC/epic_workspace",
]


def _default_workspace(for_rerun=False):
    """Where to look for (or produce) the umstead_0 example outputs.

    A `--rerun` always writes into the KI-local runs/ dir so the shipped
    reference outputs under models/EPIC/outputs/ are never overwritten.
    """
    if for_rerun:
        return WORKSPACE_CANDIDATES[0]
    for c in WORKSPACE_CANDIDATES:
        if os.path.isfile(os.path.join(c, "umstead_0.ANN")):
            return c
    return WORKSPACE_CANDIDATES[0]

RUN_NAME = "umstead_0"
EXPECTED_YIELD_RANGE = (2.0, 15.0)  # t/ha for NC corn
EXPECTED_P_RANGE = (700, 1600)       # mm/yr for NC
EXPECTED_ET_RANGE = (300, 900)       # mm/yr


def _has_outputs(workspace):
    ann = os.path.join(workspace, f"{RUN_NAME}.ANN")
    acy = os.path.join(workspace, f"{RUN_NAME}.ACY")
    return os.path.isfile(ann) and os.path.isfile(acy)


def _run_epic(workspace):
    """Run EPIC in a temporary workspace using shipped templates."""
    ws = workspace or tempfile.mkdtemp(prefix="epic_qv_")
    os.makedirs(ws, exist_ok=True)
    for fn in os.listdir(TEMPLATES_DIR):
        src = os.path.join(TEMPLATES_DIR, fn)
        dst = os.path.join(ws, fn)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
    shutil.copy2(DEFAULT_BINARY, os.path.join(ws, os.path.basename(DEFAULT_BINARY)))
    exe = os.path.join(ws, os.path.basename(DEFAULT_BINARY))
    proc = subprocess.run(
        ["wine", exe], cwd=ws, timeout=300,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"EPIC exited {proc.returncode}")
    return ws


def _parse_ann(path):
    with open(path, "rb") as f:
        raw = f.read().decode("ascii", errors="replace")
    header = None
    rows = []
    for line in raw.replace("\r", "").splitlines():
        toks = line.split()
        if not toks:
            continue
        if header is None:
            if toks[0] in ("RUN", "YR"):
                header = toks
        else:
            try:
                int(toks[0])
            except ValueError:
                continue
            rows.append(toks)
    if not header:
        return []
    idx = {c: i for i, c in enumerate(header)}
    data = []
    for r in rows:
        def g(col):
            return float(r[idx[col]]) if col in idx and idx[col] < len(r) else 0.0
        data.append({
            "yr": int(r[idx.get("YR", 0)]) if "YR" in idx else 0,
            "P": g("PRCP"), "ET": g("ET"), "Q": g("Q"),
            "PET": g("PET"), "IRGA": g("IRGA"),
        })
    return data


def _parse_acy(path):
    with open(path, "rb") as f:
        raw = f.read().decode("ascii", errors="replace")
    header = None
    rows = []
    for line in raw.replace("\r", "").splitlines():
        toks = line.split()
        if not toks:
            continue
        if header is None:
            if toks[0] == "YR":
                header = toks
        else:
            try:
                int(toks[0])
            except ValueError:
                continue
            rows.append(toks)
    if not header:
        return []
    idx = {c: i for i, c in enumerate(header)}
    yields = []
    for r in rows:
        if "YLDG" in idx and idx["YLDG"] < len(r):
            yields.append(float(r[idx["YLDG"]]))
    return yields


def validate(workspace):
    issues = []
    metrics = {}

    ann_path = os.path.join(workspace, f"{RUN_NAME}.ANN")
    acy_path = os.path.join(workspace, f"{RUN_NAME}.ACY")

    if not os.path.isfile(ann_path):
        issues.append(f"Missing {RUN_NAME}.ANN")
    if not os.path.isfile(acy_path):
        issues.append(f"Missing {RUN_NAME}.ACY")
    if issues:
        return False, issues, metrics

    ann_data = _parse_ann(ann_path)
    if not ann_data:
        issues.append("Could not parse ANN file")
        return False, issues, metrics

    P = sum(d["P"] for d in ann_data) / len(ann_data)
    ET = sum(d["ET"] for d in ann_data) / len(ann_data)
    Q = sum(d["Q"] for d in ann_data) / len(ann_data)
    IRGA = sum(d["IRGA"] for d in ann_data) / len(ann_data)

    metrics["years"] = len(ann_data)
    metrics["P_mean_mm"] = round(P, 1)
    metrics["ET_mean_mm"] = round(ET, 1)
    metrics["Q_surface_mm"] = round(Q, 1)
    metrics["IRGA_mean_mm"] = round(IRGA, 1)
    # Q in ANN is surface runoff only; deep percolation is separate
    metrics["residual_mm"] = round((P + IRGA) - (ET + Q), 1)

    if not (EXPECTED_P_RANGE[0] <= P <= EXPECTED_P_RANGE[1]):
        issues.append(f"Precipitation {P:.0f} mm/yr outside expected {EXPECTED_P_RANGE}")
    if not (EXPECTED_ET_RANGE[0] <= ET <= EXPECTED_ET_RANGE[1]):
        issues.append(f"ET {ET:.0f} mm/yr outside expected {EXPECTED_ET_RANGE}")
    if ET > P + IRGA:
        issues.append(f"ET ({ET:.0f}) exceeds P+IRGA ({P+IRGA:.0f}) — energy/water error")

    yields = _parse_acy(acy_path)
    if yields:
        mean_yield = sum(yields) / len(yields)
        metrics["mean_yield_t_ha"] = round(mean_yield, 2)
        if not (EXPECTED_YIELD_RANGE[0] <= mean_yield <= EXPECTED_YIELD_RANGE[1]):
            issues.append(
                f"Mean yield {mean_yield:.1f} t/ha outside expected {EXPECTED_YIELD_RANGE}"
            )
    else:
        issues.append("Could not parse ACY yield data")

    return len(issues) == 0, issues, metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun", action="store_true",
                    help="Force a fresh EPIC run instead of using existing outputs")
    ap.add_argument("--workspace", default=None)
    args = ap.parse_args()
    if args.workspace is None:
        args.workspace = _default_workspace(for_rerun=args.rerun)

    result = {
        "ki_usable": False,
        "tools_failed": [],
        "skill_md_issues": [],
        "metrics": {"nse": None, "r": None},
        "notes": "",
    }

    try:
        if args.rerun or not _has_outputs(args.workspace):
            print("Running EPIC umstead example via Wine...")
            ws = _run_epic(args.workspace)
        else:
            print(f"Using existing outputs in {args.workspace}")
            ws = args.workspace

        ok, issues, metrics = validate(ws)
        result["ki_usable"] = ok
        result["tools_failed"] = issues
        result["metrics"].update(metrics)
        result["notes"] = (
            f"Umstead NC corn 15yr: P={metrics.get('P_mean_mm')} "
            f"ET={metrics.get('ET_mean_mm')} Q_sfc={metrics.get('Q_surface_mm')} "
            f"yield={metrics.get('mean_yield_t_ha', '?')} t/ha"
        )
        if ok:
            print("PASS: umstead example validated")
        else:
            print(f"ISSUES: {issues}")

    except Exception as e:
        result["tools_failed"] = [str(e)]
        result["notes"] = f"quick_validate failed: {e}"
        print(f"ERROR: {e}")

    print(json.dumps(result, indent=2))
    return 0 if result["ki_usable"] else 1


if __name__ == "__main__":
    sys.exit(main())
