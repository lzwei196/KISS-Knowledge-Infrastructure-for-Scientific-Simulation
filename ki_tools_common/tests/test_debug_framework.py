"""
test_debug_framework.py — Edge case tests for the universal debug triage.

Every test case comes from a REAL bug found during KDT testing across 70+ models.
If the framework misses any of these, it needs fixing.
"""

import sys
import os
import tempfile
import json

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from debug_framework import (
    run_triage, check_value_range, check_constant_or_fill,
    check_level0_existence, check_level2_execution, check_level3_outputs,
    check_level4_domain, Severity, TriageReport,
    check_npz_cache_consistency, check_domain_consistency,
    RuntimeMonitor,
    check_level5_regression, check_level6_agent_audit,
)


# ======================================================================
# Helper
# ======================================================================
def assert_catches(report, expected_name_substring, expected_severity=None):
    """Assert that the report contains a check matching the substring."""
    matches = [c for c in report.checks if expected_name_substring in c.name]
    assert matches, (
        f"Expected check containing '{expected_name_substring}' but found: "
        f"{[c.name for c in report.checks]}"
    )
    if expected_severity:
        assert any(c.severity == expected_severity for c in matches), (
            f"Expected severity {expected_severity} for '{expected_name_substring}' "
            f"but got {[c.severity for c in matches]}"
        )
    return matches


passed = 0
failed = 0
errors = []


def run_test(name, fn):
    global passed, failed, errors
    try:
        fn()
        passed += 1
        print(f"  PASS: {name}")
    except Exception as e:
        failed += 1
        errors.append((name, str(e)))
        print(f"  FAIL: {name} — {e}")


# ======================================================================
# Level 0: Existence checks
# ======================================================================
print("\n=== Level 0: Existence ===")


def test_missing_run_dir():
    report = run_triage("test", "hydrology", "/nonexistent/path", levels=[0])
    assert report.has_blockers()
    assert_catches(report, "run_dir", Severity.BLOCK)

run_test("Missing run directory → BLOCK", test_missing_run_dir)


def test_missing_binary():
    with tempfile.TemporaryDirectory() as td:
        report = run_triage("test", "hydrology", td, levels=[0],
                           binary_path="/nonexistent/binary")
        assert_catches(report, "binary", Severity.BLOCK)

run_test("Missing binary → BLOCK", test_missing_binary)


def test_missing_required_file():
    with tempfile.TemporaryDirectory() as td:
        report = run_triage("test", "hydrology", td, levels=[0],
                           required_files=["namelist.hrldas", "hydro.namelist"])
        assert report.has_blockers()

run_test("Missing required files → BLOCK", test_missing_required_file)


# ======================================================================
# Level 1: Input range checks — REAL BUGS
# ======================================================================
print("\n=== Level 1: Input Ranges (Real Bugs) ===")


def test_lwdown_106k():
    """WRF-Hydro LWDOWN=106,000 W/m² from mixed cache units. Cost: 4 hours."""
    report = run_triage("WRF-Hydro", "hydrology", "/tmp", levels=[1],
                       input_values={"lw_radiation_W": np.array([106000, 105000, 107000])})
    assert report.has_failures()
    assert_catches(report, "range_lw_radiation", Severity.FAIL)

run_test("WRF-Hydro LWDOWN=106K (4h bug)", test_lwdown_106k)


def test_cmfd_precip_kgm2s():
    """CMFD precip in kg/m²/s (not mm/day) — the #1 system-wide bug. 86400x off."""
    report = run_triage("VIC", "hydrology", "/tmp", levels=[1],
                       input_values={"precipitation_mm": np.array([0.00005, 0.0001, 0.00008])})
    # Mean ~0.00008 — should trigger the mean-based unit trap
    assert report.has_failures()
    assert_catches(report, "unit_trap_precipitation", Severity.FAIL)

run_test("CMFD precip in kg/m²/s (system-wide bug)", test_cmfd_precip_kgm2s)


def test_hgt_m_nodata():
    """WRF-Hydro HGT_M=0 from DEM nodata fill. Cost: 2 hours."""
    elev = np.zeros(1000)  # All zeros = nodata fill
    report = run_triage("WRF-Hydro", "hydrology", "/tmp", levels=[1],
                       input_values={"elevation_m": elev})
    assert_catches(report, "constant_elevation", Severity.FAIL)

