#!/usr/bin/env python3
"""
Stage 3: assemble a site-specific SWAP main configuration (.swp) from a
validated base template.

Substitutes scalar keys, the Mualem-van Genuchten soil table, the per-crop
rotation table and a prescribed (SWIRFIX=1) fixed-irrigation table, then
re-validates the assembled file against the config traps recorded in
diagnostics/triplets.yaml.

Usage:
    python assemble_swap_config.py \\
        --base work/devcase_hupselbrook/swap_linux.swp.template \\
        --output work/mycase/swap.swp \\
        --set METFIL=usne1 --set TSTART=2001-01-01 \\
        --mvg-table work/mycase/soil_mvg.txt \\
        --crop-table work/mycase/crop_rotation.txt \\
        --irrigation-file work/mycase/irrigation.txt

Any --irrigation / --irrigation-file input forces SWIRFIX=1 and SWIRGFIL=0:
at a managed field the irrigation must be PRESCRIBED. Leaving the .crp
demand closure (SCHEDULE=1 / TCS=1) in charge holds Tact near Tpot by
construction, which makes scoring actual ET against eddy covariance
near-circular (dt_023).
"""

import argparse
import os
import re
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Table specifications — each table is located by its COLUMN-NAME header row
# and terminated by a `* End of table` line.
# ---------------------------------------------------------------------------
MVG_COLUMNS = ["ORES", "OSAT", "ALFA", "NPAR", "KSATFIT",
               "LEXP", "ALFAW", "H_ENPR", "KSATEXM", "BDENS"]
CROP_COLUMNS = ["CROPSTART", "CROPEND", "CROPFIL", "CROPTYPE"]
IRRIGATION_COLUMNS = ["IRDATE", "IRDEPTH", "IRCONC", "IRTYPE"]
SOILPROFILE_COLUMNS = ["ISUBLAY", "ISOILLAY", "HSUBLAY", "HCOMP", "NCOMP"]

END_OF_TABLE = "* End of table"

# Switches whose admissible values are fixed by the SWAP 4.2.0 input reference.
# Anything outside the domain aborts ttutil before the run starts.
SWITCH_DOMAINS = {
    "SWIRFIX": (0, 1),
    "SWIRGFIL": (0, 1),
    "SWCROP": (0, 1),
    "SWSOPHY": (0, 1),
    "SWDRA": (0, 1, 2),
    "SWVAP": (0, 1),
    "SWBLC": (0, 1),
    "SWINCO": (1, 2, 3),
    "SWBOTB": (1, 2, 3, 4, 5, 6, 7, 8),
}
# Any other SW* integer switch: SWAP has no option code above 8.
SWITCH_GENERIC_MAX = 8

# Filename-valued keys — Linux is case sensitive and SWAP lowercases nothing
# (dt_008).
FILENAME_KEYS = ["METFIL", "CROPFIL", "DRFIL", "IRGFIL", "INIFIL",
                 "BBCFIL", "OUTFIL", "AFO", "SOILTEXT"]


# ---------------------------------------------------------------------------
# Table location
# ---------------------------------------------------------------------------
def _header_regex(colnames):
    """
    Build the column-name header matcher for a .swp table.

    The anchor is `^[ \\t]*` and NOT `^\\s*` on purpose (dt_022): `\\s` also
    matches the newline that ENDS the previous line, so a match offset taken
    from a whole-file search converts to a line index one line early. Slicing
    there eats the column-name header, SWAP's ttutil rddata then reads the
    first data row as the header and aborts with "Inconsistent variable type".
    """
    return re.compile(r"^[ \t]*" + r"[ \t]+".join(colnames) + r"[ \t]*$")


def locate_table(lines, colnames):
    """
    Find a table by its column-name header row.

    Returns (header_index, end_index) where header_index is the line holding
    the column names (KEPT — never replaced) and end_index is the
    `* End of table` line. Returns None when the table is absent.
    """
    hdr = _header_regex(colnames)
    for i, line in enumerate(lines):
        if hdr.match(line.rstrip("\n")):
            for j in range(i + 1, len(lines)):
                if lines[j].strip().lower().startswith(END_OF_TABLE.lower()):
                    return i, j
            raise ValueError(
                f"Table '{' '.join(colnames)}' has no '{END_OF_TABLE}' terminator"
            )
    return None


