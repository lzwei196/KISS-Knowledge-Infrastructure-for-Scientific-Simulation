#!/usr/bin/env python3
"""Preflight check for the KINEROS2 Knowledge Infrastructure (REAL engine).

Checks, before any model run:
  1. the real KINEROS2 executable (USDA-ARS K2shell, Fortran) -- found via $KINEROS2_BIN, the models
     DB binary_path, or the builder default; exists, is executable, is an ELF binary;
  2. it actually RUNS: the official ARS sample EX1 (one plane + channel, with sediment) is run in a
     temporary folder through tools/run_kineros2_engine.py and its event totals must match the build
     log values (examples/ars_samples/expected_results.json) -- the engine exits 0 even on errors,
     so only the output text proves a run;
  3. python modules the tools need, the shipped sample inputs, and the diagnostics corpus.

The Python SURROGATE (tools/run_kineros2.py) is NOT checked here: it is not the model.

Exit 0 = model ready; 1 = blockers (each failed check prints a fix and points to
diagnostics/triplets.yaml).  Last line: PREFLIGHT_REPORT=<json>.
"""
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

MODEL_ID = "KINEROS2"
KI_DIR = Path(__file__).resolve().parent
TOOLS = KI_DIR / "tools"
EXAMPLES = KI_DIR / "examples" / "ars_samples"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
CHECKS = []


def record(kind, subject, critical, ok, fix=""):
    CHECKS.append({"kind": kind, "subject": str(subject), "critical": bool(critical),
                   "status": "pass" if ok else "fail", "fix": "" if ok else fix})
    print(f"  {'OK  ' if ok else 'FAIL'} [{'critical' if critical else 'optional'}] {kind}: {subject}")
    if not ok:
        print(f"        fix: {fix}")
    return ok


def emit_report():
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": CHECKS}, ensure_ascii=False))
    critical = [c for c in CHECKS if c["critical"]]
    ready = bool(critical) and all(c["status"] == "pass" for c in critical)
    raise SystemExit(0 if ready else 1)


def main():
    print("KINEROS2 preflight (real engine)")
    sys.path.insert(0, str(TOOLS))

    # 1. binary
    binary = None
    try:
        import _k2lib as k2
        binary = k2.resolve_binary()
        with open(binary, "rb") as fh:
            is_elf = fh.read(4) == b"\x7fELF"
        if not record("binary", os.path.realpath(binary), True, is_elf,
                      "the file is not a Linux ELF executable; rebuild with "
                      "KISSPATH_HOME/engine_builds_20261006/KINEROS2/build.sh (see triplet dt_kineros2_020)"):
            binary = None
    except Exception as e:  # resolve_binary raises with the reason
        record("binary", os.environ.get("KINEROS2_BIN") or "k2 (KINEROS2_BIN / models DB / default)", True, False,
               f"{e}; set KINEROS2_BIN=/path/to/k2 or rebuild (triplets dt_kineros2_020, dt_kineros2_021)")

    # 2. the engine runs the official example and reproduces it
    if binary is not None:
        try:
            from run_kineros2_engine import run_case
            spec = json.loads((EXAMPLES / "expected_results.json").read_text())
            ex, tol = spec["examples"]["ex1"], spec["tolerance"]["rel"]
            with tempfile.TemporaryDirectory(prefix="k2_preflight_") as td:
                res = run_case(str(EXAMPLES / ex["parfile"]), str(EXAMPLES / ex["rainfile"]), Path(td),
                               ex["tfin_min"], ex["dt_min"], courant=ex["courant"], sediment=ex["sediment"],
                               title=ex["title"], binary=str(binary))
            es = res.get("event_summary") or {}
            got = {"outflow_volume": (es.get("outflow") or {}).get("volume"),
                   "sediment_yield_t_per_ha": es.get("sediment_yield")}
            ok = res["status"] == "success" and all(
                got[k] is not None and abs(got[k] - ex["expected"][k]) <= tol * abs(ex["expected"][k]) for k in got)
            record("run", os.path.realpath(binary), True, ok,
                   f"EX1 smoke run gave status={res['status']} {got} vs expected "
                   f"{ {k: ex['expected'][k] for k in got} }; failures={res.get('failures')}; "
                   f"see triplets dt_kineros2_027/dt_kineros2_028")
        except Exception as e:
            record("run", os.path.realpath(binary), True, False,
                   f"could not run the EX1 smoke test ({type(e).__name__}: {e}); see dt_kineros2_027")

    # 3. python modules
    for mod, crit, why in (("numpy", True, "all engine tools"),
                           ("matplotlib", False, "figures in score_kineros2_event.py"),
                           ("scipy", False, "calibrate_kineros2_multipliers.py --method nelder-mead"),
                           ("yaml", False, "reading diagnostics/triplets.yaml")):
        try:
            importlib.import_module(mod)
            record("import", mod, crit, True)
        except ImportError:
            record("import", mod, crit, False, f"pip install {mod}  (needed for {why})")
    try:
        try:
            importlib.import_module("ki_tools_common.metrics")
        except ImportError:
            sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
            importlib.import_module("ki_tools_common.metrics")
        record("import", "ki_tools_common", False, True)
    except ImportError:
        record("import", "ki_tools_common", False, False,
               "add KISSPATH_KI_TOOLS_COMMON to PYTHONPATH (scoring metrics, "
               "HWSD soil lookup, gridded rain need it)")

    # 4. data shipped with the KI
    for name in ("EX1.PAR", "EX1.PRE", "wg11.par", "4Aug80.pre", "wg11_mult.txt", "expected_results.json"):
        p = EXAMPLES / name
        record("data", p, True, p.is_file(),
               f"restore {name} from the ARS Samples.zip (https://www.tucson.ars.ag.gov/kineros/Download/Samples.zip)")
    obs = KI_DIR / "examples" / "wg11_observed" / "flume11_19800804_breakpoint_cfs.txt"
    record("data", obs, False, obs.is_file(),
           "re-fetch: tools/fetch_wgew_dap.py runoff --flumes 11 --start 1980-08-04 --end 1980-08-04 --units cf")
    try:
        import yaml
        entries = yaml.safe_load(TRIPLETS.read_text())
        record("data", TRIPLETS, False, isinstance(entries, list) and len(entries) >= 15,
               "diagnostics/triplets.yaml must be a top-level YAML list with >= 15 entries")
    except Exception as e:
        record("data", TRIPLETS, False, False, f"triplets.yaml unreadable: {e}")

    crit_fail = [c for c in CHECKS if c["critical"] and c["status"] == "fail"]
    print("  STATUS:", "MODEL READY" if not crit_fail else f"{len(crit_fail)} critical blocker(s) -- see fixes above")
    emit_report()


if __name__ == "__main__":
    main()
