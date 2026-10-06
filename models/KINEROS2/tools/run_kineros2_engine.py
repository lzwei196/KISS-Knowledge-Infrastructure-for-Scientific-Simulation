#!/usr/bin/env python3
"""run_kineros2_engine.py -- run the REAL KINEROS2 engine (USDA-ARS K2shell, Fortran) headless.

This is the KI's execution wrapper for the actual model.  (tools/run_kineros2.py is a different
thing: a Python SURROGATE kept for history -- never report its output as KINEROS2.)

What it does (copy-first, validate -> run -> validate):
  1. static checks of the parameter (.par) and rainfall (.pre) files with the same tag-lookup
     rules the engine uses (_k2lib.validate_parfile): GLOBAL/UNITS/CLEN present, every
     UPSTREAM/LATERAL id defined above its user, SAT available for pervious elements, unit
     plausibility of the rain file;
  2. copies the inputs into a fresh workspace under --out-dir, writes kin.fil (and the
     multiplier file), runs ``k2 -b kin.fil``;
  3. judges success from the OUTPUT TEXT -- the engine exits 0 on every error;
  4. parses the output (event summary, per-element hydrographs, sediment) and writes
     run_result.json + one hydrograph CSV per printed element.

Usage
  # official ARS sample, compared with the build log's numbers (exit 5 if they differ)
  run_kineros2_engine.py --example wg11 --out-dir OUT --check
  # any case
  run_kineros2_engine.py --par wg11.par --rain 4Aug80.pre --tfin 360 --dt 3 --courant \
      --mult ks=0.5,g=1.5 --out-dir OUT

Exit codes: 0 success | 2 input validation failed | 3 engine reported a failure |
            4 binary missing | 5 --check mismatch against the expected example values
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _k2lib as k2  # noqa: E402


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _event_balance(parsed: dict) -> dict:
    """Event water balance from the engine's own summary (+ ki_tools_common cross-check)."""
    es = parsed.get("event_summary") or {}
    get = lambda k: (es.get(k) or {}).get("depth", 0.0)
    rain = get("rainfall")
    losses = get("plane_infiltration") + get("channel_infiltration") + get("interception") \
        + get("pond_infiltration") + get("urban_infiltration")
    out = {"rainfall": rain, "losses_infiltration_interception": losses,
           "storage": get("storage"), "outflow": get("outflow"),
           "units": "in" if parsed.get("units") == "english" else "mm"}
    out["residual_pct_of_rain"] = (100.0 * (rain - losses - get("storage") - get("outflow")) / rain) if rain else None
    try:
        try:
            from ki_tools_common.validation import validate_water_balance
        except ImportError:
            sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
            from ki_tools_common.validation import validate_water_balance
        f = 25.4 if parsed.get("units") == "english" else 1.0
        wb = validate_water_balance(rain * f, losses * f, get("outflow") * f,
                                    delta_storage_mm=get("storage") * f, period_days=1)
        out["validate_water_balance"] = {"status": wb.get("status"), "residual_pct": wb.get("residual_pct"),
                                         "note": "single-event call; annual-rate diagnostics do not apply"}
    except Exception as e:  # shared library absent -> local closure above still stands
        out["validate_water_balance"] = {"status": "unavailable", "error": str(e)[:120]}
    return out


def _parse_mult(s: str | None) -> dict:
    if not s:
        return {}
    out = {}
    for item in s.split(","):
        k, _, v = item.partition("=")
        out[k.strip().lower()] = float(v)
    return out


