#!/usr/bin/env python3
"""
dssat_workdir_setup.py — Unified DSSAT working directory setup, execution,
and output parsing utility.

Handles the 6+ known pitfalls that cause silent DSSAT failures:
  1. Fortran path truncation (>72 chars) — short /tmp workdir
  2. Missing .CDE files — symlinks from StandardData/
  3. Weather station code mismatch — 4-char code alignment
  4. CUL column alignment — fixed-width Fortran format
  5. DSSATPRO.L48 rewriting — correct paths for genotype, soil, etc.
  6. Summary.OUT parsing — structured dict output

Three public functions:
  create_workdir()  — builds a complete DSSAT working directory
  run_dssat()       — executes dscsm048 from the workdir
  parse_summary()   — parses Summary.OUT into list[dict]

Author: HydroCraft KI / auto-generated for DSSAT v4.8.5
"""

import os
import sys
import shutil
import tempfile
import subprocess
import re
import math
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Union, List, Dict, Any

# ---------------------------------------------------------------------------
# Constants — DSSAT installation paths on this server
# ---------------------------------------------------------------------------
DSSAT_BINARY = Path("KISSPATH_HOME/DSSAT/build/bin/dscsm048")
DSSAT_DATA = Path("KISSPATH_HOME/DSSAT/Data")
DSSAT_GENOTYPE = DSSAT_DATA / "Genotype"
DSSAT_STANDARD_DATA = DSSAT_DATA / "StandardData"
DSSAT_SOIL_SOL = None  # Will use the default soil file from run_test if available
DSSAT_DSSATPRO_TEMPLATE = DSSAT_DATA / "DSSATPRO.v48"

# CDE files that DSSAT requires at runtime
CDE_FILES = [
    "DATA.CDE", "DETAIL.CDE", "ECONOMIC.CDE", "GCOEFF.CDE",
    "GRSTAGE.CDE", "JDATE.CDE", "OUTPUT.CDE", "PEST.CDE",
    "SIMULATION.CDE", "SOIL.CDE", "WEATHER.CDE",
]

# SDA files DSSAT looks for
SDA_FILES = [
    "CO2048.WDA", "FERCH048.SDA", "RESCH048.SDA",
    "SOMFR048.SDA", "SOMFX048.SDA", "TILOP048.SDA",
]

# Model control file
CTR_FILE = "DSCSM048.CTR"

# MODEL.ERR reference file
MODEL_ERR = "MODEL.ERR"

# Crop registry: code -> (FileX ext, genotype prefix, crop name, is_legume)
CROP_REGISTRY = {
    "MZ": (".MZX", "MZCER048", "Maize", False),
    "WH": (".WHX", "CSCER048", "Wheat", False),
    "SB": (".SBX", "CRGRO048", "Soybean", True),
    "RI": (".RIX", "RICER048", "Rice", False),
    "SG": (".SGX", "SGCER048", "Sorghum", False),
    "BA": (".BAX", "CSCER048", "Barley", False),
    "ML": (".MLX", "MLCER048", "Pearl_Millet", False),
    "PN": (".PNX", "CRGRO048", "Peanut", True),
    "BN": (".BNX", "CRGRO048", "Dry_Bean", True),
    "PT": (".PTX", "PTSUB048", "Potato", False),
    "SC": (".SCX", "SCCAN048", "Sugarcane", False),
    "CO": (".COX", "CRGRO048", "Cotton", False),
    "SU": (".SUX", "CRGRO048", "Sunflower", False),
    "TM": (".TMX", "CRGRO048", "Tomato", False),
    "CS": (".CSX", "CSYCA048", "Cassava", False),
    "CH": (".CHX", "CRGRO048", "Chickpea", True),
    "CP": (".CPX", "CRGRO048", "Cowpea", True),
    "PP": (".PPX", "CRGRO048", "Pigeon_Pea", True),
    "FB": (".FBX", "CRGRO048", "Faba_Bean", True),
    "CN": (".CNX", "CRGRO048", "Canola", False),
    "SW": (".SWX", "SWCER048", "Sweet_Corn", False),
}

# Genotype file suffixes
GENOTYPE_SUFFIXES = [".CUL", ".ECO", ".SPE"]

# Default cultivars per crop (used if caller doesn't specify)
DEFAULT_CULTIVARS = {
    "MZ": ("IB0035", "McCurdy 84aa"),
    "WH": ("DFAULT", "DEFAULT"),
    "SB": ("IB0011", "EVANS (0)"),
    "RI": ("IB0012", "IR 58"),
    "SG": ("IB0001", "RIO"),
    "BA": ("DFAULT", "DEFAULT"),
}

# Default management parameters per crop
DEFAULT_MANAGEMENT = {
    "MZ": {"ppop": 7.2, "plrs": 76, "pldp": 5, "fert_n": 120, "fert_date_offset": 30},
    "WH": {"ppop": 350, "plrs": 20, "pldp": 4, "fert_n": 100, "fert_date_offset": 0},
    "SB": {"ppop": 30, "plrs": 38, "pldp": 4, "fert_n": 0, "fert_date_offset": 0},
    "RI": {"ppop": 25, "plrs": 30, "pldp": 3, "fert_n": 150, "fert_date_offset": 15},
    "SG": {"ppop": 12, "plrs": 76, "pldp": 5, "fert_n": 80, "fert_date_offset": 30},
}

logger = logging.getLogger("dssat_workdir_setup")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


# ==========================================================================
# Date Utilities
# ==========================================================================

def _to_yyddd(year: int, doy: int) -> int:
    """Convert (year, day-of-year) to DSSAT YYDDD format.

    DSSAT Y2K convention: YY 0-70 -> 2000-2070, YY 71-99 -> 1971-1999.
    """
    if year >= 2000:
        yy = year - 2000
    elif year >= 1971:
        yy = year - 1900
    else:
        raise ValueError(f"Year {year} out of DSSAT YYDDD range (1971-2070)")
    if yy < 0 or yy > 99:
        raise ValueError(f"Year {year} cannot be represented in 2-digit DSSAT format")
    return yy * 1000 + doy


def _date_to_yyddd(dt) -> int:
    """Convert a date-like object, 'YYYY-MM-DD' string, or YYDDD int/string to YYDDD."""
    if isinstance(dt, (int, float)):
        return int(dt)  # Already YYDDD format
    if isinstance(dt, str):
        dt = dt.strip()
        if dt.isdigit() and len(dt) <= 5:
            return int(dt)  # Already YYDDD as string like "80150"
        dt = datetime.strptime(dt, "%Y-%m-%d")
    doy = dt.timetuple().tm_yday
    return _to_yyddd(dt.year, doy)


def _yyddd_to_date(yyddd: int) -> Optional[datetime]:
    """Convert DSSAT YYDDD (5-digit) or YYYYDDD (7-digit) integer to datetime.
    Summary.OUT in DSSAT >=4.7 uses YYYYDDD; FileX still uses YYDDD.
    Returns None if invalid."""
    if yyddd is None or yyddd == -99 or yyddd <= 0:
        return None
    yy_or_year = yyddd // 1000
    ddd = yyddd % 1000
    if ddd < 1 or ddd > 366:
        return None
    if yy_or_year >= 1900:
        year = yy_or_year
    else:
        year = 2000 + yy_or_year if yy_or_year <= 70 else 1900 + yy_or_year
    try:
        return datetime(year, 1, 1) + timedelta(days=ddd - 1)
    except (ValueError, OverflowError):
        return None


# ==========================================================================
# DSSATPRO Rewriting (Pitfall #5)
# ==========================================================================

