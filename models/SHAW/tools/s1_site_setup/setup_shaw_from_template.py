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
  - compton: BARE SOIL (Line D NPLANT=0), 11 soil nodes, daily weather.
    A cropped or grassed site must add a plant (--crop_type + --gro_file,
    or add_plant()); bare soil is only right for a fallow or bare plot.

Site file facts this tool relies on (Shaw303.for read order, version 3):
  Line D      : NPLANT NSP NR NS NSALT TOLER NHRPDT LEVEL(1..6)
  Line E      : ZMCM HEIGHT PONDCM
  canopy block: only when NPLANT>0, right after Line E
  soil header : IVLCBC ITMPBC ALBDRY ALBEXP IWRC
  soil line   : ZS SAND SILT CLAY ROCK OM RHOB SATK SATKLAT AIRENTRY SAT B
                (Campbell, IWRC=1). Column 11 is SAT. SHAW has no quartz input.

Template files are case data, so they are NOT kept next to this tool. If a
registered case folder is gone (triplet shaw_037), point --template_dir (or
SHAW_TEMPLATE_DIR) at any validated SHAW case folder that holds one
<prefix>.sit + <prefix>.inp set.

Usage:
    python setup_shaw_from_template.py \
        --template jackpine \
        --output_dir outputs/shaw_new_case/ \
        --case_name mysite \
        --lat 49.81 --lon -100.37 --elev 460 \
        --start_doy 1 --end_doy 365 --year 20 \
        --ivlcbc 1 \
        --crop_type grass --gro_file mysite.gro \
        --soil_depths "0.00,0.02,0.05,0.10,0.15,0.20,0.30,0.50,0.60,0.90,1.20"
