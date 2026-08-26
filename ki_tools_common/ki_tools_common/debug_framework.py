"""
debug_framework.py — Universal 6-Level Debug Triage for KDT Models

Encodes the diagnostic triage learned from 1,182 triplets across 104 models,
58 validation scorecards, and 20+ bugs found during 3 sessions of testing.

Triage hierarchy (broad → narrow):

    Level 0: EXISTENCE    — Can it even run? (binary, files, deps)
    Level 1: INPUTS       — Are inputs physically sane? (units, ranges, format)
    Level 2: EXECUTION    — Did it finish? (exit code, logs, convergence)
    Level 3: OUTPUTS      — Are outputs physically sane? (ranges, budgets)
    Level 4: DOMAIN       — Are results scientifically valid? (category-specific)
    Level 5: REGRESSION   — Did anything get worse? (vs baseline)

Design principles (from empirical data):
    - 54% of all errors are unit conversion → Level 1 catches the majority
    - 51% of failures are SILENT (no error message) → value checks > log parsing
    - 84% detectable by value_comparison → automated range checks are primary tool
    - Hydro models almost never crash; they silently absorb garbage inputs

Usage::

    from ki_tools_common.debug_framework import run_triage, TriageReport

    report = run_triage(
        model="WRF-Hydro",
        domain="hydrology",
        run_dir="/path/to/run",
        levels=[0, 1, 2, 3],
    )
    report.print_summary()
    if report.has_blockers():
        sys.exit(1)
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import datetime
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

class Severity(Enum):
    """Check result severity, ordered by urgency."""
    PASS = "PASS"
    INFO = "INFO"
    WARN = "WARN"
    FAIL = "FAIL"
    BLOCK = "BLOCK"  # Cannot proceed to next level


@dataclass
class CheckResult:
    """Single diagnostic check result."""
    level: int
    name: str
    severity: Severity
    message: str
    detail: str = ""
    fix_hint: str = ""
    time_saved_hours: float = 0.0  # estimated debug time this check prevents

    @property
    def passed(self) -> bool:
        return self.severity in (Severity.PASS, Severity.INFO)


@dataclass
class TriageReport:
    """Aggregated results from all triage levels."""
    model: str
    domain: str
    run_dir: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    checks: List[CheckResult] = field(default_factory=list)

    def add(self, check: CheckResult):
        self.checks.append(check)

    def has_blockers(self) -> bool:
        return any(c.severity == Severity.BLOCK for c in self.checks)

    def has_failures(self) -> bool:
        return any(c.severity in (Severity.FAIL, Severity.BLOCK) for c in self.checks)

    def level_passed(self, level: int) -> bool:
        level_checks = [c for c in self.checks if c.level == level]
        return all(c.severity != Severity.BLOCK for c in level_checks)

    def summary(self) -> Dict[str, Any]:
        by_severity = {}
        for s in Severity:
            count = sum(1 for c in self.checks if c.severity == s)
            if count:
                by_severity[s.value] = count
        failures = [
            {"name": c.name, "message": c.message, "fix_hint": c.fix_hint}
            for c in self.checks if c.severity in (Severity.FAIL, Severity.BLOCK)
        ]
        return {
            "model": self.model,
            "domain": self.domain,
            "total_checks": len(self.checks),
            "by_severity": by_severity,
            "overall": "PASS" if not self.has_failures() else "FAIL",
            "failures": failures,
            "time_saved_hours": sum(c.time_saved_hours for c in self.checks if not c.passed),
        }

    def print_summary(self):
        s = self.summary()
        print(f"\n{'='*70}")
        print(f"TRIAGE REPORT: {self.model} ({self.domain})")
        print(f"{'='*70}")
        print(f"  Run dir: {self.run_dir}")
        print(f"  Checks:  {s['total_checks']}")
        print(f"  Result:  {s['overall']}")
        print(f"  Counts:  {s['by_severity']}")
        if s["failures"]:
            print(f"\n  FAILURES:")
            for f in s["failures"]:
                print(f"    [{f['name']}] {f['message']}")
                if f["fix_hint"]:
                    print(f"      Fix: {f['fix_hint']}")
        if s["time_saved_hours"] > 0:
            print(f"\n  Estimated debug time saved: {s['time_saved_hours']:.1f}h")
        print(f"{'='*70}\n")

    def to_json(self, path: Optional[str] = None) -> str:
        data = self.summary()
        data["timestamp"] = self.timestamp
        data["all_checks"] = [
            {"level": c.level, "name": c.name, "severity": c.severity.value,
             "message": c.message, "detail": c.detail}
            for c in self.checks
        ]
        text = json.dumps(data, indent=2)
        if path:
            Path(path).write_text(text)
        return text


# ---------------------------------------------------------------------------
# Level 0: EXISTENCE — Can it even run?
# ---------------------------------------------------------------------------

def check_level0_existence(
    run_dir: str,
    binary_path: Optional[str] = None,
    required_files: Optional[List[str]] = None,
    required_dirs: Optional[List[str]] = None,
) -> List[CheckResult]:
    """Check that all required files, directories, and binaries exist."""
    results = []

    # Run directory
    if not os.path.isdir(run_dir):
        results.append(CheckResult(
            level=0, name="run_dir_exists", severity=Severity.BLOCK,
            message=f"Run directory does not exist: {run_dir}",
            fix_hint="Check the path. Was the setup step completed?",
            time_saved_hours=0.5,
        ))
        return results  # Nothing else to check
    results.append(CheckResult(
        level=0, name="run_dir_exists", severity=Severity.PASS,
        message=f"Run directory exists: {run_dir}",
    ))

    # Binary
    if binary_path:
        if os.path.isfile(binary_path) and os.access(binary_path, os.X_OK):
            # Check for debug flags
            try:
                strings_out = subprocess.run(
                    ["strings", binary_path], capture_output=True, text=True, timeout=10
                ).stdout
                debug_flags = []
                for flag in ["HYDRO_D=1", "DEBUG=1", "-g -O0", "AddressSanitizer"]:
                    if flag in strings_out:
                        debug_flags.append(flag)
                if debug_flags:
                    results.append(CheckResult(
                        level=0, name="binary_debug_flags", severity=Severity.WARN,
                        message=f"Binary has debug flags: {debug_flags}",
                        detail=f"Binary: {binary_path}",
                        fix_hint="Use the release/optimized binary for production runs.",
                        time_saved_hours=1.0,
                    ))
                else:
                    results.append(CheckResult(
                        level=0, name="binary_ok", severity=Severity.PASS,
                        message=f"Binary found and executable: {binary_path}",
                    ))
            except Exception:
                results.append(CheckResult(
                    level=0, name="binary_ok", severity=Severity.PASS,
                    message=f"Binary found and executable: {binary_path}",
                ))
        elif os.path.isfile(binary_path):
            results.append(CheckResult(
                level=0, name="binary_executable", severity=Severity.BLOCK,
                message=f"Binary exists but is not executable: {binary_path}",
                fix_hint="chmod +x the binary, or check ELF interpreter (patchelf).",
                time_saved_hours=1.0,
            ))
        else:
            results.append(CheckResult(
                level=0, name="binary_exists", severity=Severity.BLOCK,
                message=f"Binary not found: {binary_path}",
                fix_hint="Check model installation. Was the binary compiled?",
                time_saved_hours=2.0,
            ))

    # Required files
    for fpath in (required_files or []):
        full = fpath if os.path.isabs(fpath) else os.path.join(run_dir, fpath)
        if os.path.isfile(full):
            results.append(CheckResult(
                level=0, name=f"file_{os.path.basename(fpath)}", severity=Severity.PASS,
                message=f"Required file found: {fpath}",
            ))
        else:
            results.append(CheckResult(
                level=0, name=f"file_{os.path.basename(fpath)}", severity=Severity.BLOCK,
                message=f"Required file missing: {full}",
                fix_hint="Run the setup/preprocessing step first.",
                time_saved_hours=0.5,
            ))

    # Required directories
    for dpath in (required_dirs or []):
        full = dpath if os.path.isabs(dpath) else os.path.join(run_dir, dpath)
        if os.path.isdir(full):
            results.append(CheckResult(
                level=0, name=f"dir_{os.path.basename(dpath)}", severity=Severity.PASS,
                message=f"Required directory found: {dpath}",
            ))
        else:
            results.append(CheckResult(
                level=0, name=f"dir_{os.path.basename(dpath)}", severity=Severity.BLOCK,
                message=f"Required directory missing: {full}",
                time_saved_hours=0.5,
            ))

    return results


# ---------------------------------------------------------------------------
# Level 1: INPUTS — Are inputs physically sane?
# ---------------------------------------------------------------------------

# Universal physical bounds (from 572 unit_conversion triplets)
UNIVERSAL_BOUNDS = {
    # Meteorological forcing
    "temperature_K":    (180.0, 340.0,   "Temperature likely in Celsius" if True else ""),
    "precipitation_mm": (0.0,   1000.0,  "Check: mm/day vs kg/m2/s (×86400)"),
    "pressure_Pa":      (30000, 110000,  "Check: Pa vs hPa (×100) vs kPa (×1000)"),
    "sw_radiation_W":   (0.0,   1400.0,  "Check: W/m² vs MJ/m²/d (×11.574) vs J/m²/d (÷86400)"),
    "lw_radiation_W":   (100.0, 600.0,   "Check: W/m² vs MJ/m²/d. LWDOWN>1000 = unit error"),
    "wind_ms":          (0.0,   80.0,    "Check: m/s vs km/h (÷3.6)"),
    "humidity_kgkg":    (0.0,   0.06,    "Check: kg/kg vs g/kg (÷1000) vs %RH (need conversion)"),
    # Elevation / terrain
    "elevation_m":      (-500,  9000,    "DEM nodata (0 or -9999) = HGT_M bug"),
    # Soil
    "ksat_cm_min":      (0.0,   10.0,    "Check: cm/min vs m/s vs mm/hr"),
    "porosity_frac":    (0.01,  0.95,    "Porosity outside [0.01, 0.95] is unphysical"),
    "clay_pct":         (0.0,   100.0,   "Check: fraction [0-1] vs percent [0-100]"),
    # Crop / vegetation
    "lai":              (0.0,   12.0,    "LAI > 12 is unphysical for all biomes"),
    "yield_kg_ha":      (0.0,   25000,   "Yield > 25 t/ha is unrealistic for any crop"),
    # Water quality
    "concentration_mg_L": (0.0, 1000.0,  "Concentration > 1000 mg/L = likely unit error or accumulation bug"),
    "n_export_kg_ha_yr":  (0.0, 50.0,    "TN > 50 kgN/ha/yr: check NPERCO, fertilizer rates"),
    # Hydrology
    "discharge_m3s":    (0.0,   None,    "Negative discharge is unphysical"),
    "nse":              (None,  1.0,     "NSE > 1.0 is mathematically impossible"),
}


def check_value_range(
    name: str,
    values: np.ndarray,
    vmin: Optional[float],
    vmax: Optional[float],
    unit_hint: str = "",
    level: int = 1,
) -> CheckResult:
    """Check if values fall within physical bounds."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return CheckResult(
            level=level, name=f"range_{name}", severity=Severity.WARN,
            message=f"{name}: all values are NaN/Inf",
            fix_hint="Check data source for missing/fill values.",
            time_saved_hours=1.0,
        )

    mean_val = float(np.mean(arr))
    min_val = float(np.min(arr))
    max_val = float(np.max(arr))

    violations = []
    if vmin is not None and min_val < vmin:
        violations.append(f"min={min_val:.4g} < bound {vmin}")
    if vmax is not None and max_val > vmax:
        violations.append(f"max={max_val:.4g} > bound {vmax}")

    if violations:
        return CheckResult(
            level=level, name=f"range_{name}", severity=Severity.FAIL,
            message=f"{name} out of range: {', '.join(violations)}",
            detail=f"mean={mean_val:.4g}, min={min_val:.4g}, max={max_val:.4g}",
            fix_hint=unit_hint or f"Check units for {name}.",
            time_saved_hours=2.0,
        )

    # Mean-based unit traps (catches values in-range but wrong-unit)
    # These are the #1 bug class: 54% of all 1,182 triplets
    MEAN_TRAPS = {
        "precipitation_mm": [
            (lambda m: 0 < m < 0.01,
             "LIKELY kg/m²/s not mm/day — multiply by 86400. "
             "This was the #1 system-wide bug across 99 models."),
        ],
        "temperature_K": [
            (lambda m: -50 < m < 60,
             "LIKELY Celsius not Kelvin — add 273.15."),
        ],
        "pressure_Pa": [
            (lambda m: 300 < m < 1200,
             "LIKELY hPa not Pa — multiply by 100."),
        ],
        "humidity_kgkg": [
            (lambda m: 1 < m < 100,
             "LIKELY percent RH not kg/kg — needs Tetens conversion."),
        ],
    }
    if name in MEAN_TRAPS:
        for condition, hint in MEAN_TRAPS[name]:
            if condition(mean_val):
                return CheckResult(
                    level=level, name=f"unit_trap_{name}", severity=Severity.FAIL,
                    message=f"{name} mean={mean_val:.4g} suggests wrong unit",
                    detail=f"Range check passed but mean is suspicious",
                    fix_hint=hint,
                    time_saved_hours=4.0,
                )

    return CheckResult(
        level=level, name=f"range_{name}", severity=Severity.PASS,
        message=f"{name} in range (mean={mean_val:.4g})",
    )


