#!/usr/bin/env python3
"""Run the official LPJmL testcase_2cell (the `make test` case) in a clean dir and check expected.json.

Foundation case for the LPJmL KI. Same two runs as the upstream Makefile `test` target:
  bin/lpjml -DTESTCASE_2CELL lpjml_config.cjson                  (spinup, 3800 years)
  bin/lpjml -DTESTCASE_2CELL -DFROM_RESTART lpjml_config.cjson   (transient, 1481-2019)
Both runs go through the KI's own tools/run_lpjml.py. Outputs output/globalflux_spinup.csv and
output/globalflux.csv are compared with the official reference files shipped by upstream in
inputs/testcase_2cell/ (expected values are read from those files).

Exit 0 PASS, 2 run or checks failed, 3 engine/dependency missing ("MISSING DEPENDENCY: ... NOT run.").
Binary lookup: --lpjml-bin -> $LPJML_BIN -> `which lpjml` -> server default. The binary must report
"Version 6.1.9" (the version that made the reference files).
"""
import argparse, csv, json, math, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP_PATH = HERE / "expected.json"
RUN_TOOL = HERE.parents[1] / "tools" / "run_lpjml.py"
DEFAULT_BIN = "/home/server/engine_builds_20261006/lpjml_v6.1.9/LPJmL/bin/lpjml"
NEED_VERSION = "6.1.9"
SUCCESS_LINE = "lpjml successfully terminated, 2 grid cells processed"
CLEAR_ENV = ("LPJINPATH", "LPJOUTPATH", "LPJRESTARTPATH", "LPJOPTIONS", "LPJPREP", "LPJNOPP", "LPJROOT")
BUDGET_S = 1200      # shared time budget for both runs (spinup ~2 min + transient ~6 min here)
REF_DIR = HERE / "inputs" / "testcase_2cell"
OUT_NAME = {"spinup": "globalflux_spinup.csv", "transient": "globalflux.csv"}


class Missing(Exception):
    pass


def bin_version(path):
    """Return the version string `lpjml -v` reports, or None."""
    try:
        r = subprocess.run([path, "-v"], capture_output=True, text=True, timeout=30, cwd=tempfile.gettempdir())
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"lpjml C Version (\S+)", r.stdout + r.stderr)
    return m.group(1) if m else None


def find_engine(arg_bin):
    explicit = [("--lpjml-bin", arg_bin), ("$LPJML_BIN", os.environ.get("LPJML_BIN"))]
    for label, cand in explicit:
        if cand:
            if not (os.path.isfile(cand) and os.access(cand, os.X_OK)):
                raise Missing(f"LPJmL binary from {label} not found or not executable: {cand}")
            v = bin_version(cand)
            if v != NEED_VERSION:
                raise Missing(f"LPJmL binary from {label} ({cand}) reports version {v}, need {NEED_VERSION}")
            return cand
    for cand in (shutil.which("lpjml"), DEFAULT_BIN):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK) and bin_version(cand) == NEED_VERSION:
            return cand
    raise Missing(f"LPJmL {NEED_VERSION} binary not found (set --lpjml-bin or $LPJML_BIN; "
                  f"server default {DEFAULT_BIN}; build notes next to it)")


def read_csv(path):
    """globalflux CSV -> (names row, units row, {column: [floats]}). Raises ValueError if malformed."""
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 3:
        raise ValueError(f"{path}: fewer than 3 rows")
    names, units = rows[0], rows[1]
    cols = {n: [] for n in names}
    for k, r in enumerate(rows[2:], 3):
        if len(r) != len(names):
            raise ValueError(f"{path}: row {k} has {len(r)} fields, header has {len(names)}")
        for n, x in zip(names, r):
            v = float(x)
            if not math.isfinite(v):
                raise ValueError(f"{path}: row {k} column {n} is not finite ({x})")
            cols[n].append(v)
    return names, units, cols


def metric(check, cols):
    """Value of one tolerance check from parsed columns."""
    v = cols[check["column"]]
    w = check.get("last_n_years")
    v = v[-w:] if w else v
    return sum(v) / len(v)