def _check_example(name: str, parsed: dict, spec: dict, tol: float) -> list:
    exp = spec["expected"]
    es = parsed["event_summary"]
    got = {
        "rainfall_depth": (es.get("rainfall") or {}).get("depth"),
        "rainfall_volume": (es.get("rainfall") or {}).get("volume"),
        "plane_infiltration_depth": (es.get("plane_infiltration") or {}).get("depth"),
        "channel_infiltration_depth": (es.get("channel_infiltration") or {}).get("depth"),
        "interception_depth": (es.get("interception") or {}).get("depth"),
        "outflow_depth": (es.get("outflow") or {}).get("depth"),
        "outflow_volume": (es.get("outflow") or {}).get("volume"),
        "watershed_area": es.get("watershed_area"),
        "sediment_yield_t_per_ha": es.get("sediment_yield"),
    }
    rows = []
    if "outlet_element_id" in exp:
        el = k2.outlet_element(parsed, exp["outlet_element_id"]) or {}
        got["outlet_element_id"] = el.get("id")
        got["outlet_peak_discharge"] = el.get("peak_discharge")
        got["outlet_peak_time_min"] = el.get("peak_time_min")
    tab = {r["id"]: r for r in parsed.get("tabular_summary") or []}
    for key, want in exp.items():
        if key == "element_peak_flow":
            for eid, w in want.items():
                g = (tab.get(int(eid)) or {}).get("peak_rate")
                rows.append((f"element_{eid}_peak_rate", w, g))
            continue
        rows.append((key, want, got.get(key)))
    bad = []
    for key, want, g in rows:
        ok = g is not None and (abs(g - want) <= tol * max(abs(want), 1e-12))
        print(f"  {'OK ' if ok else 'BAD'} {name:5s} {key:28s} expected {want!s:>14}  got {g!s:>14}")
        if not ok:
            bad.append({"quantity": key, "expected": want, "got": g})
    return bad