def _generate_dssatpro(workdir: str) -> str:
    """Generate DSSATPRO.v48 content with all paths pointing to workdir.

    This is CRITICAL — DSSAT reads this file to find StandardData, genotype
    files, soil files, and weather files. If paths are wrong, you get
    'File not found' errors or silent defaults.
    """
    wd = workdir

    lines = []
    lines.append("*** *  DSSAT PROFILE * ***")

    # Directory codes: all point to workdir
    dir_codes = [
        "DDB", "DTB", "DTE", "DTO", "DAT", "DPT", "DIM",
        "DTP", "DPF", "DFO", "DIS", "DDW", "DWG", "DWC",
        "DDS", "DTS", "DDG",
    ]
    for code in dir_codes:
        lines.append(f"{code} // {wd}")

    lines.append(f"DCG // {wd}/TOOLS/GENCALC GENCALC2.EXE")
    lines.append(f"DGL // {wd}/TOOLS/GLUE GLUE.BAT")
    lines.append(f"DPM // {wd}")
    lines.append(f"DDE // {wd}")
    lines.append(f"TOG // {wd}/TOOLS/GBUILD GBUILD.EXE")
    lines.append("")

    # Model executable references — map crop code to model
    model_map = [
        ("MAL", "PRFRM048"), ("MBA", "CSCER048"), ("MBH", "PRFRM048"),
        ("MBM", "PRFRM048"), ("MBN", "CRGRO048"), ("MBR", "PRFRM048"),
        ("MBS", "BSCER048"), ("MCB", "CRGRO048"), ("MCH", "CRGRO048"),
        ("MCN", "CRGRO048"), ("MCO", "CRGRO048"), ("MCP", "CRGRO048"),
        ("MCS", "CSYCA048"), ("MFA", "CRGRO048"), ("MFB", "CRGRO048"),
        ("MGB", "CRGRO048"), ("MGG", "PRFRM048"), ("MLT", "CRGRO048"),
        ("MML", "MLCER048"), ("MMZ", "MZCER048"), ("MNP", "CRGRO048"),
        ("MPI", "PIALO048"), ("MPN", "CRGRO048"), ("MPP", "CRGRO048"),
        ("MPR", "CRGRO048"), ("MPT", "PTSUB048"), ("MRI", "RICER048"),
        ("MSB", "CRGRO048"), ("MSC", "SCCAN048"), ("MSF", "CRGRO048"),
        ("MSG", "SGCER048"), ("MSI", None), ("MSU", "CRGRO048"),
        ("MSW", "SWCER048"), ("MTF", "TFAPS048"), ("MTM", "CRGRO048"),
        ("MTN", "TNARO048"), ("MTR", "TRARO048"), ("MVB", "CRGRO048"),
        ("MWH", "CSCER048"), ("MOT", None), ("MU1", None), ("MU2", None),
        ("MIO", None), ("MLO", None),
    ]
    for code, model in model_map:
        if model:
            lines.append(f"{code} // {wd} dscsm048 {model}")
        else:
            lines.append(f"{code} // {wd}")

    lines.append("")
    lines.append(f"MGR // {wd}")
    lines.append(f"NSH // {wd}")
    lines.append(f"ASP // {wd}")
    lines.append(f"ASS // {wd} dscsm048")
    lines.append(f"ASA // {wd} VARAN2.EXE")
    lines.append(f"AGR // {wd}")
    lines.append(f"AQS // {wd} dscsm048")
    lines.append(f"AQA // {wd} SUSTAIN2.EXE")
    lines.append(f"ASX // {wd}")
    lines.append(f"APS // {wd} dscsm048")
    lines.append(f"APV // {wd}")
    lines.append(f"APM // {wd}")
    lines.append(f"APA // {wd} VARAN2.EXE")
    lines.append(f"APJ // {wd}")
    lines.append(f"APF // {wd}")
    lines.append(f"APP // {wd}")
    lines.append(f"APK // {wd} DISC9801.EXE")
    lines.append("TOE // /usr/bin/nano")
    lines.append("TOS // ")
    lines.append("TOM // ")

    # Critical data directories
    lines.append(f"STD // {wd}/StandardData")
    lines.append(f"WED // {wd}/Weather")
    lines.append(f"WGD // {wd}/Weather/GEN")
    lines.append(f"WMD // {wd}/Weather/MONTH")
    lines.append(f"CLD // {wd}/Weather/CLIMATE")
    lines.append(f"SLD // {wd}/Soil")
    lines.append(f"CRD // {wd}/Genotype")

    # Crop-specific directories
    crop_dirs = [
        ("FID", "BACKGROUND"), ("ALD", "ALFALFA"), ("GCD", "GCWork"),
        ("GUD", "GLWork"), ("BAD", "BARLEY"), ("BHD", "BAHIA"),
        ("BMD", "Bermudagrass"), ("BND", "DRYBEAN"), ("BRD", "BRACHIARIA"),
        ("BSD", "SUGARBEET"), ("CBD", "CABBAGE"), ("CHD", "CHICKPEA"),
        ("CND", "CANOLA"), ("COD", "cotton"), ("CPD", "COWPEA"),
        ("CSD", "CASSAVA"), ("FAD", "FALLOW"), ("FBD", "FABABEAN"),
        ("GBD", "GREENBEAN"), ("GGD", "GUINEAGRASS"), ("LTD", "Lentil"),
        ("MLD", "PearlMillet"), ("MZD", "Maize"), ("NPD", "Napier"),
        ("PED", "PEA"), ("PID", "PINEAPPLE"), ("PND", "Peanut"),
        ("POD", "PERENNIALPEANUT"), ("PPD", "PIGEONPEA"),
        ("PRD", "BellPepper"), ("PTD", "POTATO"), ("RID", "Rice"),
        ("SBD", "Soybean"), ("SCD", "SUGARCANE"), ("SFD", "SAFFLOWER"),
        ("SGD", "Sorghum"), ("SID", wd), ("SUD", "SUNFLOWER"),
        ("SWD", "SweetCorn"), ("TFD", "Teff"), ("TMD", "TOMATO"),
        ("TND", "Tanier"), ("TRD", "TARO"), ("VBD", "VELVETBEAN"),
        ("WHD", "Wheat"), ("U1D", "CROP1"), ("U2D", "CROP2"),
    ]
    for code, dirname in crop_dirs:
        if dirname == wd:
            lines.append(f"{code} // {wd}")
        else:
            lines.append(f"{code} // {wd}/{dirname}")

    lines.append("OTD // ")
    lines.append(f"ASD // {wd}/Seasonal")
    lines.append(f"AQD // {wd}/Sequence")
    lines.append(f"APD // {wd}/Spatial")
    lines.append(f"PSD // {wd}/Pest")
    lines.append(f"ECD // {wd}/ECONOMIC")
    lines.append("TOD // ")
    lines.append("")

    # Additional newer model entries
    extra_models = [
        ("MQU", "CRGRO048", "Quinoa", "QUD"),
        ("MSR", "CRGRO048", "Strawberry", "SRD"),
        ("MCI", "CRGRO048", "Chia", "CID"),
        ("MPE", "CRGRO048", None, None),
        ("MPO", "PRFRM048", None, None),
        ("MSS", "CRGRO048", "Sesame", "SSD"),
        ("MBC", "CRGRO048", "Carinata", "BCD"),
        ("MGY", "CRGRO048", "Guar", "GYD"),
        ("MBG", "CRGRO048", "BambaraGroundnut", "BGD"),
        ("MAM", "CRGRO048", "Amaranth", "AMD"),
        ("MHM", "CRGRO048", "Hemp", "HMD"),
        ("MRY", "CSCER048", "Rye", "RYD"),
    ]
    for mcode, model, dirname, dcode in extra_models:
        lines.append(f"{mcode} // {wd} dscsm048 {model}")
        if dcode and dirname:
            lines.append(f"{dcode} // {wd}/{dirname}")

    lines.append(f"ACC // {wd} dscsm048")
    lines.append(f"CCD // {wd}/ClimateChange")
    lines.append(f"AYF // {wd} dscsm048")
    lines.append(f"YFD // {wd}/YieldForecast")
    lines.append("")

    # Working Linux DSSAT uses single-space separator (not "//")
    return ("\n".join(lines) + "\n").replace(" // ", " ")


# ==========================================================================
# FileX Generation (Pitfall #3: WSTA code alignment, #4: CUL column align)
# ==========================================================================

