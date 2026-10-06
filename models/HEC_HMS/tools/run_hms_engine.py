#!/usr/bin/env python3
"""Run the REAL USACE HEC-HMS engine (4.14, Linux) headless on an HMS project.

This is the KI's real-engine run tool. `tools/run_hec_hms.py` is a Python
SURROGATE (a re-implementation of a few HMS methods) and is NOT HEC-HMS.

What it does, in order:
  1. Copies the project directory (the folder holding <project>.hms) to
     --workdir. The source project is never written to: --workdir may not be
     the project folder, inside it or a parent of it, and every Log File /
     DSS File / results path must stay inside the copy (checked before any
     file is deleted or the engine starts). --overwrite only replaces a folder
     this tool made before (it holds the marker file .run_hms_engine_workdir)
     or an empty folder; any other existing folder is refused.
  2. Deletes, in the COPY, the old log, .out and results/RUN_<run>.results
     (spaces in <run> written as '_', as HMS does) of
     each requested run. The run's DSS file is NOT deleted (it may also hold
     input gages / paired data): the Jython script deletes only that run's own
     output records (F part RUN:<run>) and checks none are left before
     computing. So every output checked below is provably written by this call.
  3. Writes a Jython script (clean RUN:<run> records -> Project.open ->
     computeRun per run -> DSS export) and runs it:
     env -u DISPLAY <engine> -script <script>.
  4. Success check per run (the engine JVM can exit 0 after a failed compute,
     so the exit code alone proves nothing):
       - the RUN:<run> output records were cleaned (HMS_CLEAN_OK)
       - engine exit code 0 and computeRun(<run>) returned without a Jython
         exception (HMS_RUN_RETURNED). computeRun returns None even when HMS
         refuses the run (e.g. 'ERROR 41941: Invalid Snyder lag'), so this
         marker alone proves nothing; the log and results checks below do
       - the run log has 'Finished computing simulation run "<run>"'
       - the run log has no 'ERROR <number>:' line
       - results/RUN_<run>.results exists, is newer than the start, parses as XML
  5. Optional: exports DSS time series to CSV (--export / --export_dss) and
     compares the run's results file to a reference (--reference_results):
     the reference must be an HMS <RunResults> file whose <RunName> is the
     same run, every
     element must exist on both sides, and every reference element must carry
     peak, volume and peak time. Peak and volume are compared in SI units
     (CFS/CMS, AC-FT/1000 M3); unknown or mixed-kind units stop the compare.

Times: DSS stores times as minutes since 1899-12-31 00:00 with a 24:00
convention for midnight (dt_109). The CSV 'datetime' column is built from the
raw minutes, so 24:00 becomes 00:00 of the next day. 'dss_time' keeps the
engine's own label for audit.

Units: the CSV keeps the DSS units. A FLOW series in CFS also gets a
'value_m3s' column (x 0.028316846592); CMS is copied as is.

Exit codes: 0 ok | 2 bad arguments / missing input | 3 engine failed
            | 4 output missing, stale or unreadable | 5 reference mismatch

Usage:
  python run_hms_engine.py --project /path/castro/castro.hms --run Current \
      --workdir ./hms_run --export Outlet:FLOW \
      --export_dss "castro.dss::/CASTRO VALLEY/OUTLET/FLOW//10MIN/OBS/" \
      --reference_results /path/castro_shipped_outputs/results
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_ENGINE = "KISSPATH_HOME/engine_builds_20261006/HEC_HMS/run_hms_headless.sh"
CFS_TO_M3S = 0.028316846592
WORKDIR_MARKER = ".run_hms_engine_workdir"
HEC_EPOCH = dt.datetime(1899, 12, 31)


class ToolError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def parse_run_file(run_path):
    """Return {run_name: {key: value}} from a <project>.run file."""
    runs, cur = {}, None
    for line in Path(run_path).read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("Run:"):
            cur = s.split(":", 1)[1].strip()
            runs[cur] = {}
        elif s.startswith("End:"):
            cur = None
        elif cur and ":" in s:
            k, v = s.split(":", 1)
            runs[cur][k.strip()] = v.strip()
    return runs


def results_name(run):
    """HMS names the results file RUN_<run>.results with spaces in the run name
    written as '_' (samples: 'Jan 96 storm' -> RUN_Jan_96_storm.results,
    'Minimum Facility + Pump' -> RUN_Minimum_Facility_+_Pump.results)."""
    return "RUN_" + run.replace(" ", "_") + ".results"


def jy_str(s):
    """Quote a string for the Jython 2.7 script (ASCII paths only)."""
    if any(ord(c) > 127 for c in s):
        raise ToolError(2, f"non-ASCII path or DSS name is not supported by the Jython script: {s!r}")
    return repr(str(s))


JYTHON_TEMPLATE = r'''
import sys
from hms.model import Project
from hms import Hms
from hec.heclib.dss import HecDss
from hec.heclib.util import HecTime

PROJECT = %(project)s
RUNS = %(runs)s
CLEAN = %(clean)s   # list of (run, dss_file): delete that run's old output records
EXPORTS = %(exports)s   # list of (dss_file, pattern, out_csv)
MARKS = %(marks)s   # status lines go to this file (the DSS library writes to stdout without newlines)

def mark(line):
    f = open(MARKS, 'a')
    f.write(line + '\n')
    f.close()
    print(line)

def norm(path):
    # DSS 7 catalogs write the E part as 5Minute / 1Hour; users write 5MIN
    parts = path.upper().split('/')
    if len(parts) == 8:
        parts[5] = parts[5].replace('MINUTE', 'MIN')
    return parts

def match(pattern, path):
    pp = norm(pattern)
    qq = norm(path)
    if len(pp) != len(qq):
        return False
    for i in range(len(pp)):
        if i == 4 or pp[i] == '*':      # D part (block date) is ignored
            continue
        if pp[i] != qq[i]:
            return False
    return True

import os
import java.util
clean_ok = True
for (r, dss_file) in CLEAN:
    try:
        if not os.path.isfile(dss_file):
            mark('HMS_CLEAN_OK %%s 0 (no DSS file yet)' %% r)
            continue
        d = HecDss.open(dss_file, True)
        tag = 'RUN:' + r.upper()
        def mine(x):
            parts = x.upper().split('/')
            return len(parts) == 8 and parts[6] == tag
        old = [x for x in d.getCatalogedPathnames(True) if mine(x)]
        if old:
            d.delete(java.util.Vector(old))
        d.done()
        d = HecDss.open(dss_file, True)
        left = [x for x in d.getCatalogedPathnames(True) if mine(x)]
        d.done()
        if left:
            clean_ok = False
            mark('HMS_CLEAN_FAIL %%s %%d old RUN records still in %%s' %% (r, len(left), dss_file))
        else:
            mark('HMS_CLEAN_OK %%s %%d' %% (r, len(old)))
    except Exception, e:
        clean_ok = False
        mark('HMS_CLEAN_FAIL %%s %%s' %% (r, e))
if not clean_ok:
    mark('HMS_ABORT old output records could not be removed; nothing computed')
    Hms.shutdownEngine()
    sys.exit(0)

p = Project.open(PROJECT)
for r in RUNS:
    try:
        ok = p.computeRun(r)   # returns None, also when the compute fails
        if ok is False:
            mark('HMS_RUN_FAIL %%s computeRun returned False' %% r)
        else:
            mark('HMS_RUN_RETURNED %%s' %% r)
    except Exception, e:
        mark('HMS_RUN_FAIL %%s %%s' %% (r, e))
p.close()

for (dss_file, pattern, out_csv) in EXPORTS:
    try:
        d = HecDss.open(dss_file, True)
        hits = [x for x in d.getCatalogedPathnames() if match(pattern, x)]
        if not hits:
            mark('HMS_EXPORT_FAIL %%s no DSS path matches %%s' %% (out_csv, pattern))
            d.done()
            continue
        tsc = d.get(hits[0], True)
        f = open(out_csv, 'w')
        f.write('# dss_file=%%s\n# dss_path=%%s\n# units=%%s\n# type=%%s\n' %% (dss_file, tsc.fullName, tsc.units, tsc.type))
        f.write('hec_minutes,dss_time,value\n')
        t = HecTime()
        for i in range(tsc.numberValues):
            t.set(tsc.times[i])
            f.write('%%d,"%%s",%%.7f\n' %% (tsc.times[i], t.dateAndTime(4), tsc.values[i]))
        f.close()
        mark('HMS_EXPORT_OK %%s n=%%d units=%%s path=%%s' %% (out_csv, tsc.numberValues, tsc.units, tsc.fullName))
        d.done()
    except Exception, e:
        mark('HMS_EXPORT_FAIL %%s %%s' %% (out_csv, e))

Hms.shutdownEngine()
'''


def read_results(path, code=4):
    """Parse results/RUN_<run>.results -> {element: {stat_type: {value, units}}}.

    Raises ToolError(code) unless the file is an HMS run-results file: root
    <RunResults> with at least one named <BasinElement>."""
    root = ET.parse(path).getroot()
    if root.tag != "RunResults":
        raise ToolError(code, f"{path}: not an HMS results file (root <{root.tag}>, expected <RunResults>)")
    out = {}
    for be in root.iter("BasinElement"):
        if not be.get("name"):
            raise ToolError(code, f"{path}: <BasinElement> without a name")
        stats = {}
        for sm in be.iter("StatisticMeasure"):
            stats[sm.get("type")] = {"value": sm.get("value"), "units": sm.get("units")}
        da = be.find("DrainageArea")
        out[be.get("name")] = {
            "type": be.get("type"),
            "drainage_area": None if da is None else {"value": da.get("area"), "units": da.get("units")},
            "stats": stats,
        }
    if not out:
        raise ToolError(code, f"{path}: no <BasinElement> in the results file")
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _time(v):
    """'16 January 1973, 06:55' (HMS 4.14) or '16Jan1973, 06:55' (older results) -> datetime.

    HEC writes midnight as 24:00 of the day before (dt_109): '18Jan1996, 24:00'
    is read as 19 Jan 1996 00:00, so both spellings of one instant compare equal."""
    if not isinstance(v, str):
        return None
    s, plus = v.strip(), dt.timedelta(0)
    if s.endswith(", 24:00"):
        s, plus = s[:-5] + "00:00", dt.timedelta(days=1)
    for fmt in ("%d %B %Y, %H:%M", "%d%b%Y, %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt) + plus
        except ValueError:
            pass
    return None


# HMS results units -> (dimension, factor to SI). English: CFS, AC-FT, IN;
# metric: CMS (M3/S), 1000 M3, MM. Depth (IN/MM) is NOT a volume.
UNIT_SI = {
    "CFS": ("flow", CFS_TO_M3S), "CMS": ("flow", 1.0), "M3/S": ("flow", 1.0),
    "AC-FT": ("volume", 1233.48183754752), "1000 M3": ("volume", 1000.0), "M3": ("volume", 1.0),
    "IN": ("depth", 25.4), "MM": ("depth", 1.0),
}
STAT_DIM = {"Outflow Maximum": "flow", "Outflow Volume": "volume"}


def _si(value, units, dim):
    """value in `units` -> (SI float, None), or (None, reason) for an unknown / wrong-kind unit."""
    u = " ".join((units or "").upper().split())
    if u not in UNIT_SI:
        return None, f"unknown units {units!r}"
    d, f = UNIT_SI[u]
    if d != dim:
        return None, f"units {units!r} are {d}, expected {dim}"
    v = _num(value)
    if v is None:
        return None, f"not a number: {value!r}"
    return v * f, None


def compare_results(new, ref, rtol):
    """Compare every element's peak, volume and peak time with the reference.

    Every reference element must carry all three stats and every element of
    either side must exist in the other; peak and volume are compared in SI
    after a unit check, so 100 CFS never matches 100 CMS."""
    keys = ("Outflow Maximum", "Outflow Volume", "Outflow Maximum Time")
    rows, mism = [], []
    for name in sorted(set(new) - set(ref)):
        mism.append(f"{name}: element in the new results but not in the reference")
    for name, refel in ref.items():
        newel = new.get(name)
        if newel is None:
            mism.append(f"{name}: element in the reference but not in the new results")
        for k in keys:
            rs = refel["stats"].get(k, {})
            rv = rs.get("value")
            if rv is None:
                raise ToolError(2, f"reference element {name!r} has no '{k}' statistic; cannot compare")
            ns = {} if newel is None else newel["stats"].get(k, {})
            nv = ns.get("value")
            note = None
            if k.endswith("Time"):
                if _time(rv) is None:
                    raise ToolError(2, f"reference element {name!r} '{k}' is not a time: {rv!r}")
                same = _time(nv) is not None and _time(nv) == _time(rv)
            else:
                b, why = _si(rv, rs.get("units"), STAT_DIM[k])
                if b is None:
                    raise ToolError(2, f"reference element {name!r} '{k}': {why}")
                a, note = (None, "missing") if nv is None else _si(nv, ns.get("units"), STAT_DIM[k])
                same = a is not None and abs(a - b) <= rtol * abs(b)
            rows.append({"element": name, "stat": k, "new": nv, "new_units": ns.get("units"),
                         "ref": rv, "ref_units": rs.get("units"), "match": same})
            if not same:
                mism.append(f"{name} {k}: new={nv} {ns.get('units') or ''} ref={rv} {rs.get('units') or ''}"
                            + (f" ({note})" if note else ""))
    return rows, mism


def convert_export(raw_csv, out_csv):
    """raw Jython CSV -> CSV with ISO datetime (+ value_m3s for FLOW in CFS/CMS)."""
    meta, rows = {}, []
    for line in Path(raw_csv).read_text().splitlines():
        if line.startswith("# "):
            k, _, v = line[2:].partition("=")
            meta[k] = v
        elif line and not line.startswith("hec_minutes"):
            mins, rest = line.split(",", 1)
            label, val = rest.rsplit(",", 1)
            rows.append((int(mins), label.strip('"').replace(",", ""), float(val)))
    if not rows:
        raise ToolError(4, f"export {raw_csv} holds no values")
    units = meta.get("units", "").upper()
    parts = meta.get("dss_path", "").split("/")
    is_flow = len(parts) > 3 and parts[3].upper().startswith("FLOW")
    factor = CFS_TO_M3S if (is_flow and units == "CFS") else (1.0 if (is_flow and units == "CMS") else None)
    with open(out_csv, "w") as f:
        f.write(f"# dss_path={meta.get('dss_path','')}\n# units={meta.get('units','')}\n")
        f.write("datetime,dss_time,value" + (",value_m3s" if factor else "") + "\n")
        for mins, label, val in rows:
            ts = (HEC_EPOCH + dt.timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M:%S")
            # DSS writes a missing value as a large negative sentinel (-3.4e38 / -901)
            v = "" if (val <= -900.0) else f"{val:.7f}"
            line = f"{ts},{label},{v}"
            if factor:
                line += "," + ("" if v == "" else f"{val * factor:.7f}")
            f.write(line + "\n")
    os.remove(raw_csv)
    vals = [v for _, _, v in rows if v > -900.0]
    return {"csv": str(out_csv), "dss_path": meta.get("dss_path"), "units": meta.get("units"),
            "n": len(rows), "n_missing": len(rows) - len(vals),
            "first": (HEC_EPOCH + dt.timedelta(minutes=rows[0][0])).isoformat(),
            "last": (HEC_EPOCH + dt.timedelta(minutes=rows[-1][0])).isoformat(),
            "max": max(vals) if vals else None, "min": min(vals) if vals else None,
            "m3s_column": bool(factor)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="path to <project>.hms (its folder is copied)")
    ap.add_argument("--run", action="append", required=True, help="simulation run name (repeatable)")
    ap.add_argument("--workdir", required=True, help="new folder for the project copy and outputs")
    ap.add_argument("--engine", default=os.environ.get("HMS_ENGINE", DEFAULT_ENGINE),
                    help="headless HMS launcher (env HMS_ENGINE; default: %(default)s)")
    ap.add_argument("--export", action="append", default=[],
                    help="ELEMENT:PARAM of the run's output DSS, e.g. Outlet:FLOW (repeatable)")
    ap.add_argument("--export_dss", action="append", default=[],
                    help="FILE::/A/B/C//E/F/ DSS series in FILE (relative to the project copy), e.g. observed gage")
    ap.add_argument("--reference_results", default=None,
                    help="folder with reference RUN_<run>.results to compare with (exit 5 on mismatch)")
    ap.add_argument("--ref_rtol", type=float, default=0.0,
                    help="relative tolerance for the reference compare (default 0 = exact)")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing --workdir")
    ap.add_argument("--timeout", type=int, default=3600, help="engine time limit in seconds")
    a = ap.parse_args(argv)

    summary = {"tool": "run_hms_engine.py", "engine": a.engine, "status": "failed", "runs": {}}
    work = Path(a.workdir).resolve()
    work_ok = False   # True once --workdir is known not to overlap the source
    try:
        src_hms = Path(a.project).resolve()
        if not src_hms.is_file() or src_hms.suffix != ".hms":
            raise ToolError(2, f"--project must be an existing .hms file: {src_hms}")
        # absolute now: the engine is launched with cwd = the project copy
        engine = Path(os.path.abspath(a.engine))
        if not (engine.is_file() and os.access(engine, os.X_OK)):
            raise ToolError(2, f"HMS engine launcher missing or not executable: {engine}")
        summary["engine_realpath"] = os.path.realpath(engine)
        # the source project is never written to: --workdir may not be the
        # source folder, inside it, or one of its parents (rmtree / copytree)
        src_dir = src_hms.parent
        if work == src_dir or src_dir in work.parents or work in src_dir.parents:
            raise ToolError(2, f"--workdir {work} overlaps the source project folder {src_dir}")
        if work.exists():
            if not a.overwrite:
                raise ToolError(2, f"--workdir exists (use --overwrite): {work}")
            if not work.is_dir():
                raise ToolError(2, f"--workdir exists and is not a folder: {work}")
            # only replace a folder this tool made (marker) or an empty one
            if any(work.iterdir()) and not (work / WORKDIR_MARKER).is_file():
                raise ToolError(2, f"--overwrite refused: {work} is not empty and was not made by "
                                   f"run_hms_engine.py (no {WORKDIR_MARKER}); pick a new --workdir")
            shutil.rmtree(work)
        work.mkdir(parents=True)
        (work / WORKDIR_MARKER).write_text("made by run_hms_engine.py; --overwrite may replace this folder\n")
        work_ok = True
        proj_dir = work / "project"
        shutil.copytree(src_dir, proj_dir)
        proj_real = proj_dir.resolve()

        def in_project(rel, what):
            """proj_dir/rel, refused unless it stays inside the project copy."""
            p = (proj_dir / rel).resolve()
            if p == proj_real or proj_real not in p.parents:
                raise ToolError(2, f"{what} {rel!r} points outside the project copy ({p})")
            return p

        hms = proj_dir / src_hms.name
        run_file = proj_dir / (src_hms.stem + ".run")
        if not run_file.is_file():
            raise ToolError(2, f"run file not found next to the project: {run_file.name}")
        run_cfg = parse_run_file(run_file)
        for r in a.run:
            if r not in run_cfg:
                raise ToolError(2, f"run '{r}' not in {run_file.name} (has: {sorted(run_cfg)})")

        # every output path HMS will write (and we delete) must stay in the copy;
        # check all runs before deleting anything or launching the engine
        out_paths = {}
        for r in a.run:
            cfg = run_cfg[r]
            log_rel = cfg.get("Log File", r + ".log")
            out_paths[r] = {
                "log": in_project(log_rel, f"run '{r}' Log File"),
                "out": in_project(Path(log_rel).stem + ".out", f"run '{r}' .out file"),
                "dss": in_project(cfg.get("DSS File", r + ".dss"), f"run '{r}' DSS File"),
                "results": in_project(str(Path("results") / results_name(r)), f"run '{r}' results file"),
            }

        # 2. remove the copy's old log / .out / results so freshness can be
        # proven. The DSS file is kept (it may hold inputs); the Jython script
        # removes only this run's RUN:<run> records from it before computing.
        for r in a.run:
            for k in ("log", "out", "results"):
                out_paths[r][k].unlink(missing_ok=True)

        exports, planned = [], []
        exp_dir = work / "exports"
        exp_dir.mkdir()
        used = set()

        def unique_raw(stem):
            """exp_dir/<stem>.raw, suffixed _2, _3, ... if the name is taken
            (sanitising can map different elements to the same stem)."""
            name, n = stem, 1
            while name.lower() in used:
                n += 1
                name = f"{stem}_{n}"
            used.add(name.lower())
            return exp_dir / (name + ".raw")

        for r in a.run:
            dss = out_paths[r]["dss"]
            for spec in a.export:
                if ":" not in spec:
                    raise ToolError(2, f"--export must be ELEMENT:PARAM, got {spec!r}")
                el, par = spec.split(":", 1)
                raw = unique_raw(re.sub(r"[^A-Za-z0-9.-]+", "_", f"{r}_{el}_{par}"))
                exports.append((str(dss), f"//{el}/{par}/*/*/RUN:{r}/", str(raw)))
        for spec in a.export_dss:
            if "::" not in spec:
                raise ToolError(2, f"--export_dss must be FILE::PATH, got {spec!r}")
            fname, path = spec.split("::", 1)
            dss_in = in_project(fname, "--export_dss file")
            if not dss_in.is_file():
                raise ToolError(2, f"--export_dss file not found in project: {fname}")
            parts = path.split("/")
            if len(parts) != 8:
                raise ToolError(2, f"DSS path must look like /A/B/C/D/E/F/: {path!r}")
            raw = unique_raw("dss_" + re.sub(r"[^A-Za-z0-9]+", "_", "_".join(parts[1:4] + parts[5:7])).strip("_"))
            exports.append((str(dss_in), path, str(raw)))
        planned = [e[2] for e in exports]

        script = work / "hms_compute.py"
        marks = work / "hms_markers.txt"
        script.write_text(JYTHON_TEMPLATE % {
            "project": jy_str(str(hms)), "runs": "[" + ", ".join(jy_str(r) for r in a.run) + "]",
            "marks": jy_str(str(marks)),
            "clean": "[" + ", ".join("(%s, %s)" % (jy_str(r), jy_str(str(out_paths[r]["dss"]))) for r in a.run) + "]",
            "exports": "[" + ", ".join("(%s, %s, %s)" % (jy_str(f), jy_str(p), jy_str(o)) for f, p, o in exports) + "]",
        })

        # 3. run the engine
        env = dict(os.environ)
        env.pop("DISPLAY", None)
        t0 = time.time()
        with open(work / "engine_stdout.txt", "w") as so, open(work / "engine_stderr.txt", "w") as se:
            try:
                proc = subprocess.run([str(engine), "-script", str(script)], cwd=str(proj_dir), env=env,
                                      stdout=so, stderr=se, timeout=a.timeout)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                raise ToolError(3, f"engine exceeded --timeout {a.timeout}s")
        summary["engine_rc"] = rc
        summary["engine_seconds"] = round(time.time() - t0, 2)
        # status lines written by the Jython script (not stdout: the DSS
        # library prints there without newlines and splits lines)
        out = marks.read_text(errors="replace") if marks.is_file() else ""

        # 4. per-run success checks
        problems = []
        if any(ln.startswith("HMS_ABORT") for ln in out.splitlines()):
            problems.append("old RUN output records could not be removed from the DSS copy; nothing was computed")
        if rc != 0:
            problems.append(f"engine exit code {rc} (see engine_stderr.txt)")
        for r in a.run:
            info = {"ok": False, "checks": {}}
            info["checks"]["dss_cleaned"] = any(ln.startswith(f"HMS_CLEAN_OK {r} ") for ln in out.splitlines())
            info["checks"]["script_returned"] = any(ln.strip() == f"HMS_RUN_RETURNED {r}" for ln in out.splitlines())
            fails = [ln for ln in out.splitlines() if ln.startswith(f"HMS_RUN_FAIL {r} ")]
            log = out_paths[r]["log"]
            log_txt = log.read_text(errors="replace") if log.is_file() else ""
            info["log"] = str(log)
            info["checks"]["log_exists"] = log.is_file() and log.stat().st_mtime >= t0 - 1
            info["checks"]["log_finished"] = f'Finished computing simulation run "{r}"' in log_txt
            errs = re.findall(r"^ERROR \d+:.*$", log_txt, flags=re.M)
            info["log_errors"] = errs[:20]
            info["log_warnings"] = len(re.findall(r"^WARNING \d+:", log_txt, flags=re.M))
            info["checks"]["log_no_error"] = not errs
            res = out_paths[r]["results"]
            info["results_file"] = str(res)
            fresh = res.is_file() and res.stat().st_mtime >= t0 - 1
            info["checks"]["results_fresh"] = fresh
            elements = {}
            if fresh:
                try:
                    elements = read_results(res)
                except (ET.ParseError, ToolError) as e:
                    problems.append(f"{r}: results file does not parse ({e})")
            info["checks"]["results_parsed"] = bool(elements)
            info["elements"] = elements
            dssf = out_paths[r]["dss"]
            info["dss_file"] = str(dssf)
            info["checks"]["dss_fresh"] = dssf.is_file() and dssf.stat().st_mtime >= t0 - 1
            info["ok"] = all(info["checks"].values()) and not fails and rc == 0
            for k, v in info["checks"].items():
                if not v:
                    problems.append(f"{r}: check failed: {k}")
            problems += [f"{r}: {ln}" for ln in fails] + [f"{r}: log {e}" for e in errs[:5]]
            summary["runs"][r] = info
        if problems:
            summary["problems"] = problems
            code = 3 if (rc != 0 or any("FAIL" in p or "log_finished" in p or "log_no_error" in p
                                        or "script_returned" in p or "dss_cleaned" in p
                                        or "could not be removed" in p for p in problems)) else 4
            raise ToolError(code, "; ".join(problems[:6]))

        # 5a. exports
        summary["exports"] = []
        for raw in planned:
            okline = [ln for ln in out.splitlines() if ln.startswith(f"HMS_EXPORT_OK {raw} ")]
            failline = [ln for ln in out.splitlines() if ln.startswith(f"HMS_EXPORT_FAIL {raw} ")]
            if failline or not okline or not Path(raw).is_file():
                raise ToolError(4, f"DSS export failed: {failline[0] if failline else raw}")
            summary["exports"].append(convert_export(raw, raw[:-4] + ".csv"))

        # 5b. reference compare
        if a.reference_results:
            summary["reference"] = {}
            mism_all = []
            for r in a.run:
                refp = Path(a.reference_results) / results_name(r)
                if not refp.is_file():
                    raise ToolError(2, f"reference results not found: {refp}")
                try:
                    ref = read_results(refp, code=2)
                    ref_run = ET.parse(refp).getroot().findtext("RunName")
                except ET.ParseError as e:
                    raise ToolError(2, f"reference results do not parse: {refp} ({e})")
                if ref_run is None or ref_run.strip() != r:
                    raise ToolError(2, f"reference {refp} is for run {ref_run!r}, not {r!r} (<RunName> must match)")
                rows, mism = compare_results(summary["runs"][r]["elements"], ref, a.ref_rtol)
                if not rows:
                    raise ToolError(2, f"reference {refp} gave nothing to compare")
                summary["reference"][r] = {"file": str(refp), "n_compared": len(rows),
                                           "n_mismatch": len(mism), "rtol": a.ref_rtol, "rows": rows}
                mism_all += [f"{r}: {m}" for m in mism]
            if mism_all:
                summary["problems"] = mism_all
                raise ToolError(5, f"{len(mism_all)} value(s) differ from the reference: {mism_all[:3]}")
        summary["status"] = "success"
        code = 0
    except ToolError as e:
        summary["error"] = str(e)
        code = e.code
    except Exception as e:  # unexpected: report, never pass silently
        summary["error"] = f"{type(e).__name__}: {e}"
        code = 4
    summary["exit_code"] = code
    if work_ok and work.is_dir():
        (work / "hms_engine_run.json").write_text(json.dumps(summary, indent=1))
    brief = {k: v for k, v in summary.items() if k != "runs"}
    brief["runs"] = {r: {"ok": i.get("ok"), "checks": i.get("checks"), "log_warnings": i.get("log_warnings"),
                         "log_errors": i.get("log_errors")} for r, i in summary["runs"].items()}
    if "reference" in brief:
        brief["reference"] = {r: {k: v for k, v in i.items() if k != "rows"} for r, i in brief["reference"].items()}
    print(json.dumps(brief))
    return code


if __name__ == "__main__":
    sys.exit(main())