run_test("WRF-Hydro HGT_M=0 nodata (2h bug)", test_hgt_m_nodata)


def test_temperature_celsius_not_kelvin():
    """Temperature in Celsius when Kelvin expected — common across all models."""
    report = run_triage("any", "hydrology", "/tmp", levels=[1],
                       input_values={"temperature_K": np.array([20.0, 25.0, 15.0, 30.0])})
    assert report.has_failures()
    assert_catches(report, "range_temperature", Severity.FAIL)

run_test("Temperature in °C not K", test_temperature_celsius_not_kelvin)


def test_wofost_irrad_wrong_unit():
    """WOFOST IRRAD in J/m²/d instead of kJ/m²/d — silent zero yield."""
    # J/m2/d values are ~15,000,000; kJ/m2/d should be ~15,000
    report = run_triage("WOFOST", "crop", "/tmp", levels=[1],
                       input_values={"sw_radiation_W": np.array([15000000, 18000000, 12000000])})
    assert report.has_failures()
    assert_catches(report, "range_sw_radiation", Severity.FAIL)

run_test("WOFOST IRRAD J/m²/d not kJ (zero yield bug)", test_wofost_irrad_wrong_unit)


def test_porosity_percent_not_fraction():
    """Porosity as 35% instead of 0.35 — groundwater models."""
    report = run_triage("MODFLOW6", "groundwater", "/tmp", levels=[1],
                       input_values={"porosity_frac": np.array([35.0, 40.0, 30.0])})
    assert report.has_failures()

run_test("Porosity as % not fraction", test_porosity_percent_not_fraction)


def test_fill_value_dominated():
    """Array dominated by -9999 fill values — data extraction failure."""
    data = np.full(1000, -9999.0)
    data[:10] = np.random.uniform(0, 10, 10)
    result = check_constant_or_fill("precip", data)
    assert result.severity == Severity.FAIL

run_test("Fill-value dominated array (-9999)", test_fill_value_dominated)


# ======================================================================
# Level 2: Execution checks
# ======================================================================
print("\n=== Level 2: Execution ===")


def test_sigfpe_crash():
    """SIGFPE (exit 136) — the 6-hour misdiagnosis. Should say 'check forcing FIRST'."""
    with tempfile.TemporaryDirectory() as td:
        results = check_level2_execution(td, exit_code=136)
        assert any("SIGFPE" in r.message or "136" in r.message for r in results)
        assert any("forcing" in r.fix_hint.lower() for r in results)

run_test("SIGFPE crash → check forcing first (6h bug)", test_sigfpe_crash)


def test_oom_kill():
    """OOM kill (exit 137) — reduce domain."""
    with tempfile.TemporaryDirectory() as td:
        results = check_level2_execution(td, exit_code=137)
        assert any("memory" in r.message.lower() for r in results)

run_test("OOM kill (exit 137)", test_oom_kill)


def test_log_convergence_failure():
    """Solver convergence failure in log."""
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "model.log")
        with open(log_path, 'w') as f:
            f.write("Step 100: convergence failure after 500 iterations\n")
            f.write("Reducing time step...\n")
        results = check_level2_execution(td, log_file=log_path)
        assert any(r.severity == Severity.FAIL for r in results)

run_test("Log convergence failure", test_log_convergence_failure)


def test_log_normal_termination():
    """Normal termination in log — should PASS."""
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "model.log")
        with open(log_path, 'w') as f:
            f.write("Step 100 completed\nNormal termination of simulation\n")
        results = check_level2_execution(td, log_file=log_path, exit_code=0)
        assert any(r.severity == Severity.PASS for r in results)

run_test("Normal termination → PASS", test_log_normal_termination)


# ======================================================================
# Level 3: Output plausibility — REAL BUGS
# ======================================================================
print("\n=== Level 3: Output Plausibility (Real Bugs) ===")


