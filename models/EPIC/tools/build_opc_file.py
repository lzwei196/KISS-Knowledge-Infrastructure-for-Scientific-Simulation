#!/usr/bin/env python3
"""Build an EPIC .OPC operation-schedule file by copying umstead.OPC and
rewriting the op table for a user-specified crop/plant/harvest/fertilizer."""
import argparse
import os
import sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import copy_template, read_text_crlf, write_text_crlf, template_path


def _lookup_crop_code(name):
    text = read_text_crlf(template_path("CROPCOM.DAT"))
    for line in text.splitlines()[2:]:
        toks = line.split()
        if len(toks) >= 2 and toks[1].upper() == name.upper():
            return int(toks[0])
    raise SystemExit(f"Crop '{name}' not found in CROPCOM.DAT")


def _lookup_crop_row(name):
    """Return the CROPCOM.DAT token row for a crop name (or None)."""
    text = read_text_crlf(template_path("CROPCOM.DAT"))
    for line in text.splitlines()[2:]:
        toks = line.split()
        if len(toks) >= 6 and toks[1].upper() == name.upper():
            return toks
    return None


def crop_base_temp(name, default=8.0):
    """Base temperature TBS (degC) for a crop, from CROPCOM.DAT.

    CROPCOM row layout: `code NAME WA HI TOP TBS ...`, so TBS is token 5.
    CORN=8.0, SOYB=10.0, WWHT=0.0.
    """
    toks = _lookup_crop_row(name)
    if not toks:
        return default
    try:
        return float(toks[5])
    except (ValueError, IndexError):
        return default


def _parse_mmdd(s):
    m, d = s.split("-")
    return int(m), int(d)


def _jday(mo, dy):
    return date(2001, mo, dy).timetuple().tm_yday


def compute_phu(dly_path, plant_mmdd, harvest_mmdd, base_temp,
                fraction=1.0, min_years=1):
    """Site-specific Potential Heat Units (degC-days) from the run's own .DLY.

    WHY THIS EXISTS: the plant operation's OPV1 is the crop's PHU — the
    heat-unit total that defines maturity (EPIC reports HUSC = accumulated HU
    / PHU at each operation). This tool used to hard-code OPV1 = 1550, the
    value inherited from the shipped umstead (North Carolina) example, at
    EVERY site. Where the local growing season accumulates materially more or
    fewer heat units than piedmont NC, the crop then reaches maturity well
    before (or after) the scheduled harvest date, and HUSC at harvest falls
    outside the dag's 0.9-1.2 band — which the dag flags as "yields are
    suspect". Observed at Changchun, Jilin spring maize: HUSC 1.10 / 1.45 with
    PHU=1550 against a season that accumulates ~1750-1900 degC-days.

    Standard EPIC/SWAT practice is to derive PHU from the local climatology of
    the intended growing season. This sums daily HU = max(0, Tmean - TBS) from
    the planting to the harvest date and averages over the years in the .DLY.
    `fraction` < 1 targets maturity slightly BEFORE the scheduled harvest.

    Returns None if the .DLY cannot be parsed, so callers can fall back.
    """
    pm, pdd = _parse_mmdd(plant_mmdd)
    hm, hdd = _parse_mmdd(harvest_mmdd)
    plant_doy, harvest_doy = _jday(pm, pdd), _jday(hm, hdd)
    winter = plant_doy > harvest_doy          # season wraps the new year

    try:
        with open(dly_path, "rb") as fh:
            raw = fh.read().decode("ascii", "replace")
    except OSError:
        return None

    per_year = {}
    for line in raw.replace("\r", "").splitlines():
        if not line.strip():
            continue
        try:                                   # fixed-width Fortran layout
            y, mo, dy = int(line[0:6]), int(line[6:10]), int(line[10:14])
            tmx, tmn = float(line[20:26]), float(line[26:32])
        except ValueError:
            toks = line.split()
            if len(toks) < 6:
                continue
            try:
                y, mo, dy = int(toks[0]), int(toks[1]), int(toks[2])
                tmx, tmn = float(toks[4]), float(toks[5])
            except ValueError:
                continue
        try:
            doy = date(y, mo, dy).timetuple().tm_yday
        except ValueError:
            continue
        hu = max(0.0, 0.5 * (tmx + tmn) - base_temp)
        if winter:
            # attribute a wrapped season to its PLANTING year
            if doy >= plant_doy:
                per_year[y] = per_year.get(y, 0.0) + hu
            elif doy <= harvest_doy:
                per_year[y - 1] = per_year.get(y - 1, 0.0) + hu
        elif plant_doy <= doy <= harvest_doy:
            per_year[y] = per_year.get(y, 0.0) + hu

    vals = [v for v in per_year.values() if v > 0]
    if winter and len(vals) > 2:
        vals = sorted(vals)[1:-1]              # drop truncated first/last year
    if len(vals) < min_years:
        return None
    return round(fraction * sum(vals) / len(vals), 1)


