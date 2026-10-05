#!/usr/bin/env python3
"""Run LISFLOOD's official lat/lon "short" test in a clean dir and check expected.json.

Foundation case for the LISFLOOD KI. This is the upstream test
tests/test_latlon.py::TestLatLonShort (ec-jrc/lisflood-code, commit fe94c33, v4.3.1):
run_lat_lon.xml from 01/01/2016 to 01/02/2016 (32 daily steps), PathOut $(PathRoot)/short,
start maps (lzavin.map, avgdis.map) from reference/ via PathInit. The output dis_run.tss
(and chanqWin.tss) is compared with the official reference/dis_short.tss
(and reference/chanqWin_short.tss) using lisfloodutilities TSSComparator
(atol=1e-4, rtol=1e-3), exactly as the upstream test does.

Settings changes, made ONLY in the temp copy (same as the upstream test, plus one path):
  StepStart = 01/01/2016 00:00, StepEnd = 01/02/2016 00:00, PathOut = $(PathRoot)/short
  PathRoot  = <absolute temp dir>   (the file says $(SettingsPath); the KI run tool cannot
                                     read that, so we write the same folder as a full path)

The model is started through the KI tool tools/run_lisflood.py (its run_model function).
Its command-line preflight cannot read this official settings file, see README.

Engine lookup: --lisflood-bin -> $LISFLOOD_BIN -> `which lisflood` -> server default
(/home/server/miniconda3/envs/lisflood_official/bin/lisflood). The env must be LISFLOOD's
official environment (python 3.7, xarray 0.20.2, dask 2022.2.0, lisflood-utilities); see README.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_lisflood.py"
_DEF = "/home/server/miniconda3/envs/lisflood_official/bin/lisflood"
SETTINGS = "run_lat_lon.xml"
TEXTVARS = {  # first <textvar> of each name, as the upstream setoptions() does
    "StepStart": "01/01/2016 00:00",
    "StepEnd": "01/02/2016 00:00",
    "PathOut": "$(PathRoot)/short",
}
COMPARE = (("dis_run.tss", "reference/dis_short.tss", "dis"),
           ("chanqWin.tss", "reference/chanqWin_short.tss", "chanqWin"))
ATOL, RTOL = 1e-4, 1e-3   # TSSComparator defaults used by the upstream test


def find_bin(arg):
    w = shutil.which("lisflood")
    for c in (arg, os.environ.get("LISFLOOD_BIN"), w, _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def set_textvar(txt, name, value):
    pat = r'(<textvar name="%s" value=")[^"]*(")' % re.escape(name)
    new, n = re.subn(pat, lambda m: m.group(1) + value + m.group(2), txt, count=1)
    if n != 1:
        raise RuntimeError("textvar %s not found in settings" % name)
    return new


def read_tss(fp):
    lines = Path(fp).read_text().split("\n")
    ncol = int(lines[1])
    rows = [l.split() for l in lines[2 + ncol:] if l.strip()]
    return [int(r[0]) for r in rows], [float(r[1]) for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lisflood-bin")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()

    lbin = find_bin(a.lisflood_bin)
    if not lbin:
        print("MISSING DEPENDENCY: lisflood engine not found (set LISFLOOD_BIN or "
              "--lisflood-bin to <official env>/bin/lisflood). NOT run.", file=sys.stderr)
        return 3
    bindir = str(Path(lbin).parent)
    envpy = Path(bindir) / "python"
    chk = subprocess.run([str(envpy), "-c", "import lisflood, lisfloodutilities.compare.pcr"],
                         capture_output=True, text=True) if envpy.is_file() else None
    if chk is None or chk.returncode != 0:
        print("MISSING DEPENDENCY: %s cannot import lisflood + lisfloodutilities "
              "(need LISFLOOD's official env). NOT run." % envpy, file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print("MISSING DEPENDENCY: KI run tool %s not found. NOT run." % RUN_TOOL, file=sys.stderr)
        return 3

    tmp = Path(tempfile.mkdtemp(prefix="lisflood_latlon_short_"))
    case = tmp / "case"
    shutil.copytree(HERE / "inputs", case)
    xml = case / SETTINGS
    txt = xml.read_text()
    txt = set_textvar(txt, "PathRoot", str(case))
    for k, v in TEXTVARS.items():
        txt = set_textvar(txt, k, v)
    xml.write_text(txt)
    (case / "short").mkdir()

    # KI tool calls bare `lisflood` from PATH: put the chosen env first.
    os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
    sys.path.insert(0, str(TOOLS))
    import run_lisflood
    print("engine:", lbin)
    ok, out, err, rt = run_lisflood.run_model(str(xml), timeout=1200)

    fails, got = [], {}
    last_step_line = "10988 - 01/02/2016 00:00"
    got["finished_normally"] = bool(ok) and last_step_line in out
    if not got["finished_normally"]:
        fails.append("LISFLOOD did not finish normally (ok=%s): %s" % (ok, (err or out)[-600:]))

    if not fails:
        # 1) the official comparator, exactly as tests/test_latlon.py uses it
        code = ("import sys\nfrom lisfloodutilities.compare.pcr import TSSComparator\n"
                "c = TSSComparator()\n"
                "for ref, out in zip(sys.argv[1::2], sys.argv[2::2]):\n"
                "    c.compare_files(ref, out)\nprint('TSSComparator OK')\n")
        argv = []
        for o, r, _ in COMPARE:
            argv += [str(case / r), str(case / "short" / o)]
        cp = subprocess.run([str(envpy), "-c", code] + argv, capture_output=True, text=True)
        got["official_tsscomparator"] = cp.returncode == 0 and "TSSComparator OK" in cp.stdout
        if not got["official_tsscomparator"]:
            fails.append("official TSSComparator failed: " + (cp.stderr or cp.stdout)[-800:])
        else:
            print("  OK official TSSComparator (atol=1e-4, rtol=1e-3): dis + chanqWin")

        # 2) per-step check and summary numbers (same tolerance) against expected.json
        for o, r, tag in COMPARE:
            ts, vs = read_tss(case / "short" / o)
            rts, rvs = read_tss(case / r)
            bad = [t for t, v, rv in zip(ts, vs, rvs) if abs(v - rv) > ATOL + RTOL * abs(rv)]
            if ts != rts or bad:
                fails.append("%s: steps differ or out of tolerance at %s" % (o, bad[:5]))
            got.update({
                tag + "_n_steps": len(ts), tag + "_first_step": ts[0] if ts else None,
                tag + "_last_step": ts[-1] if ts else None,
                tag + "_first": vs[0], tag + "_last": vs[-1], tag + "_max": max(vs),
                tag + "_min": min(vs), tag + "_mean": sum(vs) / len(vs),
            })

    for c in EXP["numeric_checks"]:
        if fails and c["name"] not in got:
            continue
        v = got.get(c["name"])
        e = c["expected"]
        if isinstance(e, bool):
            okc = v is e
        else:
            okc = v is not None and abs(v - e) <= c["tol"]
        if okc:
            print("  OK %s: %s" % (c["name"], v))
        else:
            fails.append("%s: %s vs %s +/- %s" % (c["name"], v, e, c.get("tol")))

    if a.keep:
        print("kept:", tmp)
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: LISFLOOD lat/lon short test reproduced the official reference (%.1f s)." % rt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