def _generate_filex(
    crop: str,
    cultivar: str,
    cul_name: str,
    wsta: str,
    soil_id: str,
    lat: float,
    lon: float,
    planting_yyddd: int,
    sdate_yyddd: int,
    start_year: int,
    end_year: int,
    experiment_name: str,
    filex_basename: str,
    management: dict,
) -> str:
    """Generate a complete DSSAT FileX string.

    Fixed-width Fortran format — columns must be exact.
    """
    crop_info = CROP_REGISTRY[crop]
    is_legume = crop_info[3]
    nyers = end_year - start_year + 1
    symbi = "Y" if is_legume else "N"

    # Management defaults
    ppop = management.get("ppop", 7.2)
    plrs = management.get("plrs", 76)
    pldp = management.get("pldp", 5)
    fert_n = management.get("fert_n", 120)
    fert_date_offset = management.get("fert_date_offset", 30)

    # ------------------------------------------------------------------
    # Irrigation mode (added so a gridded ensemble can express an IRRIGATED
    # and a RAINFED member of the SAME crop).
    #
    #   'none'   -> IRRIG=N, MI=0, no irrigation level rows   (dryland member)
    #   'auto'   -> IRRIG=A, MI=0, AUTOMATIC MANAGEMENT drives it
    #   'events' -> IRRIG=R, MI=1, explicit @I IDATE IROP IRVAL rows
    #
    # Resolution order: an explicit management['irrigation'] wins; otherwise a
    # non-empty management['irrigation_events'] implies 'events'; otherwise the
    # historical default (rice = auto/flooded paddy, everything else rainfed).
    # Callers that pass neither key get byte-identical output to before.
    # ------------------------------------------------------------------
    irrigation_events = management.get("irrigation_events") or []
    irr_mode = management.get("irrigation")
    if irr_mode is None:
        if irrigation_events:
            irr_mode = "events"
        else:
            irr_mode = "auto" if crop == "RI" else "none"
    irr_mode = str(irr_mode).lower()
    if irr_mode not in ("none", "auto", "events"):
        raise ValueError(
            f"management['irrigation'] must be one of 'none', 'auto', 'events'; "
            f"got {irr_mode!r}"
        )
    if irr_mode == "events" and not irrigation_events:
        raise ValueError(
            "management['irrigation']='events' requires a non-empty "
            "management['irrigation_events'] list of (yyddd, mm) tuples."
        )

    irrig_flag = {"none": "N", "auto": "A", "events": "R"}[irr_mode]
    mi_val = 1 if irr_mode == "events" else 0

    def _event_rows(events):
        """Normalise irrigation_events into (yyddd:int, irop:str, irval:float)."""
        rows = []
        for ev in events:
            irop = "IR001"
            if isinstance(ev, dict):
                when = ev.get("yyddd", ev.get("date"))
                amt = ev.get("mm", ev.get("irval"))
                irop = ev.get("irop", irop)
            else:
                seq = list(ev)
                when, amt = seq[0], seq[1]
                if len(seq) >= 3:
                    irop = seq[2]
            if isinstance(when, str):
                when = _date_to_yyddd(when)
            rows.append((int(when), str(irop)[:5], float(amt)))
        return rows

    # Compute fertilizer date (planting + offset)
    pdate_dt = _yyddd_to_date(planting_yyddd)
    if pdate_dt and fert_date_offset > 0:
        fert_dt = pdate_dt + timedelta(days=fert_date_offset)
        fert_yyddd = _date_to_yyddd(fert_dt)
    else:
        fert_yyddd = planting_yyddd

    # Harvest last day (auto-management)
    hlast_yyddd = _to_yyddd(start_year, 365)

    # Planting window for automatic management
    pfirst_yyddd = planting_yyddd - 10 if planting_yyddd % 1000 > 10 else planting_yyddd
    plast_yyddd = planting_yyddd + 30

    lines = []

    # Header
    lines.append(f"*EXP.DETAILS: {experiment_name} {crop_info[2].upper()} SIMULATION")
    lines.append("")

    # General
    lines.append("*GENERAL")
    lines.append("@PEOPLE")
    lines.append(" HydroCraft Automated Agent")
    lines.append("@ADDRESS")
    lines.append(f" HydroCraft Platform, {lat:.3f}N {abs(lon):.3f}{'W' if lon < 0 else 'E'}")
    lines.append("@SITE")
    lines.append(f" Auto-generated at {lat:.4f}, {lon:.4f}")
    lines.append("")

    # Treatments
    lines.append("*TREATMENTS                        -------------FACTOR LEVELS------------")
    lines.append("@N R O C TNAME.................... CU FL SA IC MP MI MF MR MC MT ME MH SM")
    # Determine if we have fertilizer and irrigation
    has_fert = fert_n > 0
    mf_val = 1 if has_fert else 0
    tname = f"DEFAULT {crop_info[2].upper()[:18]}"
    lines.append(f" 1 1 0 0 {tname:<25s}  1  1  0  1  1{mi_val:>3d}{mf_val:>3d}  0  0  0  0  0  1")
    lines.append("")

    # Cultivars (Pitfall #4: fixed-width alignment)
    lines.append("*CULTIVARS")
    lines.append("@C CR INGENO CNAME")
    # INGENO is 6 chars, CNAME up to 16
    lines.append(f" 1 {crop} {cultivar:<6s} {cul_name}")
    lines.append("")

    # Fields (Pitfall #3: WSTA 4-char code must match .WTH filename prefix)
    lines.append("*FIELDS")
    lines.append("@L ID_FIELD WSTA....  FLSA  FLOB  FLDT  FLDD  FLDS  FLST SLTX  SLDP  ID_SOIL    FLNAME")
    field_id = f"{wsta}0001"
    lines.append(f" 1 {field_id:<8s} {wsta:<4s}       -99     0 DR000     0     0 00000 -99    210  {soil_id:<10s} -99")
    lines.append("@L ...........XCRD ...........YCRD .....ELEV .............AREA .SLEN .FLWR .SLAS FLHST FHDUR")
    # Fixed-width Fortran format: L(2)+XCRD(16)+YCRD(16)+ELEV(10)+AREA(18)+SLEN(6)+FLWR(6)+SLAS(6)+FLHST(6)+FHDUR(6) = 92 chars
    lines.append(f"{1:>2d}{lat:>16.4f}{lon:>16.4f}{-99:>10d}{0:>18d}{0:>6d}{0:>6d}{0:>6d}{-99:>6d}{-99:>6d}")
    lines.append("")

    # Initial conditions
    lines.append("*INITIAL CONDITIONS")
    lines.append("@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME")
    lines.append(f" 1    {crop} {sdate_yyddd:>5d}   100     0     1     1   -99  1000    .8     0   100    15 -99")
    lines.append("@C  ICBL  SH2O  SNH4  SNO3")
    # Rice (paddy) needs near-field-capacity initial water for germination.
    # IRRI920001 soil: SLLL=0.21, SDUL=0.48, SSAT=0.52 — start at DUL.
    # Other crops: typical dry-season initial water (0.20).
    sh2o_init = 0.45 if crop == "RI" else 0.200
    ic_layers = [
        (5,   sh2o_init, 0.5, 1.0),
        (15,  sh2o_init, 0.5, 1.0),
        (30,  sh2o_init, 0.5, 1.0),
        (60,  sh2o_init, 0.5, 0.5),
        (90,  sh2o_init, 0.5, 0.5),
        (120, sh2o_init, 0.5, 0.5),
        (150, sh2o_init, 0.5, 0.5),
        (180, sh2o_init, 0.5, 0.5),
        (210, sh2o_init, 0.5, 0.5),
    ]
    for depth, sh2o, snh4, sno3 in ic_layers:
        lines.append(f" 1   {depth:>3d} {sh2o:>5.3f}  {snh4:>4.1f}  {sno3:>4.1f}")
    lines.append("")

    # Planting details
    lines.append("*PLANTING DETAILS")
    lines.append("@P PDATE EDATE  PPOP  PPOE  PLME  PLDS  PLRS  PLRD  PLDP  PLWT  PAGE  PENV  PLPH  SPRL                        PLNAME")
    # Format PPOP: use integer if >=100 (wheat=350), decimal if <100 (maize=7.2)
    ppop_str = f"{ppop:>5.0f}" if ppop >= 100 else f"{ppop:>5.1f}"
    lines.append(f" 1 {planting_yyddd:>5d}   -99 {ppop_str} {ppop_str}     S     R   {plrs:>3d}     0   {pldp:>3d}   -99   -99   -99   -99     0                        -99")
    lines.append("")

    # Irrigation — default rainfed for non-rice; flooded auto-irrigation for
    # rice (paddy). management['irrigation_events'] (documented in
    # create_workdir's docstring but previously discarded) is now emitted as
    # @I IDATE IROP IRVAL rows and selected by treatment factor MI=1.
    lines.append("*IRRIGATION AND WATER MANAGEMENT")
    lines.append("@I  EFIR  IDEP  ITHR  IEPT  IOFF  IAME  IAMT IRNAME")
    lines.append(" 1     1   -99   -99   -99   -99   -99   -99 -99")
    lines.append("@I IDATE  IROP IRVAL")
    for _yyddd, _irop, _irval in _event_rows(irrigation_events):
        lines.append(f" 1 {_yyddd:>5d} {_irop:<5s}{_irval:>6.0f}")
    lines.append("")

    # Fertilizer
    if has_fert:
        lines.append("*FERTILIZERS (INORGANIC)")
        lines.append("@F FDATE  FMCD  FACD  FDEP  FAMN  FAMP  FAMK  FAMC  FAMO  FOCD FERNAME")
        # Split fertilizer: 40% at planting, 60% at offset.
        # Both halves MUST be int: fert_n commonly arrives as a float from
        # ki_tools_common.fertilizer (NPKGRIDS returns e.g. 193.1), and the
        # ':>3d' formats below raise "Unknown format code 'd' for object of
        # type 'float'" on a float. Round rather than truncate so the split
        # still sums to round(fert_n).
        n_at_plant = int(round(fert_n * 0.4))
        n_at_side = int(round(fert_n)) - n_at_plant
        lines.append(f" 1 {planting_yyddd:>5d} FE005 AP002    10   {n_at_plant:>3d}     0     0     0     0   -99 Planting urea")
        if n_at_side > 0 and fert_date_offset > 0:
            lines.append(f" 1 {fert_yyddd:>5d} FE005 AP002    10   {n_at_side:>3d}     0     0     0     0   -99 Sidedress urea")
        lines.append("")

    # Simulation controls
    sname = f"{experiment_name[:30]}"
    lines.append("*SIMULATION CONTROLS")
    lines.append("@N GENERAL     NYERS NREPS START SDATE RSEED SNAME.................... SMODEL")
    lines.append(f" 1 GE           {nyers:>4d}     1     S {sdate_yyddd:>5d}  2150 {sname}")
    lines.append("@N OPTIONS     WATER NITRO SYMBI PHOSP POTAS DISES  CHEM  TILL   CO2")
    lines.append(f" 1 OP              Y     Y     {symbi}     N     N     N     N     Y     M")
    lines.append("@N METHODS     WTHER INCON LIGHT EVAPO INFIL PHOTO HYDRO NSWIT MESOM MESEV MESOL")
    # CROPGRO-based crops (soybean, peanut, dry bean, cotton, etc.) require
    # PHOTO=L (leaf-level photosynthesis). CERES-based crops use PHOTO=R
    # (radiation-use efficiency). Using PHOTO=R for CROPGRO causes near-zero
    # biomass accumulation and crop death.
    photo_method = "L" if crop_info[1] == "CRGRO048" else "R"
    lines.append(f" 1 ME              M     M     E     R     S     {photo_method}     R     1     G     R     2")
    # IRRIG comes from the irrigation mode resolved at the top of this function:
    # 'none'->N (rainfed), 'auto'->A (automatic, the rice/paddy default),
    # 'events'->R (the explicit @I IDATE rows above).
    lines.append("@N MANAGEMENT  PLANT IRRIG FERTI RESID HARVS")
    lines.append(f" 1 MA              R     {irrig_flag}     R     N     M")
    lines.append("@N OUTPUTS     FNAME OVVEW SUMRY FROPT GROUT CAOUT WAOUT NIOUT MIOUT DIOUT VBOSE CHOUT OPOUT FMOPT")
    lines.append(" 1 OU              N     Y     Y     1     Y     N     Y     Y     N     N     Y     N     Y     A")
    lines.append("")

    # Automatic management
    lines.append("@  AUTOMATIC MANAGEMENT")
    lines.append("@N PLANTING    PFRST PLAST PH2OL PH2OU PH2OD PSTMX PSTMN")
    lines.append(f" 1 PL          {pfirst_yyddd:>5d} {plast_yyddd:>5d}    10   100    30    40    10")
    lines.append("@N IRRIGATION  IMDEP ITHRL ITHRU IROFF IMETH IRAMT IREFF")
    # Rice: high threshold (80%) simulates flooded paddy — irrigate whenever soil
    # drops below 80% with 50mm top-up. Non-rice: standard 50% threshold.
    # Each field is overridable so an irrigated ensemble member can carry a
    # site-specific automatic-irrigation rule; the widths below reproduce the
    # historical line byte-for-byte when nothing is overridden.
    irr_thr = str(management.get("irr_ithrl", "80" if crop == "RI" else "50"))
    irr_amt = str(management.get("irr_amt", "50" if crop == "RI" else "10"))
    irr_imdep = str(management.get("irr_imdep", "30"))
    irr_ithru = str(management.get("irr_ithru", "100"))
    irr_iroff = str(management.get("irr_iroff", "GS000"))
    irr_imeth = str(management.get("irr_imeth", "IR001"))
    irr_eff = str(management.get("irr_eff", "1"))
    lines.append(
        " 1 IR"
        f"{irr_imdep:>15s}{irr_thr:>5s}{irr_ithru:>6s}"
        f"{irr_iroff:>6s}{irr_imeth:>6s}{irr_amt:>5s}{irr_eff:>6s}"
    )
    lines.append("@N NITROGEN    NMDEP NMTHR NAMNT NCODE NAOFF")
    lines.append(" 1 NI             30    50    25 FE001 GS000")
    lines.append("@N RESIDUES    RIPCN RTIME RIDEP")
    lines.append(" 1 RE            100     1    20")
    lines.append("@N HARVEST     HFRST HLAST HPCNP HPCNR")
    lines.append(f" 1 HA              0 {hlast_yyddd:>5d}   100     0")
    lines.append("")
    lines.append("")

    return "\n".join(lines)