"""

import argparse
import importlib.util
import os
import re
import shutil
from pathlib import Path


# =============================================================================
# Template registry — add new validated cases here
# =============================================================================
PROJECT_ROOT = Path("KISSPATH_ROOT")
# The registered case folders under outputs/ were lost once already (outputs/
# moved disks; triplet shaw_037). --template_dir / this variable names another
# validated case folder to copy from; no case data lives beside the tool.
# compton was restored to its registry path on 2026-10-02 (see the README.md
# there); jackpine is still missing.
TEMPLATE_DIR_ENV = "SHAW_TEMPLATE_DIR"

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
        "description": "Quebec agricultural station, 45.3°N, daily, BARE SOIL (NPLANT=0), 11 soil nodes, full year, 2-digit year (NSE=0.85)",
        "mcanflg": 0,
        "nsoil": 11,
        "timestep": "daily",
        "notes": (
            "CRITICAL: uses 2-digit year (15, not 2015) throughout .sit/.wea/.moi/.tem — "
            "4-digit year causes SHAW to stop after 1 day (triplet shaw_032). "
            ".wea must start 1 day before JSTART (DOY 365/14 prepended). "
            "Last .tem/.moi entry must be at JEND (DOY 365) — triplet shaw_033; with IVLCBC=0 / "
            "ITMPBC=0 (as in this template) it must be at or after hour 24 of JEND, else SHAW "
            "runs out of records on the last day (check_profile_file)."
        ),
    },
}


def resolve_template(template_name: str, template_dir: str = None) -> tuple:
    """Find the folder and file prefix to copy a template from.

    template_dir (or $SHAW_TEMPLATE_DIR) overrides the registry path. The
    prefix there is the registry prefix if <prefix>.sit exists, else the stem
    of the folder's only .sit file.

    Returns (src_dir, prefix). Raises FileNotFoundError if .sit/.inp is missing.
    """
    tpl = TEMPLATES[template_name]
    src_dir = tpl["path"]
    prefix = tpl["prefix"]
    template_dir = template_dir or os.environ.get(TEMPLATE_DIR_ENV)
    if template_dir:
        src_dir = Path(template_dir)
        if not (src_dir / f"{prefix}.sit").exists():
            sits = sorted(src_dir.glob("*.sit"))
            if len(sits) != 1:
                raise FileNotFoundError(
                    f"template_dir {src_dir} must hold {prefix}.sit or exactly one .sit file "
                    f"(found {[s.name for s in sits]})")
            prefix = sits[0].stem
    # .sit and .inp are the template itself: without them there is nothing to
    # set up, so stop here instead of warning and failing later (shaw_037).
    missing = [f"{prefix}{e}" for e in (".sit", ".inp") if not (src_dir / f"{prefix}{e}").exists()]
    if missing:
        raise FileNotFoundError(
            f"SHAW template '{template_name}' is not on disk: {missing} missing in {src_dir}. "
            f"Restore the case folder, or pass --template_dir (or set {TEMPLATE_DIR_ENV}) "
            f"to a validated SHAW case folder with a .sit + .inp set.")
    return src_dir, prefix


def copy_template(template_name: str, output_dir: str, case_name: str,
                  template_dir: str = None) -> dict:
    """Copy all template files to output directory with new case name prefix.

    Returns dict mapping file type to output path.
    """
    src_dir, prefix = resolve_template(template_name, template_dir)
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


VAN_BEMMELEN = 1.724  # organic matter / organic carbon (van Bemmelen factor)


def organic_matter_pct(prop: dict):
    """SHAW OM column (% organic MATTER by weight) from a soil_properties entry.

    'om' is organic matter and is used as is. 'oc' is organic CARBON (e.g. HWSD
    T_OC / S_OC) and is converted with OM = OC x 1.724 (van Bemmelen factor,
    as create_site_file.py does). Both given: they must agree (0.05 % OM),
    else ValueError. Neither: None (column left as in the template).
    """
    om = prop.get('om')
    oc = prop.get('oc')
    if oc is not None:
        from_oc = float(oc) * VAN_BEMMELEN
        if om is not None and abs(float(om) - from_oc) > 0.05:
            raise ValueError(f"soil_properties om={om} and oc={oc} disagree "
                             f"(oc x {VAN_BEMMELEN} = {from_oc:.2f} % organic matter)")
        return from_oc if om is None else float(om)
    return None if om is None else float(om)


def shaw_latitude(lat: float) -> tuple:
    """(ALTDEG, ALTMIN) for .sit Line C, south negative.

    Shaw303.for: IF (ALTDEG.LT.0.0.AND.ALTMIN.GT.0.0) ALTMIN=-ALTMIN, then
    ALATUD = ALTDEG + ALTMIN/60. So the sign goes on the degrees (as in
    create_site_file.py); between 0 and -1 degree it goes on the minutes.
    Minutes are whole minutes (truncated). Raises for |lat| > 90.
    """
    lat = float(lat)
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude {lat} is outside -90..90")
    deg = int(abs(lat))
    minutes = int((abs(lat) - deg) * 60)
    if lat < 0:
        if deg > 0:
            deg = -deg
        else:
            minutes = -minutes
    return deg, minutes


def update_sit_file(sit_path: Path, **kwargs):
    """Update .sit file parameters while preserving Fortran fixed-width structure.

    Only modifies specific lines/values — leaves everything else as-is.

    Supported kwargs:
        title: str — Line 1 (site description)
        lat: float — Line 3 col 1-2 (lat integer + decimal handling)
        lon: float — not in .sit (for documentation only)
        elev: float — Line 3 position 6
        start_doy: int — Line 2 position 1
        end_doy: int — Line 2 position 4
        year: int — Line 2 positions 3 and 5 (start/end year, 2-digit)
        mcanflg: int — kept only as a check. Position 1 of Line D is NPLANT
            (number of plants), not MCANFLG, and it cannot be changed alone:
            NPLANT>0 needs a canopy block. A value that differs from the
            template's NPLANT raises; use add_plant() to add a plant.
        nsoil: int — check only: must equal NS (Line D position 4) of the
            template; this tool cannot add or remove soil nodes.
        soil_depths: list[float] — one depth per existing soil node line
            (found by _soil_node_indices); a different count raises.
        soil_properties: list[dict] — per node from the top (at most NS
            entries; more raises), any of: sand, silt, clay (%),
            rock (% by WEIGHT, SHAW ROCK), om (organic MATTER %, written as
            is), oc (organic CARBON %, written as OM = OC x 1.724, the van
            Bemmelen factor; om and oc together must agree), bd (kg/m3), ksat (cm/hr),
            sat (m3/m3), bpar (Campbell b)
        plant_height: not supported (raises). Plant height comes from the
            growth file named in the canopy block (see add_plant()).
    """
    with open(sit_path, 'r') as f:
        lines = f.readlines()

    # Line 1: Title/description
    if 'title' in kwargs:
        lines[0] = kwargs['title'].rstrip('\n') + '\n'

    # Shaw303.for READ (11,*): JSTART HRSTAR YRSTAR JEND YREND.
    if any(k in kwargs for k in ['start_doy', 'end_doy', 'year']):
        parts = lines[1].split()
        if 'start_doy' in kwargs:
            parts[0] = str(kwargs['start_doy'])
        if 'end_doy' in kwargs:
            parts[3] = str(kwargs['end_doy'])
        if 'year' in kwargs:
            parts[2] = str(kwargs['year'])
            parts[4] = str(kwargs['year'])
        lines[1] = '   ' + '   '.join(parts) + '\n'

    # Line 3: LAT_INT LAT_DEC LON ASPECT HEIGHT ELEV
    if any(k in kwargs for k in ['lat', 'elev']):
        parts = lines[2].split()
        if 'lat' in kwargs:
            lat_deg, lat_min = shaw_latitude(kwargs['lat'])
            parts[0] = f' {lat_deg}'
            parts[1] = f'{lat_min}'
        if 'elev' in kwargs:
            parts[5] = f'{kwargs["elev"]:.0f}.'
        lines[2] = ' ' + '  '.join(parts) + '\n'

    # Line D: NPLANT NSP NR NS NSALT TOLER NHRPDT LEVEL(1..6)
    # The old code wrote 'mcanflg' into position 1, which is NPLANT. Setting
    # NPLANT>0 without a canopy block (or 0 with one) shifts every later
    # read, so this is now a check only.
    if 'mcanflg' in kwargs:
        nplant = int(lines[3].split()[0])
        if (int(kwargs['mcanflg']) > 0) != (nplant > 0):
            raise ValueError(
                f"mcanflg={kwargs['mcanflg']} does not match the template "
                f"(Line D NPLANT={nplant}). Line D position 1 is NPLANT, not "
                f"MCANFLG; use add_plant() / --crop_type + --gro_file to add a "
                f"plant with its canopy block.")

    if 'nsoil' in kwargs and int(kwargs['nsoil']) != sit_soil_node_count(lines):
        raise ValueError(f"nsoil={kwargs['nsoil']} does not match the template .sit "
                         f"(Line D NS={sit_soil_node_count(lines)}); nodes cannot be added or removed here")

    # Soil node lines: found by _soil_node_indices (the old scan started at
    # 0-based line 10 and missed the first two nodes of the Compton template,
    # whose soil starts at line 8).
    soil_idx = _soil_node_indices(lines) if (
        'soil_depths' in kwargs or 'soil_properties' in kwargs) else []
    if soil_idx:
        ns_sit = sit_soil_node_count(lines)
        if len(soil_idx) != ns_sit:
            raise ValueError(
                f"{sit_path}: found {len(soil_idx)} soil node lines but Line D says NS={ns_sit}")
    if 'soil_depths' in kwargs:
        depths = kwargs['soil_depths']
        nsoil = len(depths)
        if not soil_idx:
            raise ValueError(f"{sit_path}: no soil node lines found")
        if len(soil_idx) != nsoil:
            raise ValueError(
                f"template has {len(soil_idx)} soil nodes, {nsoil} depths were given. "
                f"This tool only moves existing nodes; it cannot add or remove them "
                f"(the .tem/.moi records would no longer fit).")
        for j, depth in zip(soil_idx, depths):
            parts = _plain_parts(lines[j], f"soil line {j + 1}")
            parts[0] = f'{depth:.2f}'
            lines[j] = ' ' + '  '.join(parts) + '\n'
        print(f"  Updated {nsoil} soil node depths in-place")

    # Soil properties update (per-node)
    if 'soil_properties' in kwargs:
        props = kwargs['soil_properties']
        if not soil_idx:
            raise ValueError(f"{sit_path}: no soil node lines found")
        if len(props) > len(soil_idx):
            raise ValueError(
                f"{len(props)} soil_properties entries given, the template has only "
                f"{len(soil_idx)} soil nodes; extra entries would be lost")
        for j, prop in zip(soil_idx, props):
            parts = _plain_parts(lines[j], f"soil line {j + 1}")
            # Soil line columns (Shaw303.for, Campbell):
            # ZS SAND SILT CLAY ROCK OM RHOB SATK SATKLAT AIRENTRY SAT B
            if 'quartz' in prop:
                raise ValueError(
                    "soil_properties key 'quartz' is not a SHAW input; "
                    "column 11 of a soil line is SAT. Pass 'sat' instead.")
            if 'sand' in prop:
                parts[1] = f'{prop["sand"]:.1f}'
            if 'silt' in prop:
                parts[2] = f'{prop["silt"]:.1f}'
            if 'clay' in prop:
                parts[3] = f'{prop["clay"]:.1f}'
            if 'rock' in prop:
                parts[4] = f'{prop["rock"]:.1f}'
            om = organic_matter_pct(prop)
            if om is not None:
                parts[5] = f'{om:.1f}'
            if 'bd' in prop:
                parts[6] = f'{prop["bd"]:.0f}.'
            if 'ksat' in prop:
                parts[7] = f'{prop["ksat"]:.2f}'
            # col 11 (index 10) = SAT, col 12 (index 11) = Campbell b.
            # SAT: given value, else from the bulk density just written.
            if 'sat' in prop:
                if len(parts) > 10:
                    parts[10] = f'{prop["sat"]:.3f}'
            elif 'bd' in prop and len(parts) > 10:
                parts[10] = f'{sat_from_bulk_density(prop["bd"]):.3f}'
            if 'bpar' in prop:
                if len(parts) > 11:
                    parts[11] = f'{prop["bpar"]:.2f}'
            elif 'sand' in prop and 'clay' in prop and len(parts) > 11:
                sand, clay = prop['sand'], prop['clay']
                bpar = max(2.0, min(12.0, 3.10 + 0.157 * clay - 0.003 * sand))
                parts[11] = f'{bpar:.2f}'
            lines[j] = ' ' + '  '.join(parts) + '\n'

    # Plant height is not a .sit value when a growth file is used, and line 8
    # is a different line in every template (in compton it is the soil
    # header), so writing it here would damage the file.
    if 'plant_height' in kwargs:
        raise ValueError(
            "plant_height cannot be set in the .sit: with MCANFLG=1 the height "
            "comes from the growth file (see add_plant()).")

    with open(sit_path, 'w') as f:
        f.writelines(lines)

    print(f"  Updated {sit_path.name} with site-specific parameters")


PARTICLE_DENSITY = 2650.0  # kg/m3, mineral soil


def sat_from_bulk_density(rhob: float) -> float:
    """Saturated water content (m3/m3) from bulk density: 1 - RHOB/2650.

    RHOB in kg/m3. SHAW itself lowers SAT when it is too high for the density.
    """
    rhob = float(rhob)
    if not (500.0 <= rhob < PARTICLE_DENSITY):
        raise ValueError(
            f"bulk density {rhob} kg/m3 is outside 500-2650; cannot derive SAT "
            f"(is the column in g/cm3, or is this not column 7 = RHOB?)")
    return 1.0 - rhob / PARTICLE_DENSITY


def sit_soil_node_count(lines: list) -> int:
    """NS, the number of soil nodes, from Line D of a .sit.

    Line D (4th line): NPLANT NSP NR NS NSALT TOLER NHRPDT LEVEL(1..6).
    Shaw303.for reads every .tem/.moi record as JDAY JHR JYR (X(I), I=1,NS),
    so profiles must have exactly NS values.
    """
    if isinstance(lines, (str, Path)):
        lines = Path(lines).read_text().splitlines()
    parts = lines[3].split() if len(lines) > 3 else []
    try:
        ns = int(parts[3])
    except (IndexError, ValueError):
        raise ValueError(f"line 4 is not Line D (NPLANT NSP NR NS ...): "
                         f"{lines[3] if len(lines) > 3 else ''!r}")
    if ns < 1:
        raise ValueError(f"Line D NS={ns} is not a soil node count")
    return ns


def _is_number(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _list_values(line: str) -> list:
    """Leading values of a line as a Fortran list-directed READ (u,*) sees them.

    Commas count as blanks, a repeat 'r*c' gives r copies of c (e.g. 11*5.0),
    a D exponent (5.0D0) is read like E, and reading stops at '/' (also right
    after a value, as in '5.0/': that value still counts) or at the first
    token that is not a number (a trailing note). Returns the numbers as floats.
    """
    def num(t):
        t = re.sub(r'(?<=[0-9.])[dD](?=[+-]?[0-9])', 'E', t)
        return float(t) if _is_number(t) else None

    vals = []
    for tok in line.replace(',', ' ').split():
        tok, slash, _ = tok.partition('/')
        if tok:
            m = re.fullmatch(r'(\d+)\*(\S+)', tok)
            v = num(m.group(2)) if m else num(tok)
            if v is None:
                break
            vals.extend([v] * (int(m.group(1)) if m else 1))
        if slash:
            break
    return vals


def _plain_parts(line: str, what: str) -> list:
    """line.split() for a line this tool edits column by column; refuses
    repeat counts / commas, which would move the columns."""
    if '*' in line or ',' in line:
        raise ValueError(f"cannot edit {what} written with repeat counts or commas: {line.strip()!r}")
    return line.split()


def _profile_records(path: Path, ns: int) -> tuple:
    """Records of a .tem/.moi as Shaw303.for reads them.

    SHAW reads each record with READ (u,*) JDAY,JHR,JYR,(X(I),I=1,NS): it takes
    the first 3+NS values and ignores the rest of that line, so a trailing
    note such as "(See bottom of file" (bundled Trial.tem/.moi) is fine, and a
    repeat such as 11*5.0 counts as 11 values (_list_values).
    Rules here:
      - a line whose first 3+NS tokens are numbers is a record; one more
        number right after them means the file has more than NS values per
        record (wrong node count) and raises;
      - a line that starts with 3 numbers but has fewer than 3+NS numbers
        raises (SHAW would take the rest from the next line);
      - the first other line ends the records (an explanatory footer). SHAW
        never reads past the records it needs, so this is only an error when
        a needed record is missing (check_profile_file says so).
    Returns (records, stop) with records = [(year, day, hour), ...] and stop =
    the line that ended the records, or None.
    """
    recs = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        vals = _list_values(line)
        lead = len(vals)
        if lead < 3:
            return recs, f"line {n}: {line.strip()[:60]!r}"
        if lead < 3 + ns:
            raise ValueError(f"{path} line {n}: record has {lead - 3} values, the .sit has NS={ns}")
        if lead > 3 + ns:
            raise ValueError(f"{path} line {n}: record has {lead - 3} values, more than the "
                             f".sit NS={ns} (template for another node count?)")
        jday, jhr, jyr = (int(x) for x in vals[:3])
        recs.append((jyr, jday, jhr))
    return recs, None


def _shaw_time(year: int, day: int, hour: int) -> tuple:
    """(year, day, hour) with hour 24 moved to hour 0 of the next day, the way
    Shaw303.for does for boundary records (leap year: MOD(year,4)==0)."""
    if hour == 24:
        hour, day = 0, day + 1
        if day > (366 if year % 4 == 0 else 365):
            day, year = 1, year + 1
    return (year, day, hour)


def _header_flags(line: str):
    """(IVLCBC, ITMPBC) if line looks like 'IVLCBC ITMPBC ALBDRY ALBEXP IWRC', else None."""
    v = _list_values(line)
    if len(v) < 5 or v[0] not in (0.0, 1.0) or v[1] not in (0.0, 1.0, 2.0):
        return None
    return int(v[0]), int(v[1])


def _soil_header_index(lines: list) -> int:
    """Index of the soil header line 'IVLCBC ITMPBC ALBDRY ALBEXP IWRC'.

    Shaw303.for reads the header, then TSAVG on its own record only when
    ITMPBC=1, then the NS soil lines. So: the line just before the soil block
    is the header when its ITMPBC is 0 or 2; otherwise the line before that
    is the header with ITMPBC=1 and the line between is TSAVG (any trailing
    note on the TSAVG line is fine, SHAW reads one value).
    """
    nodes = _soil_node_indices(lines)
    if not nodes:
        raise ValueError("no soil node lines found in the .sit")
    # list-directed reads skip blank records, so look at non-blank lines only
    before = [k for k in range(nodes[0]) if lines[k].strip()]
    i = before[-1] if before else -1
    f = _header_flags(lines[i]) if i >= 0 else None
    if f is not None and f[1] != 1:
        return i
    j = before[-2] if len(before) >= 2 else -1
    f2 = _header_flags(lines[j]) if j >= 0 else None
    if f2 is not None and f2[1] == 1 and _list_values(lines[i]):
        return j
    raise ValueError(
        f"soil header 'IVLCBC ITMPBC ALBDRY ALBEXP IWRC' (plus a TSAVG line when ITMPBC=1) "
        f"not found before the soil lines: line {i + 1} {lines[i] if i >= 0 else ''!r}")


def sit_boundary_flags(sit_lines: list) -> tuple:
    """(IVLCBC, ITMPBC) from the soil header of a .sit."""
    return _header_flags(sit_lines[_soil_header_index(sit_lines)])


def check_profile_file(path: Path, sit_lines: list, ns: int, boundary: bool = None) -> None:
    """Fail if a .tem/.moi does not fit the .sit it will run with.

    Follows Shaw303.for:
      - start (INPUT INITIAL CONDITIONS): HRSTAR=0 is first turned into
        (JSTART-1, hour 24); SHAW then reads records in order until one is at
        (JSTART, HRSTAR, YRSTAR) or, for hour 24, at (JSTART+1, hour 0) of
        the same year. No such record -> SHAW stops.
      - boundary (DAYINP): only when the file is a lower boundary
        (.moi with IVLCBC=0, .tem with ITMPBC=0; pass boundary=None to take
        it from the .sit soil header and the file extension). SHAW also
        reads on day JEND and needs a record at or after hour 24 of JEND
        (hour 0 of JEND+1); a file that ends at (JEND, hour 0) runs out on
        the last day (checked with a 4-day Compton run: last day lost,
        "End of file" on unit 13). Records after the start must go forward
        in time, else SHAW aborts.
      - every record has exactly NS values (see _profile_records).
    """
    path = Path(path)
    jstart, hrstar, yrstar, jend, yrend = (int(float(x)) for x in sit_lines[1].split()[:5])
    if hrstar == 0:
        hrstar, jstart = 24, jstart - 1
    if boundary is None:
        ivlcbc, itmpbc = sit_boundary_flags(sit_lines)
        boundary = (ivlcbc == 0) if path.suffix == '.moi' else (itmpbc == 0)
    recs, stop = _profile_records(path, ns)
    tail = f" (records end at {stop})" if stop else ""
    start_i = next((i for i, (y, d, h) in enumerate(recs)
                    if (d, h, y) == (jstart, hrstar, yrstar) or
                    (hrstar == 24 and h == 0 and y == yrstar and d - 1 == jstart)), None)
    if start_i is None:
        raise ValueError(
            f"{path}: no record at the run start (day {jstart}, hour {hrstar}, year {yrstar}, "
            f"as SHAW reads it){tail}. SHAW needs one there. Give real profiles for this site "
            f"and period (tem_profiles / moi_profiles, or s4_initial_conditions/tools/"
            f"set_initial_conditions.py).")
    if not boundary:
        return
    need = _shaw_time(yrend, jend, 24)
    prev = _shaw_time(*recs[start_i])
    for y, d, h in recs[start_i + 1:]:
        t = _shaw_time(y, d, h)
        if t < prev:
            raise ValueError(f"{path}: record (day {d}, hour {h}, year {y}) goes back in time; "
                             f"SHAW aborts on it")
        prev = t
        if t >= need:
            return
    which = "IVLCBC=0" if path.suffix == '.moi' else "ITMPBC=0"
    raise ValueError(
        f"{path}: lower boundary ({which}) needs a record at or after hour 24 of the last day "
        f"(day {jend}, year {yrend}); last usable record is (day {recs[-1][1]}, hour "
        f"{recs[-1][2]}, year {recs[-1][0]}){tail}. SHAW would run out of records on the last day.")


def _soil_node_indices(lines: list) -> list:
    """Indices of the soil node lines of a .sit.

    The soil lines are the last records Shaw303.for reads from the .sit: NS
    lines (NS from Line D) right after the soil header. So, when Line D can
    be read, they are the last NS non-blank lines of the file (a trailing
    text footer that does not start with a number is skipped). Each must hold
    at least 10 values (list-directed: '0' and '0.00' are both fine) with
    depths starting at 0 and going down; otherwise ValueError. Lines earlier
    in the file that look like soil lines (e.g. a solute adsorption line
    LINE I-2 written as NS numbers) are never picked.
    Without a readable Line D the old pattern scan (_soil_like_lines) is used.
    """
    try:
        ns = sit_soil_node_count(lines)
    except ValueError:
        return _soil_like_lines(lines)
    rec = [i for i, line in enumerate(lines) if line.strip()]
    while rec and not _list_values(lines[rec[-1]]):
        rec.pop()  # trailing text footer
    if len(rec) < ns + 4:
        raise ValueError(f"the .sit has too few lines for NS={ns} soil lines plus the control lines")
    last = rec[-ns:]
    depths = []
    for i in last:
        v = _list_values(lines[i])
        if len(v) < 10:
            raise ValueError(f"line {i + 1} should be soil node {len(depths) + 1} of NS={ns} "
                             f"(ZS SAND SILT CLAY ...) but has {len(v)} values: {lines[i].strip()!r}")
        depths.append(v[0])
    if depths[0] != 0.0 or any(b <= a for a, b in zip(depths, depths[1:])):
        raise ValueError(f"the last NS={ns} lines do not look like soil nodes: depths {depths} "
                         f"(must start at 0 and increase)")
    return last


def _soil_like_lines(lines: list) -> list:
    idx = []
    for i, line in enumerate(lines):
        parts = line.split()
        if len(parts) < 12 or '.' not in parts[0]:
            continue
        try:
            depth = float(parts[0])
            sand = float(parts[1])
            clay = float(parts[3])
        except ValueError:
            continue
        if 0.0 <= depth <= 10.0 and 0 <= sand <= 100 and 0 <= clay <= 100:
            idx.append(i)
    return idx


def fix_bpar_sat_from_soil(sit_path: Path) -> int:
    """
    Recompute Campbell b and SAT on each soil node line of a Campbell (IWRC=1)
    .sit file.

    The Compton template ships with wrong defaults in the last two soil
    columns (30.0 and 8.5 in older copies). Values written here:
      B   = 3.10 + 0.157*clay - 0.003*sand   (Rawls et al. 1982, clamped 2-12)
      SAT = 1 - RHOB/2650                     (porosity from bulk density)

    .sit soil node line (Shaw303.for: READ ZS,SAND,SILT,CLAY,ROCK,OM,RHOB,
    SATCON,SATKL,SOILWRC(1..3)):
      ZS SAND SILT CLAY ROCK OM RHOB SATK SATKLAT AIRENTRY SAT B
      0   1    2    3    4   5   6    7     8        9     10  11   (0-based)

    Column 11 (index 10) is SAT, the saturated water content. SHAW has no
    quartz input; an older version of this function wrote a "quartz" value
    (sand/100*0.9+0.10) there, which set SAT from sand content.

    Returns the number of soil nodes updated.
    """
    sit_path = Path(sit_path)
    lines = sit_path.read_text().splitlines()
    new_lines = list(lines)
    n_updated = 0

    for i in _soil_node_indices(lines):
        parts = _plain_parts(lines[i], f"soil line {i + 1}")
        sand = float(parts[1])
        clay = float(parts[3])
        bpar = max(2.0, min(12.0, 3.10 + 0.157 * clay - 0.003 * sand))
        sat = sat_from_bulk_density(parts[6])

        parts[10] = f'{sat:.3f}'
        parts[11] = f'{bpar:.2f}'
        new_lines[i] = ' ' + '  '.join(parts)
        n_updated += 1

    if n_updated > 0:
        sit_path.write_text('\n'.join(new_lines) + '\n')

    return n_updated


# Old name, kept so existing callers do not break. It never wrote quartz that
# SHAW could read; it now writes SAT.
fix_bpar_quartz_from_texture = fix_bpar_sat_from_soil


def set_lower_boundary(sit_path: Path, ivlcbc: int) -> str:
    """Set IVLCBC, the lower boundary for water, on the soil header line.

    Soil header (the line before the first soil node; one line further up
    when ITMPBC=1 puts a TSAVG line in between):
      IVLCBC ITMPBC ALBDRY ALBEXP IWRC
    IVLCBC=1: unit gradient (free drainage). Use this unless measured deep
              water content exists.
    IVLCBC=0: SHAW reads the water content of the bottom node from the .moi
              file for the whole run. Only for measured values; a made-up
              series there acts like a fixed water table.

    Returns the new header line. Raises if the header cannot be found.
    """
    if ivlcbc not in (0, 1):
        raise ValueError(f"ivlcbc must be 0 or 1, got {ivlcbc!r}")
    sit_path = Path(sit_path)
    lines = sit_path.read_text().splitlines()
    try:
        hdr = _soil_header_index(lines)
    except ValueError as e:
        raise ValueError(f"{sit_path}: {e}")
    old_flags = _header_flags(lines[hdr])
    # Replace only the first value (IVLCBC); keep its separator (blank or
    # comma) and the rest of the line. Anything else is refused before writing.
    m = re.match(r'^(\s*)([^\s,/]+)', lines[hdr])
    if not m or m.group(2) not in ('0', '1', '0.', '1.', '0.0', '1.0'):
        raise ValueError(f"{sit_path}: cannot edit IVLCBC in soil header {lines[hdr]!r}")
    new_line = m.group(1) + str(ivlcbc) + lines[hdr][m.end():]
    if _header_flags(new_line) != (ivlcbc, old_flags[1]) or \
            _list_values(new_line)[2:] != _list_values(lines[hdr])[2:]:
        raise ValueError(f"{sit_path}: editing IVLCBC would change other header values: "
                         f"{lines[hdr]!r} -> {new_line!r}; nothing written")
    lines[hdr] = new_line
    sit_path.write_text('\n'.join(lines) + '\n')
    print(f"  Lower water boundary: IVLCBC={ivlcbc} "
          f"({'unit gradient' if ivlcbc == 1 else 'water content read from .moi'})")
    return lines[hdr]


def _load_plant_tool():
    """Import s3_plant_config/tools/create_plant_file.py from this KI."""
    path = Path(__file__).resolve().parents[2] / "s3_plant_config" / "tools" / "create_plant_file.py"
    if not path.exists():
        raise FileNotFoundError(f"plant tool not found: {path}")
    spec = importlib.util.spec_from_file_location("create_plant_file", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_growth_file(crop_type: str, start_year: int, end_year: int,
                      lat: float, output_path: Path) -> Path:
    """Write a plant growth file with the s3 tool (create_plant_file.py).

    start_year/end_year are 4-digit; the s3 tool writes a 2-digit year, which
    fits a .sit with 2-digit years (triplet shaw_032). add_plant() checks it.
    """
    mod = _load_plant_tool()
    if crop_type not in mod.PLANT_TEMPLATES:
        raise ValueError(f"unknown crop_type {crop_type!r}; choose from {sorted(mod.PLANT_TEMPLATES)}")
    template = dict(mod.PLANT_TEMPLATES[crop_type], name=crop_type)
    mod.write_plant_growth_file(template, start_year, end_year, lat, str(output_path))
    return Path(output_path)


def _check_growth_file(gro_path: Path, sit_lines: list) -> None:
    """Fail if the growth file does not cover the run set on .sit line 2."""
    jstart, hrstar, yrstar, jend, yrend = (int(float(x)) for x in sit_lines[1].split()[:5])
    # First day SHAW looks up in the growth file. Shaw303.for turns
    # (JSTART, hour 0) into (JSTART-1, hour 24) on reading the .sit, but the
    # main program then steps an hour-24 start on to the next day before the
    # first DAYINP call. So: hour 0 -> JSTART; hour 24 -> JSTART+1.
    first_day, first_year = jstart, yrstar
    if hrstar == 24:
        first_day += 1
        if first_day > (366 if yrstar % 4 == 0 else 365):  # SHAW's own leap rule
            first_day, first_year = 1, yrstar + 1
    rows = []
    for n, line in enumerate(gro_path.read_text().splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) < 8:
            raise ValueError(
                f"{gro_path} line {n}: need 8 values "
                f"(JDAY JYR PLTHGT DCHAR CLUMPNG PLTWGT PLTLAI ROOTDP), got {len(parts)}")
        [float(x) for x in parts[:8]]
        rows.append((int(float(parts[1])), int(float(parts[0]))))
    if not rows:
        raise ValueError(f"{gro_path} is empty")
    if rows != sorted(rows):
        raise ValueError(f"{gro_path}: records are not in time order")
    if rows[0] > (first_year, first_day):
        raise ValueError(
            f"{gro_path}: first record (year {rows[0][0]}, day {rows[0][1]}) is after the run's "
            f"first day (year {first_year}, day {first_day}). Check the year style: the .sit uses "
            f"{yrstar}, and the growth file must use the same (2-digit vs 4-digit).")
    # Shaw303.for DAYINP (first call) reads growth records until one is
    # strictly AFTER the first day, to interpolate; end of file first ->
    # "INITIAL CONDITIONS ... CANNOT BE INTERPOLATED FROM PLANT GROWTH FILE".
    if not any(r > (first_year, first_day) for r in rows):
        raise ValueError(
            f"{gro_path}: no record after the run's first day (year {first_year}, day "
            f"{first_day}); SHAW needs one to interpolate the start and stops otherwise.")
    if rows[-1] < (yrend, jend):
        raise ValueError(
            f"{gro_path}: last record (year {rows[-1][0]}, day {rows[-1][1]}) is before the run "
            f"end (year {yrend}, day {jend}). Check the year style and the end year.")


def add_plant(sit_path: Path, crop_type: str, gro_filename: str,
              canopy_line: str = " 1  1  -53.72  1.32   0.0") -> list:
    """Add one plant to a bare-soil .sit (NPLANT=0 -> 1) with a growth file.

    Layout follows the shipped example US-Rms.sit and the Shaw303.for reads:
      Line D : first value NPLANT set to 1
      after Line E (ZMCM HEIGHT PONDCM), three new lines:
        MCANFLG ISTOMATE CANMA CANMB WCAN        (MCANFLG=1: growth file,
                                                  model sets canopy nodes)
        ITYPE PINTRCP XANGLE CANALB TCCRIT RSTOM0 RSTEXP PLEAF0 RLEAF0 RROOT0
        <growth file name>
    With MCANFLG=1 SHAW reads no root line; rooting depth comes from the
    growth file. Plant values come from PLANT_TEMPLATES in
    s3_plant_config/tools/create_plant_file.py.

    gro_filename is written into the .sit as given (SHAW opens it relative
    to the folder it runs in, max 80 characters) and must already exist next
    to the .sit, built for the same years and year style.

    Raises on any problem. It never leaves the site as bare soil silently.
    Returns the three inserted lines.
    """
    sit_path = Path(sit_path)
    mod = _load_plant_tool()
    if crop_type not in mod.PLANT_TEMPLATES:
        raise ValueError(f"unknown crop_type {crop_type!r}; choose from {sorted(mod.PLANT_TEMPLATES)}")
    tpl = mod.PLANT_TEMPLATES[crop_type]
    if tpl['itype'] <= 0:
        raise ValueError(f"crop_type {crop_type!r} is not a transpiring plant (ITYPE={tpl['itype']}); "
                         f"for a bare plot leave NPLANT=0")
    if len(gro_filename) > 80:
        raise ValueError(f"growth file name is longer than 80 characters: {gro_filename}")
    gro_path = sit_path.parent / gro_filename
    if not gro_path.exists():
        raise FileNotFoundError(f"growth file not found next to the .sit: {gro_path}")
    canopy_parts = canopy_line.split()
    if len(canopy_parts) < 5 or canopy_parts[0] != '1' or canopy_parts[1] != '1':
        raise ValueError("canopy_line must be 'MCANFLG ISTOMATE CANMA CANMB WCAN' with "
                         "MCANFLG=1 and ISTOMATE=1 (other layouts need more lines)")

    lines = sit_path.read_text().splitlines()
    if len(lines) < 6:
        raise ValueError(f"{sit_path}: too short to be a SHAW site file")
    line_d = lines[3].split()
    if len(line_d) < 7:
        raise ValueError(f"{sit_path}: line 4 is not Line D (NPLANT NSP NR NS NSALT TOLER NHRPDT ...): {lines[3]!r}")
    if int(line_d[0]) != 0:
        raise ValueError(f"{sit_path}: NPLANT is already {line_d[0]}; add_plant only adds the first "
                         f"plant to a bare-soil file")
    line_e = lines[4].split()
    try:
        [float(x) for x in line_e[:3]]
        ok_e = len(line_e) >= 3
    except ValueError:
        ok_e = False
    if not ok_e:
        raise ValueError(f"{sit_path}: line 5 is not Line E (ZMCM HEIGHT PONDCM): {lines[4]!r}")
    _check_growth_file(gro_path, lines)

    plant_line = (f" {tpl['itype']}  {tpl['pintrcp']:.2f}  {tpl['xangle']:.2f}  {tpl['canalb']:.2f}  "
                  f"{tpl['tccrit']:.1f}  {tpl['rstomo']:.1f}  {tpl['rstexp']:.1f}  "
                  f"{tpl['pleaf0']:.1f}  {tpl['rleaf0']:.3E}  {tpl['rroot0']:.3E}")
    block = [canopy_line.rstrip(), plant_line, gro_filename]
    lines[3] = re.sub(r'^(\s*)\S+', lambda m: m.group(1) + '1', lines[3], count=1)
    lines[5:5] = block
    sit_path.write_text('\n'.join(lines) + '\n')
    print(f"  Added plant '{crop_type}' (NPLANT=1, MCANFLG=1, growth file {gro_filename})")
    return block


def update_inp_file(inp_path: Path, case_name: str, **kwargs):
    """Update .inp control file — point the input file names at the new case.

    Shaw303.for reads the .inp by position: record 1 title/version, record 2
    MTSTEP IFLAGSI INPH2O MWATRXT, then records 3-6 the input files opened on
    units 11-14 (READ (10,100) IFILE): .sit, .wea, .moi, .tem in that order.
    Only those four records are rewritten, and only when a record is exactly
    <source prefix><ext> (surrounding blanks kept) -> <case_name><ext>. No
    substring replacement, and later records (output names, an optional
    extraction file, any unused tail) are left as they are.

    Supported kwargs:
        template_prefix: str — file prefix of the copied template (the one
            resolve_template() found). Without it the registry prefixes are
            tried (one prefix for all four records).
    Raises ValueError, before writing, if records 3-6 are not exactly
    <prefix>.sit/.wea/.moi/.tem for one of those prefixes.
    """
    inp_path = Path(inp_path)
    text = inp_path.read_text()
    lines = text.splitlines()
    prefixes = ([kwargs['template_prefix']] if kwargs.get('template_prefix')
                else [tpl_info["prefix"] for tpl_info in TEMPLATES.values()])
    exts = ('.sit', '.wea', '.moi', '.tem')
    active = [l.strip() for l in lines[2:6]]
    prefix = next((p for p in prefixes if active == [p + e for e in exts]), None)
    if prefix is None:
        raise ValueError(
            f"{inp_path}: records 3-6 (input files on units 11-14) are {active}, expected "
            f"<prefix>.sit/.wea/.moi/.tem for prefix {prefixes}. Nothing written.")
    for k, ext in enumerate(exts):
        lines[2 + k] = lines[2 + k].replace(f'{prefix}{ext}', f'{case_name}{ext}', 1)
    inp_path.write_text('\n'.join(lines) + ('\n' if text.endswith('\n') else ''))
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
    """MADE-UP seasonal temperature + moisture profiles from latitude only.

    Not used by setup_shaw_case any more (it keeps the template's own .tem/.moi
    unless real profiles are given). These values are invented, not site data:
    never use them as observations or as a lower boundary (IVLCBC=0 / ITMPBC=0).
    Records are on DOY 1/91/182/274/365, so they also rarely match a run start.

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
    3. Keep the template's .tem/.moi unless real profiles are given, and check
       they fit the run (start record, end, NS from the .sit)
    """
    print(f"\n{'='*60}")
    print(f"SHAW Template-Based Setup (cm_024: copy-first)")
    print(f"  Template: {template_name}")
    print(f"  Output:   {output_dir}")
    print(f"  Case:     {case_name}")
    print(f"{'='*60}\n")

    # Step 1: Copy template files
    print("Step 1: Copying template files...")
    template_dir = kwargs.pop('template_dir', None)
    _, template_prefix = resolve_template(template_name, template_dir)
    files = copy_template(template_name, output_dir, case_name, template_dir=template_dir)

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
        if kwargs.get('ivlcbc') is not None:
            set_lower_boundary(files['.sit'], kwargs['ivlcbc'])
        if kwargs.get('crop_type') or kwargs.get('gro_file'):
            if not (kwargs.get('crop_type') and kwargs.get('gro_file')):
                raise ValueError("crop_type and gro_file must be given together")
            add_plant(files['.sit'], kwargs['crop_type'], kwargs['gro_file'])
        nplant = int(files['.sit'].read_text().splitlines()[3].split()[0])
        if nplant == 0:
            print("  NOTE: this case is BARE SOIL (NPLANT=0, no transpiration). "
                  "For a cropped or grassed site add a plant (--crop_type + --gro_file).")

    # Step 3: Update .inp file references
    if '.inp' in files:
        print("\nStep 3: Updating .inp file references...")
        update_inp_file(files['.inp'], case_name, template_prefix=template_prefix)

    # Step 4: .tem and .moi profiles.
    # The node count comes from the copied .sit (Line D NS), not from the
    # registry: a --template_dir case can have any NS.
    sit_lines = files['.sit'].read_text().splitlines()
    nsoil = sit_soil_node_count(sit_lines)
    if kwargs.get('nsoil') is not None and int(kwargs['nsoil']) != nsoil:
        raise ValueError(f"nsoil={kwargs['nsoil']} does not match the template .sit (NS={nsoil})")
    tem_profiles = kwargs.get('tem_profiles', None)
    moi_profiles = kwargs.get('moi_profiles', None)
    for name, profs, key in (('tem_profiles', tem_profiles, 'temps'),
                             ('moi_profiles', moi_profiles, 'moisture')):
        for p in profs or []:
            if len(p[key]) != nsoil:
                raise ValueError(f"{name}: record day {p.get('doy')} has {len(p[key])} values, "
                                 f"the .sit has NS={nsoil}")
    # No profiles given: the template's own .tem/.moi are kept as they are
    # (no made-up latitude formula). They are the template site's values; they
    # must still fit this run (start record, end, NS), else stop.
    print("\nStep 4: Initial / boundary soil profiles (.tem, .moi)...")
    for ext, profs, update in (('.tem', tem_profiles, update_tem_file),
                               ('.moi', moi_profiles, update_moi_file)):
        if ext not in files:
            raise FileNotFoundError(
                f"template has no {ext} file; SHAW reads it at start. Give real profiles.")
        update(files[ext], profiles=profs)
        if profs is None:
            print(f"  NOTE: {files[ext].name} holds the TEMPLATE site's profiles, not this "
                  f"site's. Replace them with real data for the site when you have it.")
        check_profile_file(files[ext], sit_lines, nsoil)

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
    parser.add_argument('--template_dir', default=None,
                        help='Validated SHAW case folder to copy from instead of the '
                             f'registry path (also read from ${TEMPLATE_DIR_ENV})')
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
                        help='Check only: 0 = template must be bare soil (NPLANT=0), '
                             '1 = template must have plants. Does not edit the .sit; '
                             'use --crop_type + --gro_file to add a plant.')
    parser.add_argument('--crop_type', type=str,
                        help='Add one plant of this type (a key of PLANT_TEMPLATES in '
                             's3_plant_config/tools/create_plant_file.py) to a bare-soil template')
    parser.add_argument('--gro_file', type=str,
                        help='Plant growth file name, already present in --output_dir '
                             '(build it with create_plant_file.py); needed with --crop_type')
    parser.add_argument('--ivlcbc', type=int, choices=[0, 1],
                        help='Lower water boundary: 1 = unit gradient (use this unless deep '
                             'water content is measured), 0 = water content read from .moi')

    # Soil
    parser.add_argument('--soil_depths', type=str,
                        help='Comma-separated soil node depths (m), e.g. "0.00,0.02,0.05,0.10"')

    # Title
    parser.add_argument('--title', type=str,
                        help='Site description (Line 1 of .sit)')

    args = parser.parse_args()

    kwargs = {}
    for key in ['lat', 'lon', 'elev', 'start_doy', 'end_doy', 'year',
                 'mcanflg', 'crop_type', 'gro_file', 'ivlcbc', 'title']:
        val = getattr(args, key, None)
        if val is not None:
            kwargs[key] = val

    if args.soil_depths:
        kwargs['soil_depths'] = [float(x) for x in args.soil_depths.split(',')]
        kwargs['nsoil'] = len(kwargs['soil_depths'])

    if args.template_dir:
        kwargs['template_dir'] = args.template_dir

    setup_shaw_case(
        template_name=args.template,
        output_dir=args.output_dir,
        case_name=args.case_name,
        **kwargs
    )


if __name__ == '__main__':
    main()
