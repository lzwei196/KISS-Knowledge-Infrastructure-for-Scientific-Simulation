#!/usr/bin/env python3
"""
setup_soybean_experiment.py — Set up and run a DSSAT CROPGRO-Soybean experiment
using Chinese cultivar defaults and the dssat_workdir_setup infrastructure.

This tool wraps dssat_workdir_setup.create_workdir() with soybean-specific logic:
  - Chinese cultivar selection by region (Northeast, Huang-Huai-Hai, South)
  - Maturity group (MG) based cultivar matching
  - Soybean-specific management (legume N fixation, lower plant density)
  - NPKGRIDS fertilizer integration (soybean typically needs minimal N)
  - Regional planting dates

Key difference from cereals: CROPGRO model uses different parameter structure
than CERES. The soybean CUL file has CSDL, PPSEN, EM-FL, FL-SH, etc.
(photothermal day parameters) instead of GDD-based P1/P2/P5.

Usage as library:
    from setup_soybean_experiment import setup_soybean, CHINESE_SB_CULTIVARS
    result = setup_soybean(lat=33.0, lon=117.0, year=2010, weather_file="path.WTH")

Usage from CLI:
    python setup_soybean_experiment.py --lat 33.0 --lon 117.0 --year 2010 \
        --weather path.WTH --soil_file path.SOL --soil_id IBMZ910014

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

logger = logging.getLogger("setup_soybean_experiment")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

# =========================================================================
# Chinese Soybean Cultivar Library
# =========================================================================
# Source: /home/server/DSSAT/Data/Genotype/China/SBGRO048_China.CUL
# These cultivar codes exist in the main SBGRO048.CUL file (appended as
# CN03xx entries). Model is CRGRO048 (CROPGRO).

CHINESE_SB_CULTIVARS = {
    # --- Northeast China (MG 0-II, early, lat >40N) ---
    "CN0301": {
        "name": "NEC MG 0 Early",
        "region": "Northeast",
        "maturity_group": 0,
        "plant_doy": 130,   # ~May 10
        "expected_yield_kgha": (1800, 2800),
        "description": "Early soybean for Heilongjiang/Jilin (MG 0), short season",
        "ecotype": "SB0001",
    },
    "CN0302": {
        "name": "NEC MG I Medium",
        "region": "Northeast",
        "maturity_group": 1,
        "plant_doy": 135,   # ~May 15
        "expected_yield_kgha": (2000, 3000),
        "description": "Medium soybean for Northeast (MG I), main production type",
        "ecotype": "SB0101",
    },
    "CN0303": {
        "name": "NEC MG II Late",
        "region": "Northeast",
        "maturity_group": 2,
        "plant_doy": 128,   # ~May 8
        "expected_yield_kgha": (2200, 3200),
        "description": "Late soybean for Northeast (MG II), needs longer frost-free period",
        "ecotype": "SB0201",
    },
    # --- Huang-Huai-Hai (MG III-IV, summer soybean after wheat, lat 32-40N) ---
    "CN0311": {
        "name": "HHH MG III",
        "region": "Huang-Huai-Hai",
        "maturity_group": 3,
        "plant_doy": 165,   # ~Jun 14 (after wheat harvest)
        "expected_yield_kgha": (2000, 3000),
        "description": "Summer soybean for HHH after wheat harvest (MG III)",
        "ecotype": "SB0301",
    },
    "CN0312": {
        "name": "HHH MG IV",
        "region": "Huang-Huai-Hai",
        "maturity_group": 4,
        "plant_doy": 160,   # ~Jun 9
        "expected_yield_kgha": (2200, 3200),
        "description": "Summer soybean for HHH (MG IV), slightly longer season",
        "ecotype": "SB0401",
    },
    # --- South China (MG V-VI, subtropical/tropical, lat <32N) ---
    "CN0321": {
        "name": "SC MG V",
        "region": "South",
        "maturity_group": 5,
        "plant_doy": 165,   # ~Jun 14
        "expected_yield_kgha": (1800, 2600),
        "description": "Soybean for South China (MG V), heat-tolerant",
        "ecotype": "SB0501",
    },
    "CN0322": {
        "name": "SC MG VI",
        "region": "South",
        "maturity_group": 6,
        "plant_doy": 170,   # ~Jun 19
        "expected_yield_kgha": (1600, 2400),
        "description": "Soybean for South China (MG VI), longest season",
        "ecotype": "SB0601",
    },
}

# DSSAT default soybean cultivars (from SBGRO048.CUL)
DEFAULT_SB_CULTIVARS = {
    "IB0001": {"name": "BRAGG", "region": "USA_South", "maturity_group": 7,
               "plant_doy": 150},
    "IB0003": {"name": "WAYNE (3)", "region": "USA_Midwest", "maturity_group": 3,
               "plant_doy": 140},
    "IB0011": {"name": "EVANS (0)", "region": "USA_North", "maturity_group": 0,
               "plant_doy": 135},
    "990003": {"name": "M GROUP 3", "region": "generic", "maturity_group": 3,
               "plant_doy": 150},
}

# Default soybean management parameters
# Key difference from cereals: soybean is a legume (SYMBI=Y in FileX)
# and typically receives little or no N fertilizer (relies on N fixation)
SOYBEAN_MANAGEMENT_DEFAULTS = {
    "ppop": 30.0,       # plants/m2 (drilled soybean)
    "plrs": 38,         # row spacing cm (narrow rows for China)
    "pldp": 4,          # planting depth cm
    "fert_n": 20,       # Minimal N starter (soybean fixes N)
    "fert_date_offset": 0,  # Applied at planting
}


def select_cultivar_by_location(lat: float, lon: float,
                                 maturity_group: Optional[int] = None) -> str:
    """Select appropriate Chinese soybean cultivar based on latitude.

    Parameters
    ----------
    lat : float
        Latitude in decimal degrees.
    lon : float
        Longitude in decimal degrees.
    maturity_group : int, optional
        Force specific maturity group (0-6).

    Returns
    -------
    str
        Cultivar code (e.g., 'CN0302').
    """
    if maturity_group is not None:
        # Find cultivar matching requested maturity group
        for code, info in CHINESE_SB_CULTIVARS.items():
            if info["maturity_group"] == maturity_group:
                return code
        # Fall back to closest available
        logger.warning("MG %d not in Chinese library, using latitude selection", maturity_group)

    if lat >= 40:
        # Northeast — MG I (most common production type)
        return "CN0302"
    elif lat >= 32:
        # Huang-Huai-Hai — MG III (summer soybean)
        return "CN0311"
    else:
        # South — MG V
        return "CN0321"


def get_planting_doy(cultivar_code: str, lat: float) -> int:
    """Get planting DOY for a soybean cultivar.

    For Huang-Huai-Hai, soybean is planted after winter wheat harvest
    (typically mid-June). For Northeast, planted in May.

    Returns
    -------
    int
        Day of year for planting.
    """
    if cultivar_code in CHINESE_SB_CULTIVARS:
        base_doy = CHINESE_SB_CULTIVARS[cultivar_code]["plant_doy"]
    elif cultivar_code in DEFAULT_SB_CULTIVARS:
        base_doy = DEFAULT_SB_CULTIVARS[cultivar_code]["plant_doy"]
    else:
        # Default based on latitude
        if lat >= 40:
            base_doy = 135  # May 15
        elif lat >= 32:
            base_doy = 165  # Jun 14 (after wheat)
        else:
            base_doy = 170  # Jun 19

    return base_doy


def get_fertilizer_rate(lat: float, lon: float) -> float:
    """Get soybean N fertilizer rate from NPKGRIDS or regional defaults.

    Soybean typically receives minimal N because of symbiotic N fixation.
    DSSAT handles N fixation when SYMBI=Y in the experiment file.

    Returns
    -------
    float
        N application rate in kg/ha (typically 0-30 for soybean).
    """
    try:
        npk_tool = "/mnt/disk1/Hydrocraft_server/data_ki/NPKGRIDS/tools/get_fertilizer.py"
        if os.path.isfile(npk_tool):
            npk_dir = os.path.dirname(npk_tool)
            if npk_dir not in sys.path:
                sys.path.insert(0, npk_dir)
            from get_fertilizer import get_npk_rates
            result = get_npk_rates(lat, lon, "soybean")
            if isinstance(result, dict) and "N_kgha" in result and result["N_kgha"] > 0:
                n_rate = result["N_kgha"]
                # Cap soybean N at 50 kg/ha — higher values from NPKGRIDS
                # likely include fixed N, not applied N
                n_rate = min(n_rate, 50.0)
                logger.info("NPKGRIDS soybean N rate: %.1f kg/ha (capped at 50)", n_rate)
                return n_rate
    except Exception as e:
        logger.warning("NPKGRIDS lookup failed: %s — using default", e)

    return 20.0  # Default minimal starter N for soybean


def setup_soybean(
    lat: float,
    lon: float,
    year: int = 2010,
    end_year: Optional[int] = None,
    weather_file: Optional[str] = None,
    soil_file: Optional[str] = None,
    soil_id: str = "IB00000001",
    cultivar: Optional[str] = None,
    maturity_group: Optional[int] = None,
    output_dir: Optional[str] = None,
    use_npkgrids: bool = True,
    fert_n: Optional[float] = None,
    shaw_planting_doy: Optional[int] = None,
    run_model: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Set up and optionally run a DSSAT CROPGRO-Soybean experiment.

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
        Cultivar code. If None, auto-selected by location/MG.
    maturity_group : int, optional
        Force maturity group (0-6).
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
        run_result : dict or None
        summary : list or None
    """
    if end_year is None:
        end_year = year

    # Select cultivar
    if cultivar is None:
        cultivar = select_cultivar_by_location(lat, lon, maturity_group)

    # Get cultivar info
    if cultivar in CHINESE_SB_CULTIVARS:
        cul_info = CHINESE_SB_CULTIVARS[cultivar]
    elif cultivar in DEFAULT_SB_CULTIVARS:
        cul_info = DEFAULT_SB_CULTIVARS[cultivar]
    else:
        cul_info = {"name": cultivar, "region": "unknown", "maturity_group": -1,
                    "plant_doy": 150}

    # Get planting DOY — SHAW thermal trigger overrides climatological default
    if shaw_planting_doy is not None:
        planting_doy = int(shaw_planting_doy)
    else:
        planting_doy = get_planting_doy(cultivar, lat)

    # Get fertilizer rate
    if fert_n is not None:
        n_rate = fert_n
    elif use_npkgrids:
        n_rate = get_fertilizer_rate(lat, lon)
    else:
        n_rate = SOYBEAN_MANAGEMENT_DEFAULTS["fert_n"]

    # Build management parameters
    mgmt = dict(SOYBEAN_MANAGEMENT_DEFAULTS)
    mgmt["fert_n"] = int(round(n_rate))
    mgmt.update(kwargs)

    logger.info("Soybean setup: cultivar=%s (%s), lat=%.2f, lon=%.2f, year=%d",
                cultivar, cul_info.get("name", "?"), lat, lon, year)
    logger.info("  planting DOY=%d, N=%.0f kg/ha, MG=%s, region=%s",
                planting_doy, n_rate,
                cul_info.get("maturity_group", "?"),
                cul_info.get("region", "?"))

    # Compute planting date in YYDDD
    if year >= 2000:
        yy = year - 2000
    elif year >= 1971:
        yy = year - 1900
    else:
        raise ValueError(f"Year {year} out of DSSAT range")
    planting_yyddd = yy * 1000 + planting_doy

    # Create workdir via the central utility
    # Note: crop="SB" triggers is_legume=True in dssat_workdir_setup,
    # which sets SYMBI=Y in the FileX (enabling N fixation)
    workdir = create_workdir(
        crop="SB",
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
        "run_result": None,
        "summary": None,
    }

    # Run DSSAT if weather file was provided and run_model=True
    if run_model and weather_file and os.path.isfile(weather_file):
        logger.info("Running DSSAT CROPGRO-Soybean...")
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
            error_file = run_result.get("error_file")
            if error_file and os.path.isfile(error_file):
                with open(error_file) as f:
                    logger.warning("ERROR.OUT:\n%s", f.read()[:500])

    return result


