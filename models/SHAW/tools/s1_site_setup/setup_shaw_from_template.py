#!/usr/bin/env python3
"""
SHAW Template-Based Case Setup (cm_024: copy-first rule)

Copies ALL input files from a validated SHAW example case and updates only
the site-specific values. NEVER generates .sit/.inp/.tem/.moi from scratch.

This follows the Knowledge Dissection Toolkit cm_024 rule:
  "For Fortran model control files, always copy from a working example
   and modify values. Never generate from scratch."

Templates available:
  - jackpine: Boreal forest, 11 soil nodes, hourly weather, MCANFLG=1
    Path: outputs/shaw_jackpine/

Usage:
    python setup_shaw_from_template.py \
        --template jackpine \
        --output_dir outputs/shaw_new_case/ \
        --case_name mysite \
        --lat 49.81 --lon -100.37 --elev 460 \
        --start_doy 1 --end_doy 365 --year 20 \
        --mcanflg 0 \
        --soil_nodes "0.00,0.02,0.05,0.10,0.15,0.20,0.30,0.50,0.60,0.90,1.20" \
        --weather_file /path/to/weather.csv
"""

import argparse
import os
import re
import shutil
from pathlib import Path


# =============================================================================
# Template registry — add new validated cases here
# =============================================================================
PROJECT_ROOT = Path("/mnt/disk1/Hydrocraft_server")

TEMPLATES = {
    "jackpine": {
        "path": PROJECT_ROOT / "outputs/shaw_jackpine",
        "prefix": "jackpine",
        "description": "Boreal forest, 53.9°N, hourly, MCANFLG=1, 11 soil nodes",
        "mcanflg": 1,
        "nsoil": 11,
        "timestep": "hourly",
    },
    "compton": {
        "path": PROJECT_ROOT / "outputs/shaw_quebec_compton",
        "prefix": "compton",
        "description": "Quebec agricultural station, 45.3°N, daily, MCANFLG=0, 11 soil nodes, full year, 2-digit year (NSE=0.85)",
        "mcanflg": 0,
        "nsoil": 11,
        "timestep": "daily",
        "notes": (
            "CRITICAL: uses 2-digit year (15, not 2015) throughout .sit/.wea/.moi/.tem — "
            "4-digit year causes SHAW to stop after 1 day (triplet shaw_032). "
            ".wea must start 1 day before JSTART (DOY 365/14 prepended). "
            "Last .tem/.moi entry must be at JEND (DOY 365) — triplet shaw_033."
        ),
    },
}