# ==========================================================================
# Batch File Generation
# ==========================================================================

# Width of the DSSBatch.v48 @FILEX path field, in columns.
#
# PRIMARY SOURCE — dssat-csm-os v4.8 as built at KISSPATH_HOME/DSSAT, NOT KI
# folklore. The batch record is parsed in CSM_Main/CSM.for:
#
#   268:  END_POS = LEN(TRIM(CHARTEST(1:92)))+1
#   269:  FILEX  = CHARTEST((END_POS-12):(END_POS-1))
#   270:  PATHEX = CHARTEST(1:END_POS-13)
#   271:  READ(CHARTEST(93:113),110,IOSTAT=ERRNUM) TRTNUM,TRTREP,ROTNUM
#   110   FORMAT(3(1X,I6))
#
# so the path field is columns 1-92 and TRTNO/TRTREP/ROTNUM are read from
# columns 93-113 (TRTNO in 94-99). A 93rd path character is not truncated —
# it lands *inside* the treatment number and yields Error 26, or silently
# runs a different treatment. InputModule/ipexp.for:97 declares the buffer
# that receives it as CHARACTER*92 FILEX_P. The shipped deck agrees:
# Data/BatchFiles/Maize.v48 data records are 127 chars with the path field
# blank-padded to 92 and TRTNO ending at column 99 (verified by reading it).
#
# SHARED-SPEC RECONCILIATION (shared_specs/dssat/base/format_spec.yaml):
# the spec carries two FILEX width rules that disagree —
# `field_widths.FILEX.record_length: 92` and `path_constraints.FILEX.max_chars: 95`.
# 92 is the value the model source supports AND the tighter of the two, so a
# field written to 92 satisfies both rules simultaneously. A tier-2 correction
# of max_chars 95 -> 92 is proposed separately; this tool is NOT bent to match
# the incorrect 95.
FILEX_FIELD_WIDTH = 92


def _generate_batch(filex_ref: str, crop_name: str, n_treatments: int = 1) -> str:
    """Generate DSSBatch.v48 content.

    ``filex_ref`` is the FileX exactly as DSSAT will read it: RELATIVE to the
    workdir (a bare basename), never a host absolute path. This is required by
    shared_specs/dssat/base/format_spec.yaml
    ``path_constraints.FILEX.must_be_relative_to_workdir`` and
    ``tool_conventions.batch_file_writers.must_use_relative_paths``, and it is
    what run_dssat() already assumes — it launches ``./dscsm048`` with
    cwd=workdir.

    Writing the basename makes PATHEX (CSM.for:270) empty, so DSSAT resolves
    the FileX against the cwd. Writing an absolute path instead burns the
    92-column budget on a directory prefix that is redundant, caps the usable
    workdir depth, and additionally risks the CHARACTER*80 PATHEX buffer
    (CSM.for:96, ipexp.for:96).

    See FILEX_FIELD_WIDTH above for the primary-source derivation of 92.
    """
    if os.path.isabs(filex_ref):
        raise ValueError(
            f"FileX reference for DSSBatch.v48 must be RELATIVE to the workdir "
            f"(format_spec path_constraints.FILEX.must_be_relative_to_workdir), "
            f"got absolute path '{filex_ref}'. Pass the basename; DSSAT runs "
            f"with cwd=workdir."
        )
    if filex_ref != filex_ref.strip() or not filex_ref:
        raise ValueError(f"FileX reference is blank or padded: {filex_ref!r}")
    if filex_ref.startswith(os.pardir + os.sep) or os.pardir + os.sep in filex_ref:
        raise ValueError(
            f"FileX reference '{filex_ref}' escapes the workdir; DSSAT resolves "
            f"it against cwd=workdir and would not find it."
        )
    if len(filex_ref) > FILEX_FIELD_WIDTH:
        raise ValueError(
            f"FileX reference length ({len(filex_ref)}) exceeds the "
            f"{FILEX_FIELD_WIDTH}-column DSSBatch FILEX field (CSM.for:268): "
            f"'{filex_ref}'. Columns 93+ are TRTNO/TRTREP/ROTNUM."
        )

    lines = []
    lines.append(f"$BATCH({crop_name.upper()})")
    lines.append("!")

    header_pad = FILEX_FIELD_WIDTH - len("@FILEX")
    lines.append(f"@FILEX{' ' * header_pad} TRTNO     RP     SQ     OP     CO")

    for trt in range(1, n_treatments + 1):
        data_line = f"{filex_ref:<{FILEX_FIELD_WIDTH}s}{trt:>6d}{1:>6d}{0:>6d}{0:>6d}{0:>6d}"
        lines.append(data_line)

    lines.append("")
    return "\n".join(lines)


