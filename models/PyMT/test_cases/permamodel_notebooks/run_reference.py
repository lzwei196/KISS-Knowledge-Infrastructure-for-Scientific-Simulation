#!/usr/bin/env python3
"""Run the official PyMT permamodel notebooks (offline part) and check expected.json.

Foundation case for the PyMT KI. It repeats the offline cells of the two official
PyMT notebooks notebooks/frost_number.ipynb and notebooks/ku.ipynb (PyMT git):
FrostNumber is set up twice and Ku five times, each with the plugin's own shipped
default config plus the notebook's parameter changes, then one update() and a
get_value(). The numbers are compared with the values saved in the notebook output
cells. No network is used (the later notebook cells that download CSV files from
GitHub are NOT part of this case).

Each step is run through the KI's own tools/run_model.py. A second, literal run
(one model object reused, exactly like the notebook) must give the same numbers.

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
Python lookup (an interpreter with pymt + pymt_permamodel): --pymt-bin -> $PYMT_BIN
-> python3 on PATH -> server default venv.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_model.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/PyMT/venv/bin/python"
DEFAULTS = HERE / "inputs" / "pymt_permamodel_0.2.3_data"

# pymt keeps setup() parameters on the model object, so in the notebook each new
# setup() adds to the earlier ones. For the KI tool (new object per call) we pass
# the same cumulative set, which is what the notebook model really used.
STEPS = [
    ("fn_air_1", "FrostNumber", {"T_air_min": -13.0, "T_air_max": 19.5}, 1, "frostnumber__air"),
    ("fn_air_2", "FrostNumber", {"T_air_min": -40.9, "T_air_max": 19.5}, 1, "frostnumber__air"),
    ("ku_alt_1", "Ku", {"T_air": -15.21, "A_air": 18.51}, None, "soil__active_layer_thickness"),
    ("ku_alt_2", "Ku", {"T_air": -15.21, "A_air": 18.51, "h_snow": 0.0}, None, "soil__active_layer_thickness"),
    ("ku_alt_3", "Ku", {"T_air": -15.21, "A_air": 18.51, "h_snow": 0.4}, None, "soil__active_layer_thickness"),
    ("ku_alt_4", "Ku", {"T_air": -15.21, "A_air": 18.51, "h_snow": 0.4, "vwc_H2O": 0.2}, None, "soil__active_layer_thickness"),
    ("ku_alt_5", "Ku", {"T_air": -15.21, "A_air": 18.51, "h_snow": 0.4, "vwc_H2O": 0.6}, None, "soil__active_layer_thickness"),
]

# Literal notebook cells (same object reused, same calls as the notebook).
LITERAL = r'''
import json, warnings
warnings.filterwarnings("ignore")
import pymt.models
out = {}
fn = pymt.models.FrostNumber()
config_file, config_folder = fn.setup(T_air_min=-13.0, T_air_max=19.5)
fn.initialize(config_file, config_folder); fn.update()
out["fn_air_1"] = float(fn.get_value("frostnumber__air")[0])
args = fn.setup(T_air_min=-40.9, T_air_max=19.5)
fn.initialize(*args); fn.update()
out["fn_air_2"] = float(fn.get_value("frostnumber__air")[0])
ku = pymt.models.Ku()
config_file, run_folder = ku.setup(T_air=-15.21, A_air=18.51)
ku.initialize(config_file, run_folder); ku.update()
out["ku_alt_1"] = float(ku.get_value("soil__active_layer_thickness")[0])
out["ku_soil_temperature_1"] = float(ku.get_value("soil__temperature")[0])
for name, kw in [("ku_alt_2", dict(h_snow=0.0)), ("ku_alt_3", dict(h_snow=0.4)),
                 ("ku_alt_4", dict(vwc_H2O=0.2)), ("ku_alt_5", dict(vwc_H2O=0.6))]:
    args = ku.setup(**kw); ku.initialize(*args); ku.update()
    out[name] = float(ku.get_value("soil__active_layer_thickness")[0])
print("LITERAL_JSON " + json.dumps(out))
'''


def has_pymt(py):
    if not py or not Path(py).is_file():
        return False
    try:
        r = subprocess.run([py, "-c", "import pymt, pymt_permamodel"],
                           capture_output=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def parse_tool_json(stdout):
    """run_model.py prints model chatter first, then one JSON object."""
    lines = stdout.splitlines()
    for i, l in enumerate(lines):
        if l == "{":
            return json.loads("\n".join(lines[i:]))
    raise ValueError("no JSON in run_model.py output")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pymt-bin", help="python interpreter with pymt + pymt_permamodel")
    a = ap.parse_args()
    cands = (a.pymt_bin, os.environ.get("PYMT_BIN"), shutil.which("python3"), _DEF)
    py = next((c for c in cands if has_pymt(c)), None)
    if not py:
        print("MISSING DEPENDENCY: no python with pymt + pymt_permamodel found "
              "(set PYMT_BIN or --pymt-bin). NOT run.", file=sys.stderr)
        return 3
    print(f"  python: {py}")

    run = Path(tempfile.mkdtemp(prefix="pymt_perma_"))
    env = dict(os.environ, TMPDIR=str(run), PYTHONWARNINGS="ignore")
    got, fails = {}, []
    try:
        # 1) installed plugin defaults must be the official 0.2.3 files we ship
        r = subprocess.run([py, "-c", "import pymt_permamodel,os;print(os.path.dirname(pymt_permamodel.__file__))"],
                           capture_output=True, text=True, env=env)
        inst = Path(r.stdout.strip()) / "data"
        same = all((inst / f.relative_to(DEFAULTS)).is_file()
                   and sha(inst / f.relative_to(DEFAULTS)) == sha(f)
                   for f in DEFAULTS.rglob("*") if f.is_file())
        got["plugin_defaults_match"] = 1 if same else 0

        # 2) each notebook step through the KI run tool, own fresh dir
        steps, ok_all = 0, True
        for name, model, params, dur, var in STEPS:
            wd = run / name
            wd.mkdir()
            cmd = [py, str(RUN_TOOL), "--model", model, "--params", json.dumps(params),
                   "--capture", var]
            if dur is not None:
                cmd += ["--duration", str(dur)]
            cp = subprocess.run(cmd, cwd=wd, capture_output=True, text=True,
                                timeout=600, env=env)
            try:
                res = parse_tool_json(cp.stdout)
            except Exception as e:
                fails.append(f"{name}: rc={cp.returncode} {e}: {cp.stderr[-400:]}")
                ok_all = False
                continue
            ok = (cp.returncode == 0 and res.get("status") == "success"
                  and res.get("finalized") is True and res.get("steps_completed") == 1)
            ok_all &= ok
            steps += res.get("steps_completed", 0)
            cv = res.get("captured_variables", {}).get(var)
            if cv:
                got[name] = cv["max"]
            print(f"  ran {name} ({model}) via KI run_model.py: status={res.get('status')} "
                  f"{var}={cv['max'] if cv else None}")
        got["steps_completed_total"] = steps

        # 3) literal notebook sequence, one model object reused
        wd = run / "literal"
        wd.mkdir()
        cp = subprocess.run([py, "-c", LITERAL], cwd=wd, capture_output=True, text=True,
                            timeout=600, env=env)
        lit = None
        for l in cp.stdout.splitlines():
            if l.startswith("LITERAL_JSON "):
                lit = json.loads(l[len("LITERAL_JSON "):])
        ok_all &= cp.returncode == 0 and lit is not None
        if lit:
            got["ku_soil_temperature_1"] = lit["ku_soil_temperature_1"]
            diffs = [abs(lit[s[0]] - got[s[0]]) for s in STEPS if s[0] in got]
            got["literal_vs_tool_max_abs_diff"] = max(diffs) if len(diffs) == len(STEPS) else 1e9
            print("  ran literal notebook sequence: " +
                  ", ".join(f"{k}={v:.8f}" for k, v in lit.items()))
        else:
            fails.append(f"literal run failed rc={cp.returncode}: {cp.stderr[-400:]}")
        got["finished_normally"] = 1 if ok_all else 0
    finally:
        shutil.rmtree(run, ignore_errors=True)

    for c in EXP["numeric_checks"]:
        n = c["name"]
        if n not in got:
            fails.append(f"{n}: no value")
            continue
        d = abs(got[n] - c["expected"])
        flag = "ok " if d <= c["tol"] else "BAD"
        print(f"  [{flag}] {n}: got {got[n]!r} expected {c['expected']!r} (tol {c['tol']})")
        if d > c["tol"]:
            fails.append(n)
    if fails:
        print("FAIL: " + "; ".join(fails))
        return 2
    print(f"PASS: {len(EXP['numeric_checks'])} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
