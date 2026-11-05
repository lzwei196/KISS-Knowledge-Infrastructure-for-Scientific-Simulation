#!/usr/bin/env python3
"""Run the REAL EPA VELMA 2.1 engine (JVelma.jar) headless and check that it worked.

This is the real model. `run_velma.py` in this directory is a Python SURROGATE
(a lumped 4-layer stand-in written for this KI); its numbers are not VELMA.

What this tool does
  1. Reads the simulation configuration .xml (never edits it). Every change is
     passed to the engine as a --kv="/group/props/key,value" override, which is
     the engine's own command-line contract (VelmaSimulatorCmdLine).
  2. VELMA 2.0 -> 2.1 humus migration (--humus-migration auto, the default):
     in 2.1 humusCtoN, initialHumusCarbon and humusNmaxDecay are SOIL
     parameters (SoilParameters.getInitialHumusN = initialHumusCarbon/humusCtoN).
     A 2.0-era configuration sets them only in the cover block, so the soil gets
     0/0 = NaN and the run stops on day 1 with "NaN TRAPPED! nitrificationAmount=NaN".
     The tool copies the SAME values from the cover block to every soil block
     that lacks them. If several cover blocks disagree it refuses (exit 2):
     there is no single right value to copy. No new numbers are made up.
     A value the soil block (or a --kv) already sets is never replaced, even 0;
     it is only checked, and a value VELMA cannot use (not a number, negative,
     or humusCtoN = 0) is refused (exit 2).
  3. Runs the engine launcher (run_velma_headless.sh = java -Djava.awt.headless=true
     -cp JVelma.jar gov.epa.velmasimulator.VelmaSimulatorCmdLine).
  4. Judges success by evidence, not by the exit code alone:
       - exit code 0, AND
       - "Simulation run completed" in the engine log, AND
       - no "FAIL!" / "NaN TRAPPED" / Java exception lines, AND
       - DailyResults.csv exists with one row per simulated day (syear..eyear)
         and finite Runoff_All, Rain, Snow and ET columns (all four feed the summary).
  5. Writes <run_output_dir>/velma_engine_summary.json and
     <run_output_dir>/velma_daily_runoff.csv (date, runoff_mm_d, and Q_sim_m3s
     when --area-km2 is given).

Exit codes: 0 success; 2 bad arguments / inputs / config; 3 the engine failed
(non-zero exit or timeout); 4 the engine exited 0 but the success checks failed.

Units: Runoff_All, Rain, Snow, ET and PET in DailyResults.csv are mm/day averaged
over the DELINEATED watershed. The Soil_Moisture(mm)_..._Layer_n columns are a
volumetric FRACTION (m3/m3) despite the "(mm)" in their header: layer water in mm =
fraction x layer thickness (soilColumnDepth x setSoilLayerWeights; WS10: 500 mm per
layer). See triplet dt_velma_029.
Q (m3/s) = runoff_mm_d * area_km2 * 1e6 / 1000 / 86400. Pass --area-km2 = the gauged
drainage area when Q is compared with a gauge (dt_velma_030); it must be finite and > 0.

Weather driver files for the DefaultWeatherModel are ONE value per row, no
header, one row per day from forcing_start: precipitation in mm/day and mean
air temperature in deg C (NOT Kelvin). Build them with
build_velma_weather_from_source.py.
"""

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

DEFAULT_LAUNCHER = "KISSPATH_HOME/engine_builds_20261006/VELMA/run_velma_headless.sh"
HUMUS_KEYS = ("humusCtoN", "initialHumusCarbon", "humusNmaxDecay")
INPUTS = "/calibration/VelmaInputs.properties"
CALIB = "/calibration/VelmaCalibration.properties"
STARTUPS = "/startups/VelmaStartups.properties"
WEATHER = "/weather/DefaultWeatherModel"
FAIL_PATTERNS = ("FAIL!", "NaN TRAPPED", "Exception in thread", "java.lang.RuntimeException",
                 "java.lang.NullPointerException", "OutOfMemoryError")