def _verify_batch_filex_contract(batch_path: str, workdir: str,
                                 filex_path: str) -> str:
    """Re-read the DSSBatch.v48 actually written and check what DSSAT will parse.

    This validates the STRING DSSAT RECEIVES, not the host path we intended to
    write — the two diverge whenever padding, a stale file or a symlink gets in
    the way, and only the former is what fails at runtime.

    Replays CSM_Main/CSM.for:268-271 on the bytes on disk:
      * path field = columns 1-92, must be non-blank, relative, and <= 92 cols;
      * FILEX = the last 12 non-blank chars, PATHEX = everything before them;
      * TRTNO/TRTREP/ROTNUM must parse as 3(1X,I6) out of columns 93-113;
      * the field must resolve, under the workdir, to the FileX we wrote.

    Returns the FILEX field as recorded. Raises ValueError on any violation.
    """
    with open(batch_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    hdr_idx = next((i for i, ln in enumerate(lines)
                    if ln.startswith("@FILEX")), None)
    if hdr_idx is None:
        raise ValueError(f"{batch_path}: no @FILEX header record")
    hdr = lines[hdr_idx]
    if hdr[:FILEX_FIELD_WIDTH].strip() != "@FILEX":
        raise ValueError(
            f"{batch_path}: @FILEX header field is not {FILEX_FIELD_WIDTH} "
            f"columns wide — TRTNO would not start at column 93"
        )
    if hdr[FILEX_FIELD_WIDTH:FILEX_FIELD_WIDTH + 6].strip() != "TRTNO":
        raise ValueError(
            f"{batch_path}: TRTNO is not in columns {FILEX_FIELD_WIDTH + 1}-"
            f"{FILEX_FIELD_WIDTH + 6} (found "
            f"{hdr[FILEX_FIELD_WIDTH:FILEX_FIELD_WIDTH + 6]!r})"
        )

    recorded = None
    n_data = 0
    for i in range(hdr_idx + 1, len(lines)):
        ln = lines[i]
        if not ln.strip():
            continue
        field = ln[:FILEX_FIELD_WIDTH].strip()
        if not field:
            raise ValueError(f"{batch_path}: record {i + 1} has a blank FILEX field")
        if os.path.isabs(field):
            raise ValueError(
                f"{batch_path}: record {i + 1} FILEX field {field!r} is ABSOLUTE — "
                f"format_spec path_constraints.FILEX.must_be_relative_to_workdir"
            )
        if len(field) > FILEX_FIELD_WIDTH:
            raise ValueError(
                f"{batch_path}: record {i + 1} FILEX field is {len(field)} chars "
                f"> {FILEX_FIELD_WIDTH} (CSM.for:268)"
            )
        # CSM.for:269-270 — DSSAT takes only the LAST 12 chars as the file name.
        end_pos = len(ln[:FILEX_FIELD_WIDTH].rstrip()) + 1
        dssat_filex = ln[max(0, end_pos - 13):end_pos - 1]
        dssat_pathex = ln[:max(0, end_pos - 13)]
        if dssat_pathex.strip():
            raise ValueError(
                f"{batch_path}: record {i + 1} leaves PATHEX={dssat_pathex.strip()!r}; "
                f"a workdir-relative basename must leave it empty"
            )
        # CSM.for:271 — READ(CHARTEST(93:113),110) TRTNUM,TRTREP,ROTNUM with
        # 110 FORMAT(3(1X,I6)). Each 1X skips one column, so the three I6
        # windows DSSAT actually reads are columns 94-99, 101-106 and 108-113.
        # Slice exactly those, so this checks what the Fortran reader sees
        # rather than re-implementing our own writer's column arithmetic.
        # (This generator lays the five fields out 6 columns wide rather than
        # the shipped deck's 7; the values still land inside DSSAT's windows,
        # and Fortran's default BLANK='NULL' ignores the padding. Parsing them
        # at DSSAT's own offsets is what proves that.)
        windows = [(93, 99), (100, 106), (107, 113)]
        try:
            trt, rep, rot = (int(ln[s:e]) for s, e in windows)
        except (ValueError, IndexError):
            raise ValueError(
                f"{batch_path}: record {i + 1} TRTNO/TRTREP/ROTNUM not parseable "
                f"as 3(1X,I6) from columns {FILEX_FIELD_WIDTH + 1}-"
                f"{FILEX_FIELD_WIDTH + 21} "
                f"({ln[FILEX_FIELD_WIDTH:FILEX_FIELD_WIDTH + 21]!r}) — the FILEX "
                f"field has overflowed into the treatment columns"
            )
        if trt < 1:
            raise ValueError(f"{batch_path}: record {i + 1} TRTNO {trt} < 1")
        resolved = os.path.realpath(os.path.join(workdir, dssat_filex.strip()))
        if resolved != os.path.realpath(filex_path):
            raise ValueError(
                f"{batch_path}: FILEX {dssat_filex.strip()!r} resolves under the "
                f"workdir to {resolved}, not the FileX written at {filex_path}"
            )
        if recorded is not None and field != recorded:
            raise ValueError(f"{batch_path}: FILEX field differs between records")
        recorded = field
        n_data += 1

    if n_data == 0:
        raise ValueError(f"{batch_path}: no data records under @FILEX")
    return recorded


# ==========================================================================
# create_workdir — Main Setup Function
# ==========================================================================

def create_workdir(
    crop: str,
    cultivar: Optional[str] = None,
    weather_file: Optional[str] = None,
    soil_id: str = "IB00000001",
    soil_file: Optional[str] = None,
    lat: float = 0.0,
    lon: float = 0.0,
    planting_date: Union[str, int, None] = None,
    start_year: int = 2005,
    end_year: int = 2005,
    output_dir: Optional[str] = None,
    **management_kwargs,
) -> str:
    """Create a complete DSSAT working directory with all required files.

    Parameters
    ----------
    crop : str
        2-character DSSAT crop code (MZ, WH, SB, RI, SG, etc.).
    cultivar : str, optional
        6-character cultivar code (e.g., 'IB0035'). If None, uses default.
    weather_file : str, optional
        Path to an existing .WTH file. Will be symlinked into the workdir.
        If None, a minimal weather file must be created separately.
    soil_id : str
        10-character soil profile ID (must exist in .SOL file). Default is
        the DSSAT generic deep silty clay 'IB00000001'.
    soil_file : str, optional
        Path to a custom .SOL file. If None, uses DSSAT default SOIL.SOL.
    lat : float
        Latitude in decimal degrees (positive N, negative S).
    lon : float
        Longitude in decimal degrees (positive E, negative W).
    planting_date : str or int, optional
        Planting date as 'YYYY-MM-DD' string or YYDDD integer.
        If None, defaults to DOY 120 (late April) of start_year.
    start_year : int
        Simulation start year (YYYY).
    end_year : int
        Simulation end year (YYYY). Set equal to start_year for single year.
    output_dir : str, optional
        If provided, creates the workdir at this path. Otherwise uses /tmp.
    **management_kwargs
        Override default management: ppop, plrs, pldp, fert_n,
        fert_date_offset, irrigation_events (list of (yyddd, mm) tuples).

        irrigation : {'none', 'auto', 'events'}, optional
            Explicit irrigation regime, so an ensemble can express a RAINFED
            and an IRRIGATED member of the same crop:
              'none'   -> IRRIG=N, no irrigation (dryland)
              'auto'   -> IRRIG=A, DSSAT automatic irrigation, tuned by
                          irr_imdep / irr_ithrl / irr_ithru / irr_iroff /
                          irr_imeth / irr_amt / irr_eff
              'events' -> IRRIG=R, the explicit irrigation_events rows
            If omitted, a non-empty irrigation_events implies 'events';
            otherwise the historical default applies (rice = 'auto',
            every other crop = 'none').

    Returns
    -------
    str
        Absolute path to the created working directory.

    Raises
    ------
    ValueError
        If crop code is unknown or inputs are invalid.
    FileNotFoundError
        If required DSSAT files are missing.
    """
    # ------------------------------------------------------------------
    # Validate inputs
    # ------------------------------------------------------------------
    crop = crop.upper()
    if crop not in CROP_REGISTRY:
        raise ValueError(
            f"Unknown crop code '{crop}'. Supported: {list(CROP_REGISTRY.keys())}"
        )

    crop_info = CROP_REGISTRY[crop]
    filex_ext = crop_info[0]
    genotype_prefix = crop_info[1]
    crop_name = crop_info[2]

    if not DSSAT_BINARY.exists():
        raise FileNotFoundError(f"DSSAT binary not found: {DSSAT_BINARY}")
    if not DSSAT_DATA.exists():
        raise FileNotFoundError(f"DSSAT Data directory not found: {DSSAT_DATA}")

    # Resolve cultivar
    if cultivar is None:
        if crop in DEFAULT_CULTIVARS:
            cultivar, cul_name = DEFAULT_CULTIVARS[crop]
        else:
            cultivar, cul_name = "DFAULT", "DEFAULT"
    else:
        cul_name = cultivar  # Use code as name if not in defaults
        # Try to look up the name from the CUL file
        cul_file = DSSAT_GENOTYPE / f"{genotype_prefix}.CUL"
        if cul_file.exists():
            with open(cul_file, "r") as f:
                for line in f:
                    if line.startswith(cultivar):
                        parts = line.split()
                        if len(parts) >= 2:
                            cul_name = " ".join(parts[1:3])[:16]
                        break

    # Resolve planting date
    if planting_date is None:
        planting_yyddd = _to_yyddd(start_year, 120)  # DOY 120 = late April
    elif isinstance(planting_date, str):
        planting_yyddd = _date_to_yyddd(planting_date)
    elif isinstance(planting_date, int):
        planting_yyddd = planting_date
    else:
        raise ValueError(f"planting_date must be str, int, or None, got {type(planting_date)}")

    # Simulation start date = 1 day before planting or DOY 1 of start_year
    sdate_yyddd = _to_yyddd(start_year, 1)

    # ------------------------------------------------------------------
    # Create workdir (Pitfall #1: short path to avoid Fortran truncation)
    # ------------------------------------------------------------------
    if output_dir:
        workdir = os.path.abspath(output_dir)
        os.makedirs(workdir, exist_ok=True)
    else:
        # Use /tmp for short paths: /tmp/dssat_XXXXXXXX/
        workdir = tempfile.mkdtemp(prefix="dssat_", dir="/tmp")

    # NOTE: the workdir's own length does NOT feed the 92-column DSSBatch
    # FILEX field (CSM.for:268). That field is written workdir-RELATIVE (see
    # _generate_batch), so it always holds the 12-char FileX basename no
    # matter how deep the workdir lives, and PATHEX (CSM.for:270) stays empty.
    # DSSATPRO.v48 does record absolute paths, which DSSAT reads into
    # CHARACTER*102 DSSATP / CHARACTER*120 PATHX (CSM.for:97,99), so warn only
    # against that much larger budget.
    if len(workdir) > 102:
        logger.warning(
            "Workdir path is %d chars; DSSATPRO.v48 entries are read into "
            "CHARACTER*102 (CSM.for:97) and may truncate. Consider /tmp.",
            len(workdir)
        )

    logger.info("Creating DSSAT workdir: %s", workdir)

    # ------------------------------------------------------------------
    # Create subdirectories
    # ------------------------------------------------------------------
    subdirs = [
        "Weather", "Soil", "Genotype", "StandardData",
        "Pest", "Maize", "Wheat", "Soybean", "Rice", "Sorghum",
    ]
    for sd in subdirs:
        os.makedirs(os.path.join(workdir, sd), exist_ok=True)

    # ------------------------------------------------------------------
    # Symlink binary (Pitfall #1: keep it in workdir for short cwd)
    # ------------------------------------------------------------------
    bin_link = os.path.join(workdir, "dscsm048")
    if not os.path.exists(bin_link):
        os.symlink(str(DSSAT_BINARY), bin_link)

    # ------------------------------------------------------------------
    # Symlink/copy CDE files (Pitfall #2: DSSAT needs these at runtime)
    # ------------------------------------------------------------------
    for cde in CDE_FILES:
        src = DSSAT_DATA / cde
        dst = os.path.join(workdir, cde)
        if src.exists() and not os.path.exists(dst):
            os.symlink(str(src), dst)

    # SDA files
    for sda in SDA_FILES:
        src = DSSAT_DATA / "StandardData" / sda
        if not src.exists():
            src = DSSAT_DATA / sda  # Some are at Data/ level
        dst_main = os.path.join(workdir, sda)
        dst_std = os.path.join(workdir, "StandardData", sda)
        if src.exists():
            if not os.path.exists(dst_main):
                os.symlink(str(src), dst_main)
            if not os.path.exists(dst_std):
                os.symlink(str(src), dst_std)

    # MODEL.ERR
    model_err_src = DSSAT_DATA / MODEL_ERR
    model_err_dst = os.path.join(workdir, MODEL_ERR)
    if model_err_src.exists() and not os.path.exists(model_err_dst):
        os.symlink(str(model_err_src), model_err_dst)

    # DSCSM048.CTR
    ctr_src = DSSAT_DATA / CTR_FILE
    ctr_dst = os.path.join(workdir, CTR_FILE)
    if ctr_src.exists() and not os.path.exists(ctr_dst):
        os.symlink(str(ctr_src), ctr_dst)

    # StandardData directory symlink (if files are inside it)
    if DSSAT_STANDARD_DATA.exists():
        for item in DSSAT_STANDARD_DATA.iterdir():
            dst = os.path.join(workdir, "StandardData", item.name)
            if not os.path.exists(dst):
                os.symlink(str(item), dst)

    # ------------------------------------------------------------------
    # Genotype files (Pitfall #4: must be accessible and correct model)
    # ------------------------------------------------------------------
    # Symlink ALL genotype files (not just this crop's) to be safe
    if DSSAT_GENOTYPE.exists():
        for gf in DSSAT_GENOTYPE.iterdir():
            if gf.suffix in (".CUL", ".ECO", ".SPE"):
                dst_main = os.path.join(workdir, gf.name)
                dst_geno = os.path.join(workdir, "Genotype", gf.name)
                if not os.path.exists(dst_main):
                    os.symlink(str(gf), dst_main)
                if not os.path.exists(dst_geno):
                    os.symlink(str(gf), dst_geno)

    # Merge China cultivar library (fixes Known Issue "China CUL not auto-loaded").
    # The CN#### cultivar definitions live in Genotype/China/<MODEL>_China.CUL and
    # are NOT reachable by the top-level symlink loop above (DSSAT reads ONE .CUL
    # per crop). For each *_China.CUL, replace the workdir's symlinked base CUL
    # with a REAL copy and append the CN#### data rows so codes like CN0001 resolve.
    # CN entries reference ecotype IB0001 which exists in the base .ECO, so the
    # merge is collision-free (CN#### vs IB#### codes never overlap).
    china_dir = DSSAT_GENOTYPE / "China"
    if china_dir.is_dir():
        for cf in china_dir.iterdir():
            if not cf.name.endswith("_China.CUL"):
                continue
            base_name = cf.name.replace("_China.CUL", ".CUL")  # MZCER048_China.CUL -> MZCER048.CUL
            base_src = DSSAT_GENOTYPE / base_name
            if not base_src.exists():
                continue
            # Extract CN#### data rows (skip comments '!', headers '*'/'@', blanks).
            cn_rows = []
            for ln in cf.read_text(errors="ignore").splitlines():
                s = ln.strip()
                if not s or s[0] in "!*@":
                    continue
                cn_rows.append(ln.rstrip("\n"))
            if not cn_rows:
                continue
            for dst in (os.path.join(workdir, base_name),
                        os.path.join(workdir, "Genotype", base_name)):
                # Replace symlink with a real, writable copy, then append CN rows.
                if os.path.islink(dst) or os.path.exists(dst):
                    try:
                        os.remove(dst)
                    except OSError:
                        pass
                shutil.copy2(str(base_src), dst)
                with open(dst, "a") as fh:
                    fh.write("\n! --- China cultivar library (auto-merged) ---\n")
                    fh.write("\n".join(cn_rows) + "\n")

    # ------------------------------------------------------------------
    # Soil file
    # ------------------------------------------------------------------
    # DSSAT matches the FileX FIELDS soil ID against the .SOL profile name over a
    # FIXED 10-char field; IDs shorter than ~8 chars break the match and INSOIL
    # reads uninitialised soil arrays -> SIGFPE (no error message). The convert_*
    # tools now zero-pad to 10, but warn loudly if a short ID slips through here.
    if soil_file and len("".join(c for c in str(soil_id) if c.isalnum())) < 8:
        logging.warning(
            "soil_id '%s' is shorter than 8 chars — DSSAT will likely SIGFPE in "
            "INSOIL (FileX<->.SOL fixed-width match fails). Use a 10-char ID "
            "(e.g. zero-padded) that matches the .SOL profile name.", soil_id)

    soil_dst_main = os.path.join(workdir, "SOIL.SOL")
    soil_dst_dir = os.path.join(workdir, "Soil", "SOIL.SOL")

    if soil_file and os.path.isfile(soil_file):
        # Use custom soil file
        shutil.copy2(soil_file, soil_dst_main)
        shutil.copy2(soil_file, soil_dst_dir)
    else:
        # Use default from DSSAT run_test (has IB00000001-12 generic profiles)
        default_soil = Path("KISSPATH_HOME/DSSAT/run_test/SOIL.SOL")
        if default_soil.exists():
            shutil.copy2(str(default_soil), soil_dst_main)
            shutil.copy2(str(default_soil), soil_dst_dir)
        else:
            logger.warning("No default SOIL.SOL found — soil file must be provided")

    # ------------------------------------------------------------------
    # Weather file (Pitfall #3: station code alignment)
    # ------------------------------------------------------------------
    if weather_file and os.path.isfile(weather_file):
        wth_basename = os.path.basename(weather_file)
        wsta = wth_basename[:4].upper()  # First 4 chars = station code (must be uppercase for DSSAT)

        # Copy weather file to workdir root AND Weather/
        shutil.copy2(weather_file, os.path.join(workdir, wth_basename))
        shutil.copy2(weather_file, os.path.join(workdir, "Weather", wth_basename))

        # Also create a copy with the expected DSSAT name (WSTA+YY+01.WTH)
        # DSSAT searches for weather files matching this pattern
        expected_name = f"{wsta}{start_year % 100:02d}01.WTH"
        if expected_name != wth_basename:
            shutil.copy2(weather_file, os.path.join(workdir, expected_name))
            shutil.copy2(weather_file, os.path.join(workdir, "Weather", expected_name))
            logger.info(f"Weather file also copied as {expected_name} (DSSAT naming convention)")
    else:
        wsta = "SITE"
        if weather_file:
            logger.warning("Weather file not found: %s", weather_file)
        else:
            logger.info("No weather file provided — must be added before running")

    # ------------------------------------------------------------------
    # Build management dict
    # ------------------------------------------------------------------
    mgmt = {}
    if crop in DEFAULT_MANAGEMENT:
        mgmt.update(DEFAULT_MANAGEMENT[crop])
    mgmt.update(management_kwargs)

    # ------------------------------------------------------------------
    # Generate FileX
    # ------------------------------------------------------------------
    # Filename: WSTA + YY + 01 + ext (Pitfall #3: must match WSTA)
    yy_str = f"{start_year % 100:02d}"
    filex_basename = f"{wsta}{yy_str}01{filex_ext}"
    experiment_name = f"{wsta}{yy_str}01{crop}"

    filex_content = _generate_filex(
        crop=crop,
        cultivar=cultivar,
        cul_name=cul_name,
        wsta=wsta,
        soil_id=soil_id,
        lat=lat,
        lon=lon,
        planting_yyddd=planting_yyddd,
        sdate_yyddd=sdate_yyddd,
        start_year=start_year,
        end_year=end_year,
        experiment_name=experiment_name,
        filex_basename=filex_basename,
        management=mgmt,
    )

    filex_path = os.path.join(workdir, filex_basename)
    with open(filex_path, "w", encoding="utf-8") as f:
        f.write(filex_content)

    logger.info("FileX written: %s", filex_path)

    # ------------------------------------------------------------------
    # Generate DSSBatch.v48
    #
    # The FILEX field is written RELATIVE to the workdir (the bare basename),
    # per format_spec path_constraints.FILEX.must_be_relative_to_workdir.
    # run_dssat() below launches ./dscsm048 with cwd=workdir, so PATHEX
    # (CSM.for:270) is empty and DSSAT resolves the FileX in the cwd. An
    # absolute path here would spend the 92-column field (CSM.for:268) on a
    # redundant prefix and cap how deep the workdir may live.
    # ------------------------------------------------------------------
    batch_content = _generate_batch(filex_basename, crop_name)
    batch_path = os.path.join(workdir, "DSSBatch.v48")
    with open(batch_path, "w", encoding="utf-8") as f:
        f.write(batch_content)

    # Read the artifact DSSAT will actually consume back off disk and confirm
    # the contract holds on those bytes — never on the host path we intended.
    recorded_filex = _verify_batch_filex_contract(batch_path, workdir, filex_path)

    logger.info("Batch file written: %s (FILEX field=%r)",
                batch_path, recorded_filex)

    # ------------------------------------------------------------------
    # Generate DSSATPRO.v48 (Pitfall #5: correct paths)
    # ------------------------------------------------------------------
    dssatpro_content = _generate_dssatpro(workdir)
    dssatpro_path = os.path.join(workdir, "DSSATPRO.v48")
    with open(dssatpro_path, "w", encoding="utf-8") as f:
        f.write(dssatpro_content)

    # Also write as DSSATPRO.L48 (Linux variant)
    dssatpro_l48_path = os.path.join(workdir, "DSSATPRO.L48")
    with open(dssatpro_l48_path, "w", encoding="utf-8") as f:
        f.write(dssatpro_content)

    logger.info("DSSATPRO written: %s", dssatpro_path)

    # ------------------------------------------------------------------
    # Preflight checks
    # ------------------------------------------------------------------
    errors = _preflight_check(workdir, filex_basename, wsta, soil_id, cultivar, crop)
    if errors:
        for e in errors:
            logger.warning("PREFLIGHT: %s", e)
    else:
        logger.info("PREFLIGHT: All checks passed")

    return workdir


# ==========================================================================
# Preflight Validation
# ==========================================================================

def _preflight_check(
    workdir: str,
    filex_basename: str,
    wsta: str,
    soil_id: str,
    cultivar: str,
    crop: str,
) -> List[str]:
    """Run preflight checks on the workdir before execution.

    Returns list of error/warning strings (empty = all good).
    """
    errors = []

    # Check binary exists and is executable
    binary = os.path.join(workdir, "dscsm048")
    if not os.path.exists(binary):
        errors.append(f"Binary symlink missing: {binary}")
    elif not os.access(binary, os.X_OK):
        errors.append(f"Binary not executable: {binary}")

    # Check FileX exists
    filex_path = os.path.join(workdir, filex_basename)
    if not os.path.isfile(filex_path):
        errors.append(f"FileX not found: {filex_path}")

    # Check DSSBatch.v48
    batch_path = os.path.join(workdir, "DSSBatch.v48")
    if not os.path.isfile(batch_path):
        errors.append(f"Batch file not found: {batch_path}")
    else:
        with open(batch_path, "r") as f:
            content = f.read()
        if "$BATCH" not in content:
            errors.append("Batch file missing $BATCH header")
        # Replay CSM.for:268-271 on the bytes on disk. The previous check here
        # (`len(line[:92].strip()) > 92`) was dead — a 92-column slice can never
        # exceed 92 chars, so it passed unconditionally and never once tested
        # the field. _verify_batch_filex_contract checks what DSSAT parses:
        # relative, <=92 columns, empty PATHEX, TRTNO still readable at 93-113,
        # and resolving under the workdir to the FileX that exists.
        try:
            _verify_batch_filex_contract(batch_path, workdir, filex_path)
        except ValueError as e:
            errors.append(str(e))

    # Check DSSATPRO.v48
    if not os.path.isfile(os.path.join(workdir, "DSSATPRO.v48")):
        errors.append("DSSATPRO.v48 not found")

    # Check SOIL.SOL and verify soil_id exists
    soil_path = os.path.join(workdir, "SOIL.SOL")
    if not os.path.isfile(soil_path):
        errors.append("SOIL.SOL not found")
    else:
        with open(soil_path, "r") as f:
            soil_content = f.read()
        if f"*{soil_id}" not in soil_content:
            errors.append(f"Soil ID '{soil_id}' not found in SOIL.SOL (looked for '*{soil_id}')")

    # Check weather file (WSTA match)
    wth_files = [f for f in os.listdir(workdir) if f.endswith(".WTH")]
    if not wth_files:
        errors.append(f"No .WTH weather file found in workdir (expected {wsta}*.WTH)")
    else:
        matching = [f for f in wth_files if f.startswith(wsta)]
        if not matching:
            errors.append(
                f"No .WTH file matching WSTA '{wsta}' "
                f"(found: {wth_files})"
            )

    # Check cultivar exists in .CUL file
    crop_info = CROP_REGISTRY.get(crop)
    if crop_info:
        genotype_prefix = crop_info[1]
        cul_base = f"{genotype_prefix}.CUL"
        cul_path = os.path.join(workdir, cul_base)
        if os.path.isfile(cul_path):
            with open(cul_path, "r") as f:
                cul_content = f.read()
            if cultivar not in cul_content:
                errors.append(
                    f"Cultivar '{cultivar}' not found in {cul_base}"
                )

    # Check CDE files present
    missing_cde = [
        cde for cde in CDE_FILES
        if not os.path.exists(os.path.join(workdir, cde))
    ]
    if missing_cde:
        errors.append(f"Missing CDE files: {missing_cde}")

    return errors


# ==========================================================================
# run_dssat — Execute DSSAT
# ==========================================================================

def run_dssat(workdir: str, timeout: int = 600) -> Dict[str, Any]:
    """Run dscsm048 from the given working directory.

    Parameters
    ----------
    workdir : str
        Path to the DSSAT working directory created by create_workdir().
    timeout : int
        Maximum seconds to wait for DSSAT to complete (default 600 = 10 min).

    Returns
    -------
    dict with keys:
        success : bool
        return_code : int
        stdout : str
        stderr : str
        summary_file : str or None  (path to Summary.OUT if it exists)
        error_file : str or None    (path to ERROR.OUT if it exists)
        warning_file : str or None  (path to WARNING.OUT if it exists)
        workdir : str
    """
    workdir = os.path.abspath(workdir)

    # Validate workdir
    batch_path = os.path.join(workdir, "DSSBatch.v48")
    binary_path = os.path.join(workdir, "dscsm048")

    if not os.path.isfile(batch_path):
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": f"DSSBatch.v48 not found in {workdir}",
            "summary_file": None,
            "error_file": None,
            "warning_file": None,
            "workdir": workdir,
        }

    if not os.path.isfile(binary_path):
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": f"dscsm048 binary not found in {workdir}",
            "summary_file": None,
            "error_file": None,
            "warning_file": None,
            "workdir": workdir,
        }

    # Clean up old output files to avoid reading stale results
    for old_out in ["Summary.OUT", "ERROR.OUT", "WARNING.OUT", "OVERVIEW.OUT",
                    "PlantGro.OUT", "SoilWat.OUT", "DSSAT48.INP"]:
        old_path = os.path.join(workdir, old_out)
        if os.path.isfile(old_path):
            os.remove(old_path)

    # Run DSSAT in batch mode
    cmd = ["./dscsm048", "B", "DSSBatch.v48"]

    logger.info("Running DSSAT: %s (cwd=%s)", " ".join(cmd), workdir)

    try:
        result = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "return_code": -2,
            "stdout": "",
            "stderr": f"DSSAT timed out after {timeout}s",
            "summary_file": None,
            "error_file": None,
            "warning_file": None,
            "workdir": workdir,
        }
    except Exception as e:
        return {
            "success": False,
            "return_code": -3,
            "stdout": "",
            "stderr": str(e),
            "summary_file": None,
            "error_file": None,
            "warning_file": None,
            "workdir": workdir,
        }

    # Check output files
    summary_path = os.path.join(workdir, "Summary.OUT")
    error_path = os.path.join(workdir, "ERROR.OUT")
    warning_path = os.path.join(workdir, "WARNING.OUT")

    has_summary = os.path.isfile(summary_path) and os.path.getsize(summary_path) > 0
    has_error = os.path.isfile(error_path) and os.path.getsize(error_path) > 0

    success = result.returncode == 0 and has_summary and not has_error

    return {
        "success": success,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "summary_file": summary_path if has_summary else None,
        "error_file": error_path if has_error else None,
        "warning_file": warning_path if os.path.isfile(warning_path) else None,
        "workdir": workdir,
    }


