#!/usr/bin/env python3
"""
setup_rice_experiment.py — Set up and run a DSSAT CERES-Rice experiment
using the dssat_workdir_setup infrastructure.

This tool wraps dssat_workdir_setup.create_workdir() with rice-specific
logic:
  - Cultivar selection by region: Chinese cultivars (Yangtze, South,
    Northeast) when inside China; IR 72 (IB0118) for South/SE Asia and
    as global default
  - Boro (dry-season) vs aman (wet-season) detection for South/SE Asia
    with auto-irrigation for boro plantings
  - Rice-specific planting densities and management (transplanting)
  - Paddy irrigation defaults (flooded rice)
  - NPKGRIDS fertilizer integration for N rates
  - Regional planting dates from China phenology data

Usage as library:
    from setup_rice_experiment import setup_rice, CHINESE_RICE_CULTIVARS
    result = setup_rice(lat=30.5, lon=114.3, year=2010, weather_file="path.WTH")

Usage from CLI:
    python setup_rice_experiment.py --lat 30.5 --lon 114.3 --year 2010 \
        --weather path.WTH --soil_file path.SOL --soil_id IBRI910001

Author: HydroCraft KI / DSSAT Knowledge Infrastructure
"""

import os
import sys
import json
import logging
from typing import Optional, Dict, Any

# Add KI tools to path
_KI_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _KI_TOOLS not in sys.path:
    sys.path.insert(0, _KI_TOOLS)

from dssat_workdir_setup import create_workdir, run_dssat, parse_summary

logger = logging.getLogger("setup_rice_experiment")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

# =========================================================================
# Chinese Rice Cultivar Library
# =========================================================================
# Source: KISSPATH_HOME/DSSAT/Data/Genotype/China/RICER048_China.CUL
# These cultivar codes exist in the main RICER048.CUL file (appended as
# CN02xx entries).

CHINESE_RICE_CULTIVARS = {
    # --- Yangtze River Region (single-crop indica, lat ~28-33N) ---
    "CN0201": {
        "name": "YZR Indica Medium",
        "region": "Yangtze",
        "system": "single_crop",
        "season_days": 150,
        "plant_doy": 120,   # ~May 1
        "expected_yield_kgha": (6000, 8000),
        "description": "Medium-duration indica for middle-lower Yangtze",
    },
    "CN0202": {
        "name": "YZR Indica Early",
        "region": "Yangtze",
        "system": "single_crop",
        "season_days": 130,
        "plant_doy": 110,   # ~Apr 20
        "expected_yield_kgha": (5000, 7000),
        "description": "Early indica for Yangtze, shorter season",
    },
    "CN0203": {
        "name": "YZR Indica Late",
        "region": "Yangtze",
        "system": "single_crop",
        "season_days": 165,
        "plant_doy": 130,   # ~May 10
        "expected_yield_kgha": (6500, 8500),
        "description": "Late indica for Yangtze, longer season, higher yield potential",
    },
    "CN0204": {
        "name": "YZR Hybrid (Shanyou)",
        "region": "Yangtze",
        "system": "single_crop",
        "season_days": 155,
        "plant_doy": 125,   # ~May 5
        "expected_yield_kgha": (7000, 9500),
        "description": "Hybrid indica (Shanyou type), highest yield potential in Yangtze",
    },
    # --- South China (double-crop early season, lat <28N) ---
    "CN0211": {
        "name": "SC Early Indica",
        "region": "South",
        "system": "double_early",
        "season_days": 115,
        "plant_doy": 75,    # ~Mar 16
        "expected_yield_kgha": (4000, 6000),
        "description": "Early-season indica for double-cropping in South China",
    },
    "CN0212": {
        "name": "SC Early Hybrid",
        "region": "South",
        "system": "double_early",
        "season_days": 120,
        "plant_doy": 80,    # ~Mar 21
        "expected_yield_kgha": (4500, 6500),
        "description": "Early-season hybrid for double-cropping in South China",
    },
    # --- South China (double-crop late season) ---
    "CN0221": {
        "name": "SC Late Indica",
        "region": "South",
        "system": "double_late",
        "season_days": 125,
        "plant_doy": 195,   # ~Jul 14
        "expected_yield_kgha": (4000, 5500),
        "description": "Late-season indica for double-cropping in South China",
    },
    "CN0222": {
        "name": "SC Late Hybrid",
        "region": "South",
        "system": "double_late",
        "season_days": 130,
        "plant_doy": 190,   # ~Jul 9
        "expected_yield_kgha": (4500, 6500),
        "description": "Late-season hybrid for double-cropping in South China",
    },
    # --- Northeast China (japonica, lat >40N) ---
    "CN0231": {
        "name": "NEC Japonica Calib",
        "region": "Northeast",
        "system": "single_crop",
        "season_days": 155,
        "plant_doy": 130,   # ~May 10
        "expected_yield_kgha": (6000, 8500),
        "description": "Calibrated japonica for Heilongjiang/Jilin, cold-tolerant",
    },
    "CN0232": {
        "name": "NEC Japonica Early",
        "region": "Northeast",
        "system": "single_crop",
        "season_days": 135,
        "plant_doy": 125,   # ~May 5
        "expected_yield_kgha": (5000, 7000),
        "description": "Early japonica for Northeast, short-season areas",
    },
    "CN0233": {
        "name": "NEC Japonica Late",
        "region": "Northeast",
        "system": "single_crop",
        "season_days": 165,
        "plant_doy": 135,   # ~May 15
        "expected_yield_kgha": (6500, 9000),
        "description": "Late japonica for Northeast, longer season, high quality grain",
    },
}