def check_constant_or_fill(
    name: str, values: np.ndarray, level: int = 1,
) -> CheckResult:
    """Detect arrays that are constant or dominated by fill values."""
    arr = np.asarray(values, dtype=float)
    FILL_VALUES = {0.0, -9999.0, -999.0, 1e20, -1e20, 9.96921e36, -32768.0}

    # Check for constant
    if np.nanstd(arr) == 0.0:
        return CheckResult(
            level=level, name=f"constant_{name}", severity=Severity.FAIL,
            message=f"{name}: all values are constant ({arr.flat[0]:.4g})",
            fix_hint="Data extraction likely failed or returned fill values.",
            time_saved_hours=2.0,
        )

    # Check for fill-value dominance
    for fv in FILL_VALUES:
        frac = np.mean(np.abs(arr - fv) < 1e-6)
        if frac > 0.5:
            return CheckResult(
                level=level, name=f"fill_{name}", severity=Severity.FAIL,
                message=f"{name}: {frac*100:.0f}% of values are fill ({fv})",
                fix_hint="Check data extraction — likely missing data or wrong variable.",
                time_saved_hours=2.0,
            )

    return CheckResult(
        level=level, name=f"quality_{name}", severity=Severity.PASS,
        message=f"{name} has valid variability",
    )


def check_cache_consistency(
    cache_dir: str, variable: str, expected_unit: str,
) -> CheckResult:
    """Detect mixed-unit cache files (e.g., LWDOWN in both MJ and W/m²)."""
    files = sorted(Path(cache_dir).glob(f"*{variable}*"))
    if len(files) < 2:
        return CheckResult(
            level=1, name=f"cache_{variable}", severity=Severity.PASS,
            message=f"Cache consistent for {variable} ({len(files)} files)",
        )

    # Sample first and last file magnitudes
    magnitudes = []
    for f in [files[0], files[-1]]:
        try:
            data = np.loadtxt(str(f), max_rows=100) if f.suffix == '.txt' else None
            if data is not None and data.size > 0:
                magnitudes.append(float(np.nanmean(np.abs(data))))
        except Exception:
            continue

    if len(magnitudes) == 2 and magnitudes[0] > 0 and magnitudes[1] > 0:
        ratio = max(magnitudes) / min(magnitudes)
        if ratio > 10.0:
            return CheckResult(
                level=1, name=f"cache_{variable}", severity=Severity.FAIL,
                message=f"Mixed-unit cache for {variable}: magnitude ratio={ratio:.1f}x "
                        f"({magnitudes[0]:.2g} vs {magnitudes[1]:.2g})",
                fix_hint=f"Clear cache and re-extract. Expected unit: {expected_unit}.",
                time_saved_hours=3.0,
            )

    return CheckResult(
        level=1, name=f"cache_{variable}", severity=Severity.PASS,
        message=f"Cache consistent for {variable}",
    )


# ---------------------------------------------------------------------------
# Level 2: EXECUTION — Did it finish correctly?
# ---------------------------------------------------------------------------