# ==========================================================================
# parse_summary — Parse Summary.OUT (Pitfall #6)
# ==========================================================================

# Date columns in YYDDD format
_DATE_COLS = {"SDAT", "PDAT", "EDAT", "ADAT", "MDAT", "HDAT"}

# Known integer columns
_INT_COLS = {
    "RUNNO", "TRNO", "WYEAR", "HYEAR", "DWAP", "CWAM", "HWAM", "HWAH",
    "BWAH", "PWAM", "IR#M", "IRCM", "PRCM", "ETCM", "EPCM", "ESCM",
    "ROCM", "DRCM", "SWXM", "NI#M", "NICM", "NUCM", "NLCM", "NIAM",
    "NMINC", "CNAM", "GNAM", "PI#M", "PICM", "KI#M", "KICM",
    "RECM", "ONTAM", "ONAM", "OPTAM", "OPAM", "OCTAM", "OCAM",
    "NDCH", "PRCP", "H#AM",
}


def _parse_value(val_str: str, col_name: str):
    """Parse a single Summary.OUT value. Returns None for -99 (missing)."""
    s = val_str.strip()
    if not s or s in ("-99", "-99.0", "-99.", "-99.000"):
        return None

    try:
        fval = float(s)
    except ValueError:
        return s  # Text field (model name, experiment name)

    if fval == -99.0 or math.isnan(fval) or math.isinf(fval):
        return None

    if col_name in _DATE_COLS:
        return int(fval)
    if col_name in _INT_COLS:
        return int(round(fval))
    return fval