def _op_line(year, mo, dy, equip, tractor, crop_id, context,
             v1=0.0, v2=0.0, v3=0.0, v4=0.0, v5=0.0, v6=0.0, v7=0.0, v8=0.0, v9=0.0):
    """Format one EPIC OPC operation line.

    EPIC OPC column layout (from edit_opc.py / EPIC docs):
      YR(I3) MO(I3) DY(I3) EQUIP(I5) TRACTOR(I5) CROP_ID(I5) CONTEXT(I5) V1..V9(F8.2)

    crop_id: CROPCOM.DAT crop code (e.g., 2=CORN, 10=WWHT)
    context: fertilizer/pesticide code from FERT2012.DAT or PESTCOM.DAT (0 for none)
    """
    return (
        f"{year:>3d}{mo:>3d}{dy:>3d}{equip:>5d}{tractor:>5d}{crop_id:>5d}{context:>5d}"
        f"{v1:>8.2f}{v2:>8.2f}{v3:>8.2f}{v4:>8.2f}{v5:>8.2f}"
        f"{v6:>8.2f}{v7:>8.2f}{v8:>8.2f}{v9:>8.2f}"
    )


def build(name, crop, plant_date, harvest_date, kill_date,
          fert_day, fert_n, workspace, fert_code=21,
          fert_p=0.0, fert_k=0.0, n_cap=9999.0, phu=None, ppop=10.0):
    """Build EPIC OPC file.

    Args:
        fert_n: N rate in kg-N/ha (elemental N, not material weight)
        fert_code: FERT2012.DAT code. Default 21 = Elemental-N (100% N).
                   Other options: 51 = Urea (46% N), 25 = AnhydAm (82% N)
        fert_p: P rate in kg-P/ha (elemental P). Applied as code 22.
        fert_k: K rate in kg-K/ha (elemental K). Applied as code 23.
        n_cap: OPV6 of the plant row = maximum N-fertilizer cap. EPIC treats a
               0 here as a default ~200 kg/ha CUMULATIVE (lifetime) cap across
               the whole simulation, so scheduled annual fert only applies in
               the first ~year and yields then decline as soil N is mined (see
               diagnostics triplet EPIC_018, discovered at zhengzhou_corn).
               A large value (default 9999) removes the artificial cap so each
               rotation year's scheduled fertilizer is applied as written.
        phu: OPV1 of the plant row = Potential Heat Units (degC-days) that
             define crop maturity. None keeps the legacy 1550 (the shipped
             umstead North-Carolina value), which is WRONG for any site whose
             season accumulates a different heat-unit total and pushes HUSC at
             harvest outside the dag's 0.9-1.2 band. Derive a site value with
             compute_phu(<stn>.DLY, plant, harvest, crop_base_temp(crop)) and
             pass it here — build the forcing BEFORE the .OPC so the .DLY is
             available.
        ppop: OPV5 of the plant row = plant population (plants m-2), echoed
             back as the .ACY PPOP column. The default 10.0 is the shipped
             umstead North-Carolina value, i.e. the SAME class of site-blind
             legacy as phu=1550, and it drives LAI, biomass and therefore
             yield. 10 plants m-2 (100 000 ha-1) is far denser than most
             real cropping systems (NE-China rainfed spring maize is
             ~6.0-7.5 plants m-2), so a site that knows its planting density
             should pass it. There is no gridded planting-density product on
             this server, so this stays an explicit caller decision rather
             than an auto-derived default — do NOT tune it against the
             observation being scored.
    """
    os.makedirs(workspace, exist_ok=True)
    dst = copy_template("umstead.OPC", workspace, new_name=f"{name}.OPC")

    text = read_text_crlf(dst)
    lines = text.splitlines()

    crop_code = _lookup_crop_code(crop)
    pm, pd = _parse_mmdd(plant_date)
    hm, hd = _parse_mmdd(harvest_date)
    km, kd = _parse_mmdd(kill_date)
    fm, fdd = _parse_mmdd(fert_day)

    # Detect winter crop: planting month > harvest month means cross-year
    winter_crop = pm > hm  # e.g., plant Oct, harvest Jun
    plant_yr = 1
    harvest_yr = 2 if winter_crop else 1

    lines[0] = f"{crop_code:>2d} {crop} 1Y ROT {name} MED TILL"
    # Line 2 = NROT (rotation length) + IAUI. Force NROT=1 for an annual
    # monocrop so EPIC does not mis-cycle a multi-year rotation and so the
    # scheduled (year-1) ops repeat every simulation year (triplet EPIC_018).
    lines[1] = "   1 500"

    ops = []
    # Planting: equip 136, crop_id=crop_code, context=0.
    # v6 = N-fertilizer cap (see n_cap docstring); 0 silently throttles annual
    # fert to a ~200 kg/ha lifetime quota and collapses multi-year yields.
    # v1 = PHU (see `phu` in the docstring); 1550 is the umstead NC legacy.
    ops.append(_op_line(plant_yr, pm, pd, 136, 0, crop_code, 0,
                        v1=float(phu if phu else 1550.0), v5=float(ppop),
                        v6=float(n_cap)))
    # Nitrogen: equip 261, crop_id=crop_code, context=fert_code
    if fert_n > 0:
        ops.append(_op_line(plant_yr, fm, fdd, 261, 0, crop_code, fert_code,
                            v1=float(fert_n), v2=50.8))
    # Phosphorus: context=22 (elemental-P)
    if fert_p > 0:
        ops.append(_op_line(plant_yr, fm, fdd, 261, 0, crop_code, 22,
                            v1=float(fert_p), v2=50.8))
    # Potassium: context=23 (elemental-K)
    if fert_k > 0:
        ops.append(_op_line(plant_yr, fm, fdd, 261, 0, crop_code, 23,
                            v1=float(fert_k), v2=50.8))
    # Harvest: equip 292 (year 2 for winter crops)
    ops.append(_op_line(harvest_yr, hm, hd, 292, 0, crop_code, 0, v7=1.0))
    # Kill crop: equip 451. crop_id MUST be the crop being killed, not 0.
    # The shipped umstead.OPC kill row carries crop_id=2 (CORN); writing 0 here
    # left the standing crop alive, so EPIC never reset its heat-unit index at
    # the end of the season. The residual HUI then carried into the next
    # rotation year (.OUT monthly HUI rows: Jan = 0.00, 0.11, 0.21, 0.29 ...
    # stabilising near 0.30) and HUSC at harvest climbed to 1.14-1.38 —
    # outside the dag's required 0.9-1.2 band. See triplet EPIC_024.
    ops.append(_op_line(harvest_yr, km, kd, 451, 0, crop_code, 0))

    new_lines = lines[:2] + ops
    write_text_crlf(dst, "\r\n".join(new_lines))
    return dst, crop_code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--crop", required=True)
    ap.add_argument("--plant", default="04-24")
    ap.add_argument("--harvest", default="09-01")
    ap.add_argument("--kill", default="09-01")
    ap.add_argument("--fert-day", default="04-24")
    ap.add_argument("--fert-n", type=float, default=143.0)
    ap.add_argument("--workspace", required=True)
    args = ap.parse_args()
    path, code = build(args.name, args.crop, args.plant, args.harvest,
                       args.kill, args.fert_day, args.fert_n, args.workspace)
    print(f"wrote {path} (crop {args.crop} = code {code})")


if __name__ == "__main__":
    main()