# IRRI / international cultivars available in the default CUL file
IRRI_RICE_CULTIVARS = {
    "IB0118": {"name": "IR 72", "region": "tropical", "plant_doy": 150},
    "IB0012": {"name": "IR 58", "region": "tropical", "plant_doy": 150},
    "IB0015": {"name": "IR 64", "region": "tropical", "plant_doy": 150},
    "IB0001": {"name": "IR 8", "region": "tropical", "plant_doy": 150},
    "990001": {"name": "IRRI ORIGINALS", "region": "tropical", "plant_doy": 150},
    "990003": {"name": "JAPANESE", "region": "temperate", "plant_doy": 130},
}

# Default rice management parameters
RICE_MANAGEMENT_DEFAULTS = {
    "ppop": 25.0,       # plants/m2 (transplanting density)
    "plrs": 30,         # row spacing cm
    "pldp": 3,          # planting depth cm
    "fert_n": 150,      # N fertilizer kg/ha (will be overridden by NPKGRIDS if available)
    "fert_date_offset": 15,  # days after planting for topdressing
}


def select_cultivar_by_location(lat: float, lon: float,
                                 system: Optional[str] = None) -> str:
    """Select appropriate rice cultivar based on location.

    For locations within China (lat 18-53N, lon 73-135E), Chinese cultivars
    are selected by region.  For South/SE Asia (lat 5-30N, lon 70-130E) and
    all other non-China locations, IRRI IR 72 (IB0118) is used as it is the
    standard indica benchmark available in the DSSAT genotype files.

    Parameters
    ----------
    lat : float
        Latitude in decimal degrees.
    lon : float
        Longitude in decimal degrees.
    system : str, optional
        Override cropping system: 'single_crop', 'double_early', 'double_late'.
        If None, auto-selects based on latitude.

    Returns
    -------
    str
        Cultivar code (e.g., 'CN0201', 'IB0118').
    """
    # --- China-specific logic ---
    # For lat >= 28N (Yangtze + Northeast): broad lon range covers Xinjiang to coast.
    # For lat < 28N (South China): narrower lon (97-122E) excludes Bangladesh,
    # Myanmar, and Thailand while keeping Yunnan, Guangxi, and Hainan.
    if lat >= 28:
        _is_china = (lat <= 53) and (73 <= lon <= 135)
    else:
        _is_china = (18 <= lat) and (97 <= lon <= 122)

    if _is_china:
        if system == "double_early":
            return "CN0212"  # SC Early Hybrid
        elif system == "double_late":
            return "CN0222"  # SC Late Hybrid

        if lat >= 40:
            # Northeast China — japonica
            return "CN0231"  # Calibrated japonica
        elif lat >= 28:
            # Yangtze region — single-crop indica
            return "CN0204"  # Hybrid Shanyou (highest yield)
        else:
            # South China — default to single-crop or double-early
            if system is None:
                return "CN0212"  # Double-crop early
            return "CN0211"

    # --- Non-China: South / SE Asia tropical belt ---
    if 5 <= lat <= 30 and 70 <= lon <= 130:
        logger.info("South/SE Asia location — selecting IR 72 (IB0118)")
        return "IB0118"  # IR 72 (IRRI standard indica)

    # --- Temperate non-China (e.g., Korea, Japan, US) ---
    if 30 < lat <= 45:
        logger.info("Temperate non-China location — selecting IR 72 (IB0118)")
        return "IB0118"  # IR 72 as reasonable default

    # --- Global fallback ---
    logger.info("No region-specific cultivar — selecting IR 72 (IB0118)")
    return "IB0118"  # IR 72 global default


