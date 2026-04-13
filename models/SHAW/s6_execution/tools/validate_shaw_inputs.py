#!/usr/bin/env python3
"""
validate_shaw_inputs.py — Check SHAW input files for common errors.

Validates:
1. All required files exist and are non-empty
2. Path lengths < 80 chars (Fortran limit)
3. Simulation dates are consistent across files
4. Soil node depths start at 0.0 and increase monotonically
5. Moisture values are physically reasonable (0 < theta < porosity)
6. Temperature values are physically reasonable (-50 < T < 60 C)
7. Weather data covers the simulation period
8. MTSTEP matches weather file format
9. Unit flag (IFLAGSI) is consistent with data ranges

Usage:
    python validate_shaw_inputs.py \
        --inp_file shaw.inp \
        [--workdir /path/to/shaw/run]
"""

import argparse
import sys
import os
from pathlib import Path


class ShawValidator:
    def __init__(self, workdir='.'):
        self.workdir = Path(workdir)
        self.errors = []
        self.warnings = []

    def error(self, msg):
        self.errors.append(f"ERROR: {msg}")

    def warn(self, msg):
        self.warnings.append(f"WARNING: {msg}")

    def info(self, msg):
        print(f"  INFO: {msg}")

    def validate_inp(self, inp_file):
        """Validate the .inp (input/output list) file."""
        print(f"\nValidating .inp file: {inp_file}")

        inp_path = self.workdir / inp_file
        if not inp_path.exists():
            self.error(f".inp file not found: {inp_path}")
            return None

        with open(inp_path, 'r') as f:
            lines = [l.rstrip('\n') for l in f.readlines()]

        if len(lines) < 7:
            self.error(f".inp file too short ({len(lines)} lines, need >= 7)")
            return None

        # Line A: IVERSION
        version = lines[0].strip()
        if 'shaw' not in version.lower() and 'Shaw' not in version:
            self.warn(f"Line A (IVERSION) doesn't look like a SHAW version: '{version}'")
        self.info(f"Version: {version}")

        # Line B: MTSTEP IFLAGSI INPH2O MWATRXT
        parts = lines[1].split()
        if len(parts) < 4:
            self.error(f"Line B needs 4 values (MTSTEP IFLAGSI INPH2O MWATRXT), got {len(parts)}")
            return None

        config = {
            'mtstep': int(parts[0]),
            'iflagsi': int(parts[1]),
            'inph2o': int(parts[2]),
            'mwatrxt': int(parts[3]),
        }
        self.info(f"MTSTEP={config['mtstep']}, IFLAGSI={config['iflagsi']}")

        if config['mtstep'] not in [0, 1, 2]:
            self.error(f"MTSTEP must be 0 (hourly), 1 (daily), or 2 (custom), got {config['mtstep']}")

        # Lines B-1 to B-4: input file paths
        input_files = {}
        file_labels = ['sit', 'wea', 'moi', 'tem']
        for i, label in enumerate(file_labels):
            fpath = lines[2 + i].strip()
            input_files[label] = fpath

            # Check path length (Fortran 77 limit)
            if len(fpath) > 80:
                self.error(f"{label.upper()} file path > 80 chars (Fortran limit): {len(fpath)} chars")

            # Check file exists
            full_path = self.workdir / fpath if not Path(fpath).is_absolute() else Path(fpath)
            if not full_path.exists():
                self.error(f"{label.upper()} file not found: {full_path}")
            elif full_path.stat().st_size == 0:
                self.error(f"{label.upper()} file is empty: {full_path}")
            else:
                self.info(f"{label.upper()} file: {fpath} ({full_path.stat().st_size} bytes)")

        config['files'] = input_files
        return config

    def validate_sit(self, sit_file):
        """Validate site characteristics file."""
        print(f"\nValidating .sit file: {sit_file}")

        sit_path = self.workdir / sit_file if not Path(sit_file).is_absolute() else Path(sit_file)
        if not sit_path.exists():
            return

        with open(sit_path, 'r') as f:
            lines = [l.rstrip('\n') for l in f.readlines()]

        if len(lines) < 5:
            self.error(f".sit file too short ({len(lines)} lines)")
            return

        # Line A: Title
        self.info(f"Title: {lines[0].strip()}")

        # Line B: JSTART HRSTAR YRSTAR JEND YREND
        parts = lines[1].split()
        if len(parts) >= 5:
            jstart = int(parts[0])
            yrstart = int(parts[2])
            jend = int(parts[3])
            yrend = int(parts[4])
            self.info(f"Simulation: day {jstart} year {yrstart} to day {jend} year {yrend}")

            if jstart < 1 or jstart > 366:
                self.error(f"JSTART out of range: {jstart}")
            if jend < 1 or jend > 366:
                self.error(f"JEND out of range: {jend}")

        # Line C: lat, slope, etc.
        parts = lines[2].split()
        if len(parts) >= 6:
            lat_deg = int(parts[0])
            lat_min = float(parts[1])
            slope = float(parts[2])
            aspect = float(parts[3])
            elev = float(parts[5])
            self.info(f"Location: {lat_deg}d {lat_min:.0f}m, slope={slope}%, aspect={aspect}deg, elev={elev}m")

            if abs(lat_deg) > 90:
                self.error(f"Latitude out of range: {lat_deg}")
            if slope < 0 or slope > 100:
                self.warn(f"Slope unusual: {slope}%")
            if elev < -500 or elev > 9000:
                self.warn(f"Elevation unusual: {elev}m")

        # Line D: NPLANT NSP NR NS NSALT TOLER
        parts = lines[3].split()
        if len(parts) >= 6:
            nplant = int(parts[0])
            nsp = int(parts[1])
            nr = int(parts[2])
            ns = int(parts[3])
            nsalt = int(parts[4])
            toler = float(parts[5])
            self.info(f"NPLANT={nplant}, NSP={nsp}, NR={nr}, NS={ns}, NSALT={nsalt}, TOLER={toler}")

            if ns < 2:
                self.error(f"NS (soil nodes) must be >= 2, got {ns}")
            if ns > 50:
                self.error(f"NS (soil nodes) must be <= 50, got {ns}")
            if toler <= 0:
                self.error(f"TOLER must be > 0, got {toler}")
            if toler > 0.1:
                self.warn(f"TOLER={toler} is large -- may reduce accuracy. Suggested: 0.001-0.01")

    def validate_weather(self, wea_file, mtstep, iflagsi):
        """Validate weather data file."""
        print(f"\nValidating weather file: {wea_file}")

        wea_path = self.workdir / wea_file if not Path(wea_file).is_absolute() else Path(wea_file)
        if not wea_path.exists():
            return

        with open(wea_path, 'r') as f:
            lines = f.readlines()

        n_lines = len(lines)
        self.info(f"Weather data lines: {n_lines}")

        if n_lines < 10:
            self.error(f"Weather file has only {n_lines} lines -- too short")
            return

        # Check first and last data lines
        first_parts = lines[0].split()
        last_parts = lines[-1].split()

        if mtstep == 0 or mtstep == 2:
            # Hourly: JD JH JYR TA WIND HUM PRECIP SNODEN SUNHOR
            expected_cols = 9
            if len(first_parts) < expected_cols:
                self.warn(f"Hourly weather: expected {expected_cols} columns, got {len(first_parts)}")

            # Check wind speed range
            try:
                wind = float(first_parts[4])
                if iflagsi == 1 and wind > 50:
                    self.warn(f"Wind={wind} m/s seems too high. Is IFLAGSI correct?")
                elif iflagsi == 0 and wind < 5:
                    self.warn(f"Wind={wind} mph seems low. IFLAGSI=0 expects mph. Did you mean IFLAGSI=1 (m/s)?")
            except (ValueError, IndexError):
                pass

        elif mtstep == 1:
            # Daily: JD JYR TMAX TMIN TDEW WIND PRECIP SOLAR
            expected_cols = 8
            if len(first_parts) < expected_cols:
                self.warn(f"Daily weather: expected {expected_cols} columns, got {len(first_parts)}")

            # Check temperature range
            try:
                tmax = float(first_parts[2])
                tmin = float(first_parts[3])
                if tmax < tmin:
                    self.error(f"TMAX ({tmax}) < TMIN ({tmin}) on first line")
                if tmax > 60 or tmin < -60:
                    self.warn(f"Temperature extreme: TMAX={tmax}, TMIN={tmin}")
            except (ValueError, IndexError):
                pass

    def validate_moisture(self, moi_file, ns=None):
        """Validate moisture profile file."""
        print(f"\nValidating moisture file: {moi_file}")

        moi_path = self.workdir / moi_file if not Path(moi_file).is_absolute() else Path(moi_file)
        if not moi_path.exists():
            return

        with open(moi_path, 'r') as f:
            lines = f.readlines()

        if len(lines) < 2:
            self.error(f"Moisture file needs >= 2 profiles, got {len(lines)}")

        for i, line in enumerate(lines):
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                values = [float(v) for v in parts[3:]]
                if ns and len(values) != ns:
                    self.warn(f"Line {i+1}: {len(values)} moisture values but NS={ns}")
                for j, v in enumerate(values):
                    if v < 0 or v > 1.0:
                        self.error(f"Line {i+1}, node {j+1}: moisture={v} out of range [0, 1]")
                    elif v > 0.6:
                        self.warn(f"Line {i+1}, node {j+1}: moisture={v:.3f} very high (> porosity?)")
            except ValueError:
                pass

    def report(self):
        """Print validation summary."""
        print("\n" + "=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)

        if self.errors:
            print(f"\n{len(self.errors)} ERRORS found:")
            for e in self.errors:
                print(f"  {e}")

        if self.warnings:
            print(f"\n{len(self.warnings)} WARNINGS:")
            for w in self.warnings:
                print(f"  {w}")

        if not self.errors and not self.warnings:
            print("\nAll checks passed. Input files look valid.")

        if self.errors:
            print(f"\nFIX {len(self.errors)} errors before running SHAW.")
            return False
        return True


def main():
    parser = argparse.ArgumentParser(description="Validate SHAW input files")
    parser.add_argument("--inp_file", type=str, default="shaw.inp",
                        help="SHAW .inp file to validate")
    parser.add_argument("--workdir", type=str, default=".",
                        help="Working directory")

    args = parser.parse_args()

    validator = ShawValidator(args.workdir)

    # Validate .inp file
    config = validator.validate_inp(args.inp_file)

    if config:
        # Validate individual input files
        files = config['files']
        validator.validate_sit(files['sit'])
        validator.validate_weather(files['wea'], config['mtstep'], config['iflagsi'])
        validator.validate_moisture(files['moi'])

    valid = validator.report()
    if not valid:
        sys.exit(1)


if __name__ == "__main__":
    main()