def run_case(par, rain, out_dir: Path, tfin, dt_min, courant=False, sediment=False, mult=None,
             mult_file=None, title="KINEROS2 run", binary=None, keep_workspace=False,
             outlet_id=None, table=True, extra_files=()) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    binp = k2.resolve_binary(binary)
    par_tf = k2.read_tagged(par)
    rain_tf = k2.read_tagged(rain) if rain else None
    units = k2.par_units(par_tf)
    v = k2.validate_parfile(par_tf, rain_tf)
    if rain_tf is not None:
        v["warnings"] += k2.rain_units_check(rain_tf, units)
    if v["errors"]:
        raise ValueError("input validation failed:\n  " + "\n  ".join(v["errors"]))

    ws = Path(tempfile.mkdtemp(prefix="_k2ws_", dir=str(out_dir)))
    placed = k2.copy_case({"par": par, "rain": rain, "mult_file": mult_file}, ws)
    for f in extra_files:                       # e.g. INJECT data files referenced by FILE=
        k2.copy_case({"extra": f}, ws)
    mname = placed.get("mult_file")
    if mult:
        mname = "mult_k2.txt"
        k2.write_mult_file(ws / mname, mult)
    outname = Path(placed["par"]).stem + ".out"
    line = k2.write_kin_fil(ws / "kin.fil", placed["par"], placed.get("rain"), outname, title,
                            tfin, dt_min, courant, sediment, mname, table)
    t0 = time.time()
    r = k2.run_engine(ws, binp)
    wall = time.time() - t0
    out_path = ws / outname
    out_text = out_path.read_text(errors="replace") if out_path.is_file() else ""
    failures = k2.engine_failures(out_text, r["stdout"], r["stderr"])
    if r["rc"] != 0:
        failures.insert(0, f"engine exit status {r['rc']}")

    # collect: raw output + any PRINT=3 csv / diagnostics written by the engine
    shutil.copy2(ws / "kin.fil", out_dir / "kin.fil")
    if out_path.is_file():
        shutil.copy2(out_path, out_dir / outname)
    for f in ws.iterdir():
        if f.suffix.lower() in (".csv",) or f.name.lower() == "diagnostics.txt":
            shutil.copy2(f, out_dir / f.name)
    (out_dir / "engine_stdout.txt").write_text(r["stdout"] + ("\n[stderr]\n" + r["stderr"] if r["stderr"] else ""))

    parsed = k2.parse_output(out_text) if out_text else {}
    result = {
        "tool": "run_kineros2_engine.py",
        "engine": "REAL KINEROS2 (USDA-ARS K2shell Fortran) -- not the Python surrogate",
        "status": "success" if not failures else "failed",
        "failures": failures,
        "warnings_static": v["warnings"],
        "binary": {"path": str(binp), "sha256": _sha256(binp)},
        "engine_version_in_output": parsed.get("version"),
        "kin_fil": line,
        "command": f"cd <workspace> && {binp} -b kin.fil",
        "exit_status": r["rc"],
        "wallclock_s": round(wall, 3),
        "inputs": {role: {"source": str(Path(src).resolve()), "sha256": _sha256(Path(src))}
                   for role, src in (("par", par), ("rain", rain), ("mult_file", mult_file)) if src},
        "multipliers": parsed.get("multipliers"),
        "units": parsed.get("units"),
        "topology": {"elements": len(v["elements"]), "outlet": v["outlet"]},
        "output_file": str(out_dir / outname),
        "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    if parsed:
        result["event_summary"] = parsed.get("event_summary")
        result["event_summary_si"] = k2.to_si(parsed)
        result["event_water_balance"] = _event_balance(parsed)
        result["engine_warnings"] = parsed.get("warnings")
        result["tabular_summary"] = parsed.get("tabular_summary")
        outlet = k2.outlet_element(parsed, outlet_id or v["outlet"])
        if outlet_id is None and outlet is None:
            outlet = k2.outlet_element(parsed)
        hyd_files = []
        for el in parsed.get("elements") or []:
            if not el.get("hydrograph"):
                continue
            fn = out_dir / f"hydrograph_{el['type'].lower()}_{el['id']}.csv"
            with open(fn, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(el["hydrograph_columns"])
                w.writerows(el["hydrograph"])
            hyd_files.append(str(fn))
        result["hydrograph_files"] = hyd_files
        if outlet:
            result["outlet"] = {k: outlet.get(k) for k in ("type", "id", "peak_discharge", "peak_discharge_unit",
                                                          "peak_rate", "peak_rate_unit", "peak_time_min",
                                                          "peak_sediment_discharge", "peak_sediment_unit")}
            if outlet.get("peak_discharge") is not None:
                f = k2.FT3_TO_M3 if parsed.get("units") == "english" else 1.0
                result["outlet"]["peak_discharge_m3s"] = outlet["peak_discharge"] * f
            if not outlet.get("hydrograph"):
                result["warnings_static"].append(
                    f"outlet {outlet.get('type')} {outlet.get('id')} has no hydrograph table: set PRINT = 2 "
                    f"(or 3 with FILE=) in its block")
        elif v["outlet"] is not None:
            result["warnings_static"].append(
                f"outlet element {v['outlet']} printed no section (PRINT=0): only event totals are available; "
                f"set PRINT = 2 on the outlet to get the discharge hydrograph")
    if keep_workspace:
        result["workspace"] = str(ws)
    else:
        shutil.rmtree(ws, ignore_errors=True)
    k2.write_json(out_dir / "run_result.json", result)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--example", choices=["ex1", "wg11"], help="run an official ARS sample shipped in examples/ars_samples")
    ap.add_argument("--check", action="store_true", help="with --example: compare with expected_results.json (exit 5 on mismatch)")
    ap.add_argument("--par", help="parameter file (.par)")
    ap.add_argument("--rain", help="rainfall file (.pre); omit only for injection-only runs")
    ap.add_argument("--tfin", type=float, help="run length, minutes")
    ap.add_argument("--dt", type=float, help="output/computational time step, minutes")
    ap.add_argument("--courant", action="store_true", help="let the engine shorten the step (Courant)")
    ap.add_argument("--sediment", action="store_true", help="route erosion/sediment (needs sediment tags)")
    ap.add_argument("--mult", help="multipliers, e.g. ks=0.5,g=1.5 (keys: " + ",".join(k2.MULT_KEYS + k2.CHANNEL_MULT_KEYS) + ")")
    ap.add_argument("--mult-file", help="existing 7- or 13-line multiplier file")
    ap.add_argument("--title", default="KINEROS2 run")
    ap.add_argument("--outlet-id", type=int, help="element whose hydrograph is the headline (default: last element)")
    ap.add_argument("--extra-file", action="append", default=[], help="extra input to copy (e.g. injection data)")
    ap.add_argument("--binary", help="override the k2 executable")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--keep-workspace", action="store_true")
    a = ap.parse_args(argv)
    out_dir = Path(a.out_dir).resolve()

    spec = None
    if a.example:
        exp = json.loads((k2.EXAMPLES_DIR / "expected_results.json").read_text())
        spec = exp["examples"][a.example]
        mult_file = str(k2.EXAMPLES_DIR / spec["multfile"]) if spec["multfile"] else None
        kw = dict(par=str(k2.EXAMPLES_DIR / spec["parfile"]), rain=str(k2.EXAMPLES_DIR / spec["rainfile"]),
                  tfin=spec["tfin_min"], dt_min=spec["dt_min"], courant=spec["courant"],
                  sediment=spec["sediment"], mult=None, mult_file=mult_file, title=spec["title"])
    else:
        if not (a.par and a.tfin and a.dt):
            ap.error("--par, --tfin and --dt are required unless --example is given")
        if a.mult and a.mult_file:
            ap.error("give --mult or --mult-file, not both")
        kw = dict(par=a.par, rain=a.rain, tfin=a.tfin, dt_min=a.dt, courant=a.courant, sediment=a.sediment,
                  mult=_parse_mult(a.mult), mult_file=a.mult_file, title=a.title)
    try:
        res = run_case(out_dir=out_dir, binary=a.binary, keep_workspace=a.keep_workspace,
                       outlet_id=a.outlet_id, extra_files=a.extra_file, **kw)
    except k2.EngineError as e:
        print(f"ENGINE NOT RUNNABLE: {e}", file=sys.stderr)
        return 4
    except (ValueError, FileNotFoundError) as e:
        print(f"INPUT ERROR: {e}", file=sys.stderr)
        return 2

    print(f"status: {res['status']}   output: {res['output_file']}")
    for w in res.get("warnings_static") or []:
        print(f"  warning: {w}")
    if res["status"] != "success":
        for f in res["failures"]:
            print(f"  FAILURE: {f}", file=sys.stderr)
        print("  -> see diagnostics/triplets.yaml (dt_kineros2_027 explains why the engine exits 0 on errors)",
              file=sys.stderr)
        return 3
    es = res.get("event_summary") or {}
    u = "in" if res.get("units") == "english" else "mm"
    for key in ("rainfall", "plane_infiltration", "channel_infiltration", "interception", "storage", "outflow"):
        if key in es:
            print(f"  {key:22s} {es[key]['depth']:12.6g} {u}   {es[key]['volume']:14.6g} vol")
    if "sediment_yield" in es:
        print(f"  sediment yield         {es['sediment_yield']} {es.get('sediment_yield_unit')}")
    if res.get("outlet"):
        o = res["outlet"]
        print(f"  outlet {o['type']} {o['id']}: peak {o.get('peak_discharge')} {o.get('peak_discharge_unit')} "
              f"at {o.get('peak_time_min')} min")
    if spec is not None and a.check:
        exp = json.loads((k2.EXAMPLES_DIR / "expected_results.json").read_text())
        parsed = k2.parse_output(Path(res["output_file"]).read_text())
        bad = _check_example(a.example, parsed, spec, exp["tolerance"]["rel"])
        res["example_check"] = {"example": a.example, "tolerance_rel": exp["tolerance"]["rel"],
                                "mismatches": bad, "reproduced": not bad}
        k2.write_json(out_dir / "run_result.json", res)
        if bad:
            print(f"EXAMPLE {a.example}: {len(bad)} value(s) differ from the build log", file=sys.stderr)
            return 5
        print(f"EXAMPLE {a.example}: reproduced (all values within rel {exp['tolerance']['rel']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