def detect_season_south_asia(planting_doy: int, lat: float) -> Optional[str]:
    """Detect boro (dry) vs aman (wet) rice season for South/SE Asia.

    Parameters
    ----------
    planting_doy : int
        Day of year for planting.
    lat : float
        Latitude in decimal degrees.

    Returns
    -------
    str or None
        'boro' for dry-season rice (Nov-Apr planting, needs irrigation),
        'aman' for wet-season rice (Jun-Sep planting, rainfed OK),
        None if outside the South/SE Asia tropical belt (5-30N).
    """
    if not (5 <= lat <= 30):
        return None
    if (1 <= planting_doy <= 120) or (305 <= planting_doy <= 365):
        return "boro"
    if 150 <= planting_doy <= 270:
        return "aman"
    return None  # transitional dates — no strong signal


def get_planting_doy(cultivar_code: str, lat: float) -> int:
    """Get planting DOY for a cultivar, with latitude-based adjustment.

    Returns
    -------
    int
        Day of year for planting.
    """
    if cultivar_code in CHINESE_RICE_CULTIVARS:
        base_doy = CHINESE_RICE_CULTIVARS[cultivar_code]["plant_doy"]
    elif cultivar_code in IRRI_RICE_CULTIVARS:
        base_doy = IRRI_RICE_CULTIVARS[cultivar_code]["plant_doy"]
    else:
        base_doy = 130  # generic mid-May

    # Latitude adjustment: ~2 days later per degree north above 25N
    if lat > 25:
        base_doy += int((lat - 25) * 2)

    return min(base_doy, 180)  # Cap at end of June


def get_fertilizer_rate(lat: float, lon: float) -> float:
    """Try to get rice N fertilizer rate from NPKGRIDS Data KI.

    Falls back to regional defaults if NPKGRIDS is unavailable.

    Returns
    -------
    float
        N application rate in kg/ha.
    """
    try:
        npk_tool = "KISSPATH_DATA_KI/NPKGRIDS/tools/get_fertilizer.py"
        if os.path.isfile(npk_tool):
            npk_dir = os.path.dirname(npk_tool)
            if npk_dir not in sys.path:
                sys.path.insert(0, npk_dir)
            from get_fertilizer import get_npk_rates
            result = get_npk_rates(lat, lon, "rice")
            if isinstance(result, dict) and "N_kgha" in result and result["N_kgha"] > 0:
                logger.info("NPKGRIDS rice N rate: %.1f kg/ha", result["N_kgha"])
                return result["N_kgha"]
    except Exception as e:
        logger.warning("NPKGRIDS lookup failed: %s — using regional default", e)

    # Regional defaults for China (Zhang et al., 2013)
    if lat >= 40:
        return 120.0  # Northeast
    elif lat >= 28:
        return 180.0  # Yangtze
    else:
        return 150.0  # South