def check_level2_execution(
    run_dir: str,
    log_file: Optional[str] = None,
    exit_code: Optional[int] = None,
    triplets_yaml: Optional[str] = None,
    max_runtime_seconds: float = 3600,
) -> List[CheckResult]:
    """Check execution success via exit code, logs, and triplet matching."""
    results = []

    # Exit code
    if exit_code is not None:
        if exit_code == 0:
            results.append(CheckResult(
                level=2, name="exit_code", severity=Severity.PASS,
                message="Exit code 0 (success)",
            ))
        elif exit_code in (134, 136):  # SIGABRT, SIGFPE
            results.append(CheckResult(
                level=2, name="exit_code", severity=Severity.FAIL,
                message=f"Crashed with signal (exit code {exit_code})",
                fix_hint="SIGFPE (136) often means bad forcing (NaN/Inf/zero), "
                         "not a code bug. Check Level 1 inputs FIRST.",
                time_saved_hours=6.0,  # The SIGFPE misdiagnosis cost 6h
            ))
        elif exit_code == 137:  # OOM kill
            results.append(CheckResult(
                level=2, name="exit_code", severity=Severity.FAIL,
                message=f"Killed by OS (exit code 137) — likely out of memory",
                fix_hint="Reduce grid resolution, domain size, or output frequency.",
                time_saved_hours=1.0,
            ))
        else:
            results.append(CheckResult(
                level=2, name="exit_code", severity=Severity.FAIL,
                message=f"Non-zero exit code: {exit_code}",
            ))

    # Log file analysis
    if log_file and os.path.isfile(log_file):
        try:
            with open(log_file, 'r', errors='replace') as f:
                log_text = f.read()

            # Universal success patterns
            success_patterns = [
                "Normal termination",
                "Run completed",
                "Simulation complete",
                "successfully",
                "NORMAL EXIT",
            ]
            found_success = any(p.lower() in log_text.lower() for p in success_patterns)

            # Universal failure patterns
            failure_patterns = {
                "segmentation fault": "Memory access violation — check array bounds, input file sizes",
                "bus error": "Memory alignment — check binary compatibility with this CPU",
                "floating point exception": "NaN/Inf in computation — check forcing data FIRST, then parameters",
                "out of memory": "Reduce domain size or output frequency",
                "file not found": "Missing input file — check Level 0",
                "convergence failure": "Solver did not converge — check time step, parameters",
                "mass balance error": "Water/mass not conserved — check boundary conditions",
            }

            for pattern, hint in failure_patterns.items():
                if pattern.lower() in log_text.lower():
                    results.append(CheckResult(
                        level=2, name=f"log_{pattern.replace(' ', '_')}",
                        severity=Severity.FAIL,
                        message=f"Log contains: '{pattern}'",
                        fix_hint=hint,
                        time_saved_hours=2.0,
                    ))

            if found_success and not any(c.severity == Severity.FAIL for c in results if c.level == 2):
                results.append(CheckResult(
                    level=2, name="log_success", severity=Severity.PASS,
                    message="Log indicates successful completion",
                ))

            # Triplet matching (if triplets.yaml provided)
            if triplets_yaml and os.path.isfile(triplets_yaml):
                results.extend(_match_triplets(log_text, triplets_yaml))

        except Exception as e:
            results.append(CheckResult(
                level=2, name="log_read_error", severity=Severity.WARN,
                message=f"Could not read log file: {e}",
            ))

    return results


def _match_triplets(log_text: str, triplets_yaml: str) -> List[CheckResult]:
    """Match log text against diagnostic triplets."""
    results = []
    try:
        import yaml
        with open(triplets_yaml) as f:
            triplets = yaml.safe_load(f) or []

        for t in triplets:
            symptom = t.get("symptom", "")
            if symptom and symptom.lower() in log_text.lower():
                results.append(CheckResult(
                    level=2, name=f"triplet_{t.get('id', '?')}",
                    severity=Severity.WARN,
                    message=f"Triplet match: {symptom}",
                    detail=f"Cause: {t.get('cause', '?')}",
                    fix_hint=t.get("remedy", "See diagnostics/triplets.yaml"),
                    time_saved_hours=1.0,
                ))
    except ImportError:
        pass  # PyYAML not available
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Level 3: OUTPUTS — Are outputs physically sane?
# ---------------------------------------------------------------------------

def check_level3_outputs(
    output_values: Dict[str, np.ndarray],
    domain: str = "general",
) -> List[CheckResult]:
    """Check output plausibility using universal + domain-specific bounds."""
    results = []

    # Universal output checks
    for name, values in output_values.items():
        arr = np.asarray(values, dtype=float)

        # NaN/Inf check
        nan_frac = np.mean(~np.isfinite(arr))
        if nan_frac > 0.5:
            results.append(CheckResult(
                level=3, name=f"nan_{name}", severity=Severity.FAIL,
                message=f"{name}: {nan_frac*100:.0f}% NaN/Inf values",
                fix_hint="Model likely crashed mid-run or input data had gaps.",
                time_saved_hours=1.0,
            ))
            continue

        # Constant output (model didn't actually compute anything)
        if np.nanstd(arr) == 0 and arr.size > 10:
            results.append(CheckResult(
                level=3, name=f"constant_{name}", severity=Severity.FAIL,
                message=f"{name}: output is constant ({arr.flat[0]:.4g})",
                fix_hint="Model may not have run, or output variable not populated.",
                time_saved_hours=2.0,
            ))
            continue

    # Domain-specific checks
    domain_checks = DOMAIN_CHECKS.get(domain, {})
    for name, (vmin, vmax, hint) in domain_checks.items():
        if name in output_values:
            results.append(check_value_range(
                name, output_values[name], vmin, vmax, hint, level=3,
            ))

    return results


# Domain-specific output bounds (from 58 scorecards + literature)
DOMAIN_CHECKS: Dict[str, Dict[str, Tuple]] = {
    "hydrology": {
        "discharge_m3s":       (0.0,   None,  "Negative Q is unphysical"),
        "et_mm":               (0.0,   20.0,  "Daily ET > 20 mm is unrealistic"),
        "runoff_mm":           (0.0,   500.0, "Daily runoff > 500 mm = flash flood or unit error"),
        "soil_moisture_frac":  (0.0,   1.0,   "SM > 1.0 means fraction vs mm confusion"),
        "snow_swe_mm":         (0.0,   5000,  "SWE > 5m is unrealistic everywhere"),
    },
    "crop": {
        "yield_kg_ha":         (0.0,   25000, "Max realistic yield: ~25 t/ha (sugarcane)"),
        "lai_max":             (0.0,   12.0,  "LAI > 12 is unphysical"),
        "harvest_index":       (0.0,   0.7,   "HI > 0.7 is unrealistic for all crops"),
        "biomass_kg_ha":       (0.0,   50000, "Biomass > 50 t/ha is extreme"),
        "et_season_mm":        (0.0,   2000,  "Seasonal crop ET > 2000 mm is unrealistic"),
    },
    "groundwater": {
        "head_m":              (-500,  9000,  "Head below sea level is possible but check datum"),
        "budget_pct":          (-1.0,  1.0,   "Budget closure > 1% indicates solver/config issue"),
        "concentration_mg_L":  (0.0,   1000,  "> 1000 mg/L: check source term or accumulation"),
    },
    "lake": {
        "surface_temp_C":      (-2.0,  45.0,  "Lake T > 45°C = unit error or solar miscalc"),
        "bottom_temp_C":       (0.0,   30.0,  "Bottom T > 30°C is rare; check thermocline"),
        "stratification_C":    (0.0,   30.0,  "Strat > 30°C = unit issue"),
        "do_mg_L":             (0.0,   20.0,  "DO > 20 mg/L at surface is supersaturation"),
    },
    "biogeochemistry": {
        "n2o_kgN_ha_yr":      (0.0,   10.0,  "N₂O > 10 kgN/ha = check N deposition, fertilizer, airchemistry module"),
        "ch4_kgC_ha_yr":      (0.0,   800,   "CH₄ > 800 kgC/ha = paddy soil Ksat issue or flooding schedule"),
        "no3_leach_kgN_ha":   (0.0,   80,    "NO₃ leach > 80 kgN/ha = check soil drainage, N inputs"),
        "co2_resp_kgC_ha_yr": (0.0,   8000,  "CO₂ resp > 8000 kgC/ha = check soil C pools"),
    },
    "flood": {
        "depth_m":             (0.0,   50.0,  "Flood depth > 50m = unit error"),
        "velocity_ms":         (0.0,   20.0,  "Velocity > 20 m/s: check roughness or DEM"),
        "mass_balance_ratio":  (0.95,  1.05,  "Mass balance > 5% = numerical instability"),
    },
    "water_quality": {
        "tn_kg_ha_yr":        (0.0,   50.0,  "TN > 50 kgN/ha/yr: check NPERCO, calibration"),
        "tp_kg_ha_yr":        (0.0,   10.0,  "TP > 10 kgP/ha/yr: check P parameters"),
        "sediment_t_ha_yr":   (0.0,   100,   "Sed > 100 t/ha: check USLE params, slope"),
        "concentration_mg_L": (0.0,   1000,  "> 1000 mg/L: accumulation bug or unit error"),
    },
    "glacier": {
        "volume_change_pct":  (-100,  10,    "Volume gain > 10% is unrealistic for warming"),
        "area_change_pct":    (-100,  5,     "Area growth > 5% is unusual"),
    },
    "urban": {
        "continuity_pct":     (-5.0,  5.0,   "EPA threshold: continuity error < 5%"),
        "runoff_coeff":       (0.0,   1.0,   "Runoff coefficient > 1.0 is unphysical"),
    },
}