def test_hype_npc_accumulation():
    """HYPE NPC IN concentration = 64,000 mg/L. Single-subbasin accumulation."""
    results = check_level3_outputs(
        {"concentration_mg_L": np.array([64000, 50000, 70000])},
        domain="water_quality",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("HYPE NPC 64,000 mg/L accumulation", test_hype_npc_accumulation)


def test_swatplus_tn_overestimate():
    """SWAT+ TN=117 kgN/ha/yr from NPERCO=20."""
    results = check_level3_outputs(
        {"tn_kg_ha_yr": np.array([117, 141, 99, 167])},
        domain="water_quality",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("SWAT+ TN=117 kgN/ha/yr (NPERCO bug)", test_swatplus_tn_overestimate)


def test_ldndc_n2o_overestimate():
    """LDNDC N2O=18 kgN/ha/yr from airchemistrydndc bug."""
    results = check_level3_outputs(
        {"n2o_kgN_ha_yr": np.array([18, 24, 15, 10])},
        domain="biogeochemistry",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("LDNDC N2O=18 kgN/ha (airchemistry bug)", test_ldndc_n2o_overestimate)


def test_constant_output():
    """Output that is constant — model didn't actually compute."""
    results = check_level3_outputs(
        {"discharge_m3s": np.full(365, 0.0)},
        domain="hydrology",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("Constant zero discharge output", test_constant_output)


def test_flood_depth_unit_error():
    """SFINCS flood depth in cm not m — 699 instead of 6.99."""
    results = check_level3_outputs(
        {"depth_m": np.array([699, 450, 300, 550])},
        domain="flood",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("Flood depth cm not m (699 vs 6.99)", test_flood_depth_unit_error)


def test_crop_yield_unrealistic():
    """DSSAT yield 50,000 kg/ha — impossible for any crop."""
    results = check_level3_outputs(
        {"yield_kg_ha": np.array([50000, 45000, 55000])},
        domain="crop",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("Crop yield 50,000 kg/ha (impossible)", test_crop_yield_unrealistic)


def test_gwt_zero_mass_budget():
    """MODFLOW6 GWT all-zero mass budget — no contaminant source."""
    results = check_level3_outputs(
        {"concentration_mg_L": np.zeros(100)},
        domain="groundwater",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("MODFLOW6 GWT zero mass budget", test_gwt_zero_mass_budget)


def test_lake_temp_unit_error():
    """GLM surface temperature in K not °C — 293 instead of 20."""
    results = check_level3_outputs(
        {"surface_temp_C": np.array([293, 298, 288, 285])},
        domain="lake",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("GLM lake temp in K not °C", test_lake_temp_unit_error)


def test_urban_continuity_error():
    """SWMM continuity error > 5% — EPA threshold."""
    results = check_level3_outputs(
        {"continuity_pct": np.array([8.5])},
        domain="urban",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("SWMM continuity error 8.5% > EPA 5%", test_urban_continuity_error)


# ======================================================================
# Level 4: Domain metrics — REAL BUGS
# ======================================================================
print("\n=== Level 4: Domain Metrics (Real Bugs) ===")


def test_swatplus_nse_negative():
    """SWAT+ NSE=-6.45, PBIAS=247% — uncalibrated."""
    results = check_level4_domain(
        {"NSE": -6.45, "PBIAS": 247.0},
        domain="hydrology",
        calibrated=False,
    )
    assert any(r.severity in (Severity.FAIL, Severity.WARN) for r in results)

run_test("SWAT+ NSE=-6.45 PBIAS=247%", test_swatplus_nse_negative)


def test_budget_closure_fail():
    """Budget closure > 1% — solver/config issue."""
    results = check_level4_domain(
        {"budget_pct": 5.3},
        domain="groundwater",
    )
    assert any(r.severity == Severity.FAIL for r in results)

run_test("Budget closure 5.3% > 1%", test_budget_closure_fail)


def test_good_calibration():
    """Well-calibrated model — should PASS."""
    results = check_level4_domain(
        {"NSE": 0.76, "PBIAS": -7.4, "KGE": 0.85},
        domain="hydrology",
        calibrated=True,
    )
    assert all(r.severity in (Severity.PASS, Severity.INFO) for r in results)

run_test("Good calibration NSE=0.76 → PASS", test_good_calibration)


# ======================================================================
# Integration: Full pipeline
# ======================================================================
print("\n=== Integration: Full Pipeline ===")


def test_full_pipeline_pass():
    """A healthy model run should pass all levels."""
    with tempfile.TemporaryDirectory() as td:
        # Create a fake log file
        log = os.path.join(td, "run.log")
        with open(log, 'w') as f:
            f.write("Simulation complete. Normal termination.\n")

        report = run_triage(
            model="VIC",
            domain="hydrology",
            run_dir=td,
            levels=[0, 1, 2, 3, 4],
            log_file=log,
            exit_code=0,
            input_values={
                "temperature_K": np.random.uniform(260, 310, 365),
                "precipitation_mm": np.random.uniform(0, 50, 365),
                "lw_radiation_W": np.random.uniform(200, 400, 365),
            },
            output_values={
                "discharge_m3s": np.random.uniform(100, 2000, 365),
                "et_mm": np.random.uniform(1, 8, 365),
            },
            metrics={"NSE": 0.68, "PBIAS": 19.8, "KGE": 0.74},
            calibrated=False,
        )
        assert not report.has_failures()

run_test("Full pipeline healthy run → PASS", test_full_pipeline_pass)


def test_full_pipeline_catches_multiple():
    """Multiple bugs at once — should catch all."""
    with tempfile.TemporaryDirectory() as td:
        report = run_triage(
            model="WRF-Hydro",
            domain="hydrology",
            run_dir=td,
            levels=[0, 1, 3, 4],
            stop_on_block=False,
            input_values={
                "lw_radiation_W": np.array([106000, 105000]),  # Mixed cache
                "elevation_m": np.zeros(100),                   # HGT_M nodata
            },
            output_values={
                "discharge_m3s": np.full(365, 0.0),            # Constant output
            },
            metrics={"NSE": -6.45, "PBIAS": 247.0},
        )
        assert report.has_failures()
        failures = [c for c in report.checks if c.severity in (Severity.FAIL, Severity.BLOCK)]
        assert len(failures) >= 3, f"Expected 3+ failures, got {len(failures)}"

run_test("Multiple bugs caught simultaneously", test_full_pipeline_catches_multiple)


def test_stop_on_block():
    """stop_on_block should prevent running later levels."""
    report = run_triage(
        model="test",
        domain="hydrology",
        run_dir="/nonexistent",
        levels=[0, 1, 2, 3],
        stop_on_block=True,
        input_values={"temperature_K": np.array([20.0])},  # Would fail Level 1
    )
    # Level 0 blocks, so Level 1 input checks should NOT run
    level1_checks = [c for c in report.checks if c.level == 1]
    assert len(level1_checks) == 0, "Level 1 should not run when Level 0 blocks"

run_test("stop_on_block prevents later levels", test_stop_on_block)


# ======================================================================
# Report generation
# ======================================================================
print("\n=== Report Generation ===")


def test_json_export():
    """TriageReport should produce valid JSON."""
    report = run_triage("test", "hydrology", "/tmp", levels=[1],
                       input_values={"temperature_K": np.array([290.0, 295.0])})
    json_str = report.to_json()
    data = json.loads(json_str)
    assert "model" in data
    assert "overall" in data
    assert "all_checks" in data

run_test("JSON export valid", test_json_export)


def test_time_saved_tracking():
    """Time saved should accumulate for failures."""
    report = run_triage("WRF-Hydro", "hydrology", "/tmp", levels=[1],
                       input_values={"lw_radiation_W": np.array([106000])})
    s = report.summary()
    assert s["time_saved_hours"] > 0

run_test("Time saved tracking", test_time_saved_tracking)


# ======================================================================
# Feature 1: NPZ Cache Checker
# ======================================================================
print("\n=== Feature 1: NPZ Cache Checker ===")


def test_npz_cache_mixed_units():
    """NASA POWER cache with mixed MJ/m2/hr and W/m2 files."""
    with tempfile.TemporaryDirectory() as td:
        # Create two subdirs simulating grid cells with different units
        cell1 = os.path.join(td, "cell_30.0_110.0")
        cell2 = os.path.join(td, "cell_31.0_111.0")
        cell3 = os.path.join(td, "cell_32.0_112.0")
        os.makedirs(cell1)
        os.makedirs(cell2)
        os.makedirs(cell3)

        # Cell1: old cache in MJ/m2/hr (values ~1-4)
        hourly = np.zeros(24)
        hourly[10:15] = np.array([1.5, 2.0, 2.5, 2.0, 1.5])  # daytime
        np.savez(os.path.join(cell1, "2020_001.npz"),
                 ALLSKY_SFC_SW_DWN=hourly,
                 ALLSKY_SFC_LW_DWN=np.full(24, 0.97))

        # Cell2: new API in W/m2 (values ~300-700)
        hourly2 = np.zeros(24)
        hourly2[10:15] = np.array([450.0, 600.0, 700.0, 550.0, 400.0])
        np.savez(os.path.join(cell2, "2020_001.npz"),
                 ALLSKY_SFC_SW_DWN=hourly2,
                 ALLSKY_SFC_LW_DWN=np.full(24, 310.0))

        # Cell3: also new API
        hourly3 = np.zeros(24)
        hourly3[10:15] = np.array([420.0, 580.0, 650.0, 520.0, 380.0])
        np.savez(os.path.join(cell3, "2020_001.npz"),
                 ALLSKY_SFC_SW_DWN=hourly3,
                 ALLSKY_SFC_LW_DWN=np.full(24, 305.0))

        results = check_npz_cache_consistency(td)
        # Should detect the 100x+ magnitude difference
        sw_results = [r for r in results if "SW_DWN" in r.name]
        lw_results = [r for r in results if "LW_DWN" in r.name]
        # At least one of them should FAIL (depending on random sampling)
        all_fails = [r for r in results if r.severity == Severity.FAIL]
        assert len(all_fails) >= 1, (
            f"Expected at least 1 FAIL for mixed units, got: "
            f"{[(r.name, r.severity.value) for r in results]}"
        )

run_test("NPZ cache mixed MJ/m2/hr and W/m2", test_npz_cache_mixed_units)


def test_npz_cache_consistent():
    """Consistent NPZ cache should PASS."""
    with tempfile.TemporaryDirectory() as td:
        cell1 = os.path.join(td, "cell_30.0_110.0")
        cell2 = os.path.join(td, "cell_31.0_111.0")
        os.makedirs(cell1)
        os.makedirs(cell2)

        hourly = np.zeros(24)
        hourly[10:15] = np.array([450.0, 600.0, 700.0, 550.0, 400.0])
        for cell in [cell1, cell2]:
            np.savez(os.path.join(cell, "2020_001.npz"),
                     ALLSKY_SFC_SW_DWN=hourly,
                     ALLSKY_SFC_LW_DWN=np.full(24, 310.0))

        results = check_npz_cache_consistency(td)
        fails = [r for r in results if r.severity == Severity.FAIL]
        assert len(fails) == 0, f"Consistent cache should not FAIL: {fails}"

run_test("NPZ cache consistent units → PASS", test_npz_cache_consistent)


# ======================================================================
# Feature 2: Domain File Cross-Checks
# ======================================================================
print("\n=== Feature 2: Domain File Cross-Checks ===")


def test_domain_hgt_landmask_mismatch():
    """HGT_M=0 where LANDMASK=1 (DEM nodata bug)."""
    try:
        import netCDF4
    except ImportError:
        print("  SKIP: netCDF4 not available")
        return

    with tempfile.TemporaryDirectory() as td:
        geo_path = os.path.join(td, "geo_em.d01.nc")
        ds = netCDF4.Dataset(geo_path, "w")
        ds.createDimension("south_north", 10)
        ds.createDimension("west_east", 10)
        ds.createDimension("Time", 1)

        hgt = ds.createVariable("HGT_M", "f4", ("Time", "south_north", "west_east"))
        mask = ds.createVariable("LANDMASK", "i4", ("Time", "south_north", "west_east"))

        # All land (mask=1) but HGT_M=0 (nodata)
        mask[:] = np.ones((1, 10, 10))
        hgt[:] = np.zeros((1, 10, 10))
        ds.close()

        results = check_domain_consistency({"geo_em": geo_path})
        assert any(r.name == "domain_hgt_landmask" and r.severity == Severity.FAIL
                   for r in results), \
            f"Expected FAIL for HGT_M=0 on land, got: {[(r.name, r.severity.value) for r in results]}"

run_test("HGT_M=0 where LANDMASK=1 → FAIL", test_domain_hgt_landmask_mismatch)


def test_domain_smois_zero():
    """SMOIS=0 anywhere → arid basin crash risk."""
    try:
        import netCDF4
    except ImportError:
        print("  SKIP: netCDF4 not available")
        return

    with tempfile.TemporaryDirectory() as td:
        wrf_path = os.path.join(td, "wrfinput_d01.nc")
        ds = netCDF4.Dataset(wrf_path, "w")
        ds.createDimension("south_north", 5)
        ds.createDimension("west_east", 5)
        ds.createDimension("soil_layers_stag", 4)
        ds.createDimension("Time", 1)

        smois = ds.createVariable("SMOIS", "f4",
                                  ("Time", "soil_layers_stag", "south_north", "west_east"))
        data = np.full((1, 4, 5, 5), 0.3)
        data[0, :, 2, 3] = 0.0  # One cell with zero SM
        smois[:] = data
        ds.close()

        results = check_domain_consistency({"wrfinput": wrf_path})
        assert any(r.name == "domain_smois_zero" and r.severity == Severity.FAIL
                   for r in results), \
            f"Expected FAIL for SMOIS=0, got: {[(r.name, r.severity.value) for r in results]}"

run_test("SMOIS=0 anywhere → FAIL", test_domain_smois_zero)


def test_domain_grid_dims_match():
    """Matching grid dimensions → PASS."""
    try:
        import netCDF4
    except ImportError:
        print("  SKIP: netCDF4 not available")
        return

    with tempfile.TemporaryDirectory() as td:
        geo_path = os.path.join(td, "geo_em.d01.nc")
        wrf_path = os.path.join(td, "wrfinput_d01.nc")

        for path in [geo_path, wrf_path]:
            ds = netCDF4.Dataset(path, "w")
            ds.createDimension("south_north", 20)
            ds.createDimension("west_east", 30)
            ds.createDimension("Time", 1)
            ds.close()

        results = check_domain_consistency({"geo_em": geo_path, "wrfinput": wrf_path})
        dim_results = [r for r in results if r.name == "domain_grid_dims"]
        assert any(r.severity == Severity.PASS for r in dim_results), \
            f"Expected PASS for matching dims, got: {[(r.name, r.severity.value) for r in dim_results]}"

run_test("Grid dimensions match → PASS", test_domain_grid_dims_match)


# ======================================================================
# Feature 3: Runtime Monitor
# ======================================================================
print("\n=== Feature 3: Runtime Monitor ===")


def test_runtime_monitor_stall():
    """Detect output file creation stall."""
    import time as _time
    with tempfile.TemporaryDirectory() as td:
        out_dir = os.path.join(td, "output")
        os.makedirs(out_dir)
        # Create one initial file
        with open(os.path.join(out_dir, "step_001.nc"), 'w') as f:
            f.write("data")

        # Monitor our own PID (we know it is alive)
        monitor = RuntimeMonitor(
            pid=os.getpid(),
            output_dir=out_dir,
            poll_interval=0.1,
            stall_timeout=0.5,  # Very short for testing
        )
        monitor.start()
        # Wait long enough for stall to be detected
        _time.sleep(1.5)
        results = monitor.stop()

        stall_results = [r for r in results if "stall" in r.name]
        assert len(stall_results) >= 1, \
            f"Expected stall detection, got: {[(r.name, r.severity.value) for r in results]}"
        assert stall_results[0].severity == Severity.WARN

run_test("Runtime monitor detects output stall", test_runtime_monitor_stall)


def test_runtime_monitor_dead_process():
    """Detect process that has died."""
    import subprocess as _sp
    import time as _time

    # Start a process that exits immediately
    proc = _sp.Popen(["true"])
    proc.wait()  # Let it finish

    monitor = RuntimeMonitor(
        pid=proc.pid,
        poll_interval=0.1,
    )
    monitor.start()
    _time.sleep(0.5)
    results = monitor.stop()

    died_results = [r for r in results if "died" in r.name]
    assert len(died_results) >= 1, \
        f"Expected dead process detection, got: {[(r.name, r.severity.value) for r in results]}"

run_test("Runtime monitor detects dead process", test_runtime_monitor_dead_process)


# ======================================================================
# Feature 4: Level 5 — Regression Suite
# ======================================================================
print("\n=== Feature 4: Level 5 Regression ===")


def test_regression_nse_degraded():
    """NSE drops from 0.68 to 0.45 → FAIL."""
    with tempfile.TemporaryDirectory() as td:
        baseline = os.path.join(td, "baseline.json")
        with open(baseline, 'w') as f:
            json.dump({"NSE": 0.68, "r": 0.83, "PBIAS": 10.5}, f)

        results = check_level5_regression(
            current_metrics={"NSE": 0.45, "r": 0.80, "PBIAS": 12.0},
            baseline_file=baseline,
        )
        nse_results = [r for r in results if "NSE" in r.name]
        assert any(r.severity == Severity.FAIL for r in nse_results), \
            f"Expected FAIL for NSE 0.68→0.45, got: {[(r.name, r.severity.value) for r in nse_results]}"

run_test("NSE 0.68→0.45 → FAIL (beyond tolerance)", test_regression_nse_degraded)


def test_regression_within_tolerance():
    """NSE drops from 0.68 to 0.65 → WARN (within tolerance)."""
    with tempfile.TemporaryDirectory() as td:
        baseline = os.path.join(td, "baseline.json")
        with open(baseline, 'w') as f:
            json.dump({"NSE": 0.68}, f)

        results = check_level5_regression(
            current_metrics={"NSE": 0.65},
            baseline_file=baseline,
        )
        nse_results = [r for r in results if "NSE" in r.name]
        assert any(r.severity == Severity.WARN for r in nse_results), \
            f"Expected WARN for NSE 0.68→0.65, got: {[(r.name, r.severity.value) for r in nse_results]}"
        # Should NOT be FAIL (0.03 < 0.1 default tolerance)
        assert not any(r.severity == Severity.FAIL for r in nse_results), \
            "NSE drop of 0.03 should be WARN, not FAIL"

run_test("NSE 0.68→0.65 → WARN (within tolerance)", test_regression_within_tolerance)


def test_regression_improved():
    """NSE improves from 0.68 to 0.75 → PASS."""
    with tempfile.TemporaryDirectory() as td:
        baseline = os.path.join(td, "baseline.json")
        with open(baseline, 'w') as f:
            json.dump({"NSE": 0.68}, f)

        results = check_level5_regression(
            current_metrics={"NSE": 0.75},
            baseline_file=baseline,
        )
        nse_results = [r for r in results if "NSE" in r.name]
        assert all(r.severity == Severity.PASS for r in nse_results), \
            f"Expected PASS for NSE improvement, got: {[(r.name, r.severity.value) for r in nse_results]}"

run_test("NSE 0.68→0.75 → PASS (improved)", test_regression_improved)


def test_regression_via_run_triage():
    """Level 5 works via run_triage()."""
    with tempfile.TemporaryDirectory() as td:
        baseline = os.path.join(td, "baseline.json")
        with open(baseline, 'w') as f:
            json.dump({"NSE": 0.68, "PBIAS": 10.0}, f)

        report = run_triage(
            model="VIC", domain="hydrology", run_dir=td,
            levels=[5],
            metrics={"NSE": 0.45, "PBIAS": 25.0},
            baseline_file=baseline,
        )
        assert report.has_failures(), \
            "Expected failures from regression with degraded NSE"

run_test("Level 5 regression via run_triage()", test_regression_via_run_triage)


# ======================================================================
# Feature 5: Level 6 — Agent Audit
# ======================================================================
print("\n=== Feature 5: Level 6 Agent Audit ===")


def test_agent_used_wrong_tool():
    """Agent used cmfd_to_wrfhydro.py instead of nasa_power_to_ldasin.py."""
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "agent_session.log")
        with open(log_path, 'w') as f:
            f.write("Reading SKILL.md for WRF-Hydro...\n")
            f.write("Running cmfd_to_wrfhydro.py to prepare forcing...\n")
            f.write("cat <<EOF > custom_converter.py\n")
            f.write("import matplotlib.pyplot as plt\n")
            f.write("Simulation complete.\n")

        results = check_level6_agent_audit(log_path)

        # Should PASS read_skill (mentions SKILL.md)
        skill_results = [r for r in results if r.name == "agent_read_skill"]
        assert any(r.severity == Severity.PASS for r in skill_results), \
            "Agent read SKILL.md, should PASS"

        # Should WARN avoided_custom (used cat <<EOF and matplotlib)
        custom_results = [r for r in results if r.name == "agent_avoided_custom"]
        assert any(r.severity == Severity.WARN for r in custom_results), \
            f"Agent used custom patterns, should WARN: {[(r.name, r.severity.value, r.message) for r in custom_results]}"

        # Should WARN used_ki_tools (cmfd_to_wrfhydro is NOT a KI tool)
        tool_results = [r for r in results if r.name == "agent_used_ki_tools"]
        assert any(r.severity == Severity.WARN for r in tool_results), \
            "Agent did not use KI tools, should WARN"

run_test("Agent used wrong tool + custom code", test_agent_used_wrong_tool)


def test_agent_read_skill_md():
    """Agent read SKILL.md before running."""
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "agent_session.log")
        with open(log_path, 'w') as f:
            f.write("Reading knowledge_infrastructure/SKILL.md...\n")
            f.write("Using build_geo_em tool from KI...\n")
            f.write("Applied rst_typ fix for lake cells.\n")
            f.write("Running model...\n")

        results = check_level6_agent_audit(log_path)

        # Should PASS read_skill
        assert any(r.name == "agent_read_skill" and r.severity == Severity.PASS
                   for r in results), "Should PASS for reading SKILL.md"

        # Should PASS used_ki_tools (build_geo_em is a KI tool)
        assert any(r.name == "agent_used_ki_tools" and r.severity == Severity.PASS
                   for r in results), "Should PASS for using build_geo_em"

        # Should PASS avoided_custom (no custom code)
        assert any(r.name == "agent_avoided_custom" and r.severity == Severity.PASS
                   for r in results), "Should PASS for avoiding custom code"

        # Should INFO applied_fixes (rst_typ fix applied)
        assert any(r.name == "agent_applied_fixes" and r.severity == Severity.INFO
                   for r in results), "Should INFO for applying rst_typ fix"

run_test("Agent read SKILL.md and used KI tools → PASS", test_agent_read_skill_md)


def test_agent_no_skill_read():
    """Agent did NOT read SKILL.md → FAIL."""
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "agent_session.log")
        with open(log_path, 'w') as f:
            f.write("Starting WRF-Hydro simulation...\n")
            f.write("Running wrf_hydro.exe directly...\n")
            f.write("Done.\n")

        results = check_level6_agent_audit(log_path)
        skill_results = [r for r in results if r.name == "agent_read_skill"]
        assert any(r.severity == Severity.FAIL for r in skill_results), \
            "Agent did not read SKILL.md, should FAIL"

run_test("Agent did NOT read SKILL.md → FAIL", test_agent_no_skill_read)


def test_agent_audit_via_run_triage():
    """Level 6 works via run_triage()."""
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "agent.log")
        with open(log_path, 'w') as f:
            f.write("cat <<EOF > my_script.py\nimport matplotlib\n")

        report = run_triage(
            model="WRF-Hydro", domain="hydrology", run_dir=td,
            levels=[6],
            agent_log=log_path,
        )
        # Should have FAIL (no SKILL.md read) and WARN (custom code)
        assert any(c.severity == Severity.FAIL and c.level == 6 for c in report.checks), \
            "Expected FAIL from agent not reading SKILL.md"

run_test("Level 6 agent audit via run_triage()", test_agent_audit_via_run_triage)


# ======================================================================
# Summary
# ======================================================================
print(f"\n{'='*60}")
print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed}")
if errors:
    print(f"\nFailed tests:")
    for name, err in errors:
        print(f"  {name}: {err}")
print(f"{'='*60}")

sys.exit(0 if failed == 0 else 1)
