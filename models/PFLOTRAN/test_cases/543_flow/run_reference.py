#!/usr/bin/env python3
"""Run the official PFLOTRAN regression test default/543/543_flow and check expected.json.

Foundation case for the PFLOTRAN KI. Steps:
  1. copy the unmodified official files (inputs/) to a fresh temp dir,
  2. run PFLOTRAN (serial) through the KI's own tools/run_pflotran.py,
  3. check the run with PFLOTRAN's own regression_tests.py --check-only
     (official gold file + official tolerances from 543.cfg),
  4. check the numbers in expected.json (copied from the gold file) ourselves.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Binary lookup: --pflotran-bin -> $PFLOTRAN_BIN -> `which pflotran` -> server default.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_pflotran.py"
_DEF = "/mnt/disk1/Hydrocraft_server/models/PFLOTRAN/source/repo/src/pflotran/pflotran"
CASE_FILES = ("543_flow.in", "543.h5", "543_initial_pressure.h5",
              "543_flow.regression.gold", "543.cfg")


def find_bin(arg):
    for c in (arg, os.environ.get("PFLOTRAN_BIN"), shutil.which("pflotran"), _DEF):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def parse_regression(fp):
    """PFLOTRAN .regression file -> {SECTION: {key: [values]}}."""
    out, sec = {}, None
    for line in Path(fp).read_text().splitlines():
        m = re.match(r"^--\s*([A-Z_]+):", line)
        if m:
            sec = out.setdefault(m.group(1), {})
            continue
        if sec is not None and ":" in line:
            k, v = line.split(":", 1)
            sec[k.strip()] = [float(x) for x in v.split()]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pflotran-bin")
    a = ap.parse_args()
    exe = find_bin(a.pflotran_bin)
    if not exe:
        print("MISSING DEPENDENCY: PFLOTRAN binary not found (use --pflotran-bin or "
              "$PFLOTRAN_BIN). NOT run.", file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {RUN_TOOL} not found. NOT run.", file=sys.stderr)
        return 3

    tmp = Path(tempfile.mkdtemp(prefix="pflotran_543_"))
    run = tmp / "543"
    run.mkdir()
    try:
        for f in CASE_FILES:
            shutil.copy(HERE / "inputs" / f, run / f)
        shutil.copy(HERE / "inputs" / "regression_tests.py", tmp / "regression_tests.py")
        fails = []

        # 1) run through the KI tool (serial)
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--input-file", str(run / "543_flow.in"),
                             "--pflotran-bin", exe, "--nproc", "1", "--timeout", "600",
                             "--workdir", str(run)],
                            capture_output=True, text=True, timeout=900)
        print(f"  KI run tool rc={cp.returncode}")
        screen = (run / "543_flow.out").read_text() if (run / "543_flow.out").is_file() else ""
        if cp.returncode != 0:
            fails.append(f"KI run tool failed rc={cp.returncode}: {cp.stdout[-400:]} {cp.stderr[-400:]}")
        # PFLOTRAN prints the full path here when given -pflotranin <abs path>
        if not re.search(r"--> write regression output file: \S*543_flow\.regression", screen):
            fails.append("success line missing: '--> write regression output file: ...543_flow.regression'")
        if "Wall Clock Time:" not in screen:
            fails.append("success line missing: 'Wall Clock Time:'")
        reg = run / "543_flow.regression"
        if not reg.is_file():
            fails.append("543_flow.regression not written")

        # 2) PFLOTRAN's own comparison (official gold + official tolerances)
        if not fails:
            cp2 = subprocess.run([sys.executable, "regression_tests.py", "--check-only",
                                  "-e", exe, "-c", "543/543.cfg", "-t", "543_flow"],
                                 cwd=tmp, capture_output=True, text=True, timeout=300)
            ok = cp2.returncode == 0 and "All tests passed." in cp2.stdout
            print(f"  official regression_tests.py --check-only: rc={cp2.returncode} "
                  f"{'All tests passed.' if ok else 'FAILED'}")
            if not ok:
                fails.append("official regression_tests.py check failed:\n" + cp2.stdout[-1500:])

        # 3) our own numeric checks (values from the gold file)
        if reg.is_file():
            got = parse_regression(reg)
            for c in EXP["numeric_checks"]:
                try:
                    v = got[c["section"]][c["key"]][c.get("index", 0)]
                except (KeyError, IndexError):
                    fails.append(f"{c['name']}: not found in 543_flow.regression")
                    continue
                e, t = c["expected"], c["tol"]
                err = abs(v - e) / abs(e) if (c["tol_type"] == "relative" and e != 0) else abs(v - e)
                good = err <= t
                print(f"  {'ok  ' if good else 'FAIL'} {c['name']}: got {v!r} expected {e!r} "
                      f"({c['tol_type']} diff {err:.3g} <= {t})")
                if not good:
                    fails.append(f"{c['name']} got {v} expected {e} tol {t} {c['tol_type']}")

        if fails:
            print("FAIL:\n  " + "\n  ".join(fails))
            return 2
        print(f"PASS: PFLOTRAN 543_flow matches the official gold file "
              f"({len(EXP['numeric_checks'])} numeric checks + official regression_tests.py)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