def run_tool(run, mode, env, timeout_s):
    if timeout_s < 1:
        return None, "", "no time left in the shared run budget"
    cmd = [sys.executable, str(RUN_TOOL), "--lpjroot", str(run), "--config", "lpjml_config.cjson",
           "--mode", mode, "--macro", "TESTCASE_2CELL", "--timeout", str(timeout_s)]
    try:
        r = subprocess.run(cmd, cwd=run, env=env, capture_output=True, text=True, timeout=timeout_s + 60)
    except subprocess.TimeoutExpired:
        return None, "", f"KI tool did not return within {timeout_s + 60} s"
    (run / "output" / f"ki_tool_{mode}.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
    return r.returncode, r.stdout, r.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lpjml-bin")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    ap.add_argument("--save-csv", help="copy the two output CSVs (and KI tool logs) to this dir")
    a = ap.parse_args()

    # ---- package file (exit 2 if broken) ----
    try:
        exp = json.loads(EXP_PATH.read_text())
        assert isinstance(exp.get("numeric_checks"), list) and exp["numeric_checks"]
    except Exception as e:
        print(f"FAIL: cannot read expected.json ({type(e).__name__}: {e})", file=sys.stderr)
        return 2

    # ---- dependencies (exit 3) ----
    try:
        if not RUN_TOOL.is_file():
            raise Missing(f"KI run tool not found: {RUN_TOOL}")
        if not shutil.which("cpp"):
            raise Missing("C preprocessor 'cpp' not on PATH (lpjml needs it to read the .cjson config)")
        engine = find_engine(a.lpjml_bin)
    except Missing as e:
        print(f"MISSING DEPENDENCY: {e}. NOT run.", file=sys.stderr)
        return 3
    print(f"engine: {engine} (version {NEED_VERSION})")

    try:
        run = Path(tempfile.mkdtemp(prefix="lpjml_tc2cell_"))
    except OSError as e:
        print(f"FAIL: cannot make a temp run dir ({e}); NOT run.", file=sys.stderr)
        return 2
    fails, lines = [], []
    try:
        for item in ("lpjml_config.cjson", "par", "include", "testcase_2cell"):
            src = HERE / "inputs" / item
            (shutil.copytree if src.is_dir() else shutil.copy)(src, run / item)
        for d in ("output", "restart", "bin"):
            (run / d).mkdir()
        os.symlink(engine, run / "bin" / "lpjml")
        env = {k: v for k, v in os.environ.items() if k not in CLEAR_ENV}

        # ---- the two make-test runs through the KI tool ----
        t0 = time.time()
        for mode in ("spinup", "transient"):
            rc, out, err = run_tool(run, mode, env, int(BUDGET_S - (time.time() - t0)))
            ok = rc == 0 and SUCCESS_LINE in out
            lines.append(f"{'ok  ' if ok else 'FAIL'} {mode} run: KI tool rc={rc}, success line "
                         f"{'found' if SUCCESS_LINE in out else 'MISSING'}")
            if not ok:
                fails.append(f"{mode} run")
                tail = "\n".join((out + "\n" + err).strip().splitlines()[-25:])
                print(f"--- {mode} run failed; tail of KI tool output ---\n{tail}", file=sys.stderr)
                break

        if not fails:
            # ---- compare with the official reference files ----
            parsed = {}
            for mode in ("spinup", "transient"):
                ref = read_csv(REF_DIR / OUT_NAME[mode])
                new = read_csv(run / "output" / OUT_NAME[mode])
                parsed[mode] = (ref, new)
                (rn, ru, rc_), (nn, nu, nc) = ref, new
                same = rn == nn and ru == nu
                lines.append(f"{'ok  ' if same else 'FAIL'} {mode}: header + units rows identical to official file")
                if not same:
                    fails.append(f"{mode} header")
                    continue
                years_same = rc_["Year"] == nc["Year"]
                lines.append(f"{'ok  ' if years_same else 'FAIL'} {mode}: Year column identical to official file "
                             f"({int(rc_['Year'][0])}..{int(rc_['Year'][-1])}, {len(rc_['Year'])} rows)")
                if not years_same:
                    fails.append(f"{mode} years")
                ident = (REF_DIR / OUT_NAME[mode]).read_bytes() == (run / "output" / OUT_NAME[mode]).read_bytes()
                lines.append(f"info {mode}: byte-identical to official file: {ident}")

            for c in exp["numeric_checks"]:
                mode = c["file"]
                if mode not in parsed:
                    fails.append(c["name"]); lines.append(f"FAIL {c['name']}: file not parsed"); continue
                (rn, ru, rcols), (nn, nu, ncols) = parsed[mode]
                kind = c["kind"]
                if kind == "n_rows":
                    ref_v, got = len(rcols["Year"]), len(ncols["Year"])
                elif kind == "column_identical":
                    ref_v = 0.0
                    got = max(abs(x - y) for x, y in zip(rcols[c["column"]], ncols[c["column"]])) \
                        if len(rcols[c["column"]]) == len(ncols[c["column"]]) else float("inf")
                else:  # mean
                    ref_v, got = metric(c, rcols), metric(c, ncols)
                # the stored expected value must equal the value in the official reference file
                if abs(ref_v - c["expected"]) > 1e-12 * max(1.0, abs(ref_v)):
                    fails.append(c["name"])
                    lines.append(f"FAIL {c['name']}: expected.json value {c['expected']} != official file value {ref_v}")
                    continue
                # explicit rule: |run - ref| <= tol * |ref| (rel) or <= tol (abs); NaN never passes
                limit = c["tol"] * abs(c["expected"]) if c["tol_type"] == "rel" else c["tol"]
                diff = abs(got - c["expected"])
                ok = math.isfinite(got) and diff <= limit
                dev = diff / abs(c["expected"]) if c["tol_type"] == "rel" else diff
                lines.append(f"{'ok  ' if ok else 'FAIL'} {c['name']}: got {got:.8g} expected {c['expected']:.8g} "
                             f"({c['tol_type']} dev {dev:.3g} <= tol {c['tol']:g})")
                if not ok:
                    fails.append(c["name"])

            if a.save_csv:
                dst = Path(a.save_csv); dst.mkdir(parents=True, exist_ok=True)
                for f in list(OUT_NAME.values()) + ["ki_tool_spinup.log", "ki_tool_transient.log"]:
                    shutil.copy(run / "output" / f, dst / f)
    except Exception as e:  # malformed/missing output or any other run problem -> checks failed
        fails.append(f"error: {type(e).__name__}: {e}")
        lines.append(f"FAIL unexpected error: {type(e).__name__}: {e}")
    finally:
        if a.keep:
            print(f"run dir kept: {run}")
        else:
            shutil.rmtree(run, ignore_errors=True)

    print("\n".join(lines))
    if fails:
        print(f"FAIL: {len(fails)} check(s) failed: {', '.join(fails)}")
        return 2
    n = len(exp["numeric_checks"]) + 6
    print(f"PASS: LPJmL testcase_2cell ({n} checks: 2 runs finished, 2 headers, 2 year columns, "
          f"{len(exp['numeric_checks'])} numeric checks vs official reference)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