def list_cultivars(region: Optional[str] = None) -> list:
    """List available soybean cultivars, optionally filtered by region.

    Parameters
    ----------
    region : str, optional
        Filter by region: 'Northeast', 'Huang-Huai-Hai', 'South'.

    Returns
    -------
    list of dict
    """
    cultivars = []
    for code, info in CHINESE_SB_CULTIVARS.items():
        if region and info["region"].lower() != region.lower():
            continue
        cultivars.append({
            "code": code,
            "name": info["name"],
            "region": info["region"],
            "maturity_group": info["maturity_group"],
            "expected_yield_kgha": info["expected_yield_kgha"],
        })
    for code, info in DEFAULT_SB_CULTIVARS.items():
        if region and info["region"].lower() != region.lower():
            continue
        cultivars.append({
            "code": code,
            "name": info["name"],
            "region": info["region"],
            "maturity_group": info["maturity_group"],
        })
    return cultivars


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Set up DSSAT CROPGRO-Soybean experiment with Chinese cultivar defaults"
    )
    parser.add_argument("--lat", type=float, default=None, help="Latitude")
    parser.add_argument("--lon", type=float, default=None, help="Longitude")
    parser.add_argument("--year", type=int, default=2010, help="Start year")
    parser.add_argument("--end_year", type=int, default=None, help="End year")
    parser.add_argument("--weather", type=str, default=None, help="Path to .WTH file")
    parser.add_argument("--soil_file", type=str, default=None, help="Path to .SOL file")
    parser.add_argument("--soil_id", type=str, default="IB00000001", help="Soil profile ID")
    parser.add_argument("--cultivar", type=str, default=None, help="Cultivar code")
    parser.add_argument("--maturity_group", type=int, default=None, choices=range(0, 7),
                        help="Maturity group (0-6)")
    parser.add_argument("--output_dir", type=str, default=None, help="Output directory")
    parser.add_argument("--fert_n", type=float, default=None, help="Override N rate kg/ha")
    parser.add_argument("--no_npkgrids", action="store_true", help="Skip NPKGRIDS lookup")
    parser.add_argument("--list_cultivars", action="store_true", help="List cultivars and exit")

    args = parser.parse_args()

    if args.list_cultivars:
        cultivars = list_cultivars()
        print(json.dumps(cultivars, indent=2))
        return

    if args.lat is None or args.lon is None:
        parser.error("--lat and --lon are required (unless --list_cultivars)")

    result = setup_soybean(
        lat=args.lat,
        lon=args.lon,
        year=args.year,
        end_year=args.end_year,
        weather_file=args.weather,
        soil_file=args.soil_file,
        soil_id=args.soil_id,
        cultivar=args.cultivar,
        maturity_group=args.maturity_group,
        output_dir=args.output_dir,
        use_npkgrids=not args.no_npkgrids,
        fert_n=args.fert_n,
    )

    print(json.dumps({
        "workdir": result["workdir"],
        "cultivar": result["cultivar"],
        "cultivar_name": result["cultivar_info"].get("name"),
        "maturity_group": result["cultivar_info"].get("maturity_group"),
        "planting_doy": result["planting_doy"],
        "fert_n_kgha": result["fert_n_kgha"],
        "run_success": result["run_result"]["success"] if result["run_result"] else None,
        "yield_kgha": (result["summary"][0].get("HWAM") if result["summary"] else None),
    }, indent=2))


if __name__ == "__main__":
    main()
