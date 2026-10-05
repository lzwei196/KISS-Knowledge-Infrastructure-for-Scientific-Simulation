#!/usr/bin/env python3
"""Run pysteps' own official tests on the official MeteoSwiss (mch) radar sample.

Foundation case for the pySTEPS KI. Steps:
  1. copy inputs/radar/mch/20150515/*.gif (unmodified, from pySTEPS/pysteps-data) to a
     fresh temp dir;
  2. write a temp copy of the installed default pystepsrc in which ONLY the "mch"
     root_path is changed to that temp dir (the shipped value is the relative
     "./radar/mch"); point $PYSTEPSRC at it;
  3. run the official pysteps test modules listed in expected.json with pytest
     (they carry the official assert values, e.g. STEPS CRPS limits);
  4. re-run the official STEPS skill test settings (test_nowcasts_steps.steps_arg_values,
     seed 42) and record the CRPS of each, checked against the official limit AND the
     value recorded on 2026-10-05.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Python lookup: --python -> $PYSTEPS_PYTHON -> this python (if it has pysteps) ->
server default /mnt/disk1/Hydrocraft_server/python_env/bin/python.
The KI tools in tools/ are not used (they cannot drive pytest; see README "Known KI gaps").
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
_DEF = "/mnt/disk1/Hydrocraft_server/python_env/bin/python"
DEPS = "import pysteps, pysteps.tests, pytest, cv2, PIL, importlib.metadata as m; print(m.version('pysteps'))"
THREADS = {k: "4" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                            "NUMEXPR_NUM_THREADS")}

CRPS_SNIPPET = r"""
import json
from pysteps import motion, nowcasts, verification
from pysteps.tests.helpers import get_precipitation_fields
from pysteps.tests.test_nowcasts_steps import steps_arg_names, steps_arg_values
out = []
for vals in steps_arg_values:
    a = dict(zip(steps_arg_names, vals))
    # identical to pysteps.tests.test_nowcasts_steps.test_steps_skill
    pin, md = get_precipitation_fields(num_prev_files=2, num_next_files=0, return_raw=False,
                                       metadata=True, upscale=2000)
    pin = pin.filled()
    pobs = get_precipitation_fields(num_prev_files=0, num_next_files=3, return_raw=False,
                                    upscale=2000)[1:, :, :].filled()
    V = motion.get_method("LK")(pin)
    fc = nowcasts.get_method("steps")(
        pin, V, timesteps=a["timesteps"], precip_thr=md["threshold"], kmperpixel=2.0,
        timestep=md["accutime"], seed=42, n_ens_members=a["n_ens_members"],
        n_cascade_levels=a["n_cascade_levels"], ar_order=a["ar_order"],
        mask_method=a["mask_method"], probmatching_method=a["probmatching_method"],
        domain=a["domain"])
    crps = float(verification.probscores.CRPS(fc[:, -1], pobs[-1]))
    out.append({"crps": crps, "max_crps": a["max_crps"], "shape": list(fc.shape)})
print("CRPS_JSON=" + json.dumps(out))
"""


def find_python(arg):
    for c in (arg, os.environ.get("PYSTEPS_PYTHON"), sys.executable, _DEF):
        if not c or not Path(c).is_file():
            continue
        cp = subprocess.run([c, "-c", DEPS], capture_output=True, text=True, cwd=tempfile.gettempdir())
        if cp.returncode == 0:
            return c, cp.stdout.strip().splitlines()[-1]
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python")
    a = ap.parse_args()
    py, ver = find_python(a.python)
    if not py:
        print("MISSING DEPENDENCY: a python with pysteps (incl. pysteps.tests), pytest, cv2 and "
              "PIL not found (set PYSTEPS_PYTHON or --python). NOT run.", file=sys.stderr)
        return 3
    print(f"  python: {py}  pysteps {ver}")

    run = Path(tempfile.mkdtemp(prefix="pysteps_mch_"))
    fails = []
    try:
        src = HERE / "inputs" / "radar" / "mch" / "20150515"
        dst = run / "radar" / "mch" / "20150515"
        shutil.copytree(src, dst)
        n_files = len(list(dst.glob("*.gif")))

        # temp pystepsrc: installed default with only the mch root_path made absolute
        rc_src = subprocess.run([py, "-c", "import pysteps,os;print(os.path.join("
                                 "os.path.dirname(pysteps.__file__),'pystepsrc'))"],
                                capture_output=True, text=True, cwd=run,
                                env={**os.environ, "PYSTEPSRC": ""}).stdout.strip().splitlines()[-1]
        rc_txt = Path(rc_src).read_text()
        if rc_txt.count('"./radar/mch"') != 1:
            fails.append("default pystepsrc has no unique \"./radar/mch\" root_path")
            raise RuntimeError
        (run / "pystepsrc").write_text(rc_txt.replace('"./radar/mch"', json.dumps(str(run / "radar" / "mch"))))
        env = {**os.environ, **THREADS, "PYSTEPSRC": str(run / "pystepsrc")}

        # 1) official pytest modules
        args = [py, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--pyargs",
                *EXP["pytest_modules"], "-k", " and ".join(f"not {d}" for d in EXP["pytest_deselect_names"]),
                f"--junitxml={run / 'junit.xml'}"]
        cp = subprocess.run(args, capture_output=True, text=True, cwd=run, env=env, timeout=1500)
        tail = [l for l in cp.stdout.splitlines() if l.strip()][-1:]
        print(f"  pytest rc={cp.returncode}: {tail[0] if tail else ''}")
        r = ET.parse(run / "junit.xml").getroot()
        ts = r if r.tag == "testsuite" else r.find("testsuite")
        got = {"n_mch_files": n_files, "pytest_returncode": cp.returncode,
               "pytest_tests": int(ts.get("tests")), "pytest_failures": int(ts.get("failures")),
               "pytest_errors": int(ts.get("errors")), "pytest_skipped": int(ts.get("skipped"))}
        bad = [tc.get("classname") + "::" + tc.get("name") for tc in r.iter("testcase")
               if any(ch.tag in ("failure", "error") for ch in tc)]
        if bad:
            fails.append("official tests failed: " + ", ".join(bad[:10]))

        # 2) official STEPS skill settings, CRPS values
        cp2 = subprocess.run([py, "-c", CRPS_SNIPPET], capture_output=True, text=True,
                             cwd=run, env=env, timeout=900)
        line = [l for l in cp2.stdout.splitlines() if l.startswith("CRPS_JSON=")]
        if cp2.returncode != 0 or not line:
            fails.append(f"STEPS CRPS re-run failed (rc={cp2.returncode}): {cp2.stderr[-400:]}")
        else:
            for i, d in enumerate(json.loads(line[0][10:])):
                got[f"steps_skill_{i}_crps"] = d["crps"]
                got[f"steps_skill_{i}_official_max_crps"] = d["max_crps"]

        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not produced")
                continue
            ok = abs(v - c["expected"]) <= c["tol"]
            if "official_max" in c:
                ok = ok and v < c["official_max"]
                if got.get(c["name"].replace("_crps", "_official_max_crps")) != c["official_max"]:
                    fails.append(f"{c['name']}: official limit in pysteps test changed")
            lim = f" (< official {c['official_max']})" if "official_max" in c else ""
            if ok:
                print(f"  OK {c['name']}: {v:.6g}{lim}")
            else:
                fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}±{c['tol']}{lim}")
    except RuntimeError:
        pass
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: pysteps official tests on the official mch sample reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