def setup_rice(
    lat: float,
    lon: float,
    year: int = 2010,
    end_year: Optional[int] = None,
    weather_file: Optional[str] = None,
    soil_file: Optional[str] = None,
    soil_id: str = "IB00000001",
    cultivar: Optional[str] = None,
    system: Optional[str] = None,
    output_dir: Optional[str] = None,
    use_npkgrids: bool = True,
    fert_n: Optional[float] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Set up and optionally run a DSSAT CERES-Rice experiment.

    Parameters
    ----------
    lat, lon : float
        Location coordinates.
    year : int
        Start year of simulation.
    end_year : int, optional
        End year (default = year, single-year run).
    weather_file : str, optional
        Path to .WTH file.
    soil_file : str, optional
        Path to .SOL file.
    soil_id : str
        Soil profile ID in the SOL file.
    cultivar : str, optional
        Cultivar code. If None, auto-selected by location.
    system : str, optional
        Cropping system override.
    output_dir : str, optional
        Output directory for workdir.
    use_npkgrids : bool
        Whether to query NPKGRIDS for fertilizer rates.
    fert_n : float, optional
        Override N fertilizer rate (kg/ha).
    **kwargs
        Additional management kwargs passed to create_workdir.

    Returns
    -------
    dict with keys:
        workdir : str
        cultivar : str
        cultivar_info : dict
        planting_doy : int
        fert_n_kgha : float
        run_result : dict or None (if weather_file provided and run succeeds)
        summary : list or None
    """
    if end_year is None:
        end_year = year

    # Select cultivar
    if cultivar is None:
        cultivar = select_cultivar_by_location(lat, lon, system)

    # Get cultivar info
    if cultivar in CHINESE_RICE_CULTIVARS:
        cul_info = CHINESE_RICE_CULTIVARS[cultivar]
    elif cultivar in IRRI_RICE_CULTIVARS:
        cul_info = IRRI_RICE_CULTIVARS[cultivar]
    else:
        cul_info = {"name": cultivar, "region": "unknown", "plant_doy": 130}

    # Get planting DOY
    planting_doy = get_planting_doy(cultivar, lat)

    # Detect boro/aman season for South/SE Asia
    sa_season = detect_season_south_asia(planting_doy, lat)

    # Get fertilizer rate
    if fert_n is not None:
        n_rate = fert_n
    elif use_npkgrids:
        n_rate = get_fertilizer_rate(lat, lon)
    else:
        n_rate = RICE_MANAGEMENT_DEFAULTS["fert_n"]

    # Build management parameters
    mgmt = dict(RICE_MANAGEMENT_DEFAULTS)
    mgmt["fert_n"] = int(round(n_rate))
    mgmt.update(kwargs)

    # Auto-enable irrigation for boro (dry-season) rice
    if sa_season == "boro" and "irrig" not in kwargs:
        mgmt["irrig"] = "A"  # Automatic irrigation
        logger.info("Boro (dry-season) rice detected — enabling automatic irrigation")

    logger.info("Rice setup: cultivar=%s (%s), lat=%.2f, lon=%.2f, year=%d",
                cultivar, cul_info.get("name", "?"), lat, lon, year)
    logger.info("  planting DOY=%d, N=%.0f kg/ha, region=%s, season=%s",
                planting_doy, n_rate, cul_info.get("region", "?"),
                sa_season or "default")

    # Compute planting date in YYDDD
    if year >= 2000:
        yy = year - 2000
    elif year >= 1971:
        yy = year - 1900
    else:
        raise ValueError(f"Year {year} out of DSSAT range")
    planting_yyddd = yy * 1000 + planting_doy

    # Create workdir via the central utility
    workdir = create_workdir(
        crop="RI",
        cultivar=cultivar,
        weather_file=weather_file,
        soil_id=soil_id,
        soil_file=soil_file,
        lat=lat,
        lon=lon,
        planting_date=planting_yyddd,
        start_year=year,
        end_year=end_year,
        output_dir=output_dir,
        **mgmt,
    )

    result = {
        "workdir": workdir,
        "cultivar": cultivar,
        "cultivar_info": cul_info,
        "planting_doy": planting_doy,
        "fert_n_kgha": n_rate,
        "season": sa_season,            # 'boro', 'aman', or None
        "irrig_auto": sa_season == "boro" and "irrig" not in kwargs,
        "run_result": None,
        "summary": None,
    }

    # Run DSSAT if weather file was provided
    if weather_file and os.path.isfile(weather_file):
        logger.info("Running DSSAT CERES-Rice...")
        run_result = run_dssat(workdir)
        result["run_result"] = run_result

        if run_result["success"]:
            try:
                summary = parse_summary(workdir)
                result["summary"] = summary
                for rec in summary:
                    hwam = rec.get("HWAM")
                    adat = rec.get("ADAT_ISO", rec.get("ADAT"))
                    mdat = rec.get("MDAT_ISO", rec.get("MDAT"))
                    logger.info("  Year HWAM=%s kg/ha, anthesis=%s, maturity=%s",
                                hwam, adat, mdat)
            except Exception as e:
                logger.warning("Summary parsing failed: %s", e)
        else:
            logger.warning("DSSAT run failed: %s", run_result.get("stderr", ""))
            # Check ERROR.OUT
            error_file = run_result.get("error_file")
            if error_file and os.path.isfile(error_file):
                with open(error_file) as f:
                    logger.warning("ERROR.OUT:\n%s", f.read()[:500])

    return result


def list_cultivars(region: Optional[str] = None) -> list:
    """List available rice cultivars, optionally filtered by region.

    Parameters
    ----------
    region : str, optional
        Filter by region: 'Yangtze', 'South', 'Northeast', 'tropical', 'temperate'.

    Returns
    -------
    list of dict
        Each dict has keys: code, name, region, system, expected_yield_kgha.
    """
    cultivars = []
    for code, info in CHINESE_RICE_CULTIVARS.items():
        if region and info["region"].lower() != region.lower():
            continue
        cultivars.append({
            "code": code,
            "name": info["name"],
            "region": info["region"],
            "system": info["system"],
            "expected_yield_kgha": info["expected_yield_kgha"],
        })
    for code, info in IRRI_RICE_CULTIVARS.items():
        if region and info["region"].lower() != region.lower():
            continue
        cultivars.append({
            "code": code,
            "name": info["name"],
            "region": info["region"],
            "system": "international",
        })
    return cultivars


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Set up DSSAT CERES-Rice experiment with Chinese cultivar defaults"
    )
    parser.add_argument("--lat", type=float, default=None, help="Latitude")
    parser.add_argument("--lon", type=float, default=None, help="Longitude")
    parser.add_argument("--year", type=int, default=2010, help="Start year")
    parser.add_argument("--end_year", type=int, default=None, help="End year")
    parser.add_argument("--weather", type=str, default=None, help="Path to .WTH file")
    parser.add_argument("--soil_file", type=str, default=None, help="Path to .SOL file")
    parser.add_argument("--soil_id", type=str, default="IB00000001", help="Soil profile ID")
    parser.add_argument("--cultivar", type=str, default=None, help="Cultivar code (auto if omitted)")
    parser.add_argument("--system", type=str, default=None,
                        choices=["single_crop", "double_early", "double_late"],
                        help="Cropping system")
    parser.add_argument("--output_dir", type=str, default=None, help="Output directory")
    parser.add_argument("--fert_n", type=float, default=None, help="Override N rate kg/ha")
    parser.add_argument("--no_npkgrids", action="store_true", help="Skip NPKGRIDS lookup")
    parser.add_argument("--list_cultivars", action="store_true", help="List cultivars and exit")
    parser.add_argument("--run", action="store_true", help="Run DSSAT after setup")

    args = parser.parse_args()

    if args.list_cultivars:
        cultivars = list_cultivars()
        print(json.dumps(cultivars, indent=2))
        return

    if args.lat is None or args.lon is None:
        parser.error("--lat and --lon are required (unless --list_cultivars)")

    result = setup_rice(
        lat=args.lat,
        lon=args.lon,
        year=args.year,
        end_year=args.end_year,
        weather_file=args.weather,
        soil_file=args.soil_file,
        soil_id=args.soil_id,
        cultivar=args.cultivar,
        system=args.system,
        output_dir=args.output_dir,
        use_npkgrids=not args.no_npkgrids,
        fert_n=args.fert_n,
    )

    print(json.dumps({
        "workdir": result["workdir"],
        "cultivar": result["cultivar"],
        "cultivar_name": result["cultivar_info"].get("name"),
        "planting_doy": result["planting_doy"],
        "fert_n_kgha": result["fert_n_kgha"],
        "run_success": result["run_result"]["success"] if result["run_result"] else None,
        "yield_kgha": (result["summary"][0].get("HWAM") if result["summary"] else None),
    }, indent=2))


if __name__ == "__main__":
    main()