def replace_table_rows(lines, colnames, new_rows):
    """
    Replace the data rows of a table, keeping the column-name header line and
    the `* End of table` terminator intact.

    new_rows : list of str (no trailing newline)
    """
    loc = locate_table(lines, colnames)
    if loc is None:
        raise ValueError(
            f"Could not locate table with columns: {' '.join(colnames)}"
        )
    hdr_i, end_i = loc
    body = [r.rstrip("\n") + "\n" for r in new_rows]
    return lines[: hdr_i + 1] + body + lines[end_i:]


# ---------------------------------------------------------------------------
# Scalar substitution
# ---------------------------------------------------------------------------
def set_scalar(lines, key, value):
    """
    Replace `  KEY = VALUE   ! comment` in place, preserving the comment AND
    the existing quoting.

    SWAP's ttutil types every entry from the template: a character-valued key
    such as OUTFIL or METFIL must stay quoted. Writing `OUTFIL = result`
    where the template had `OUTFIL = 'result'` makes rddata abort with
    "Value expected" before the run starts.

    Returns (lines, True) when the key was found.
    """
    pattern = re.compile(r"^([ \t]*" + re.escape(key) + r"[ \t]*=[ \t]*)(.*?)([ \t]*!.*)?$")
    out = []
    found = False
    for line in lines:
        m = pattern.match(line.rstrip("\n"))
        if m and not found:
            old = m.group(2).strip()
            comment = m.group(3) or ""
            new = str(value).strip()
            was_quoted = len(old) >= 2 and old[0] == old[-1] == "'"
            is_quoted = len(new) >= 2 and new[0] == new[-1] == "'"
            if was_quoted and not is_quoted:
                new = "'" + new.strip("'") + "'"
            out.append(f"{m.group(1)}{new}{comment}\n")
            found = True
        else:
            out.append(line)
    return out, found