# ---------------------------------------------------------------------------
# Level 4: DOMAIN — Cross-check against expected behavior
# ---------------------------------------------------------------------------

def check_level4_domain(
    metrics: Dict[str, float],
    domain: str,
    calibrated: bool = False,
) -> List[CheckResult]:
    """Domain-specific scientific validity checks."""
    results = []

    # Hydrological performance metrics
    nse = metrics.get("NSE") or metrics.get("nse")
    kge = metrics.get("KGE") or metrics.get("kge")
    pbias = metrics.get("PBIAS") or metrics.get("pbias")

    if nse is not None:
        if nse < -1.0 and calibrated:
            results.append(CheckResult(
                level=4, name="nse_calibrated", severity=Severity.FAIL,
                message=f"NSE={nse:.2f} after calibration — worse than mean-flow model",
                fix_hint="Check: (1) obs/sim period alignment, (2) unit match, (3) correct gauge",
                time_saved_hours=2.0,
            ))
        elif nse < 0.0 and not calibrated:
            results.append(CheckResult(
                level=4, name="nse_uncalibrated", severity=Severity.WARN,
                message=f"NSE={nse:.2f} (uncalibrated) — needs calibration",
            ))
        elif nse >= 0.5:
            results.append(CheckResult(
                level=4, name="nse", severity=Severity.PASS,
                message=f"NSE={nse:.2f} — {'good' if nse > 0.7 else 'acceptable'}",
            ))

    if pbias is not None:
        if abs(pbias) > 100:
            results.append(CheckResult(
                level=4, name="pbias", severity=Severity.FAIL,
                message=f"PBIAS={pbias:.0f}% — {'overestimates' if pbias > 0 else 'underestimates'} "
                        f"by {abs(pbias)/100:.1f}x",
                fix_hint="Check: (1) precip units, (2) ET parameterization, (3) basin area",
                time_saved_hours=2.0,
            ))
        elif abs(pbias) > 30:
            results.append(CheckResult(
                level=4, name="pbias", severity=Severity.WARN,
                message=f"PBIAS={pbias:.0f}% — moderate bias",
            ))

    # Water balance closure
    wb_closure = metrics.get("water_balance_mm")
    if wb_closure is not None and abs(wb_closure) > 50:
        results.append(CheckResult(
            level=4, name="water_balance", severity=Severity.WARN,
            message=f"Water balance closure: {wb_closure:.0f} mm/yr",
            fix_hint="P ≠ ET + Q + ΔS. Check deep percolation or storage terms.",
        ))

    # Budget closure (GW, flood, lake models)
    budget_pct = metrics.get("budget_pct") or metrics.get("budget_error_pct")
    if budget_pct is not None and abs(budget_pct) > 1.0:
        results.append(CheckResult(
            level=4, name="budget_closure", severity=Severity.FAIL,
            message=f"Budget closure error: {budget_pct:.2f}%",
            fix_hint="Check solver convergence, time step, boundary conditions.",
            time_saved_hours=1.0,
        ))

    return results


# ---------------------------------------------------------------------------
# Feature 1: NPZ Cache Checker
# ---------------------------------------------------------------------------

def check_npz_cache_consistency(
    cache_dir: str,
    variables: Optional[List[str]] = None,
) -> List[CheckResult]:
    """Check NPZ cache files for mixed-unit contamination.

    Scans subdirectories of cache_dir, loads first and last NPZ files,
    compares magnitude of radiation variables (ALLSKY_SFC_SW_DWN, ALLSKY_SFC_LW_DWN).
    If ratio > 50x between any two files, flags FAIL (mixed MJ/m2/hr and W/m2).

    The specific bug: old cache stored MJ/m2/hr (values ~1-4), new API returns W/m2
    (values ~300-700). Mixed cache causes LWDOWN=106,000 W/m2 (277.78x too high).
    """
    results = []
    if variables is None:
        variables = ["ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_LW_DWN"]

    cache_path = Path(cache_dir)
    if not cache_path.is_dir():
        results.append(CheckResult(
            level=1, name="npz_cache_dir", severity=Severity.WARN,
            message=f"NPZ cache directory does not exist: {cache_dir}",
        ))
        return results

    # Collect subdirectories (each represents a grid cell)
    subdirs = [d for d in cache_path.iterdir() if d.is_dir()]
    if not subdirs:
        # Try NPZ files directly in cache_dir
        npz_files = sorted(cache_path.glob("*.npz"))
        if not npz_files:
            results.append(CheckResult(
                level=1, name="npz_cache_empty", severity=Severity.WARN,
                message=f"No NPZ files or subdirectories found in {cache_dir}",
            ))
            return results
        subdirs = [cache_path]

    # Sample up to 3 random subdirectories
    sample_dirs = random.sample(subdirs, min(3, len(subdirs)))

    for var in variables:
        magnitudes: List[Tuple[str, float]] = []

        for sdir in sample_dirs:
            npz_files = sorted(sdir.glob("*.npz"))
            if len(npz_files) < 1:
                continue

            # Sample first and last NPZ file in each subdir
            sample_files = [npz_files[0]]
            if len(npz_files) > 1:
                sample_files.append(npz_files[-1])

            for npz_path in sample_files:
                try:
                    data = np.load(str(npz_path), allow_pickle=True)
                    if var not in data:
                        continue
                    arr = np.asarray(data[var], dtype=float)
                    arr = arr[np.isfinite(arr)]

                    if var == "ALLSKY_SFC_SW_DWN":
                        # Filter daytime hours (indices 10-14 for hourly, approximate)
                        # For hourly data with 24 values per day
                        if arr.size >= 24:
                            day_indices = []
                            for i in range(arr.size):
                                hour = i % 24
                                if 10 <= hour <= 14:
                                    day_indices.append(i)
                            if day_indices:
                                day_vals = arr[day_indices]
                                day_vals = day_vals[day_vals > 0]
                                if day_vals.size > 0:
                                    magnitudes.append(
                                        (str(npz_path), float(np.mean(day_vals)))
                                    )
                        elif arr.size > 0:
                            pos = arr[arr > 0]
                            if pos.size > 0:
                                magnitudes.append(
                                    (str(npz_path), float(np.mean(pos)))
                                )
                    else:
                        if arr.size > 0:
                            magnitudes.append(
                                (str(npz_path), float(np.mean(np.abs(arr))))
                            )
                except Exception:
                    continue

        if len(magnitudes) < 2:
            results.append(CheckResult(
                level=1, name=f"npz_cache_{var}", severity=Severity.PASS,
                message=f"NPZ cache for {var}: insufficient files to compare "
                        f"({len(magnitudes)} samples)",
            ))
            continue

        # Check all pairs for magnitude ratio > 50x
        all_mags = [m for _, m in magnitudes if m > 0]
        if len(all_mags) >= 2:
            max_mag = max(all_mags)
            min_mag = min(all_mags)
            ratio = max_mag / min_mag

            if ratio > 50.0:
                # Find the files with min and max
                min_file = [f for f, m in magnitudes if m == min_mag][0]
                max_file = [f for f, m in magnitudes if m == max_mag][0]
                results.append(CheckResult(
                    level=1, name=f"npz_cache_{var}", severity=Severity.FAIL,
                    message=f"Mixed-unit NPZ cache for {var}: magnitude ratio={ratio:.1f}x "
                            f"(min={min_mag:.2g} vs max={max_mag:.2g})",
                    detail=f"Low file: {min_file}\nHigh file: {max_file}",
                    fix_hint=f"Clear cache directory {cache_dir} and re-fetch. "
                             f"Old cache stored MJ/m2/hr (~1-4), new API returns W/m2 (~300-700). "
                             f"Mixed cache causes LWDOWN=106,000 W/m2.",
                    time_saved_hours=4.0,
                ))
            else:
                results.append(CheckResult(
                    level=1, name=f"npz_cache_{var}", severity=Severity.PASS,
                    message=f"NPZ cache consistent for {var} (ratio={ratio:.1f}x, "
                            f"range={min_mag:.2g}–{max_mag:.2g})",
                ))
        else:
            results.append(CheckResult(
                level=1, name=f"npz_cache_{var}", severity=Severity.PASS,
                message=f"NPZ cache for {var}: all positive samples consistent",
            ))

    return results