SECONDS_PER_DAY = 86400.0


class Refused(Exception):
    """Input or configuration problem found before the engine runs (exit 2)."""


def log(msgs, text):
    msgs.append(text)
    print(text, flush=True)


def parse_kv(text):
    if "," not in text:
        raise Refused(f"--kv needs '/group/props/key,value', got {text!r}")
    key, val = text.split(",", 1)
    if not key.startswith("/") or key.count("/") != 3:
        raise Refused(f"--kv key must be /group/props/key, got {key!r}")
    return key, val


def config_value(root, key):
    """Value of /group/props/key in the configuration xml, or None."""
    _, group, props, name = key.split("/")
    node = root.find(f"./{group}/{props}/{name}")
    return None if node is None else (node.text or "").strip()


def check_humus_value(key, text):
    """Refuse an explicit soil humus value VELMA 2.1 cannot run with; never change it."""
    try:
        val = float(text)
    except ValueError:
        raise Refused(f"{key} = {text!r} is not a number")
    if not math.isfinite(val) or val < 0:
        raise Refused(f"{key} = {text!r} must be a finite number >= 0")
    if key.endswith("/humusCtoN") and val == 0:
        raise Refused(
            f"{key} = {text!r}: VELMA 2.1 divides initialHumusCarbon by humusCtoN, so 0 gives "
            f"NaN on day 1. Fix the configuration or set it with --kv={key},<value>")


def humus_migration(root, overrides, msgs):
    """--kv overrides that carry the 3 humus keys from the cover block to the soil block."""
    covers = root.find("./cover")
    soils = root.find("./soil")
    if covers is None or soils is None:
        return {}
    cover_vals = {}
    for cover in covers:
        for k in HUMUS_KEYS:
            # the EFFECTIVE cover value: a --kv on /cover/<tag>/<key> wins over the xml
            node = cover.find(k)
            text = overrides.get(f"/cover/{cover.tag}/{k}", "" if node is None else (node.text or "")).strip()
            if text:
                cover_vals.setdefault(k, set()).add(text)
    added = {}
    for soil in soils:
        for k in HUMUS_KEYS:
            key = f"/soil/{soil.tag}/{k}"
            node = soil.find(k)
            text = "" if node is None else (node.text or "").strip()
            if key in overrides or text:
                # an explicit value (config or --kv) is never replaced, only checked
                check_humus_value(key, overrides.get(key, text))
                continue
            vals = cover_vals.get(k)
            if not vals:
                raise Refused(
                    f"soil block {soil.tag} has no {k} and no cover block sets it; "
                    f"VELMA 2.1 will stop with NaN on day 1. Set it with --kv={key},<value>")
            if len(vals) > 1:
                raise Refused(
                    f"soil block {soil.tag} has no {k}, and the cover blocks disagree "
                    f"({sorted(vals)}); refusing to pick one. Set it with --kv={key},<value>")
            val = next(iter(vals))
            # a copied cover value must pass the same check as an explicit soil value
            check_humus_value(key, val)
            added[key] = val
    for key, val in added.items():
        log(msgs, f"humus migration 2.0->2.1: {key} = {val} (copied from the cover block)")
    return added


