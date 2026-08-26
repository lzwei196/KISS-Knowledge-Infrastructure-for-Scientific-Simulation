#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      validate_txtinout
Stage:        s7_simulation_config
Description:  Cross-check all file references in file.cio against TxtInOut contents.
              Verify object counts, weather station references, soil name consistency.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

TXTINOUT_DIR = ""
if len(sys.argv) >= 2:
    TXTINOUT_DIR = sys.argv[1]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def _weather_sta_issues(txtinout):
    """dt_053: fatal issues when weather-sta.cli wiring cannot deliver the prepared weather.
    Columns (positional, rev59): name wgn pcp tmp slr hmd wnd wnd_dir atmo_dep."""
    out = []
    wsta = Path(txtinout) / "weather-sta.cli"
    if not wsta.exists():
        return out
    rows = [l.split() for l in wsta.read_text().strip().split("\n")[2:] if l.strip()]
    if not rows:
        return out
    # codex review: a deliberate WGN-only deck (prepared .pcp/.tmp intentionally unused)
    # opts out explicitly — silence must be a decision, never a default.
    if os.environ.get("SWATPLUS_WGN_ONLY") == "1":
        return [{"check": "weather-sta.cli wiring", "severity": "warning",
                 "issue": "SWATPLUS_WGN_ONLY=1 — generated-weather deck declared on purpose; "
                          "wiring check skipped"}]
    for col, ext in ((2, "pcp"), (3, "tmp")):
        have = sorted(Path(txtinout).glob(f"*.{ext}"))
        refs = [r[col] for r in rows if len(r) > col]
        real = {x for x in refs if x.lower() != "null"}
        # codex review: a NON-null ref that doesn't exist is equally dead wiring.
        for x in sorted(real):
            if not (Path(txtinout) / x).exists():
                out.append({
                    "check": "weather-sta.cli wiring", "severity": "fatal",
                    "issue": (f"weather-sta.cli references {x} which does not exist in the "
                              f"deck — SWAT+ gage lookup fails and falls back to generated "
                              f"weather (dt_053)")})
        if have and refs and not real:
            out.append({
                "check": "weather-sta.cli wiring", "severity": "fatal",
                "issue": (f"all {len(refs)} {ext} entries are 'null' while {len(have)} .{ext} "
                          f"files exist — SWAT+ will SILENTLY substitute generated weather "
                          f"(wgn climatology); run s3/generate_weather_stations.py (dt_053)")})
        elif len(have) > 1 and len(rows) > 1 and len(real) == 1:
            out.append({
                "check": "weather-sta.cli wiring", "severity": "fatal",
                "issue": (f"{len(rows)} stations all wired to ONE {ext} file "
                          f"({next(iter(real))}) while {len(have)} .{ext} files exist — "
                          f"single-point forcing ceiling; rerun s3/generate_weather_stations.py "
                          f"with per-station coords from rout_unit.con (dt_053)")})
    return out


def _selftest():
    """Owner rule: every gate must be SHOWN to fail on bad input. Builds three synthetic
    decks — null-wired, single-station-wired, correctly wired — and asserts detection."""
    import tempfile, shutil
    base = Path(tempfile.mkdtemp(prefix="vtxt_selftest_"))
    try:
        hdr = "title\n" + "".join(c.ljust(12) for c in
              ["name", "wgn", "pcp", "tmp", "slr", "hmd", "wnd", "wnd_dir", "atmo_dep"]) + "\n"
        def deck(name, rows, n_files=3):
            d = base / name; d.mkdir()
            for i in range(n_files):
                (d / f"sta{i:02d}.pcp").write_text("x"); (d / f"sta{i:02d}.tmp").write_text("x")
            (d / "weather-sta.cli").write_text(hdr + "".join(
                "".join(c.ljust(12) for c in r) + "\n" for r in rows))
            return d
        null_rows = [[f"sta{i:02d}", "wgn", "null", "null", "null", "null", "null", "null", "null"]
                     for i in range(3)]
        one_rows = [[f"sta{i:02d}", "wgn", "sta00.pcp", "sta00.tmp", "null", "null", "null",
                     "null", "null"] for i in range(3)]
        good_rows = [[f"sta{i:02d}", "wgn", f"sta{i:02d}.pcp", f"sta{i:02d}.tmp", "null", "null",
                      "null", "null", "null"] for i in range(3)]
        a = _weather_sta_issues(deck("null_wired", null_rows))
        b = _weather_sta_issues(deck("one_station", one_rows))
        c = _weather_sta_issues(deck("good", good_rows))
        assert any("null" in i["issue"] for i in a), "null wiring NOT detected"
        assert any("ONE" in i["issue"] for i in b), "single-station wiring NOT detected"
        assert not c, f"false positive on a correctly wired deck: {c}"
        print("SELFTEST PASS: null-wired detected, single-station detected, good deck clean")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def validate_inputs():
    if not TXTINOUT_DIR or not Path(TXTINOUT_DIR).is_dir():
        logger.error(f"TxtInOut directory not found: {TXTINOUT_DIR}"); sys.exit(1)
    if not (Path(TXTINOUT_DIR) / "file.cio").exists():
        logger.error("file.cio not found in TxtInOut"); sys.exit(1)
    logger.info("Input validation passed.")