# ---------------------------------------------------------------------------
# Feature 2: Domain File Cross-Checks
# ---------------------------------------------------------------------------

def check_domain_consistency(
    domain_files: Dict[str, str],
) -> List[CheckResult]:
    """Cross-validate WRF-Hydro domain files for internal consistency.

    Accepts dict like: {"geo_em": "path", "wrfinput": "path",
                        "fulldom": "path", "metadata": "path"}

    Checks:
    1. HGT_M=0 where LANDMASK=1 -> DEM nodata bug (cost: 2 hours)
    2. SOILTEMP < 200K on land cells -> uninitialized soil temperature
    3. Grid dimension mismatch between geo_em and wrfinput (south_north, west_east)
    4. Fulldom routing grid dimensions = geo_em dimensions * AGGFACTRT
    5. GEOGRID_LDASOUT_Spatial_Metadata has 'resolution' attribute on x/y
    6. SMOIS = 0 anywhere -> dry soil crash risk (Section 21 arid basin fix)
    """
    results = []

    try:
        import netCDF4
    except ImportError:
        results.append(CheckResult(
            level=1, name="domain_netcdf4", severity=Severity.WARN,
            message="netCDF4 not available — skipping domain file cross-checks",
        ))
        return results

    geo_em_path = domain_files.get("geo_em", "")
    wrfinput_path = domain_files.get("wrfinput", "")
    fulldom_path = domain_files.get("fulldom", "")
    metadata_path = domain_files.get("metadata", "")

    # --- Check 1: HGT_M=0 where LANDMASK=1 ---
    if geo_em_path and os.path.isfile(geo_em_path):
        try:
            ds = netCDF4.Dataset(geo_em_path, "r")
            try:
                if "HGT_M" in ds.variables and "LANDMASK" in ds.variables:
                    hgt = np.asarray(ds["HGT_M"][:]).flatten()
                    mask = np.asarray(ds["LANDMASK"][:]).flatten()
                    land_cells = mask == 1
                    if land_cells.any():
                        zero_hgt_on_land = np.sum((hgt == 0) & land_cells)
                        total_land = int(np.sum(land_cells))
                        if zero_hgt_on_land > 0:
                            frac = zero_hgt_on_land / total_land
                            if frac > 0.1:
                                results.append(CheckResult(
                                    level=1, name="domain_hgt_landmask",
                                    severity=Severity.FAIL,
                                    message=f"HGT_M=0 on {zero_hgt_on_land}/{total_land} "
                                            f"land cells ({frac*100:.0f}%) — DEM nodata bug",
                                    fix_hint="Re-run geogrid with correct DEM. "
                                             "HGT_M=0 on land means DEM fill values leaked through.",
                                    time_saved_hours=2.0,
                                ))
                            else:
                                results.append(CheckResult(
                                    level=1, name="domain_hgt_landmask",
                                    severity=Severity.WARN,
                                    message=f"HGT_M=0 on {zero_hgt_on_land} land cells "
                                            f"({frac*100:.1f}%) — possible coastal cells or DEM issue",
                                ))
                        else:
                            results.append(CheckResult(
                                level=1, name="domain_hgt_landmask",
                                severity=Severity.PASS,
                                message="HGT_M consistent with LANDMASK (no zero-elev land cells)",
                            ))
            finally:
                ds.close()
        except Exception as e:
            results.append(CheckResult(
                level=1, name="domain_hgt_landmask", severity=Severity.WARN,
                message=f"Could not read geo_em file: {e}",
            ))

    # --- Check 2: SOILTEMP < 200K on land ---
    if wrfinput_path and os.path.isfile(wrfinput_path):
        try:
            ds = netCDF4.Dataset(wrfinput_path, "r")
            try:
                if "SOILTEMP" in ds.variables:
                    soiltemp = np.asarray(ds["SOILTEMP"][:]).flatten()
                    low_temp = np.sum(soiltemp < 200.0)
                    if "LANDMASK" in ds.variables:
                        land = np.asarray(ds["LANDMASK"][:]).flatten() == 1
                        low_temp = np.sum((soiltemp < 200.0) & land)
                    if low_temp > 0:
                        results.append(CheckResult(
                            level=1, name="domain_soiltemp",
                            severity=Severity.FAIL,
                            message=f"SOILTEMP < 200K on {low_temp} cells — uninitialized soil temperature",
                            fix_hint="Check wrfinput generation. SOILTEMP should be ~250-310K on land.",
                            time_saved_hours=1.5,
                        ))
                    else:
                        results.append(CheckResult(
                            level=1, name="domain_soiltemp",
                            severity=Severity.PASS,
                            message="SOILTEMP >= 200K on all cells",
                        ))
            finally:
                ds.close()
        except Exception as e:
            results.append(CheckResult(
                level=1, name="domain_soiltemp", severity=Severity.WARN,
                message=f"Could not read wrfinput file: {e}",
            ))

    # --- Check 3: Grid dimension mismatch geo_em vs wrfinput ---
    if (geo_em_path and os.path.isfile(geo_em_path)
            and wrfinput_path and os.path.isfile(wrfinput_path)):
        try:
            ds_geo = netCDF4.Dataset(geo_em_path, "r")
            ds_wrf = netCDF4.Dataset(wrfinput_path, "r")
            try:
                geo_sn = ds_geo.dimensions.get("south_north")
                geo_we = ds_geo.dimensions.get("west_east")
                wrf_sn = ds_wrf.dimensions.get("south_north")
                wrf_we = ds_wrf.dimensions.get("west_east")
                if geo_sn and geo_we and wrf_sn and wrf_we:
                    geo_dims = (len(geo_sn), len(geo_we))
                    wrf_dims = (len(wrf_sn), len(wrf_we))
                    if geo_dims != wrf_dims:
                        results.append(CheckResult(
                            level=1, name="domain_grid_dims",
                            severity=Severity.FAIL,
                            message=f"Grid mismatch: geo_em={geo_dims} vs wrfinput={wrf_dims}",
                            fix_hint="Re-run real.exe or check WPS namelist domain settings.",
                            time_saved_hours=2.0,
                        ))
                    else:
                        results.append(CheckResult(
                            level=1, name="domain_grid_dims",
                            severity=Severity.PASS,
                            message=f"Grid dimensions match: {geo_dims}",
                        ))
            finally:
                ds_geo.close()
                ds_wrf.close()
        except Exception as e:
            results.append(CheckResult(
                level=1, name="domain_grid_dims", severity=Severity.WARN,
                message=f"Could not compare grid dimensions: {e}",
            ))

    # --- Check 4: Fulldom routing grid = geo_em * AGGFACTRT ---
    if (fulldom_path and os.path.isfile(fulldom_path)
            and geo_em_path and os.path.isfile(geo_em_path)):
        try:
            ds_geo = netCDF4.Dataset(geo_em_path, "r")
            ds_full = netCDF4.Dataset(fulldom_path, "r")
            try:
                geo_sn = ds_geo.dimensions.get("south_north")
                geo_we = ds_geo.dimensions.get("west_east")
                # AGGFACTRT is usually stored as a global attribute or in Fulldom_hires
                aggfact = None
                if hasattr(ds_full, "AGGFACTRT"):
                    aggfact = int(ds_full.AGGFACTRT)
                elif "AGGFACTRT" in ds_full.variables:
                    aggfact = int(ds_full["AGGFACTRT"][0])

                if geo_sn and geo_we and aggfact:
                    expected_sn = len(geo_sn) * aggfact
                    expected_we = len(geo_we) * aggfact
                    full_y = ds_full.dimensions.get("y") or ds_full.dimensions.get("south_north")
                    full_x = ds_full.dimensions.get("x") or ds_full.dimensions.get("west_east")
                    if full_y and full_x:
                        actual = (len(full_y), len(full_x))
                        expected = (expected_sn, expected_we)
                        if actual != expected:
                            results.append(CheckResult(
                                level=1, name="domain_fulldom_dims",
                                severity=Severity.FAIL,
                                message=f"Fulldom dims {actual} != geo_em {(len(geo_sn), len(geo_we))} "
                                        f"x AGGFACTRT={aggfact} = {expected}",
                                fix_hint="Re-run GIS preprocessing with correct AGGFACTRT.",
                                time_saved_hours=2.0,
                            ))
                        else:
                            results.append(CheckResult(
                                level=1, name="domain_fulldom_dims",
                                severity=Severity.PASS,
                                message=f"Fulldom dims consistent: {actual} = geo_em x {aggfact}",
                            ))
            finally:
                ds_geo.close()
                ds_full.close()
        except Exception as e:
            results.append(CheckResult(
                level=1, name="domain_fulldom_dims", severity=Severity.WARN,
                message=f"Could not check Fulldom dimensions: {e}",
            ))

    # --- Check 5: Spatial Metadata resolution attribute ---
    if metadata_path and os.path.isfile(metadata_path):
        try:
            ds = netCDF4.Dataset(metadata_path, "r")
            try:
                has_res = False
                for coord in ("x", "y"):
                    if coord in ds.variables:
                        if hasattr(ds[coord], "resolution"):
                            has_res = True
                if has_res:
                    results.append(CheckResult(
                        level=1, name="domain_metadata_resolution",
                        severity=Severity.PASS,
                        message="Spatial metadata has resolution attribute on x/y",
                    ))
                else:
                    results.append(CheckResult(
                        level=1, name="domain_metadata_resolution",
                        severity=Severity.WARN,
                        message="Spatial metadata missing resolution attribute on x/y",
                        fix_hint="Add resolution attribute to GEOGRID_LDASOUT_Spatial_Metadata.",
                    ))
            finally:
                ds.close()
        except Exception as e:
            results.append(CheckResult(
                level=1, name="domain_metadata_resolution", severity=Severity.WARN,
                message=f"Could not read metadata file: {e}",
            ))

    # --- Check 6: SMOIS = 0 anywhere ---
    if wrfinput_path and os.path.isfile(wrfinput_path):
        try:
            ds = netCDF4.Dataset(wrfinput_path, "r")
            try:
                if "SMOIS" in ds.variables:
                    smois = np.asarray(ds["SMOIS"][:]).flatten()
                    zero_count = int(np.sum(smois == 0.0))
                    if zero_count > 0:
                        results.append(CheckResult(
                            level=1, name="domain_smois_zero",
                            severity=Severity.FAIL,
                            message=f"SMOIS=0 in {zero_count} cells — dry soil crash risk",
                            fix_hint="Apply Section 21 arid basin fix: set minimum SMOIS=0.02. "
                                     "Zero soil moisture causes numerical instability.",
                            time_saved_hours=3.0,
                        ))
                    else:
                        results.append(CheckResult(
                            level=1, name="domain_smois_zero",
                            severity=Severity.PASS,
                            message="SMOIS > 0 everywhere",
                        ))
            finally:
                ds.close()
        except Exception as e:
            results.append(CheckResult(
                level=1, name="domain_smois_zero", severity=Severity.WARN,
                message=f"Could not check SMOIS: {e}",
            ))

    return results