def read_daily(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def outlet_area_m2(out_dir, cell_m):
    """Delineated watershed area from the engine's own ReachSummary.csv."""
    path = os.path.join(out_dir, "ReachSummary.csv")
    if not os.path.isfile(path):
        return None
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    cells = [int(r["Reach_plus_Contributor_Cells"]) for r in rows
             if (r.get("Reach_plus_Contributor_Cells") or "").strip()]
    return max(cells) * cell_m * cell_m if cells else None


def parse_nse(out_dir):
    path = os.path.join(out_dir, "NashSutcliffeCoefficients.txt")
    if not os.path.isfile(path):
        return {}
    text = open(path).read()
    out = {}
    m = re.search(r"Nash-Sutcliffe Coefficient=([-\d.Ee+]+).*?Years=\[(\d+) to (\d+)\]"
                  r".*?used=(\d+) rejected=(\d+)", text)
    if m:
        out.update(engine_nse=float(m.group(1)), engine_nse_years=[int(m.group(2)), int(m.group(3))],
                   engine_nse_used=int(m.group(4)), engine_nse_rejected=int(m.group(5)))
    m = re.search(r"Root Mean Square Error value=([-\d.Ee+]+)", text)
    if m:
        out["engine_rmse_mm_d"] = float(m.group(1))
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Run the REAL EPA VELMA 2.1 Java engine headless (not the Python surrogate) "
                    "and verify the run from its log and DailyResults.csv.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--config", required=True, help="Full path of the VELMA simulation configuration .xml")
    ap.add_argument("--input-root", required=True,
                    help="Directory that HOLDS the input folder named by inputDataLocationDirName "
                         "(-> /startups/.../inputDataLocationRootName)")
    ap.add_argument("--output-root", required=True,
                    help="Output root; the engine writes <output-root>/<run_index>/")
    ap.add_argument("--run-index", help="Override run_index (name of the output folder)")
    ap.add_argument("--syear", type=int, help="First simulated year")
    ap.add_argument("--eyear", type=int, help="Last simulated year")
    ap.add_argument("--forcing-start", type=int,
                    help="Year of the FIRST row of the weather driver files")
    ap.add_argument("--rain-file", help="Daily precipitation driver (mm/day, one value per row, no header)")
    ap.add_argument("--temp-file", help="Daily mean air temperature driver (deg C, one value per row)")
    ap.add_argument("--observed-runoff", help="Observed runoff file (mm/day, one value per row from forcing_start)")
    ap.add_argument("--nse-years", help="START-END years for the engine's own Nash-Sutcliffe file")
    ap.add_argument("--end-state-dir", help="Save the end-of-run spatial state here (spin-up run)")
    ap.add_argument("--start-state-dir", help="Start from a spatial state saved by a spin-up run")
    ap.add_argument("--kv", action="append", default=[],
                    help="Extra engine override '/group/props/key,value' (repeatable)")
    ap.add_argument("--humus-migration", choices=["auto", "off"], default="auto",
                    help="auto: copy humus keys cover->soil when the soil block lacks them (2.0 configs)")
    ap.add_argument("--area-km2", type=float,
                    help="Area used to turn runoff mm/d into Q_sim_m3s (default: the engine's delineated area)")
    ap.add_argument("--launcher", default=DEFAULT_LAUNCHER, help="Engine launcher script")
    ap.add_argument("--xmx", default="8g", help="Java heap (VELMA_XMX)")
    ap.add_argument("--timeout", type=float, default=6 * 3600, help="Seconds before the run is killed")
    ap.add_argument("--no-scope", action="store_true",
                    help="Do not wrap the engine in systemd-run --user --scope (TasksMax/MemoryMax caps)")
    ap.add_argument("--overwrite", action="store_true",
                    help="Delete an existing <output-root>/<run_index> first (the engine will not reuse it)")
    ap.add_argument("--lint", action="store_true", help="Engine --lint only: initialise, do not run")
    args = ap.parse_args()

    msgs = []
    result = {"status": "error", "engine": "EPA VELMA 2.1 JVelma.jar (real engine)", "output": {}, "log": msgs}
    code = 2
    try:
        if args.area_km2 is not None and not (math.isfinite(args.area_km2) and args.area_km2 > 0):
            raise Refused(f"--area-km2 must be a finite number > 0, got {args.area_km2!r}")
        cfg = os.path.abspath(args.config)
        if not os.path.isfile(cfg):
            raise Refused(f"config not found: {cfg}")
        if not os.access(args.launcher, os.X_OK):
            raise Refused(f"engine launcher not executable: {args.launcher}")
        root = ET.parse(cfg).getroot()
        input_root = os.path.abspath(args.input_root)
        output_root = os.path.abspath(args.output_root)
        kv = {}
        for text in args.kv:
            k, v = parse_kv(text)
            kv[k] = v
        root_key = f"{STARTUPS}/inputDataLocationRootName"
        if root_key in kv and os.path.abspath(kv[root_key]) != input_root:
            raise Refused(f"--kv {root_key} conflicts with --input-root {input_root}; use --input-root")
        # the input folder the ENGINE reads: a --kv on inputDataLocationDirName wins over the xml
        dir_key = f"{STARTUPS}/inputDataLocationDirName"
        in_dir_name = kv.get(dir_key, config_value(root, dir_key)) or ""
        if os.path.isabs(in_dir_name) or in_dir_name in (".", "..") or os.sep in in_dir_name:
            raise Refused(f"inputDataLocationDirName {in_dir_name!r} must be a plain folder name under --input-root")
        in_dir = os.path.join(input_root, in_dir_name)
        if not os.path.isdir(in_dir):
            raise Refused(f"input folder {in_dir} not found (input-root + effective inputDataLocationDirName)")
        kv[root_key] = input_root
        kv[f"{INPUTS}/initializeOutputDataLocationRoot"] = output_root
        if args.run_index:
            kv[f"{INPUTS}/run_index"] = args.run_index
        if args.syear is not None:
            kv[f"{INPUTS}/syear"] = str(args.syear)
        if args.eyear is not None:
            kv[f"{INPUTS}/eyear"] = str(args.eyear)
        if args.forcing_start is not None:
            kv[f"{INPUTS}/forcing_start"] = str(args.forcing_start)
        for opt, keys in ((args.rain_file, (f"{INPUTS}/input_rain", f"{WEATHER}/rainDriverDataFileName")),
                          (args.temp_file, (f"{INPUTS}/input_at", f"{WEATHER}/airTemperatureDriverDataFileName"))):
            if opt:
                if not os.path.isfile(opt if os.path.isabs(opt) else os.path.join(in_dir, opt)):
                    raise Refused(f"weather driver not found: {opt}")
                for k in keys:
                    kv[k] = opt
        if args.observed_runoff:
            kv[f"{INPUTS}/input_runoff"] = args.observed_runoff
        if args.nse_years:
            try:
                a, b = (int(x) for x in args.nse_years.split("-"))
            except ValueError:
                raise Refused(f"--nse-years must be START-END, got {args.nse_years!r}")
            kv[f"{CALIB}/nashSutcliffeStartYearForRunoffStats"] = str(a)
            kv[f"{CALIB}/nashSutcliffeEndYearForRunoffStats"] = str(b)
        if args.end_state_dir:
            os.makedirs(args.end_state_dir, exist_ok=True)
            kv[f"{STARTUPS}/setEndStateSpatialDataLocationName"] = os.path.abspath(args.end_state_dir)
        if args.start_state_dir:
            sdir = os.path.abspath(args.start_state_dir)
            if not os.path.isdir(sdir) or not any(f.endswith(".asc") for f in os.listdir(sdir)):
                raise Refused(f"start state dir has no .asc state maps: {sdir}")
            kv[f"{STARTUPS}/setStartStateSpatialDataLocationName"] = sdir
        if args.humus_migration == "auto":
            kv.update(humus_migration(root, kv, msgs))

        def eff(key):
            return kv.get(key, config_value(root, key))

        def eff_number(key, kind):
            text = eff(key)
            try:
                return kind(text)
            except (TypeError, ValueError):
                raise Refused(f"{key} = {text!r} is missing or not a {kind.__name__} "
                              f"(set it in the xml or with --kv={key},<value>)")

        run_index = eff(f"{INPUTS}/run_index")
        syear, eyear = eff_number(f"{INPUTS}/syear", int), eff_number(f"{INPUTS}/eyear", int)
        fstart = eff_number(f"{INPUTS}/forcing_start", int)
        cell_m = eff_number(f"{INPUTS}/cell", float)
        if syear < fstart or eyear < syear:
            raise Refused(f"years inconsistent: forcing_start={fstart} syear={syear} eyear={eyear}")
        # Every driver row count must cover forcing_start..eyear (no filling, no cutting).
        need_rows = (date(eyear, 12, 31) - date(fstart, 1, 1)).days + 1
        for key in (f"{WEATHER}/rainDriverDataFileName", f"{WEATHER}/airTemperatureDriverDataFileName"):
            name = eff(key)
            if not name:
                continue
            p = name if os.path.isabs(name) else os.path.join(in_dir, name)
            try:
                with open(p) as f:
                    rows = [ln for ln in f if ln.strip()]
            except OSError as exc:
                raise Refused(f"weather driver {p} cannot be read: {exc}")
            if len(rows) < need_rows:
                raise Refused(f"{p}: {len(rows)} rows, needs >= {need_rows} "
                              f"(forcing_start {fstart} .. eyear {eyear})")
            try:
                vals = [float(r.split(",")[-1]) for r in rows[:need_rows]]
            except ValueError as exc:
                raise Refused(f"{p}: a row is not a number ({exc})")
            if any(not math.isfinite(v) for v in vals):
                raise Refused(f"{p}: non-finite driver values")
            if "Temperature" in key and (min(vals) < -60 or max(vals) > 50):
                raise Refused(f"{p}: temperature {min(vals):.1f}..{max(vals):.1f} is not deg C "
                              f"(Kelvin passed? VELMA weather files are Celsius)")
            if "rain" in key and (min(vals) < 0 or max(vals) > 1000):
                raise Refused(f"{p}: precipitation {min(vals):.1f}..{max(vals):.1f} is not mm/day")

        # run_index must name ONE folder strictly inside output_root ('.', '..', '/x', 'a/b' refused)
        if (not run_index or run_index in (".", "..") or os.path.isabs(run_index)
                or os.sep in run_index or (os.altsep and os.altsep in run_index)):
            raise Refused(f"run_index {run_index!r} must be a plain folder name")
        if os.path.islink(os.path.join(output_root, run_index)):
            raise Refused(f"{os.path.join(output_root, run_index)} is a symlink; refusing to use or delete it")
        run_out = os.path.realpath(os.path.join(output_root, run_index))
        real_root = os.path.realpath(output_root)
        if os.path.dirname(run_out) != real_root:
            raise Refused(f"run_index {run_index!r} resolves to {run_out}, "
                          f"not a folder directly under {real_root}")
        if os.path.exists(run_out) and not args.lint:
            if not args.overwrite:
                raise Refused(f"output folder exists: {run_out} (use --overwrite)")
            shutil.rmtree(run_out)
        os.makedirs(output_root, exist_ok=True)

        cmd = [args.launcher, cfg] + [f"--kv={k},{v}" for k, v in kv.items()]
        if args.lint:
            cmd.append("--lint")
        if not args.no_scope and shutil.which("systemd-run"):
            cmd = ["systemd-run", "--user", "--scope", "--quiet", "-p", "TasksMax=300",
                   "-p", "MemoryMax=16G"] + cmd
        env = dict(os.environ, VELMA_XMX=args.xmx)
        log_path = os.path.join(output_root, f"{run_index}_engine_stdout.txt")
        log(msgs, "engine command: " + " ".join(cmd))
        t0 = time.time()
        code = 3
        with open(log_path, "w") as lf:
            try:
                proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env,
                                      cwd=output_root, timeout=args.timeout)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                rc = None
        wall = time.time() - t0
        text = open(log_path, errors="replace").read()
        out = result["output"]
        out.update(engine_log=log_path, exit_code=rc, wall_s=round(wall, 1), run_output_dir=run_out,
                   overrides=kv, syear=syear, eyear=eyear, forcing_start=fstart)
        if rc is None:
            raise RuntimeError(f"engine timed out after {args.timeout} s; log {log_path}")
        bad = [ln.strip() for ln in text.splitlines() if any(p in ln for p in FAIL_PATTERNS)]
        if rc != 0:
            raise RuntimeError(f"engine exit code {rc}; first failure lines: {bad[:3]}; log {log_path}")
        if args.lint:
            if bad:
                code = 4
                raise RuntimeError(f"lint reported: {bad[:3]}")
            result["status"] = "success"
            return 0
        code = 4
        if bad:
            raise RuntimeError(f"engine exit 0 but log has failures: {bad[:3]}; log {log_path}")
        if "Simulation run completed" not in text:
            raise RuntimeError(f"engine exit 0 but no 'Simulation run completed' in {log_path}")
        daily = os.path.join(run_out, "DailyResults.csv")
        if not os.path.isfile(daily):
            raise RuntimeError(f"engine exit 0 but {daily} is missing")
        header, rows = read_daily(daily)
        expect = (date(eyear, 12, 31) - date(syear, 1, 1)).days + 1
        if len(rows) != expect:
            raise RuntimeError(f"DailyResults.csv has {len(rows)} rows, expected {expect} ({syear}-{eyear})")
        col = {h: i for i, h in enumerate(header)}
        need = {"runoff": "Runoff_All(mm/day)_Delineated_Average", "rain": "Rain(mm/day)_Delineated_Average",
                "snow": "Snow(mm/day)_Delineated_Average", "et": "ET(mm/day)_Delineated_Average"}
        for k, h in need.items():
            if h not in col:
                raise RuntimeError(f"DailyResults.csv lacks column {h}")
        # every column written or summed below must be numeric and finite
        vals = {}
        for k, h in need.items():
            try:
                vals[k] = [float(r[col[h]]) for r in rows]
            except (ValueError, IndexError):
                raise RuntimeError(f"DailyResults.csv column {h} has a missing or non-numeric value")
            if any(not math.isfinite(v) for v in vals[k]):
                raise RuntimeError(f"DailyResults.csv column {h} has non-finite values")
        runoff = vals["runoff"]
        for h in ("Year", "Day"):
            if h not in col:
                raise RuntimeError(f"DailyResults.csv lacks column {h}")
        dates = [date(int(r[col["Year"]]), 1, 1) + timedelta(days=int(r[col["Day"]]) - 1) for r in rows]
        # the rows must be EXACTLY syear-01-01 .. eyear-12-31, one per day, in order
        start = date(syear, 1, 1)
        for i, d in enumerate(dates):
            want = start + timedelta(days=i)
            if d != want:
                raise RuntimeError(f"DailyResults.csv row {i + 2} is {d.isoformat()}, "
                                   f"expected {want.isoformat()} (daily {syear}-{eyear})")
        area_m2 = outlet_area_m2(run_out, cell_m)
        area_km2 = args.area_km2 if args.area_km2 is not None else (area_m2 / 1e6 if area_m2 else None)
        qcsv = os.path.join(run_out, "velma_daily_runoff.csv")
        with open(qcsv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "runoff_mm_d"] + (["Q_sim_m3s"] if area_km2 else []))
            for d, q in zip(dates, runoff):
                w.writerow([d.isoformat(), q] + ([q * area_km2 * 1e6 / 1000.0 / SECONDS_PER_DAY]
                                                 if area_km2 else []))
        nyr = len(rows) / 365.25
        tot = {k: sum(v) / nyr for k, v in vals.items()}
        out.update(daily_results=daily, n_days=len(rows), runoff_csv=qcsv,
                   delineated_area_km2=(area_m2 / 1e6 if area_m2 else None), q_area_km2=area_km2,
                   mean_annual_mm={k: round(v, 1) for k, v in tot.items()}, **parse_nse(run_out))
        result["status"] = "success"
        code = 0
    except Refused as exc:
        log(msgs, f"REFUSED: {exc}")
        code = 2
    except ET.ParseError as exc:
        log(msgs, f"REFUSED: configuration xml cannot be parsed: {exc}")
        code = 2
    except (RuntimeError, OSError, ValueError) as exc:
        # before the engine starts code is 2 (input problem); after launch it is 3 or 4
        log(msgs, f"FAILED: {exc}")
        code = code if code in (3, 4) else 2
    finally:
        run_out = result["output"].get("run_output_dir")
        if run_out and os.path.isdir(run_out):
            with open(os.path.join(run_out, "velma_engine_summary.json"), "w") as f:
                json.dump(result, f, indent=2)
        print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