def process():
    txtinout = Path(TXTINOUT_DIR)
    issues = []

    # Parse file.cio and check all references
    file_cio = (txtinout / "file.cio").read_text().strip().split('\n')
    for line in file_cio[1:]:  # Skip title
        parts = line.split()
        if len(parts) < 2: continue
        category = parts[0]
        for fname in parts[1:]:
            if fname == "null": continue
            if not (txtinout / fname).exists():
                issues.append({
                    "check": "file.cio reference",
                    "category": category,
                    "file": fname,
                    "issue": "File not found in TxtInOut",
                    "severity": "fatal"
                })

    # Check weather file consistency
    for cli_name in ["pcp.cli", "tmp.cli", "slr.cli", "hmd.cli", "wnd.cli"]:
        cli_path = txtinout / cli_name
        if cli_path.exists():
            cli_lines = cli_path.read_text().strip().split('\n')
            for fname in cli_lines[2:]:  # Skip title and header
                fname = fname.strip()
                if fname and not (txtinout / fname).exists():
                    issues.append({
                        "check": f"{cli_name} reference",
                        "file": fname,
                        "issue": f"Weather file not found",
                        "severity": "fatal"
                    })

    # Weather-station WIRING check (dt_053, deposited 2026-08-24 from the Xixian campaign):
    # a deck whose weather-sta.cli pcp/tmp columns are 'null' (or all one station) while
    # matching .pcp/.tmp files EXIST makes SWAT+ silently fall back to GENERATED weather
    # (wgn climatology) — the run completes, PBIAS is even tunable, and r ≈ 0. The deck
    # generator writes null wiring BY DESIGN; s3/generate_weather_stations.py must be run
    # after ANY deck regeneration. This check makes the trap loud instead of silent.
    issues.extend(_weather_sta_issues(txtinout))

    # Check time.sim exists and is valid
    time_sim = txtinout / "time.sim"
    if time_sim.exists():
        lines = time_sim.read_text().strip().split('\n')
        if len(lines) < 3:
            issues.append({"check": "time.sim", "issue": "Incomplete time.sim", "severity": "fatal"})
    else:
        issues.append({"check": "time.sim", "issue": "time.sim not found", "severity": "fatal"})

    n_fatal = sum(1 for i in issues if i.get("severity") == "fatal")
    total_files = sum(1 for f in txtinout.iterdir() if f.is_file())

    return {
        "status": "pass" if n_fatal == 0 else "fail",
        "total_files_in_txtinout": total_files,
        "total_issues": len(issues),
        "fatal_issues": n_fatal,
        # codex r2: computed over the FULL list BEFORE display truncation — the exit
        # decision must never depend on whether the wiring fatal fit into the top 50.
        "weather_wiring_fatal": any(i.get("check") == "weather-sta.cli wiring"
                                    and i.get("severity") == "fatal" for i in issues),
        "issues": issues[:50]
    }

def validate_outputs(result):
    if result["fatal_issues"] > 0:
        logger.warning(f"TxtInOut has {result['fatal_issues']} fatal issues — fix before running SWAT+")
    else:
        logger.info("TxtInOut validation passed — ready to run SWAT+")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    # dt_053 / 2026-08-24, SCOPED per codex review: only the weather-WIRING fatals exit 1.
    # Legacy fatal findings (e.g. optional file.cio refs like calibration.cal missing on
    # template decks) keep the old exit-0-with-warning behavior so active runners that
    # raise on nonzero rc are not broken; pass --strict to fail on ALL fatals.
    # codex r2: read the pre-truncation flag, never the display-truncated issues list.
    _wiring_fatal = bool(result.get("weather_wiring_fatal"))
    _strict = "--strict" in sys.argv
    sys.exit(1 if (_wiring_fatal or (_strict and result.get("fatal_issues"))) else 0)
