"""s5_update_control.py — Update APEXCONT.DAT simulation period in place.

APEXCONT.DAT line 1 holds the time-control header:
    NBYR  IYR  IMO  IDA  IPD  NGN  ...

We rewrite NBYR (number of years), IYR (start year), IMO/IDA (start month/day),
optionally IPD (print frequency) and NGN (weather generator code). Everything
else on that line, and every subsequent line of APEXCONT.DAT, is preserved.

**Format: Fortran I4 fixed-width (NOT list-directed).** APEX0806 reads line 1
with Fortran I4 format — each token occupies exactly 4 chars. We write all
fields as I4 (``_CONT_WIDTHS = [4] * 20``), which gives, e.g., NBYR=6,
IYR=2010 as ``   62010   1   1...``:
  - Fortran chars 1-4:  "   6" → NBYR = 6  ✓
  - Fortran chars 5-8:  "2010" → IYR = 2010 ✓

**PITFALL — free-format APEXCONT causes NBYR to be parsed as a concatenated
value.** If the source template was written in free format (tokens separated by
spaces, e.g. ``6  2010  1  6  2  ...``), Fortran I4 reads chars 1-4 as ``"6  2"``
which BN-blank-strips to ``"62"`` → NBYR = 62 (a 62-year run, not 6). This is
the "accidental spin-up" behavior of the shipped ex1_RiselTX working case.
s5 always writes proper I4 fixed-width, so NBYR is exact.

**Spin-up requirement.** The ex1_RiselTX template workspace has Texas soil at
Texas-climate equilibrium. For any non-Texas location, 6 years is not enough for
the soil to reach the new location's water/nutrient steady state — expect extreme
water stress (WS > 50) and unrealistically low yields in the first years.
Use ``--spinup-years N`` (default 25) to prepend N extra years before year1;
s7_parse_output will mark spin-up rows with ``spinup=True`` so you can filter
them out. Recommended: N=25 (≥10 min; soil typically equilibrates in 15-20 yr).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

CONT_NAME = "APEXCONT.DAT"

_CONT_WIDTHS = [4] * 20  # 80 cols, all I4 — APEX0806 reads fixed-width, NOT list-directed


def validate_inputs(workspace: Path, year1: int, year2: int) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    if not (workspace / CONT_NAME).is_file():
        raise FileNotFoundError(f"{CONT_NAME} missing in workspace")
    if year2 < year1:
        raise ValueError(f"year2 ({year2}) must be >= year1 ({year1})")
    if year1 < 1900 or year2 > 2100:
        raise ValueError(f"year range {year1}-{year2} outside [1900, 2100]")


# NGN=0 makes APEX0806 IGNORE the *.DLY and generate all six weather variables
# from the *.WP1 monthly statistics. A pipeline that spent hours building real
# daily forcing and then passes ngn=0 silently simulates a random climate --
# the run still succeeds, the yields still look plausible, and the correlation
# against any observed series is ~0 by construction. That is the single most
# expensive silent failure this KI has produced, so we refuse it by default.
NGN_READ_ALL = 2345   # reads SRAD, TMX, TMN, PRCP, RH, WIND (fits I4)


def _daily_weather_wired(ws: Path) -> str | None:
    """Path of a populated daily weather file in the workspace, if any."""
    for p in sorted(ws.glob("*.DLY")) + sorted(ws.glob("*.dly")):
        try:
            n = sum(1 for ln in p.read_text(errors="replace").splitlines()
                    if len(ln.split()) >= 7)
        except OSError:
            continue
        if n >= 365:
            return p.name
    return None


def _guard_ngn(ws: Path, ngn: int, allow_generated_weather: bool) -> int:
    if ngn != 0 or allow_generated_weather:
        return ngn
    dly = _daily_weather_wired(ws)
    if dly is None:
        return ngn          # no real forcing to ignore; generator is correct
    sys.stderr.write(
        f"[s5] WARNING: ngn=0 makes APEX0806 IGNORE {dly} and generate ALL "
        f"weather from the *.WP1 monthly statistics, which destroys any "
        f"year-to-year correspondence with observations. A populated daily "
        f"file is wired, so ngn is being corrected to "
        f"{NGN_READ_ALL} (reads all six DLY columns). Pass "
        f"allow_generated_weather=True to force ngn=0 deliberately.\n"
    )
    return NGN_READ_ALL


def update_control(workspace, *, year1: int, year2: int,
                   month1: int = 1, day1: int = 1,
                   ipd: int = 3, ngn: int = 2,
                   spinup_years: int = 25,
                   allow_generated_weather: bool = False,
                   iet: int | None = None,
                   gws0: float | None = None,
                   rft0: float | None = None,
                   rfp0: float | None = None) -> Path:
    """Update APEXCONT.DAT simulation period (and optionally baseflow params).

    Args:
        spinup_years: Extra years prepended before year1 for soil equilibration.
            The binary runs (spinup_years + year2 - year1 + 1) total years,
            starting from (year1 - spinup_years). s7_parse_output filters
            these out automatically. Default 25 (covers ~2 full weather cycles
            of a 6-12 yr forcing dataset, enough for soil to equilibrate).
            Set to 0 only if you have already run a spin-up separately.
        ngn: Which daily weather variables APEX0806 READS from the *.DLY.
            MEASURED on the Huaibin GDHY workspace 2026-08-09 by perturbing one
            *.DLY column at a time and diffing OUTPUT.ACY (the previous
            docstring here had this exactly BACKWARDS):
              ngn=0      -> reads NOTHING. APEX generates ALL SIX variables
                            stochastically from the *.WP1 monthly statistics.
                            Zeroing all 56 years of *.DLY precipitation leaves
                            OUTPUT.ACY byte-identical; zeroing the WP1 monthly
                            rainfall row collapses maize yield 7.51 -> 0.01
                            t/ha. A run at ngn=0 therefore carries NO
                            year-specific weather signal and cannot correlate
                            with an observed time series (measured r_firstdiff
                            vs GDHY = -0.09).
              ngn=2      -> reads TMX, TMN, PRCP; generates SRAD, RH, WIND.
              ngn=1234   -> reads SRAD, TMX, TMN, PRCP, WIND; generates RH.
              ngn=2345   -> reads ALL SIX (SRAD, TMX, TMN, PRCP, RH, WIND).
            Measured at Huaibin vs GDHY 1981-2016 (36 yr): ngn=0 r_firstdiff
            -0.09 / PBIAS +63.1; ngn=2 0.55 / +65.8; ngn=1234 0.68 / +53.8;
            ngn=2345 0.56 / +49.3. Use 2345 to consume every column you built
            (best magnitude); drop to 1234 if the *.DLY RH column is suspect
            (RH is written as a FRACTION by s2 and only enters via PET).
            NGN must fit the I4 field -- 12345 overflows LINE 1 and shifts
            every later flag by one column.
            ngn=0 is ONLY for a genuine
            synthetic-climate run; passing it with a populated *.DLY is treated
            as a wiring mistake and corrected (see allow_generated_weather).
        allow_generated_weather: Set True to honour ngn=0 even when a populated
            *.DLY is wired (a deliberate weather-generator experiment).
        gws0: Maximum groundwater storage, mm (APEXCONT LINE 4 pos 4, range
            5-200). Higher = more baseflow buffer.
        rft0: Groundwater residence time, days (LINE 4 pos 5, range 0-365).
            Higher = slower, more sustained baseflow recession.
        rfp0: Return-Flow / (Return-Flow + Deep-Percolation) ratio (LINE 4
            pos 6, range 0-1). Higher converts deep-percolation LOSS into
            baseflow that reaches the gauge — the primary lever for matching a
            perennial baseflow-dominated stream. The Riesel TX template ships
            0.51; raise toward 0.8-0.95 for humid baseflow catchments.
    """
    ws = Path(workspace).expanduser().resolve()
    actual_start = year1 - spinup_years
    validate_inputs(ws, actual_start, year2)

    cont_path = ws / CONT_NAME
    lines = cont_path.read_text().splitlines()
    if not lines:
        raise RuntimeError(f"{cont_path} is empty")

    nbyr = year2 - actual_start + 1
    # Parse LINE 1 into its integer fields, then ALWAYS re-emit as fixed-width
    # I4 (the layout APEX0806 reads reliably once we own the file).
    #
    # The shipped ex1_RiselTX / validated-Bengbu templates write LINE 1 in
    # FREE format with 2-space separators (e.g. "6  2010  1  6  2  0 ...").
    # A blind 4-char slice of that produces chunks like "6  2" whose internal
    # space makes int() raise (the historical crash) or, worse, silently maps
    # NBYR onto the wrong column. But a genuinely fixed-width source can pack
    # NBYR+IYR with no separator ("222001" = NBYR 22, IYR 2001), where split()
    # would merge them. So detect the format and parse accordingly, then write
    # canonical I4 either way.
    line0 = lines[0].rstrip("\n")
    toks = line0.split()
    is_free_format = (
        len(toks) >= 6
        and all(t.lstrip("+-").isdigit() for t in toks[:6])
        # a fixed-width NBYR+IYR blob like "222001" is a single 6-digit token
        # in field 0 (year-like), not a short NBYR — free format keeps them apart
        and len(toks[0]) <= 4
    )
    if is_free_format:
        fields = list(toks) + ["0"] * (len(_CONT_WIDTHS) - len(toks))
    else:
        fields = []
        for i in range(len(_CONT_WIDTHS)):
            chunk = line0[i * 4:(i + 1) * 4].strip()
            fields.append(chunk if chunk else "0")
    fields = fields[: len(_CONT_WIDTHS)]
    while len(fields) < len(_CONT_WIDTHS):
        fields.append("0")
    fields[0] = str(nbyr)
    fields[1] = str(actual_start)
    fields[2] = str(month1)
    fields[3] = str(day1)
    fields[4] = str(ipd)
    ngn = _guard_ngn(ws, ngn, allow_generated_weather)
    if not 0 <= ngn <= 9999:
        # LINE 1 is fixed-width I4; a 5-digit NGN (e.g. 12345) does not fit and
        # shifts every following flag one column right -- the same class of
        # silent corruption as triplet apex0806_apexcont_split_field_shift.
        raise ValueError(f"ngn={ngn} does not fit the I4 field on APEXCONT "
                         f"LINE 1 (must be 0-9999)")
    fields[5] = str(ngn)
    if iet is not None:
        # LINE 1 pos 10 = IET, the PET-equation code: 1/0=Penman-Monteith,
        # 2=Penman, 3=Priestley-Taylor, 4=Hargreaves, 5=Baier-Robertson. The
        # Riesel TX template (Penman-Monteith) overestimates PET (~1500 mm/yr)
        # in humid temperate basins; Priestley-Taylor (3) or Hargreaves (4)
        # give realistic PET, freeing water for runoff and baseflow.
        if not 0 <= iet <= 5:
            raise ValueError(f"iet out of range [0,5]: {iet}")
        fields[9] = str(iet)
    lines[0] = "".join(
        f"{int(v):{w}d}" for v, w in zip(fields[: len(_CONT_WIDTHS)], _CONT_WIDTHS)
    )

    # Optional baseflow / groundwater knobs on APEXCONT LINE 4 (free format,
    # 8-char fields): pos4 GWS0, pos5 RFT0, pos6 RFP0. Edit in place only the
    # requested positions, preserving the rest of the line.
    if any(v is not None for v in (gws0, rft0, rfp0)):
        if len(lines) < 4:
            raise RuntimeError(f"{cont_path}: fewer than 4 lines; cannot set baseflow params")
        l4 = lines[3].split()
        while len(l4) < 10:
            l4.append("0.00")
        if gws0 is not None:
            if not 5.0 <= gws0 <= 200.0:
                raise ValueError(f"gws0 out of range [5,200]: {gws0}")
            l4[3] = f"{gws0:.2f}"
        if rft0 is not None:
            if not 0.0 <= rft0 <= 365.0:
                raise ValueError(f"rft0 out of range [0,365]: {rft0}")
            l4[4] = f"{rft0:.2f}"
        if rfp0 is not None:
            if not 0.0 <= rfp0 <= 1.0:
                raise ValueError(f"rfp0 out of range [0,1]: {rfp0}")
            l4[5] = f"{rfp0:.4f}"
        lines[3] = "".join(f"{v:>8}" for v in l4[:10])

    cont_path.write_text("\n".join(lines) + "\n")
    validate_outputs(cont_path, year1, year2, spinup_years=spinup_years)
    return cont_path


def validate_outputs(cont_path: Path, year1: int, year2: int,
                     spinup_years: int = 25) -> None:
    actual_start = year1 - spinup_years
    line = cont_path.read_text().splitlines()[0]
    # Read back as I4 fixed-width (same format we wrote): each field = 4 chars
    nbyr_got = int(line[0:4].strip())
    iyr_got  = int(line[4:8].strip())
    expected_nbyr = year2 - actual_start + 1
    if nbyr_got != expected_nbyr:
        raise RuntimeError(
            f"{cont_path}: NBYR write-back mismatch "
            f"(got {nbyr_got}, expected {expected_nbyr})"
        )
    if iyr_got != actual_start:
        raise RuntimeError(
            f"{cont_path}: IYR write-back mismatch "
            f"(got {iyr_got}, expected {actual_start})"
        )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--year1", type=int, required=True)
    p.add_argument("--year2", type=int, required=True)
    p.add_argument("--allow-generated-weather", action="store_true",
                   help="honour --ngn 0 even when a populated *.DLY is wired")
    p.add_argument("--ngn", type=int, default=2,
                   help="Weather generator code (default 2 = generate TMAX from WP1, read others from DLY)")
    p.add_argument("--spinup-years", type=int, default=25,
                   help="Years of spin-up prepended before year1 (default 25). Set 0 if already spun up.")
    p.add_argument("--gws0", type=float, default=None,
                   help="Max groundwater storage mm (APEXCONT L4 pos4, 5-200). Higher = more baseflow buffer.")
    p.add_argument("--rft0", type=float, default=None,
                   help="Groundwater residence time days (APEXCONT L4 pos5, 0-365). Higher = slower, more sustained baseflow recession.")
    p.add_argument("--rfp0", type=float, default=None,
                   help="Return-flow/(return-flow+deep-perc) ratio (APEXCONT L4 pos6, 0-1). Raise toward 0.8-0.95 for humid perennial baseflow streams; Texas default 0.51 yields near-zero QRF here.")
    p.add_argument("--iet", type=int, default=None,
                   help="PET equation code (APEXCONT L1 pos10): 1=Penman-Monteith, 2=Penman, 3=Priestley-Taylor, 4=Hargreaves, 5=Baier-Robertson. Texas template default (PM) overestimates PET in humid temperate basins; use 3 or 4 to free water for runoff and baseflow.")
    args = p.parse_args()
    out = update_control(args.workspace, year1=args.year1, year2=args.year2,
                         ngn=args.ngn, spinup_years=args.spinup_years,
                         allow_generated_weather=args.allow_generated_weather,
                         iet=args.iet, gws0=args.gws0, rft0=args.rft0, rfp0=args.rfp0)
    actual_start = args.year1 - args.spinup_years
    nbyr = args.year2 - actual_start + 1
    print(f"[OK] control updated at {out} (NBYR={nbyr}, IYR={actual_start}, spinup={args.spinup_years}yr, ngn={args.ngn})")