def get_scalar(content, key):
    """Read a scalar key's raw value from .swp content, or None."""
    m = re.search(r"^[ \t]*" + re.escape(key) + r"[ \t]*=[ \t]*([^!\n]+)",
                  content, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip()


# ---------------------------------------------------------------------------
# Input table readers
# ---------------------------------------------------------------------------
def read_table_file(path, expect_columns):
    """
    Read a helper table file produced by another stage tool.

    Skips blank lines, `*` comments and a repeated column-name header, and
    returns the data rows verbatim (already SWAP-formatted).
    """
    rows = []
    hdr_tokens = {c.upper() for c in expect_columns}
    with open(path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip() or s.strip().startswith("*") or s.strip().startswith("!"):
                continue
            tokens = {t.upper().strip("'\"") for t in s.split()}
            if tokens & hdr_tokens:
                continue  # the file repeated its own header
            rows.append(s)
    if not rows:
        raise ValueError(f"No data rows found in {path}")
    return rows


def parse_irrigation_spec(spec):
    """Parse a `DATE,DEPTH,CONC,TYPE` --irrigation argument into a .swp row."""
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 4:
        raise ValueError(
            f"--irrigation expects DATE,DEPTH,CONC,TYPE — got '{spec}'"
        )
    date, depth, conc, irtype = parts
    datetime.strptime(date, "%Y-%m-%d")  # raises on a malformed date
    return f" {date}  {float(depth):7.1f}  {float(conc):7.1f}  {int(irtype):5d}"


def read_irrigation_file(path):
    """
    Read an irrigation event file.

    Accepts either whitespace- or comma-separated `DATE DEPTH CONC TYPE`
    rows; `*`/`!` comments and a repeated header are skipped.
    """
    rows = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("*") or s.startswith("!"):
                continue
            if "IRDATE" in s.upper():
                continue
            parts = [p for p in re.split(r"[,\s]+", s) if p]
            if len(parts) < 4:
                raise ValueError(
                    f"{path}: expected DATE DEPTH CONC TYPE, got '{s}'"
                )
            rows.append(parse_irrigation_spec(",".join(parts[:4])))
    if not rows:
        raise ValueError(f"No irrigation events found in {path}")
    return rows


# ---------------------------------------------------------------------------
# Crop-file (.crp) irrigation-scheduling closure
#
# SWAP's fixed irrigation (.swp SWIRFIX) and its scheduled irrigation
# (.crp SCHEDULE) are INDEPENDENT sources: with SWIRFIX = 1 and SCHEDULE = 1
# the model applies the prescribed events AND its own demand-driven events on
# top. The shipped reference case proves the intended pairing —
# tests/cases/1.hupselbrook has swap.swp SWIRFIX = 1 with maizes.crp:337,
# grassd.crp:488 and potatod.crp:579 all SCHEDULE = 0, while the scheduling
# block (STARTIRR/ENDIRR/TCS/...) stays in the file unread. Leaving
# SCHEDULE = 1 with the shipped TCS = 1 / TREL = 0.95 defaults irrigates
# whenever Tact/Tpot < 0.95, which holds Tact near Tpot all season and makes
# scoring actual ET against eddy covariance near-circular (dt_023).
#
# .crp files are read AND written as latin-1: that round-trips every byte, so
# rewriting one switch can never corrupt a degree sign elsewhere in the file.
# ---------------------------------------------------------------------------
def resolve_crp(swp_path, content, cropfil, crp_dir=None):
    """
    Locate a .crp referenced from a .swp by CROPFIL.

    Search order: an explicit --crp-dir, then PATHCROP from the .swp
    (relative to the .swp's own directory), then the .swp's directory.
    Returns the path, or None when the file cannot be found.
    """
    base = os.path.dirname(os.path.abspath(swp_path))
    cands = []
    if crp_dir:
        cands.append(crp_dir)
    m = re.search(r"^[ \t]*PATHCROP[ \t]*=[ \t]*'([^']*)'", content,
                  re.MULTILINE)
    if m:
        p = m.group(1).strip()
        cands.append(p if os.path.isabs(p) else os.path.join(base, p))
    cands.append(base)
    for d in cands:
        cand = os.path.join(d, cropfil + ".crp")
        if os.path.isfile(cand):
            return cand
    return None


def crp_schedule(crp_path):
    """Return the .crp SCHEDULE switch as a string, or None when absent."""
    with open(crp_path, "r", encoding="latin-1") as f:
        return get_scalar(f.read(), "SCHEDULE")


def close_crp_schedule(crp_path):
    """
    Force SCHEDULE = 0 in a .crp so the crop file cannot add its own
    demand-driven irrigation on top of prescribed events (dt_023).

    Returns True when the file was rewritten, False when it was already
    closed. Raises ValueError when the file has no SCHEDULE key at all —
    silently leaving an unverifiable crop file in a scored run is exactly
    the failure this closure exists to prevent.
    """
    with open(crp_path, "r", encoding="latin-1") as f:
        lines = f.readlines()
    current = (get_scalar("".join(lines), "SCHEDULE") or "").strip()
    if current == "0":
        return False
    if current == "":
        raise ValueError(
            f"{crp_path} has no SCHEDULE key — the irrigation-scheduling "
            f"closure cannot be established"
        )
    new_lines, found = set_scalar(lines, "SCHEDULE", "0")
    if not found:
        raise ValueError(f"{crp_path}: could not rewrite SCHEDULE")
    with open(crp_path, "w", encoding="latin-1") as f:
        f.writelines(new_lines)
    return True


def close_referenced_crp_schedules(swp_path, crp_dir=None):
    """
    Inspect every .crp referenced by the crop rotation table of `swp_path`
    and rewrite SCHEDULE to 0. Exits non-zero when a referenced crop file
    cannot be located or has no SCHEDULE key.
    """
    with open(swp_path, "r") as f:
        lines = f.readlines()
    content = "".join(lines)

    closed, already, missing = [], [], []
    for row in _table_data_rows(lines, CROP_COLUMNS):
        vals = row.split()
        if len(vals) < 3:
            continue
        cf = vals[2].strip("'\"")
        crp = resolve_crp(swp_path, content, cf, crp_dir=crp_dir)
        if crp is None:
            missing.append(cf)
            continue
        try:
            if close_crp_schedule(crp):
                closed.append(os.path.basename(crp))
            else:
                already.append(os.path.basename(crp))
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    if missing:
        print(f"ERROR: prescribed irrigation requires the SCHEDULE closure, but "
              f"these crop files could not be located: "
              f"{', '.join(sorted(set(missing)))} "
              f"(searched --crp-dir, PATHCROP and the .swp directory)",
              file=sys.stderr)
        sys.exit(1)
    for name in closed:
        print(f"  [OK] {name}: SCHEDULE rewritten 1 -> 0 (dt_023 closure)")
    for name in already:
        print(f"  [OK] {name}: SCHEDULE already 0")
    return closed


# ---------------------------------------------------------------------------
# Validation — the traps recorded in diagnostics/triplets.yaml
# ---------------------------------------------------------------------------
def _table_data_rows(lines, colnames):
    loc = locate_table(lines, colnames)
    if loc is None:
        return []
    hdr_i, end_i = loc
    out = []
    for line in lines[hdr_i + 1: end_i]:
        s = line.strip()
        if not s or s.startswith("*") or s.startswith("!"):
            continue
        out.append(s)
    return out


def check_config(swp_path, verbose=True, crp_dir=None):
    """
    Validate an assembled .swp against the known SWAP config traps.

    Returns True when the file passes, False when any trap fires. Never
    raises on a malformed file — a parse failure is itself a failure.

    `crp_dir` overrides where the .crp files referenced by the crop rotation
    table are looked up for the dt_023 SCHEDULE closure check.
    """
    errors = []
    warnings = []

    if not os.path.isfile(swp_path):
        print(f"ERROR: .swp not found: {swp_path}", file=sys.stderr)
        return False

    with open(swp_path, "r") as f:
        lines = f.readlines()
    content = "".join(lines)

    # --- switch domains (rejects e.g. SWIRFIX = 9) --------------------------
    for m in re.finditer(r"^[ \t]*(SW[A-Z0-9_]*)[ \t]*=[ \t]*(-?\d+)[ \t]*(?:!|$)",
                         content, re.MULTILINE):
        key, raw = m.group(1), int(m.group(2))
        domain = SWITCH_DOMAINS.get(key)
        if domain is not None:
            if raw not in domain:
                errors.append(
                    f"{key} = {raw} is outside its admissible domain {domain}"
                )
        elif raw < 0 or raw > SWITCH_GENERIC_MAX:
            errors.append(
                f"{key} = {raw} is outside the generic switch range "
                f"[0, {SWITCH_GENERIC_MAX}]"
            )

    # --- dt_006 / dt_007: MvG table ----------------------------------------
    for n, row in enumerate(_table_data_rows(lines, MVG_COLUMNS), start=1):
        vals = row.split()
        if len(vals) < len(MVG_COLUMNS):
            errors.append(f"MvG layer {n}: expected {len(MVG_COLUMNS)} columns, "
                          f"got {len(vals)}")
            continue
        try:
            ores, osat = float(vals[0]), float(vals[1])
            npar, ksatfit = float(vals[3]), float(vals[4])
            bdens = float(vals[9])
        except ValueError:
            errors.append(f"MvG layer {n}: non-numeric entry in '{row}'")
            continue
        if not ores < osat:
            errors.append(f"MvG layer {n}: ORES ({ores}) must be strictly "
                          f"less than OSAT ({osat})")   # dt_006
        if npar <= 1.001:
            errors.append(f"MvG layer {n}: NPAR ({npar}) must exceed 1.001")
        if ksatfit <= 0:
            errors.append(f"MvG layer {n}: KSATFIT ({ksatfit}) must be > 0")
        if not (100.0 <= bdens <= 10000.0):
            errors.append(f"MvG layer {n}: BDENS ({bdens}) outside "
                          f"[100, 10000] mg/cm3 — g/cm3 was probably not "
                          f"scaled by 1000")   # dt_007

    # --- dt_015: NCOMP * HCOMP == HSUBLAY ----------------------------------
    for n, row in enumerate(_table_data_rows(lines, SOILPROFILE_COLUMNS), start=1):
        vals = row.split()
        if len(vals) < 5:
            errors.append(f"Soil profile row {n}: expected 5 columns, got {len(vals)}")
            continue
        try:
            hsublay, hcomp, ncomp = float(vals[2]), float(vals[3]), int(vals[4])
        except ValueError:
            errors.append(f"Soil profile row {n}: non-numeric entry in '{row}'")
            continue
        if abs(ncomp * hcomp - hsublay) > 1e-6:
            errors.append(
                f"Soil sub-layer {n}: NCOMP*HCOMP ({ncomp}*{hcomp} = "
                f"{ncomp * hcomp}) != HSUBLAY ({hsublay})"
            )   # dt_015

    # --- dt_013 / dt_014: crop calendar ------------------------------------
    crop_rows = _table_data_rows(lines, CROP_COLUMNS)
    periods = []
    for n, row in enumerate(crop_rows, start=1):
        vals = row.split()
        if len(vals) < 4:
            errors.append(f"Crop row {n}: expected 4 columns, got {len(vals)}")
            continue
        try:
            cs = datetime.strptime(vals[0], "%Y-%m-%d")
            ce = datetime.strptime(vals[1], "%Y-%m-%d")
        except ValueError:
            errors.append(f"Crop row {n}: dates must be YYYY-MM-DD, got "
                          f"'{vals[0]}' / '{vals[1]}'")
            continue
        if ce <= cs:
            errors.append(f"Crop row {n}: CROPEND ({vals[1]}) must follow "
                          f"CROPSTART ({vals[0]})")
        periods.append((cs, ce, vals[2].strip("'\"")))

    for n in range(len(periods) - 1):
        if not periods[n][1] < periods[n + 1][0]:
            errors.append(
                f"Crop periods overlap: CROPEND "
                f"({periods[n][1]:%Y-%m-%d}) is not before the next CROPSTART "
                f"({periods[n + 1][0]:%Y-%m-%d})"
            )   # dt_014

    tstart_raw = get_scalar(content, "TSTART")
    tend_raw = get_scalar(content, "TEND")
    if tstart_raw and periods:
        try:
            tstart = datetime.strptime(tstart_raw, "%Y-%m-%d")
            if tstart > periods[0][0]:
                errors.append(
                    f"TSTART ({tstart_raw}) is after the first CROPSTART "
                    f"({periods[0][0]:%Y-%m-%d})"
                )   # dt_013
        except ValueError:
            errors.append(f"TSTART is not YYYY-MM-DD: '{tstart_raw}'")
    if tstart_raw and tend_raw:
        try:
            if datetime.strptime(tend_raw, "%Y-%m-%d") <= \
               datetime.strptime(tstart_raw, "%Y-%m-%d"):
                errors.append(f"TEND ({tend_raw}) must follow TSTART ({tstart_raw})")
        except ValueError:
            pass

    # --- irrigation consistency (both directions) ---------------------------
    # A populated IRDATE table with SWIRFIX != 1 is the dangerous case: SWAP
    # reads the switch, never the table, so the events vanish with no message
    # and the run silently becomes non-prescribed.
    swirfix = (get_scalar(content, "SWIRFIX") or "").strip()
    swirgfil = (get_scalar(content, "SWIRGFIL") or "").strip()
    irr_rows = _table_data_rows(lines, IRRIGATION_COLUMNS)

    if irr_rows and swirfix != "1":
        errors.append(
            f"The IRDATE table holds {len(irr_rows)} prescribed event(s) but "
            f"SWIRFIX = {swirfix or 'unset'} — SWAP would ignore every one of "
            f"them and apply no fixed irrigation"
        )
    if irr_rows and swirfix == "1" and swirgfil not in ("", "0"):
        errors.append(
            f"The IRDATE table holds {len(irr_rows)} event(s) but "
            f"SWIRGFIL = {swirgfil} — SWAP reads IRGFIL instead and the "
            f"in-file table is ignored"
        )
    if swirfix == "1" and swirgfil == "0" and not irr_rows:
        errors.append("SWIRFIX = 1 with SWIRGFIL = 0 but the IRDATE table "
                      "is empty")

    # Row syntax is checked unconditionally — a malformed row must not be
    # excused by the switch that happens to be set.
    for n, row in enumerate(irr_rows, start=1):
        vals = row.split()
        if len(vals) < 4:
            errors.append(f"Irrigation row {n}: expected 4 columns")
            continue
        try:
            datetime.strptime(vals[0], "%Y-%m-%d")
            depth = float(vals[1])
        except ValueError:
            errors.append(f"Irrigation row {n}: malformed '{row}'")
            continue
        if not (0.0 <= depth <= 1000.0):
            errors.append(f"Irrigation row {n}: IRDEPTH ({depth}) outside "
                          f"[0, 1000] mm")

    # --- dt_023: prescribed irrigation must close the .crp scheduling loop --
    if swirfix == "1":
        for row in crop_rows:
            vals = row.split()
            if len(vals) < 3:
                continue
            cf = vals[2].strip("'\"")
            crp = resolve_crp(swp_path, content, cf, crp_dir=crp_dir)
            if crp is None:
                errors.append(
                    f"SWIRFIX = 1 but crop file '{cf}.crp' cannot be located "
                    f"— the SCHEDULE closure (dt_023) cannot be verified"
                )
                continue
            sched = (crp_schedule(crp) or "").strip()
            if sched != "0":
                errors.append(
                    f"{os.path.basename(crp)}: SCHEDULE = "
                    f"{sched or 'absent'} while the .swp prescribes irrigation "
                    f"(SWIRFIX = 1) — SWAP would apply its own demand-driven "
                    f"irrigation ON TOP of the prescribed events, holding Tact "
                    f"near Tpot and making an ET score near-circular (dt_023). "
                    f"Set SCHEDULE = 0."
                )

    # --- dt_008: referenced filenames must be lowercase ---------------------
    work_dir = os.path.dirname(os.path.abspath(swp_path))
    for key in FILENAME_KEYS:
        for m in re.finditer(r"^[ \t]*" + key + r"[ \t]*=[ \t]*'([^']+)'",
                             content, re.MULTILINE):
            name = m.group(1)
            if name != name.lower():
                errors.append(f"{key} = '{name}' is not lowercase — Linux "
                              f"will not find it")   # dt_008
    for row in crop_rows:
        vals = row.split()
        if len(vals) >= 3:
            cf = vals[2].strip("'\"")
            if cf != cf.lower():
                errors.append(f"CROPFIL '{cf}' is not lowercase")
            if not os.path.isfile(os.path.join(work_dir, cf + ".crp")):
                warnings.append(f"Crop file not found next to the .swp: {cf}.crp")

    if verbose:
        for w in warnings:
            print(f"WARNING: {w}")
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        if verbose:
            print(f"[FAIL] check_config: {len(errors)} traps fired in {swp_path}")
        return False
    if verbose:
        print(f"[OK] check_config passed ({len(warnings)} warnings): {swp_path}")
    return True


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def _reject_closure_overrides(sets):
    """
    Refuse a --set that would contradict the prescribed-irrigation closure.

    Supplying irrigation events is a declaration that irrigation is
    PRESCRIBED. The forced switches are also re-asserted after the --set loop,
    so ordering cannot bypass them; this check exists so the operator gets a
    loud error instead of a silently overridden intent.
    """
    for kv in (sets or []):
        if "=" not in kv:
            continue
        key, value = kv.split("=", 1)
        key = key.strip().upper()
        value = value.strip().strip("'\"")
        if key == "SWIRFIX" and value != "1":
            print(f"ERROR: irrigation events were supplied, which forces "
                  f"SWIRFIX = 1, but --set SWIRFIX={value} demands the "
                  f"opposite. Drop the events or drop the override.",
                  file=sys.stderr)
            sys.exit(1)
        if key == "SWIRGFIL" and value != "0":
            print(f"ERROR: irrigation events were supplied, which forces "
                  f"SWIRGFIL = 0 (events live in the .swp), but --set "
                  f"SWIRGFIL={value} demands a separate .irg file. Drop the "
                  f"events or drop the override.", file=sys.stderr)
            sys.exit(1)
        if key == "SCHEDULE":
            print("ERROR: SCHEDULE is a .crp switch, not a .swp key; "
                  "prescribed irrigation forces SCHEDULE = 0 in every "
                  "referenced crop file automatically.", file=sys.stderr)
            sys.exit(1)


def assemble(base, output, sets=None, mvg_table=None, crop_table=None,
             irrigation=None, irrigation_file=None, crp_dir=None):
    """Build `output` from `base` and return the path written."""
    if not os.path.isfile(base):
        print(f"ERROR: base template not found: {base}", file=sys.stderr)
        sys.exit(1)

    with open(base, "r") as f:
        lines = f.readlines()

    # 1. tables first — they shift line numbers, so do them before nothing
    #    else depends on position (all scalar edits are regex-matched).
    if mvg_table:
        rows = read_table_file(mvg_table, MVG_COLUMNS)
        lines = replace_table_rows(lines, MVG_COLUMNS, rows)
        print(f"  [OK] MvG table: {len(rows)} soil physical layers")

    if crop_table:
        rows = read_table_file(crop_table, CROP_COLUMNS)
        lines = replace_table_rows(lines, CROP_COLUMNS, rows)
        print(f"  [OK] Crop rotation table: {len(rows)} crop periods")

    irr_rows = []
    if irrigation_file:
        irr_rows.extend(read_irrigation_file(irrigation_file))
    for spec in (irrigation or []):
        irr_rows.append(parse_irrigation_spec(spec))

    if irr_rows:
        _reject_closure_overrides(sets)
        lines = replace_table_rows(lines, IRRIGATION_COLUMNS, irr_rows)

    # 2. scalar overrides
    for kv in (sets or []):
        if "=" not in kv:
            print(f"ERROR: --set expects KEY=VALUE, got '{kv}'", file=sys.stderr)
            sys.exit(1)
        key, value = kv.split("=", 1)
        key, value = key.strip(), value.strip()
        lines, found = set_scalar(lines, key, value)
        if not found:
            print(f"ERROR: --set {key}: key not present in {base}", file=sys.stderr)
            sys.exit(1)
        print(f"  [OK] {key} = {value}")

    # 3. FORCED closure — asserted AFTER the --set loop so no override
    #    ordering can leave a non-prescribed irrigation config behind. The
    #    earlier version set these BEFORE the loop and `--irrigation ...
    #    --set SWIRFIX=0` silently won.
    if irr_rows:
        lines, ok_fix = set_scalar(lines, "SWIRFIX", "1")
        lines, ok_gfil = set_scalar(lines, "SWIRGFIL", "0")
        if not (ok_fix and ok_gfil):
            print(f"ERROR: {base} has no SWIRFIX/SWIRGFIL key — it is not a "
                  f"SWAP 4.2.0 main input template", file=sys.stderr)
            sys.exit(1)
        total_mm = sum(float(r.split()[1]) for r in irr_rows)
        print(f"  [OK] Fixed irrigation: {len(irr_rows)} events, "
              f"{total_mm:.1f} mm total (SWIRFIX=1, SWIRGFIL=0 — forced)")

    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w") as f:
        f.writelines(lines)
    print(f"[OK] Wrote assembled config to {output}")

    # 4. and the crop files the assembled .swp points at must not schedule
    #    their own irrigation on top of the prescribed events (dt_023).
    if irr_rows:
        close_referenced_crp_schedules(output, crp_dir=crp_dir)

    return output


def main():
    p = argparse.ArgumentParser(
        description="Assemble a site SWAP .swp from a validated base template"
    )
    p.add_argument("--base", help="Base .swp template")
    p.add_argument("--output", help="Assembled .swp to write")
    p.add_argument("--check", default=None, metavar="SWP",
                   help="Validate an EXISTING .swp and exit (no assembly)")
    p.add_argument("--crp-dir", default=None,
                   help="Directory holding the referenced .crp files "
                        "(default: PATHCROP, else the .swp's own directory)")
    p.add_argument("--set", action="append", dest="sets", default=[],
                   metavar="KEY=VALUE", help="Scalar override (repeatable)")
    p.add_argument("--mvg-table", default=None,
                   help="File with MvG soil rows (from convert_soil_to_swap.py)")
    p.add_argument("--crop-table", default=None,
                   help="File with CROPSTART CROPEND CROPFIL CROPTYPE rows")
    p.add_argument("--irrigation", action="append", default=[],
                   metavar="DATE,DEPTH,CONC,TYPE",
                   help="Fixed irrigation event (repeatable)")
    p.add_argument("--irrigation-file", default=None,
                   help="File of DATE DEPTH CONC TYPE irrigation events")
    p.add_argument("--no-check", action="store_true",
                   help="Skip the post-assembly config check")
    args = p.parse_args()

    if args.check:
        sys.exit(0 if check_config(args.check, crp_dir=args.crp_dir) else 1)

    if not args.base or not args.output:
        p.error("--base and --output are required unless --check is given")

    out = assemble(args.base, args.output, sets=args.sets,
                   mvg_table=args.mvg_table, crop_table=args.crop_table,
                   irrigation=args.irrigation,
                   irrigation_file=args.irrigation_file,
                   crp_dir=args.crp_dir)

    # --no-check may skip the optional traps, but NEVER the closure that
    # prescribed irrigation depends on.
    forced = bool(args.irrigation or args.irrigation_file)
    if forced or not args.no_check:
        if not check_config(out, crp_dir=args.crp_dir):
            sys.exit(1)


if __name__ == "__main__":
    main()
