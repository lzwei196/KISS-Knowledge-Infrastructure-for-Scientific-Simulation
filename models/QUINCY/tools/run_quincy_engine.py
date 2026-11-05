#!/usr/bin/env python3
"""Run the REAL QUINCY engine (qs.bin, public release qs-2026.04-public) headless.

This is the KI's real-model runner. (tools/run_quincy.py is a Python SURROGATE, not QUINCY.)

Modes
  test_canopy | test_radiation   built-in engine self-tests; no forcing. The namelist is
                                 exactly the one in BUILD_LOG.md (`&base_ctl quincy_model_name=...`).
                                 This is the KI's REFERENCE CHECK (the public release ships no
                                 official site example): by default the outputs are compared
                                 byte for byte with the build-time run
                                 <engine>/run_builtin_<mode> (test_canopy: fort.10-17 response
                                 tables + quincy_standalone.log + stdout.log; test_radiation:
                                 quincy_standalone.log + stdout.log). The reference must exist
                                 and hold that whole set, and the run must produce exactly the
                                 same set of comparable files; any missing, extra or different
                                 file fails (exit 4, "reproduced": false). --reference_dir ''
                                 skips the comparison: the JSON then says "reproduced": false
                                 (an install check only, NOT a reproduction).
  land | plant | canopy          site run driven by climate.dat from tools/build_quincy_climate.py.

Site runs use QUINCY's transient protocol: the first --spinup_cycle_years of climate.dat are
cycled for --spinup_years (spin-up from bare ground, yearly *_spinup_yearly.txt output), then
the file is rewound and all forcing years are simulated with --output_interval output
(*_daily.txt etc.). The namelist is a copy of templates/qs.namelist.template with single
values replaced (site_config.json, climate_meta.json and --nml overrides).

Engine success = exit code 0 AND "End QUINCY model" printed AND empty quincy_standalone.err
AND no engine consistency warning ("... Please check!" in the log; e.g. forcing years that do
not match the namelist, which the text-output build only LOGS) AND every expected output file
present with the expected number of rows. Expected files = the key files that the chosen
--output_set writes (mo_qs_output_txt_util.f90 init_output_txt_config); expected rows per
simulated year = 365 // interval days (daily 365, weekly 52, monthly 12, yearly 1: the engine
counts output days within each 365-day year, so monthly output is 30-day blocks, 12 per year).
Before the run, climate.dat must have exactly the rows and years of climate_meta.json, and every
namelist value set must read back from qs.namelist. With --param_list, a PFT parameter group
(lctlib_pft<N>_nml) must match the run's PFT (the engine applies only that PFT's group); the old
and new values the engine applied (parameter_sensi_param_values.txt and
parameter_sensi_lctlib_values.txt) are recorded in run_manifest.json "parameters_applied".

Exit codes: 0 success; 2 bad arguments/inputs, incl. a missing or incomplete --reference_dir
(engine not started); 3 engine failed (exit code, missing end message, or error file); 4 engine
finished but outputs are missing, short, or differ from the reference.
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _quincy_common import (ENGINE_BIN, ENGINE_ROOT, LCTLIB, TEMPLATE_NML, engine_status,  # noqa: E402
                            finite, fmt_nml, get_nml, set_nml)

INTERVAL_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "yearly": 365}
KEY_FILES = ["vegflux_c", "vegflux_h2o", "vegflux_energy", "veg_diagnostics", "soilflux_cdc13dc14",
             "vegpool_c", "soilpool_org", "soil_physics"]
# which key files each engine output set writes (mo_qs_output_txt_util.f90 init_output_txt_config;
# checked with 2-year runs 2026-10-07)
SET_KEY_FILES = {
    "all": KEY_FILES, "basic": KEY_FILES,
    "minimal": ["vegflux_c", "vegflux_h2o", "vegflux_energy", "veg_diagnostics", "vegpool_c", "soilpool_org"],
    "plant": ["vegflux_c", "vegflux_h2o", "vegflux_energy", "veg_diagnostics", "vegpool_c", "soilpool_org",
              "soil_physics"],
    "canopy": ["vegflux_c", "vegflux_h2o", "vegflux_energy"],
    "soil": ["soilflux_cdc13dc14", "soilpool_org"],
}
# build-time self-test runs (BUILD_LOG.md) and the files each must hold
SELFTEST_REFERENCE = {m: ENGINE_ROOT / f"run_builtin_{m}" for m in ("test_canopy", "test_radiation")}
SELFTEST_FILES = {"test_canopy": [f"fort.{i}" for i in range(10, 18)] + ["quincy_standalone.log", "stdout.log"],
                  "test_radiation": ["quincy_standalone.log", "stdout.log"]}
WALL_CLOCK_FILES = ("time.txt", "sim_runtime_estimate.txt")


def comparable(d: Path) -> set[str]:
    """Engine outputs + engine log/stdout; time.txt and the runtime estimate hold wall-clock times."""
    return {p.name for p in d.iterdir() if p.is_file()
            and (p.name.startswith("fort.") or p.name.endswith((".txt", ".log")))
            and p.name not in WALL_CLOCK_FILES}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def n_rows(p: Path) -> int:
    with p.open() as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def parse_override(text):
    try:
        lhs, val = text.split("=", 1)
        group, key = lhs.strip().split(".", 1)
    except ValueError:
        raise ValueError(f"--nml {text!r}: use group.key=value, e.g. lnd_q_syl_nml.flag_stand_harvest=.TRUE.")
    return group.strip(), key.strip(), val.strip()


def build_site_namelist(a, meta, site):
    nml = TEMPLATE_NML.read_text()
    y0, y1 = int(meta["start_year"]), int(meta["end_year"])
    n_years = y1 - y0 + 1
    cyc = a.spinup_cycle_years or n_years
    if not 1 <= cyc <= n_years:
        raise ValueError(f"--spinup_cycle_years {cyc} must be within the {n_years} forcing years")
    if a.spinup_years < 0:
        raise ValueError("--spinup_years must be >= 0")
    values = {
        "base_ctl": {"quincy_model_name": a.mode, "dtime_step_length_sec": float(meta["dtime_s"]),
                     "output_interval_pool": a.output_interval, "output_interval_flux": a.output_interval,
                     "output_start_first_day_year": 1, "output_end_last_day_year": n_years,
                     "forcing_file_start_yr": y0, "forcing_file_last_yr": y1,
                     "output_txt_file_set": a.output_set},
        "jsb_forcing_ctl": {"is_daily_forcing": bool(meta["is_daily_forcing"]),
                            "read_precipitation": bool(meta["read_precipitation"]),
                            "flag_forcing_with_snow_data": False,
                            "flag_read_dC13": False, "flag_read_DC14": False,
                            "simulation_length_unit": "y", "simulation_length_number": n_years},
    }
    if a.spinup_years > 0:
        values["jsb_forcing_ctl"].update({"forcing_mode": "transient", "transient_spinup_start_year": y0,
                                          "transient_spinup_end_year": y0 + cyc - 1,
                                          "transient_spinup_years": a.spinup_years,
                                          "transient_simulation_start_year": y0})
    else:
        values["jsb_forcing_ctl"]["forcing_mode"] = "static"
    if a.param_list:
        values["base_ctl"].update({"set_parameter_values_from_file": True,
                                   "set_parameter_values_proportional": True})
    for group, kv in (site or {}).get("nml", {}).items():
        values.setdefault(group, {}).update(kv)
    for group, kv in values.items():
        for k, v in kv.items():
            nml = set_nml(nml, group, k, v)
    for text in a.nml or []:
        g, k, v = parse_override(text)
        values.setdefault(g, {})[k] = v
        nml = set_nml(nml, g, k, v)
    check_namelist(nml, values)
    return nml, n_years


def check_namelist(nml, values):
    """Every group once, every value we set reads back (Fortran reads only the FIRST copy of a group)."""
    for group, kv in values.items():
        n = len(re.findall(rf"(?im)^&{re.escape(group)}[ \t]*$", nml))
        if n != 1:
            raise ValueError(f"namelist group &{group} appears {n} times")
        for k, v in kv.items():
            if get_nml(nml, group, k) != fmt_nml(v):
                raise ValueError(f"namelist {group}.{k} reads back {get_nml(nml, group, k)!r}, wanted {fmt_nml(v)!r}")


def check_param_list(path: Path, nml: str):
    """A PFT group lctlib_pft<N>_nml only acts when N is the run's PFT; refuse a mismatch."""
    text = path.read_text()
    groups = [g.lower() for g in re.findall(r"(?im)^\s*&(\w+)", text)]
    pft = get_nml(nml, "lnd_veg_nml", "plant_functional_type_id") if nml else None
    for g in groups:
        m = re.fullmatch(r"lctlib_pft(\d+)_nml", g)
        if m and (pft is None or int(m.group(1)) != int(pft)):
            raise ValueError(f"--param_list group &{g} targets PFT {m.group(1)} but the run's PFT is {pft}: "
                             "the engine would silently ignore it")