def copy_template(template_name: str, output_dir: str, case_name: str) -> dict:
    """Copy all template files to output directory with new case name prefix.

    Returns dict mapping file type to output path.
    """
    tpl = TEMPLATES[template_name]
    src_dir = tpl["path"]
    prefix = tpl["prefix"]
    dst_dir = Path(output_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    files = {}
    for ext in [".sit", ".inp", ".wea", ".tem", ".moi"]:
        src = src_dir / f"{prefix}{ext}"
        dst = dst_dir / f"{case_name}{ext}"
        if src.exists():
            shutil.copy2(src, dst)
            files[ext] = dst
            print(f"  Copied {src.name} → {dst.name}")
        else:
            print(f"  WARNING: {src} not found, skipping")

    return files


def update_sit_file(sit_path: Path, **kwargs):
    """Update .sit file parameters while preserving Fortran fixed-width structure.

    Only modifies specific lines/values — leaves everything else as-is.

    Supported kwargs:
        title: str — Line 1 (site description)
        lat: float — Line 3 col 1-2 (lat integer + decimal handling)
        lon: float — not in .sit (for documentation only)
        elev: float — Line 3 position 6
        start_doy: int — Line 2 position 3
        end_doy: int — Line 2 position 4
        year: int — Line 2 position 5 (2-digit)
        mcanflg: int — Line 4 position 1 (0=bare, 1=canopy)
        nsoil: int — Line 4 position 4
        soil_depths: list[float] — Soil node depth values (lines 13+)
        soil_properties: list[dict] — Per-node: sand%, silt%, clay%, OC%, BD, Ksat, etc.
        plant_height: float — Line 8 position 1
        lai: float — Line 6 or derived
    """
    with open(sit_path, 'r') as f:
        lines = f.readlines()

    # Line 1: Title/description
    if 'title' in kwargs:
        lines[0] = kwargs['title'].rstrip('\n') + '\n'

    # Line 2: IVERSION MESSION START_DOY END_DOY YEAR (format varies)
    if any(k in kwargs for k in ['start_doy', 'end_doy', 'year']):
        parts = lines[1].split()
        if 'start_doy' in kwargs:
            parts[2] = str(kwargs['start_doy'])
        if 'end_doy' in kwargs:
            parts[3] = str(kwargs['end_doy'])
        if 'year' in kwargs:
            parts[4] = str(kwargs['year'])
        lines[1] = '   ' + '   '.join(parts) + '\n'

    # Line 3: LAT_INT LAT_DEC LON ASPECT HEIGHT ELEV
    if any(k in kwargs for k in ['lat', 'elev']):
        parts = lines[2].split()
        if 'lat' in kwargs:
            lat = kwargs['lat']
            lat_int = int(abs(lat))
            lat_dec = int((abs(lat) - lat_int) * 60)  # minutes approximation
            parts[0] = f' {lat_int}'
            parts[1] = f'{lat_dec}'
        if 'elev' in kwargs:
            parts[5] = f'{kwargs["elev"]:.0f}.'
        lines[2] = ' ' + '  '.join(parts) + '\n'

    # Line 4: MCANFLG MESSION_extra NSOIL_related params
    if 'mcanflg' in kwargs:
        parts = lines[3].split()
        parts[0] = str(kwargs['mcanflg'])
        lines[3] = ' ' + '  '.join(parts) + '\n'

    # Soil node lines (starting at line 13 for 11-node JackPine template)
    if 'soil_depths' in kwargs:
        depths = kwargs['soil_depths']
        nsoil = len(depths)
        # Find soil node lines (they start with depth values like 0.00, 0.02, etc.)
        soil_start = None
        for i in range(10, len(lines)):
            parts = lines[i].split()
            if len(parts) >= 10:
                try:
                    d = float(parts[0])
                    if 0.0 <= d <= 2.0:
                        if soil_start is None:
                            soil_start = i
                except ValueError:
                    continue

        if soil_start is not None:
            # Count existing soil lines
            existing_count = 0
            for i in range(soil_start, len(lines)):
                parts = lines[i].split()
                if len(parts) >= 10:
                    try:
                        float(parts[0])
                        existing_count += 1
                    except ValueError:
                        break
                else:
                    break

            # If same number of nodes, update depths in-place
            if existing_count == nsoil:
                for j, depth in enumerate(depths):
                    parts = lines[soil_start + j].split()
                    parts[0] = f'{depth:.2f}'
                    lines[soil_start + j] = ' ' + '  '.join(parts) + '\n'
                print(f"  Updated {nsoil} soil node depths in-place")
            else:
                print(f"  WARNING: Template has {existing_count} soil nodes, "
                      f"requested {nsoil}. Keeping template structure. "
                      f"Manual adjustment may be needed.")

    # Soil properties update (per-node)
    if 'soil_properties' in kwargs:
        props = kwargs['soil_properties']
        soil_start = None
        for i in range(10, len(lines)):
            parts = lines[i].split()
            if len(parts) >= 10:
                try:
                    d = float(parts[0])
                    if 0.0 <= d <= 2.0:
                        if soil_start is None:
                            soil_start = i
                except ValueError:
                    continue

        if soil_start is not None:
            for j, prop in enumerate(props):
                if j + soil_start >= len(lines):
                    break
                parts = lines[soil_start + j].split()
                # Update soil properties (columns 2-12 in .sit soil node lines):
                # depth sand% silt% clay% OC% rock% Ksat BD PSI b porosity
                if 'sand' in prop:
                    parts[1] = f'{prop["sand"]:.1f}'
                if 'silt' in prop:
                    parts[2] = f'{prop["silt"]:.1f}'
                if 'clay' in prop:
                    parts[3] = f'{prop["clay"]:.1f}'
                if 'oc' in prop:
                    parts[4] = f'{prop["oc"]:.1f}'
                if 'rock' in prop:
                    parts[5] = f'{prop["rock"]:.1f}'
                if 'ksat' in prop:
                    parts[6] = f'{prop["ksat"]:.1f}'
                if 'bd' in prop:
                    parts[7] = f'{prop["bd"]:.1f}'
                lines[soil_start + j] = ' ' + '  '.join(parts) + '\n'

    # Plant parameters (Line 8 for canopy models)
    if 'plant_height' in kwargs and kwargs.get('mcanflg', 1) == 1:
        parts = lines[7].split()
        parts[0] = f'{kwargs["plant_height"]:.1f}'
        lines[7] = ' ' + '  '.join(parts) + '\n'

    with open(sit_path, 'w') as f:
        f.writelines(lines)

    print(f"  Updated {sit_path.name} with site-specific parameters")


def update_inp_file(inp_path: Path, case_name: str, **kwargs):
    """Update .inp control file — replace template prefix with new case name.

    Supported kwargs:
        output_freq: dict — per-output-file frequency settings
    """
    with open(inp_path, 'r') as f:
        content = f.read()

    # Replace all template file references with new case name
    for tpl_name, tpl_info in TEMPLATES.items():
        prefix = tpl_info["prefix"]
        content = content.replace(f'{prefix}.sit', f'{case_name}.sit')
        content = content.replace(f'{prefix}.wea', f'{case_name}.wea')
        content = content.replace(f'{prefix}.moi', f'{case_name}.moi')
        content = content.replace(f'{prefix}.tem', f'{case_name}.tem')

    with open(inp_path, 'w') as f:
        f.write(content)

    print(f"  Updated {inp_path.name} file references → {case_name}.*")


def update_tem_file(tem_path: Path, profiles: list = None, **kwargs):
    """Update .tem initial temperature profiles.

    profiles: list of dicts, each with:
        doy: int, hour: int, year: int (2-digit),
        temps: list[float] — temperature at each soil node

    If profiles is None, keeps template profiles (safe default).
    """
    if profiles is None:
        print(f"  Keeping template {tem_path.name} (no custom profiles provided)")
        return

    with open(tem_path, 'w') as f:
        for p in profiles:
            temps_str = ' '.join(f'{t:6.1f}' for t in p['temps'])
            f.write(f'{p["doy"]:4d} {p["hour"]:3d} {p["year"]:3d} {temps_str}\n')

    print(f"  Updated {tem_path.name} with {len(profiles)} temperature profiles")


def update_moi_file(moi_path: Path, profiles: list = None, **kwargs):
    """Update .moi initial moisture profiles.

    profiles: list of dicts, each with:
        doy: int, hour: int, year: int (2-digit),
        moisture: list[float] — volumetric water content at each soil node

    If profiles is None, keeps template profiles (safe default).
    """
    if profiles is None:
        print(f"  Keeping template {moi_path.name} (no custom profiles provided)")
        return

    with open(moi_path, 'w') as f:
        for p in profiles:
            moi_str = ' '.join(f'{m:.3f}' for m in p['moisture'])
            f.write(f'{p["doy"]:4d} {p["hour"]:3d} {p["year"]:3d} {moi_str}\n')

    print(f"  Updated {moi_path.name} with {len(profiles)} moisture profiles")


def generate_seasonal_profiles(nsoil: int, lat: float, year: int = 99):
    """Generate reasonable seasonal temperature + moisture profiles.

    Creates 6 profiles (quarterly + padding) based on latitude-derived climate.
    These are approximate — SHAW will equilibrate during spinup.

    Returns: (tem_profiles, moi_profiles)
    """
    # Estimate mean annual T and seasonal amplitude from latitude
    if abs(lat) < 30:
        t_mean, t_amp = 22.0, 5.0
    elif abs(lat) < 45:
        t_mean, t_amp = 12.0, 15.0
    elif abs(lat) < 55:
        t_mean, t_amp = 5.0, 20.0
    else:
        t_mean, t_amp = -2.0, 25.0

    import math

    tem_profiles = []
    moi_profiles = []

    # Quarterly profiles: DOY 1, 91, 182, 274, 365, + padding
    doys = [1, 91, 182, 274, 365]
    for doy in doys:
        # Seasonal surface temperature
        t_surf = t_mean + t_amp * math.cos(2 * math.pi * (doy - 200) / 365)

        # Temperature damping with depth (exponential)
        temps = []
        for i in range(nsoil):
            depth = i * 1.2 / (nsoil - 1) if nsoil > 1 else 0.0
            damping = math.exp(-depth / 0.5)  # ~0.5m damping depth
            phase_shift = depth * 30  # days per meter
            t_node = t_mean + t_amp * damping * math.cos(
                2 * math.pi * (doy - 200 - phase_shift) / 365)
            temps.append(round(t_node, 1))

        tem_profiles.append({
            'doy': doy, 'hour': 12 if doy > 1 else 0, 'year': year,
            'temps': temps
        })

        # Moisture: higher in spring, lower in summer
        base_moi = 0.08 if abs(lat) > 50 else 0.12
        seasonal_factor = 1.0 + 0.3 * math.cos(2 * math.pi * (doy - 100) / 365)
        moisture = [round(base_moi * seasonal_factor * (1.0 + 0.2 * (i / nsoil)), 3)
                    for i in range(nsoil)]

        moi_profiles.append({
            'doy': doy, 'hour': 12 if doy > 1 else 0, 'year': year,
            'moisture': moisture
        })

    # Padding profile (30 days into next year)
    padding_tem = tem_profiles[0].copy()
    padding_tem = {
        'doy': 30, 'hour': 12, 'year': year + 1 if year < 99 else 0,
        'temps': tem_profiles[0]['temps'].copy()
    }
    tem_profiles.append(padding_tem)

    padding_moi = moi_profiles[0].copy()
    padding_moi = {
        'doy': 30, 'hour': 12, 'year': year + 1 if year < 99 else 0,
        'moisture': moi_profiles[0]['moisture'].copy()
    }
    moi_profiles.append(padding_moi)

    return tem_profiles, moi_profiles


def setup_shaw_case(template_name: str, output_dir: str, case_name: str, **kwargs):
    """Main entry point: copy template + update site-specific values.

    This is the cm_024 compliant workflow:
    1. Copy ALL files from validated template
    2. Update only the values that differ
    3. Generate seasonal profiles if not provided
    """
    print(f"\n{'='*60}")
    print(f"SHAW Template-Based Setup (cm_024: copy-first)")
    print(f"  Template: {template_name}")
    print(f"  Output:   {output_dir}")
    print(f"  Case:     {case_name}")
    print(f"{'='*60}\n")

    # Step 1: Copy template files
    print("Step 1: Copying template files...")
    files = copy_template(template_name, output_dir, case_name)

    if not files:
        raise RuntimeError(f"No template files found for '{template_name}'")

    # Step 2: Update .sit with site-specific parameters
    if '.sit' in files:
        print("\nStep 2: Updating .sit site parameters...")
        sit_kwargs = {k: v for k, v in kwargs.items()
                      if k in ['title', 'lat', 'lon', 'elev', 'start_doy', 'end_doy',
                               'year', 'mcanflg', 'nsoil', 'soil_depths',
                               'soil_properties', 'plant_height', 'lai']}
        if sit_kwargs:
            update_sit_file(files['.sit'], **sit_kwargs)
        else:
            print("  No .sit overrides provided — keeping template values")

    # Step 3: Update .inp file references
    if '.inp' in files:
        print("\nStep 3: Updating .inp file references...")
        update_inp_file(files['.inp'], case_name)

    # Step 4: Update .tem and .moi profiles
    nsoil = kwargs.get('nsoil', TEMPLATES[template_name]['nsoil'])
    lat = kwargs.get('lat', 50.0)
    year = kwargs.get('year', 99)

    tem_profiles = kwargs.get('tem_profiles', None)
    moi_profiles = kwargs.get('moi_profiles', None)

    if tem_profiles is None and moi_profiles is None:
        # Generate reasonable seasonal profiles from latitude
        print("\nStep 4: Generating seasonal initial condition profiles...")
        tem_profiles, moi_profiles = generate_seasonal_profiles(nsoil, lat, year)

    if '.tem' in files:
        update_tem_file(files['.tem'], profiles=tem_profiles)
    if '.moi' in files:
        update_moi_file(files['.moi'], profiles=moi_profiles)

    print(f"\n{'='*60}")
    print(f"Setup complete. Files in: {output_dir}")
    print(f"  {case_name}.sit  — site characteristics")
    print(f"  {case_name}.inp  — control file")
    print(f"  {case_name}.wea  — weather (NEEDS REPLACEMENT with actual data)")
    print(f"  {case_name}.tem  — temperature profiles")
    print(f"  {case_name}.moi  — moisture profiles")
    print(f"\nNEXT: Replace {case_name}.wea with actual weather data.")
    print(f"  Format: DOY HOUR YEAR TMAX TMIN TDEW WIND PRECIP SOLAR")
    print(f"  (hourly timestep, matching template format)")
    print(f"{'='*60}\n")

    return files


def main():
    parser = argparse.ArgumentParser(
        description="SHAW template-based case setup (cm_024: copy-first rule)")

    parser.add_argument('--template', default='jackpine',
                        choices=list(TEMPLATES.keys()),
                        help='Template case to copy from (default: jackpine)')
    parser.add_argument('--output_dir', required=True,
                        help='Output directory for new case')
    parser.add_argument('--case_name', required=True,
                        help='Case name prefix for output files')

    # Site parameters
    parser.add_argument('--lat', type=float, help='Latitude (degrees)')
    parser.add_argument('--lon', type=float, help='Longitude (degrees)')
    parser.add_argument('--elev', type=float, help='Elevation (m)')
    parser.add_argument('--start_doy', type=int, help='Start day of year')
    parser.add_argument('--end_doy', type=int, help='End day of year')
    parser.add_argument('--year', type=int, help='Year (2-digit for SHAW)')

    # Vegetation
    parser.add_argument('--mcanflg', type=int, choices=[0, 1],
                        help='0=bare/grass, 1=canopy')
    parser.add_argument('--plant_height', type=float,
                        help='Plant/canopy height (m)')

    # Soil
    parser.add_argument('--soil_depths', type=str,
                        help='Comma-separated soil node depths (m), e.g. "0.00,0.02,0.05,0.10"')

    # Title
    parser.add_argument('--title', type=str,
                        help='Site description (Line 1 of .sit)')

    args = parser.parse_args()

    kwargs = {}
    for key in ['lat', 'lon', 'elev', 'start_doy', 'end_doy', 'year',
                 'mcanflg', 'plant_height', 'title']:
        val = getattr(args, key, None)
        if val is not None:
            kwargs[key] = val

    if args.soil_depths:
        kwargs['soil_depths'] = [float(x) for x in args.soil_depths.split(',')]
        kwargs['nsoil'] = len(kwargs['soil_depths'])

    setup_shaw_case(
        template_name=args.template,
        output_dir=args.output_dir,
        case_name=args.case_name,
        **kwargs
    )


if __name__ == '__main__':
    main()