# ---------------------------------------------------------------------------
# Feature 3: Runtime Monitor
# ---------------------------------------------------------------------------

class RuntimeMonitor:
    """Background monitor for long-running model processes.

    Usage:
        monitor = RuntimeMonitor(pid, log_files=["diag_hydro.00000"], poll_interval=10.0)
        monitor.start()  # starts background thread
        # ... model runs ...
        results = monitor.stop()  # returns List[CheckResult]

    Monitors:
    1. Process alive check (detect silent crashes)
    2. RSS memory growth (warn at 80% system RAM)
    3. Output file creation stall (no new files for 5 minutes)
    4. Log file error pattern matching (same patterns as Level 2)
    """

    # Error patterns shared with Level 2 execution checks
    _ERROR_PATTERNS = {
        "segmentation fault": "Memory access violation — check array bounds",
        "bus error": "Memory alignment — check binary compatibility",
        "floating point exception": "NaN/Inf in computation — check forcing",
        "out of memory": "Reduce domain size or output frequency",
        "convergence failure": "Solver did not converge — check time step",
        "mass balance error": "Water/mass not conserved — check BCs",
        "forrtl": "Fortran runtime error — check input formats",
        "error": None,  # generic, lower priority
    }

    def __init__(
        self,
        pid: int,
        log_files: Optional[List[str]] = None,
        output_dir: Optional[str] = None,
        poll_interval: float = 10.0,
        memory_warn_fraction: float = 0.80,
        stall_timeout: float = 300.0,
    ):
        self._pid = pid
        self._log_files = log_files or []
        self._output_dir = output_dir
        self._poll_interval = poll_interval
        self._memory_warn_fraction = memory_warn_fraction
        self._stall_timeout = stall_timeout

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._results: List[CheckResult] = []
        self._lock = threading.Lock()

        # Tracking state
        self._last_output_count: int = 0
        self._last_output_time: float = time.time()
        self._peak_rss_mb: float = 0.0
        self._last_log_sizes: Dict[str, int] = {}
        self._process_died = False
        self._stall_warned = False
        self._memory_warned = False

    def start(self):
        """Start the background monitoring thread."""
        self._stop_event.clear()
        self._last_output_time = time.time()
        # Initialize log sizes
        for lf in self._log_files:
            if os.path.isfile(lf):
                self._last_log_sizes[lf] = os.path.getsize(lf)
            else:
                self._last_log_sizes[lf] = 0
        # Initialize output count
        if self._output_dir and os.path.isdir(self._output_dir):
            self._last_output_count = len(os.listdir(self._output_dir))

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> List[CheckResult]:
        """Stop monitoring and return accumulated results."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        with self._lock:
            # Add final summary
            if self._process_died:
                self._results.append(CheckResult(
                    level=2, name="monitor_process_died",
                    severity=Severity.FAIL,
                    message=f"Process {self._pid} died during monitoring",
                    fix_hint="Check exit code and log files for crash details.",
                    time_saved_hours=1.0,
                ))
            if self._peak_rss_mb > 0:
                self._results.append(CheckResult(
                    level=2, name="monitor_peak_memory",
                    severity=Severity.INFO,
                    message=f"Peak RSS memory: {self._peak_rss_mb:.0f} MB",
                ))
            return list(self._results)

    def _monitor_loop(self):
        """Main polling loop run in background thread."""
        while not self._stop_event.is_set():
            self._check_process_alive()
            self._check_memory()
            self._check_output_stall()
            self._check_log_errors()
            self._stop_event.wait(self._poll_interval)

    def _add_result(self, result: CheckResult):
        with self._lock:
            self._results.append(result)

    def _check_process_alive(self):
        """Check if the monitored process is still running."""
        if self._process_died:
            return
        try:
            import psutil
            if not psutil.pid_exists(self._pid):
                self._process_died = True
                return
            proc = psutil.Process(self._pid)
            status = proc.status()
            if status in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                self._process_died = True
        except ImportError:
            # Fallback: use os.kill with signal 0
            try:
                os.kill(self._pid, 0)
            except ProcessLookupError:
                self._process_died = True
            except PermissionError:
                pass  # Process exists but we lack permission
        except Exception:
            pass

    def _check_memory(self):
        """Check RSS memory usage."""
        if self._memory_warned:
            return
        try:
            import psutil
            if not psutil.pid_exists(self._pid):
                return
            proc = psutil.Process(self._pid)
            rss_mb = proc.memory_info().rss / (1024 * 1024)
            self._peak_rss_mb = max(self._peak_rss_mb, rss_mb)

            total_mb = psutil.virtual_memory().total / (1024 * 1024)
            if total_mb > 0 and (rss_mb / total_mb) > self._memory_warn_fraction:
                self._memory_warned = True
                self._add_result(CheckResult(
                    level=2, name="monitor_memory_high",
                    severity=Severity.WARN,
                    message=f"Process RSS={rss_mb:.0f} MB "
                            f"({rss_mb/total_mb*100:.0f}% of system RAM)",
                    fix_hint="Risk of OOM kill. Reduce domain, resolution, or output frequency.",
                    time_saved_hours=1.0,
                ))
        except ImportError:
            pass
        except Exception:
            pass

    def _check_output_stall(self):
        """Check if new output files have been created."""
        if self._stall_warned or not self._output_dir:
            return
        if not os.path.isdir(self._output_dir):
            return

        current_count = len(os.listdir(self._output_dir))
        now = time.time()
        if current_count > self._last_output_count:
            self._last_output_count = current_count
            self._last_output_time = now
        elif (now - self._last_output_time) > self._stall_timeout:
            self._stall_warned = True
            elapsed_min = (now - self._last_output_time) / 60.0
            self._add_result(CheckResult(
                level=2, name="monitor_output_stall",
                severity=Severity.WARN,
                message=f"No new output files for {elapsed_min:.1f} minutes "
                        f"(count stuck at {current_count})",
                fix_hint="Process may be stuck in a long computation or hung. "
                         "Check CPU usage with 'top' or 'ps'.",
                time_saved_hours=1.0,
            ))

    def _check_log_errors(self):
        """Scan log files for new error patterns."""
        for lf in self._log_files:
            if not os.path.isfile(lf):
                continue
            try:
                current_size = os.path.getsize(lf)
                prev_size = self._last_log_sizes.get(lf, 0)
                if current_size <= prev_size:
                    continue

                with open(lf, 'r', errors='replace') as f:
                    f.seek(prev_size)
                    new_text = f.read()

                self._last_log_sizes[lf] = current_size

                for pattern, hint in self._ERROR_PATTERNS.items():
                    if pattern == "error":
                        continue  # Skip generic, too noisy
                    if pattern.lower() in new_text.lower():
                        self._add_result(CheckResult(
                            level=2, name=f"monitor_log_{pattern.replace(' ', '_')}",
                            severity=Severity.WARN,
                            message=f"Log '{os.path.basename(lf)}' contains: '{pattern}'",
                            fix_hint=hint or "Check log file for details.",
                        ))
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Feature 4: Level 5 — Regression Suite
# ---------------------------------------------------------------------------

_DEFAULT_REGRESSION_TOLERANCES = {
    "NSE": 0.1,
    "nse": 0.1,
    "r": 0.05,
    "R2": 0.05,
    "r2": 0.05,
    "PBIAS": 10.0,
    "pbias": 10.0,
    "KGE": 0.1,
    "kge": 0.1,
    "RMSE": None,  # absolute; need context
}


def check_level5_regression(
    current_metrics: Dict[str, float],
    baseline_file: str,
    tolerance: Optional[Dict[str, float]] = None,
) -> List[CheckResult]:
    """Compare current metrics against a stored baseline.

    baseline_file: JSON with {"NSE": 0.68, "r": 0.83, "PBIAS": 10.5, ...}
    tolerance: {"NSE": 0.05, "r": 0.03, "PBIAS": 5.0} -- max allowed degradation

    Default tolerances: NSE +/-0.1, r +/-0.05, PBIAS +/-10%

    FAIL if any metric degrades beyond tolerance.
    WARN if within tolerance but degraded.
    """
    results = []

    if not os.path.isfile(baseline_file):
        results.append(CheckResult(
            level=5, name="regression_baseline", severity=Severity.WARN,
            message=f"Baseline file not found: {baseline_file}",
            fix_hint="Create baseline with a known-good run: "
                     "json.dumps({'NSE': 0.68, ...}) > baseline.json",
        ))
        return results

    try:
        with open(baseline_file, 'r') as f:
            baseline = json.load(f)
    except Exception as e:
        results.append(CheckResult(
            level=5, name="regression_baseline", severity=Severity.WARN,
            message=f"Could not parse baseline file: {e}",
        ))
        return results

    tol = dict(_DEFAULT_REGRESSION_TOLERANCES)
    if tolerance:
        tol.update(tolerance)

    # Metrics where HIGHER is better (degradation = current < baseline)
    higher_is_better = {"NSE", "nse", "r", "R2", "r2", "KGE", "kge"}
    # Metrics where LOWER absolute value is better (degradation = |current| > |baseline|)
    lower_abs_better = {"PBIAS", "pbias", "RMSE", "rmse"}

    for metric_name, baseline_val in baseline.items():
        if metric_name not in current_metrics:
            results.append(CheckResult(
                level=5, name=f"regression_{metric_name}",
                severity=Severity.WARN,
                message=f"Metric '{metric_name}' in baseline but not in current results",
            ))
            continue

        current_val = current_metrics[metric_name]
        metric_tol = tol.get(metric_name)

        if metric_name in higher_is_better:
            # Degradation = baseline - current (positive means got worse)
            degradation = baseline_val - current_val
            if metric_tol is not None and degradation > metric_tol:
                results.append(CheckResult(
                    level=5, name=f"regression_{metric_name}",
                    severity=Severity.FAIL,
                    message=f"{metric_name} degraded beyond tolerance: "
                            f"{current_val:.4f} vs baseline {baseline_val:.4f} "
                            f"(delta={degradation:+.4f}, tolerance={metric_tol})",
                    fix_hint=f"Check what changed since baseline. "
                             f"Max allowed degradation: {metric_tol}.",
                    time_saved_hours=2.0,
                ))
            elif degradation > 0:
                results.append(CheckResult(
                    level=5, name=f"regression_{metric_name}",
                    severity=Severity.WARN,
                    message=f"{metric_name} slightly degraded: "
                            f"{current_val:.4f} vs baseline {baseline_val:.4f} "
                            f"(delta={degradation:+.4f})",
                ))
            else:
                results.append(CheckResult(
                    level=5, name=f"regression_{metric_name}",
                    severity=Severity.PASS,
                    message=f"{metric_name} maintained or improved: "
                            f"{current_val:.4f} vs baseline {baseline_val:.4f}",
                ))
        elif metric_name in lower_abs_better:
            # Degradation = |current| - |baseline| (positive means got worse)
            degradation = abs(current_val) - abs(baseline_val)
            if metric_tol is not None and degradation > metric_tol:
                results.append(CheckResult(
                    level=5, name=f"regression_{metric_name}",
                    severity=Severity.FAIL,
                    message=f"{metric_name} degraded beyond tolerance: "
                            f"{current_val:.4f} vs baseline {baseline_val:.4f} "
                            f"(|delta|={degradation:+.4f}, tolerance={metric_tol})",
                    fix_hint=f"Check what changed since baseline. "
                             f"Max allowed degradation: {metric_tol}.",
                    time_saved_hours=2.0,
                ))
            elif degradation > 0:
                results.append(CheckResult(
                    level=5, name=f"regression_{metric_name}",
                    severity=Severity.WARN,
                    message=f"{metric_name} slightly degraded: "
                            f"{current_val:.4f} vs baseline {baseline_val:.4f}",
                ))
            else:
                results.append(CheckResult(
                    level=5, name=f"regression_{metric_name}",
                    severity=Severity.PASS,
                    message=f"{metric_name} maintained or improved: "
                            f"{current_val:.4f} vs baseline {baseline_val:.4f}",
                ))
        else:
            # Unknown metric direction — just compare
            diff = abs(current_val - baseline_val)
            if metric_tol is not None and diff > metric_tol:
                results.append(CheckResult(
                    level=5, name=f"regression_{metric_name}",
                    severity=Severity.WARN,
                    message=f"{metric_name} changed: {current_val:.4f} vs "
                            f"baseline {baseline_val:.4f} (delta={diff:.4f})",
                ))
            else:
                results.append(CheckResult(
                    level=5, name=f"regression_{metric_name}",
                    severity=Severity.PASS,
                    message=f"{metric_name} stable: {current_val:.4f} vs "
                            f"baseline {baseline_val:.4f}",
                ))

    return results


# ---------------------------------------------------------------------------
# Feature 5: Level 6 — Agent Audit
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_PATTERNS = {
    "read_skill": ["SKILL.md", "knowledge_infrastructure"],
    "used_ki_tools": ["nasa_power_to_ldasin", "build_geo_em", "build_fulldom"],
    "avoided_custom": [r"cat <<EOF", "matplotlib", r"custom.*script"],
    "applied_fixes": ["rst_typ", "SMOIS", r"arid.*fix", "Section 21"],
}


def check_level6_agent_audit(
    agent_log: str,
    expected_patterns: Optional[Dict[str, List[str]]] = None,
) -> List[CheckResult]:
    """Audit an AI agent's behavior from its session log.

    Default expected_patterns:
    {
        "read_skill": ["SKILL.md", "knowledge_infrastructure"],
        "used_ki_tools": ["nasa_power_to_ldasin", "build_geo_em", "build_fulldom"],
        "avoided_custom": ["cat <<EOF", "matplotlib", "custom.*script"],
        "applied_fixes": ["rst_typ", "SMOIS", "arid.*fix", "Section 21"],
    }

    For each pattern group:
    - "read_skill": PASS if any pattern found in log
    - "used_ki_tools": PASS if any KI tool path found
    - "avoided_custom": WARN if any custom code pattern found
    - "applied_fixes": INFO if fixes were applied (context-dependent)
    """
    results = []
    patterns = expected_patterns or dict(_DEFAULT_AGENT_PATTERNS)

    if not os.path.isfile(agent_log):
        results.append(CheckResult(
            level=6, name="agent_log_exists", severity=Severity.WARN,
            message=f"Agent log file not found: {agent_log}",
            fix_hint="Provide the session log path from ~/.claude/sessions/",
        ))
        return results

    try:
        with open(agent_log, 'r', errors='replace') as f:
            log_text = f.read()
    except Exception as e:
        results.append(CheckResult(
            level=6, name="agent_log_read", severity=Severity.WARN,
            message=f"Could not read agent log: {e}",
        ))
        return results

    # --- read_skill: PASS if any pattern found ---
    read_skill_patterns = patterns.get("read_skill", [])
    if read_skill_patterns:
        found = any(
            re.search(p, log_text, re.IGNORECASE) for p in read_skill_patterns
        )
        if found:
            results.append(CheckResult(
                level=6, name="agent_read_skill", severity=Severity.PASS,
                message="Agent read SKILL.md / knowledge_infrastructure before running",
            ))
        else:
            results.append(CheckResult(
                level=6, name="agent_read_skill", severity=Severity.FAIL,
                message="Agent did NOT read SKILL.md before running",
                fix_hint="Agents must read models/<Model>/knowledge_infrastructure/SKILL.md "
                         "before executing any model. This is a mandatory step.",
                time_saved_hours=3.0,
            ))

    # --- used_ki_tools: PASS if any KI tool found ---
    ki_tool_patterns = patterns.get("used_ki_tools", [])
    if ki_tool_patterns:
        found_tools = [
            p for p in ki_tool_patterns
            if re.search(p, log_text, re.IGNORECASE)
        ]
        if found_tools:
            results.append(CheckResult(
                level=6, name="agent_used_ki_tools", severity=Severity.PASS,
                message=f"Agent used KI tools: {', '.join(found_tools)}",
            ))
        else:
            results.append(CheckResult(
                level=6, name="agent_used_ki_tools", severity=Severity.WARN,
                message="Agent did not use any recognized KI tools",
                detail=f"Expected one of: {', '.join(ki_tool_patterns)}",
                fix_hint="Use validated KI tools instead of custom scripts. "
                         "Custom scripts reintroduce bugs that KI tools prevent.",
                time_saved_hours=2.0,
            ))

    # --- avoided_custom: WARN if custom code patterns found ---
    custom_patterns = patterns.get("avoided_custom", [])
    if custom_patterns:
        found_custom = [
            p for p in custom_patterns
            if re.search(p, log_text, re.IGNORECASE)
        ]
        if found_custom:
            results.append(CheckResult(
                level=6, name="agent_avoided_custom", severity=Severity.WARN,
                message=f"Agent used custom code patterns: {', '.join(found_custom)}",
                fix_hint="Prefer validated KI tools over custom scripts. "
                         "Custom code is the #1 agent failure mode.",
                time_saved_hours=2.0,
            ))
        else:
            results.append(CheckResult(
                level=6, name="agent_avoided_custom", severity=Severity.PASS,
                message="Agent avoided custom code patterns (good)",
            ))

    # --- applied_fixes: INFO if fixes were applied ---
    fix_patterns = patterns.get("applied_fixes", [])
    if fix_patterns:
        found_fixes = [
            p for p in fix_patterns
            if re.search(p, log_text, re.IGNORECASE)
        ]
        if found_fixes:
            results.append(CheckResult(
                level=6, name="agent_applied_fixes", severity=Severity.INFO,
                message=f"Agent applied known fixes: {', '.join(found_fixes)}",
            ))
        else:
            results.append(CheckResult(
                level=6, name="agent_applied_fixes", severity=Severity.INFO,
                message="No known fix patterns detected (may not be needed)",
            ))

    return results


# ---------------------------------------------------------------------------
# Orchestrator: run_triage()
# ---------------------------------------------------------------------------

def run_triage(
    model: str,
    domain: str,
    run_dir: str,
    levels: Sequence[int] = (0, 1, 2, 3),
    binary_path: Optional[str] = None,
    required_files: Optional[List[str]] = None,
    required_dirs: Optional[List[str]] = None,
    input_values: Optional[Dict[str, np.ndarray]] = None,
    log_file: Optional[str] = None,
    exit_code: Optional[int] = None,
    triplets_yaml: Optional[str] = None,
    output_values: Optional[Dict[str, np.ndarray]] = None,
    metrics: Optional[Dict[str, float]] = None,
    calibrated: bool = False,
    stop_on_block: bool = True,
    baseline_file: str = "",
    regression_tolerance: Optional[Dict[str, float]] = None,
    agent_log: str = "",
    agent_patterns: Optional[Dict[str, List[str]]] = None,
) -> TriageReport:
    """Run the universal debug triage pipeline.

    Levels are run in order. If stop_on_block=True and a BLOCK is found,
    subsequent levels are skipped (fix the blocker first).

    Args:
        model: Model name (e.g., "WRF-Hydro", "SWAT+", "DSSAT")
        domain: Model domain for domain-specific checks
                ("hydrology", "crop", "groundwater", "lake",
                 "biogeochemistry", "flood", "water_quality",
                 "glacier", "urban", "general")
        run_dir: Path to the model run directory
        levels: Which triage levels to run (default 0-3)
        binary_path: Path to model executable (Level 0)
        required_files: List of required input files (Level 0)
        required_dirs: List of required input directories (Level 0)
        input_values: Dict of input variable arrays (Level 1)
        log_file: Path to model log file (Level 2)
        exit_code: Model process exit code (Level 2)
        triplets_yaml: Path to model's diagnostics/triplets.yaml (Level 2)
        output_values: Dict of output variable arrays (Level 3)
        metrics: Dict of performance metrics (Level 4)
        calibrated: Whether the model has been calibrated (Level 4)
        stop_on_block: Stop at first BLOCK severity (default True)
        baseline_file: Path to baseline JSON for Level 5 regression checks
        regression_tolerance: Custom tolerances for Level 5 (e.g., {"NSE": 0.05})
        agent_log: Path to agent session log for Level 6 audit
        agent_patterns: Custom pattern dict for Level 6 agent audit

    Returns:
        TriageReport with all check results.
    """
    report = TriageReport(model=model, domain=domain, run_dir=run_dir)

    # Level 0: Existence
    if 0 in levels:
        for r in check_level0_existence(
            run_dir, binary_path, required_files, required_dirs
        ):
            report.add(r)
        if stop_on_block and not report.level_passed(0):
            return report

    # Level 1: Input ranges
    if 1 in levels and input_values:
        for name, values in input_values.items():
            # Look up bounds from universal table
            bounds = UNIVERSAL_BOUNDS.get(name)
            if bounds:
                vmin, vmax, hint = bounds
                report.add(check_value_range(name, values, vmin, vmax, hint, level=1))
            # Always check for constant/fill
            report.add(check_constant_or_fill(name, values, level=1))
        if stop_on_block and not report.level_passed(1):
            return report

    # Level 2: Execution
    if 2 in levels:
        for r in check_level2_execution(
            run_dir, log_file, exit_code, triplets_yaml
        ):
            report.add(r)
        if stop_on_block and not report.level_passed(2):
            return report

    # Level 3: Output plausibility
    if 3 in levels and output_values:
        for r in check_level3_outputs(output_values, domain):
            report.add(r)

    # Level 4: Domain metrics
    if 4 in levels and metrics:
        for r in check_level4_domain(metrics, domain, calibrated):
            report.add(r)

    # Level 5: Regression
    if 5 in levels and baseline_file:
        current = metrics or {}
        for r in check_level5_regression(current, baseline_file, regression_tolerance):
            report.add(r)

    # Level 6: Agent audit
    if 6 in levels and agent_log:
        for r in check_level6_agent_audit(agent_log, agent_patterns):
            report.add(r)

    return report