def _yyddd_to_iso(yyddd_val) -> Optional[str]:
    """Convert YYDDD int to 'YYYY-MM-DD' string."""
    dt = _yyddd_to_date(yyddd_val if isinstance(yyddd_val, int) else None)
    return dt.strftime("%Y-%m-%d") if dt else None


def parse_summary(workdir: str) -> List[Dict[str, Any]]:
    """Parse Summary.OUT from a DSSAT working directory.

    Parameters
    ----------
    workdir : str
        Path to directory containing Summary.OUT.

    Returns
    -------
    list of dict
        Each dict is one treatment-season with keys like HWAM, HWAH,
        PDAT, ADAT, MDAT, PRCM, ETCM, etc. Missing values (-99) are None.
        Date fields also get _ISO suffix keys with 'YYYY-MM-DD' strings.
    """
    summary_path = os.path.join(workdir, "Summary.OUT")
    if not os.path.isfile(summary_path):
        raise FileNotFoundError(f"Summary.OUT not found in {workdir}")

    with open(summary_path, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.readlines()

    # Find @ header line
    header_idx = None
    for i, line in enumerate(raw_lines):
        if line.strip().startswith("@"):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("No column header line (starting with @) found in Summary.OUT")

    header_raw = raw_lines[header_idx].rstrip("\n\r")

    # Parse column names and positions from header
    col_parts = header_raw.split()
    if col_parts[0].startswith("@"):
        col_parts[0] = col_parts[0].lstrip("@")
        if not col_parts[0]:
            col_parts = col_parts[1:]

    # Build column position map
    col_positions = []
    search_start = 0
    for col in col_parts:
        pos = header_raw.find(col, search_start)
        if pos >= 0:
            col_positions.append((pos, col))
            search_start = pos + len(col)
        else:
            col_positions.append((search_start, col))
            search_start += len(col) + 1

    # Column bounds: (start, end, name)
    # DSSAT Summary.OUT numeric fields are RIGHT-aligned — the value ends at the
    # right edge of the header token. Using [token_start, next_token_start) clips
    # the leading digit of values wider than the header token (e.g. CWAM=17357
    # in an 8-char column whose header "CWAM" left-edge is at pos+4). Use
    # [end_of_prev_token, end_of_this_token) so right-aligned values are
    # fully captured, padding to the left.
    col_bounds = []
    for k in range(len(col_positions)):
        if k == 0:
            start = 0
        else:
            prev_pos, prev_name = col_positions[k - 1]
            start = prev_pos + len(prev_name)
        this_pos, this_name = col_positions[k]
        end = this_pos + len(this_name)
        col_bounds.append((start, end, this_name))

    # Parse data records
    records = []
    for i in range(header_idx + 1, len(raw_lines)):
        line = raw_lines[i].rstrip("\n\r")
        stripped = line.strip()
        if not stripped or stripped.startswith("*") or stripped.startswith("!") or stripped.startswith("@"):
            continue

        record = {}
        for start, end, col_name in col_bounds:
            if start < len(line):
                val_str = line[start:end] if end and end <= len(line) else line[start:]
                parsed = _parse_value(val_str.strip(), col_name)
                record[col_name] = parsed
            else:
                record[col_name] = None

        # Add ISO date conversions
        for date_col in _DATE_COLS:
            if date_col in record and record[date_col] is not None:
                record[f"{date_col}_ISO"] = _yyddd_to_iso(record[date_col])

        if any(v is not None for v in record.values()):
            records.append(record)

    return records


# ==========================================================================
# CLI Entry Point
# ==========================================================================

if __name__ == "__main__":
    import json

    print("=" * 70)
    print("DSSAT Workdir Setup — Preflight Test")
    print("=" * 70)

    # Test: create a workdir for maize in Montreal (45.5N, 73.6W)
    # Uses existing weather file from DSSAT run_test if available
    weather_src = "KISSPATH_HOME/DSSAT/run_test/MTRL0501.WTH"
    if not os.path.isfile(weather_src):
        print(f"WARNING: Weather file not found: {weather_src}")
        weather_src = None

    try:
        workdir = create_workdir(
            crop="MZ",
            cultivar="IB0035",
            weather_file=weather_src,
            soil_id="IB00000001",
            lat=45.5,
            lon=-73.6,
            planting_date="2005-05-10",
            start_year=2005,
            end_year=2005,
        )
    except Exception as e:
        print(f"ERROR: create_workdir failed: {e}")
        sys.exit(1)

    print(f"\nWorkdir: {workdir}")
    print(f"Path length: {len(workdir)} chars")

    # Show directory structure
    print("\n--- Directory Structure ---")
    for item in sorted(os.listdir(workdir)):
        full = os.path.join(workdir, item)
        if os.path.islink(full):
            target = os.readlink(full)
            print(f"  {item} -> {target}")
        elif os.path.isdir(full):
            count = len(os.listdir(full))
            print(f"  {item}/ ({count} items)")
        else:
            size = os.path.getsize(full)
            print(f"  {item} ({size} bytes)")

    # Show FileX
    filex_files = [f for f in os.listdir(workdir) if f.endswith((".MZX", ".WHX", ".SBX", ".RIX", ".SGX"))]
    if filex_files:
        print(f"\n--- FileX: {filex_files[0]} ---")
        with open(os.path.join(workdir, filex_files[0])) as f:
            print(f.read()[:2000])

    # Show batch file
    batch_path = os.path.join(workdir, "DSSBatch.v48")
    if os.path.isfile(batch_path):
        print("\n--- DSSBatch.v48 ---")
        with open(batch_path) as f:
            print(f.read())

    # Run preflight
    print("\n--- Preflight Checks ---")
    errors = _preflight_check(
        workdir, filex_files[0] if filex_files else "??",
        "MTRL", "IB00000001", "IB0035", "MZ"
    )
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
    else:
        print("  ALL CHECKS PASSED")

    # Show DSSATPRO paths (first few lines)
    print("\n--- DSSATPRO.v48 (first 5 lines) ---")
    with open(os.path.join(workdir, "DSSATPRO.v48")) as f:
        for i, line in enumerate(f):
            if i >= 5:
                break
            print(f"  {line.rstrip()}")

    print(f"\n--- Workdir ready at: {workdir} ---")
    print("To run: cd workdir && ./dscsm048 B DSSBatch.v48")
    print("=" * 70)