def read_sensi(p: Path):
    """Rows 'name old new' of an engine parameter_sensi_*_values.txt where the value changed."""
    rows = [ln.split() for ln in p.read_text().splitlines()[1:]]
    return [r for r in rows if len(r) == 3 and r[1] != r[2]]


def check_climate(path: Path, meta):
    """climate.dat must hold exactly the rows and years climate_meta.json describes: the engine
    reads it line by line and silently REWINDS at end of file (only a log note)."""
    with path.open() as fh:
        lines = fh.read().splitlines()[2:]
    if len(lines) != int(meta["n_rows"]):
        raise ValueError(f"{path}: {len(lines)} data rows, climate_meta.json says {meta['n_rows']}")
    y_first, y_last = int(lines[0].split()[0]), int(lines[-1].split()[0])
    if (y_first, y_last) != (int(meta["start_year"]), int(meta["end_year"])):
        raise ValueError(f"{path}: years {y_first}-{y_last}, meta says {meta['start_year']}-{meta['end_year']}")


def expected_files(run_dir: Path, interval: str, n_years: int, spinup_years: int, output_set: str = "basic"):
    """Return problems with the output files (empty list = complete)."""
    probs = []
    want = n_years * (365 // INTERVAL_DAYS[interval])
    for stem in SET_KEY_FILES[output_set]:
        p = run_dir / f"{stem}_{interval}.txt"
        if not p.exists():
            probs.append(f"missing {p.name}")
        elif n_rows(p) < want:
            probs.append(f"{p.name}: {n_rows(p)} rows, expected {want}")
        if spinup_years > 0:
            s = run_dir / f"{stem}_spinup_yearly.txt"
            if s.exists() and n_rows(s) < spinup_years:
                probs.append(f"{s.name}: {n_rows(s)} rows, expected {spinup_years}")
    return probs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=["land", "plant", "canopy", "test_canopy", "test_radiation"])
    ap.add_argument("--run_dir", required=True, help="new or empty directory the engine runs in")
    ap.add_argument("--climate_dir", help="dir with climate.dat + climate_meta.json (site modes)")
    ap.add_argument("--site_config", help="site_config.json from build_quincy_site_config.py (site modes)")
    ap.add_argument("--spinup_years", type=int, default=500,
                    help="transient spin-up length in years (0 = static run, no spin-up; default 500)")
    ap.add_argument("--spinup_cycle_years", type=int,
                    help="number of leading forcing years cycled during spin-up (default: all)")
    ap.add_argument("--output_interval", default="daily", choices=sorted(INTERVAL_DAYS))
    ap.add_argument("--output_set", default="basic", choices=["basic", "minimal", "plant", "canopy", "soil", "all"])
    ap.add_argument("--param_list", help="parameter_slm_run.list from edit_quincy_parameters.py")
    ap.add_argument("--nml", action="append", help="extra namelist value group.key=value (repeatable)")
    ap.add_argument("--reference_dir", default=None,
                    help="directory whose outputs must match byte for byte (test modes default: the "
                         "build-time run <engine>/run_builtin_<mode>; '' = skip, NOT a reproduction)")
    ap.add_argument("--binary", default=str(ENGINE_BIN))
    ap.add_argument("--timeout_s", type=float, default=6 * 3600)
    a = ap.parse_args(argv)

    run_dir, binary = Path(a.run_dir), Path(a.binary)
    ref, made = None, False
    try:
        finite(a.timeout_s, "timeout_s", 1)
        if a.reference_dir is None and a.mode in SELFTEST_REFERENCE:
            ref = SELFTEST_REFERENCE[a.mode]
        elif a.reference_dir:
            ref = Path(a.reference_dir)
        if ref is not None:
            if not ref.is_dir():
                raise ValueError(f"reference_dir {ref} does not exist (use --reference_dir '' to skip the "
                                 f"comparison; that is NOT a reproduction)")
            have = comparable(ref)
            need = SELFTEST_FILES.get(a.mode, [])
            lack = [n for n in need if n not in have]
            if lack or not have:
                raise ValueError(f"reference_dir {ref} is incomplete: lacks {lack or 'any comparable output'}")
        if not binary.is_file():
            raise ValueError(f"engine binary not found: {binary}")
        if run_dir.exists() and any(run_dir.iterdir()):
            raise ValueError(f"run_dir {run_dir} is not empty (old outputs could pass as new ones)")
        existed = run_dir.exists()
        run_dir.mkdir(parents=True, exist_ok=True)
        made = True
        shutil.copy2(LCTLIB, run_dir / LCTLIB.name)
        meta, n_years = {}, 0
        if a.mode.startswith("test_"):
            nml = f"&base_ctl\n  quincy_model_name = '{a.mode}'\n/\n"
        else:
            if not a.climate_dir or not a.site_config:
                raise ValueError("site modes need --climate_dir and --site_config")
            cdir = Path(a.climate_dir)
            meta = json.loads((cdir / "climate_meta.json").read_text())
            site = json.loads(Path(a.site_config).read_text())
            if meta.get("lat") is not None and abs(float(meta["lat"]) - float(site["lat"])) > 0.5:
                raise ValueError(f"climate lat {meta['lat']} and site lat {site['lat']} disagree")
            check_climate(cdir / "climate.dat", meta)
            nml, n_years = build_site_namelist(a, meta, site)
            shutil.copy2(cdir / "climate.dat", run_dir / "climate.dat")
        if a.param_list:
            check_param_list(Path(a.param_list), nml if not a.mode.startswith("test_") else "")
            shutil.copy2(a.param_list, run_dir / "parameter_slm_run.list")
        (run_dir / "qs.namelist").write_text(nml)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as e:
        if made:   # run_dir was new or empty: remove what this call wrote, so a retry is not refused
            for q in run_dir.iterdir():
                shutil.rmtree(q) if q.is_dir() and not q.is_symlink() else q.unlink()
            if not existed:
                run_dir.rmdir()
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    t0 = time.time()
    try:
        cp = subprocess.run([str(binary)], cwd=run_dir, capture_output=True, text=True, timeout=a.timeout_s)
        rc, out = cp.returncode, cp.stdout + cp.stderr
    except subprocess.TimeoutExpired as e:
        rc, out = -9, (e.stdout or b"").decode(errors="replace") + "\nTIMEOUT"
    (run_dir / "stdout.log").write_text(out)
    fails = engine_status(run_dir, rc, out)
    manifest = {"mode": a.mode, "binary": str(binary.resolve()), "binary_sha256": sha256(binary),
                "run_dir": str(run_dir.resolve()), "returncode": rc, "runtime_s": round(time.time() - t0, 1),
                "engine_failures": fails, "namelist": nml}
    if not a.mode.startswith("test_"):
        manifest.update({"forcing": meta, "site_config": a.site_config, "spinup_years": a.spinup_years,
                         "output_interval": a.output_interval, "sim_years": n_years,
                         "first_output_year": meta.get("start_year"),
                         "pft_id": get_nml(nml, "lnd_veg_nml", "plant_functional_type_id")})
    code = 0
    if fails:
        code = 3
    else:
        probs = []
        if a.mode == "test_canopy" and not (run_dir / "fort.10").exists():
            probs.append("test_canopy wrote no fort.10 response table")
        if a.mode in ("land", "plant", "canopy"):
            probs = expected_files(run_dir, a.output_interval, n_years, a.spinup_years, a.output_set)
        if a.param_list:
            applied = []
            pft = manifest.get("pft_id")
            names = ["parameter_sensi_param_values.txt"]
            if pft is not None and 1 <= int(pft) <= 8:   # the engine has PFT parameter groups for PFT 1-8 only
                names.append("parameter_sensi_lctlib_values.txt")
            for name in names:
                pv = run_dir / name
                if not pv.exists():
                    probs.append(f"parameter list given but engine wrote no {name}")
                else:
                    applied += read_sensi(pv)
            manifest["parameters_applied"] = applied
        if ref is not None:
            in_ref, in_run = comparable(ref), comparable(run_dir)
            names = sorted(in_ref | in_run)
            only_ref, only_run = sorted(in_ref - in_run), sorted(in_run - in_ref)
            diff = [n for n in sorted(in_ref & in_run) if not filecmp.cmp(ref / n, run_dir / n, shallow=False)]
            identical = len(in_ref & in_run) - len(diff)
            manifest["reference_compare"] = {
                "reference_dir": str(ref.resolve()), "files": names, "files_compared": len(names),
                "files_identical": identical, "missing_in_run": only_ref, "extra_in_run": only_run,
                "differ": diff}
            probs += [f"missing in run (present in reference): {n}" for n in only_ref]
            probs += [f"extra output not in reference: {n}" for n in only_run]
            probs += [f"differs from reference: {n}" for n in diff]
        manifest["output_problems"] = probs
        code = 4 if probs else 0
    if ref is not None:
        manifest["reproduced"] = code == 0 and bool(manifest.get("reference_compare"))
    elif a.mode in SELFTEST_REFERENCE:
        manifest["reproduced"] = False
        manifest["reference_note"] = "--reference_dir '' given: install check only, NOT a reproduction"
    manifest["status"] = {0: "ok", 3: "engine_failed", 4: "outputs_incomplete"}[code]
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
    rc_ = manifest.get("reference_compare") or {}
    print(json.dumps({k: manifest[k] for k in ("status", "mode", "returncode", "runtime_s", "run_dir")}
                     | ({"reproduced": manifest["reproduced"]} if "reproduced" in manifest else {})
                     | ({"reference_dir": rc_["reference_dir"], "files_compared": rc_["files_compared"],
                         "files_identical": rc_["files_identical"]} if rc_ else {})
                     | ({"reference_note": manifest["reference_note"]} if "reference_note" in manifest else {})
                     | ({"problems": fails or manifest.get("output_problems")} if code else {})))
    return code


if __name__ == "__main__":
    sys.exit(main())
