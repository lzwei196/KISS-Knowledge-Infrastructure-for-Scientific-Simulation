#!/usr/bin/env python3
"""Run the official HydroTrend default example in a clean dir and check expected.json.

Foundation case for the HydroTrend KI. The case is the CSDMS HydroTrend default input
(data/input/HYDRO.IN + HYDRO0.HYPS, "Greenland Fjord, 1000 year simulation") that the
HydroTrend repo checks against its own reference output data/output/HYDROASCII.Q
(see data/hydrotrend_test_with_args.sh.in: run, then `diff` HYDROASCII.Q).

The model is run through the KI's own tools/run_hydrotrend.py. The tool is called from
inside the temp dir with SHORT RELATIVE paths ("input", "output"): HydroTrend keeps the
output path in fixed-size C buffers (98 / 80 chars) and crashes on long absolute paths.
Exit 0 PASS, 2 checks failed, 3 engine missing.

Binary lookup: --hydrotrend-bin -> $HYDROTREND_BIN -> which hydrotrend -> server default.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_hydrotrend.py"
_DEF = "/mnt/disk1/Hydrocraft_server/models/HydroTrend/bin/hydrotrend"
INPUTS = ("HYDRO.IN", "HYDRO0.HYPS")


def col(fp, ncol=1):
    """Read a HydroTrend ASCII file (2 header lines) -> list of rows (floats)."""
    rows = [l.split() for l in open(fp).read().splitlines()[2:] if l.strip()]
    return [[float(x) for x in r[:ncol]] for r in rows]


def find_bin(arg):
    if arg:  # an explicit path must be right; do not silently fall back
        return arg if Path(arg).is_file() and os.access(arg, os.X_OK) else None
    for c in (arg, os.environ.get("HYDROTREND_BIN"), shutil.which("hydrotrend"), _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hydrotrend-bin")
    a = ap.parse_args()
    binary = find_bin(a.hydrotrend_bin)
    if not binary:
        print("MISSING DEPENDENCY: hydrotrend binary not found (use --hydrotrend-bin or "
              "$HYDROTREND_BIN). NOT run.", file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {RUN_TOOL} not found. NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="ht_gf_"))
    (run / "input").mkdir()
    for f in INPUTS:
        shutil.copy(HERE / "inputs" / f, run / "input" / f)

    fails = []
    cp = subprocess.run([sys.executable, str(RUN_TOOL), "--binary", binary,
                         "--in-dir", "input", "--out-dir", "output", "--prefix", "HYDRO",
                         "--timeout", "600"],
                        cwd=run, capture_output=True, text=True, timeout=900)
    try:
        rep = json.loads(cp.stdout)
    except ValueError:
        rep = {}
    ex = rep.get("execution", {})
    if cp.returncode != 0 or ex.get("returncode") != 0:
        fails.append(f"run failed (tool rc={cp.returncode}, model rc={ex.get('returncode')}): "
                     f"{(ex.get('stderr') or cp.stderr)[-400:]}")
    elif "HydroTrend 3.0 finished." not in (ex.get("stdout", "") + ex.get("stderr", "")):
        fails.append("model did not print its success line 'HydroTrend 3.0 finished.'")
    else:
        print(f"  ran {binary} via KI tool (rc 0, 'HydroTrend 3.0 finished.')")

    if not fails:
        out = run / "output"
        qfile = out / "HYDROASCII.Q"
        q = [r[0] for r in col(qfile)]
        qs = [r[0] for r in col(out / "HYDROASCII.QS")]
        qb = [r[0] for r in col(out / "HYDROASCII.QB")]
        log = (out / "HYDRO.LOG").read_text()
        m = re.search(r"\n1\s+0\(100%\)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", log)
        area = re.search(r"Basin area\s*=\s*([\d.]+)", log)
        got = {
            "Q_sha256_matches_official": float(
                hashlib.sha256(qfile.read_bytes()).hexdigest()
                == hashlib.sha256((HERE / "reference" / "HYDROASCII.Q").read_bytes()).hexdigest()),
            "Q_n_records": len(q),
            "Q_mean_m3s": sum(q) / len(q), "Q_max_m3s": max(q), "Q_min_m3s": min(q),
            "Q_first_m3s": q[0], "Q_last_m3s": q[-1],
            "Qs_mean_kgs": sum(qs) / len(qs), "Qs_max_kgs": max(qs),
            "Qb_mean_kgs": sum(qb) / len(qb),
            "log_Qbar_m3s": float(m.group(1)) if m else float("nan"),
            "log_Qsbar_kgs": float(m.group(2)) if m else float("nan"),
            "log_Qpeak_m3s": float(m.group(3)) if m else float("nan"),
            "log_basin_area_km2": float(area.group(1)) if area else float("nan"),
        }
        for c in EXP["numeric_checks"]:
            v = got[c["name"]]
            if not abs(v - c["expected"]) <= c["tol"]:
                fails.append(f"{c['name']}: {v:.8g} vs {c['expected']}+-{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.8g}")

    shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: HydroTrend default example reproduced the official HYDROASCII.Q exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
