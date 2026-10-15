#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      convert_hwsd_to_pcse_soil
Stage:        s2_soil_params
Description:  Convert HWSD soil properties (sand/silt/clay/OC/bulk density)
              to WOFOST water balance parameters (SMW/SMFCF/SM0/K0) via
              the SHARED ki_tools_common.soil_utils hydraulics (dt_v007, 2026-09-12:
              a private formula mislabelled as Wosten 1999 was removed).

Inputs:
  - LAT, LON: target location coordinates
  - HWSD_RASTER: path to HWSD global raster (hwsd.bil)
  - HWSD_MDB: path to HWSD MDB database

Outputs:
  - JSON on stdout with WOFOST soil parameter dictionary

Exit codes:
  0 — success
  1 — input validation failed
  2 — processing error
  3 — output validation failed
"""

import sys
import os
import json
import math
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LAT = 52.0
LON = 5.5
# KDT 5.0 fix (2026-06-08): default HWSD_RASTER was the cwd-RELATIVE path
# "data/soil/HWSD_RASTER/hwsd.bil", which only resolves when the tool happens to
# be launched from the data root ($ROOT). Run from any other cwd (e.g. an
# outputs/<case>/ dir, the normal driver pattern) validate_inputs() failed with
# "Either HWSD raster or manual texture must be provided" and the soil step died.
# Use the canonical absolute server path so the lookup is cwd-independent; a
# caller may still override via argv[3].
HWSD_RASTER = "KISSPATH_STATIC/HWSD_RASTER/hwsd.bil"
HWSD_MDB = "data/forcing/huaihe_raw/soil/HWSD.mdb"

# Manual override: provide texture directly if HWSD not available
SAND_PCT = None  # override: sand percentage
CLAY_PCT = None  # override: clay percentage
SILT_PCT = None  # override: silt percentage
OC_PCT = None    # override: organic carbon percentage
BULK_DENSITY = None  # override: g/cm3


def validate_inputs():
    errors = []
    if LAT is None or LON is None:
        errors.append("LAT and LON must be set")
    if LAT is not None and not (-90 <= LAT <= 90):
        errors.append(f"LAT={LAT} out of range [-90, 90]")
    if LON is not None and not (-180 <= LON <= 180):
        errors.append(f"LON={LON} out of range [-180, 180]")

    # Either HWSD files or manual texture must be available
    has_hwsd = Path(HWSD_RASTER).exists() if HWSD_RASTER else False
    has_manual = SAND_PCT is not None and CLAY_PCT is not None
    if not has_hwsd and not has_manual:
        errors.append("Either HWSD raster or manual texture (SAND_PCT, CLAY_PCT) must be provided")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(soil_params):
    errors = []
    # PCSE 6.0: only soil-hydraulic properties belong in soildata (dt_v003).
    required = ["SMW", "SMFCF", "SM0", "CRAIRC", "K0", "SOPE", "KSUB", "RDMSOL"]
    for key in required:
        if key not in soil_params:
            errors.append(f"Missing required key: {key}")

    if soil_params.get("SMW", 0) >= soil_params.get("SMFCF", 0):
        errors.append(f"SMW ({soil_params['SMW']}) must be < SMFCF ({soil_params['SMFCF']})")
    if soil_params.get("SMFCF", 0) >= soil_params.get("SM0", 0):
        errors.append(f"SMFCF ({soil_params['SMFCF']}) must be < SM0 ({soil_params['SM0']})")
    if soil_params.get("SM0", 0) > 0.65:
        errors.append(f"SM0 ({soil_params['SM0']}) > 0.65 (physically impossible porosity)")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def get_texture_from_hwsd(lat, lon):
    """Extract soil texture from HWSD raster + properties CSV.

    KDT 5.0 fix (2026-06-08): the previous implementation imported
    ``skills.dssat_crop_run.hwsd_soil_adapter`` which does NOT exist anywhere on
    the server (verified by tree search) — so the lookup ALWAYS raised
    ImportError and silently fell back to a generic loam (sand=40, clay=25)
    everywhere, regardless of location. That made every site identical and
    defeated the purpose of an HWSD lookup. The canonical HWSD reader is
    ``ki_tools_common.soil_utils.lookup_hwsd`` (rasterio MU_GLOBAL lookup ->
    HWSD_DATA.csv topsoil texture); use it instead. HWSD_MDB is no longer
    needed (the CSV export replaces the Access DB).
    """
    from ki_tools_common.soil_utils import lookup_hwsd
    raster = HWSD_RASTER if Path(HWSD_RASTER).exists() else None
    try:
        props = lookup_hwsd(lat, lon, hwsd_raster=raster)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        # A failed lookup stops the tool; no default texture is used in its place.
        raise RuntimeError(f"HWSD soil lookup failed at lat={lat}, lon={lon}: {e}") from e
    # lookup_hwsd returns sand/silt/clay (%), oc (%), bulk_density (g/cm3)
    # and RAISES when the raster/table cannot be read or the point has no
    # soil; it no longer falls back to generic defaults.
    #
    # dt_v007 (2026-09-12): it ALSO returns props['hydraulics'] — wilting point, field
    # capacity, saturation, ksat — from the shared ki_tools_common lookup. This function
    # used to throw those away and recompute them with a formula that was wrong by ~40%.
    # Carry them through; process() now uses them.
    #
    # 2026-10-15 (codex kiss_sync review): every field this tool USES is read directly, so a
    # missing one stops the tool (lookup_hwsd raises ValueError; process() fails, exit 2) -
    # nothing is caught and no generic soil is put in its place. Bulk density is NOT used on
    # this path (the hydraulics come from texture + OC via the shared saxton_rawls); it is only
    # recorded in the provenance sidecar. When HWSD lacks it, it is recorded as missing (None
    # plus 'bd_status') instead of being read, so a valid texture/OC soil is not refused for
    # an unused field and no stand-in value is written.
    bd_missing = 'bulk_density' in (getattr(props, 'missing_fields', ()) or ()) or 'bulk_density' not in props
    return {
        'sand': props['sand'],
        'clay': props['clay'],
        'silt': props['silt'],
        'oc': props['oc'],
        'bd': None if bd_missing else props['bulk_density'],
        'bd_status': 'missing in HWSD (not used: hydraulics from texture + OC)' if bd_missing else 'HWSD T_REF_BULK_DENSITY',
        'hydraulics': props['hydraulics'],
        'hwsd_component': props['hwsd_component'],
    }


def _legacy_linear_ptf(sand, clay, silt, oc, bd):
    """
    SUPERSEDED 2026-09-12 (dt_v007) — kept only so the history is auditable. NOT CALLED.

    This was documented as "Wosten et al. (1999)". It is not: Wosten's HYPRES functions are
    van Genuchten regressions; this is three ad-hoc linear forms. Measured against an independent
    continuous Saxton & Rawls (2006) across 11 USDA classes, its plant-available water was a
    median 0.58x the reference (range 0.52-0.93x); at the C01 Huai cell 0.56x. The shared
    ki_tools_common lookup, which lookup_hwsd() already returns, measures 0.86x (0.77-1.03x).

    Original (wrong) docstring follows.
    Wosten et al. (1999) pedotransfer functions.
    Convert soil texture to WOFOST hydraulic parameters.

    sand, clay, silt: percentage (0-100)
    oc: organic carbon percentage
    bd: bulk density g/cm3

    Returns dict with SMW, SMFCF, SM0, K0
    """
    om = oc * 1.724  # OC to OM via van Bemmelen factor

    # Wilting point (pF 4.2, ~1500 kPa)
    SMW = 0.001 + 0.26 * (clay / 100.0) + 0.05 * (om / 100.0)

    # Field capacity (pF 2.0, ~10 kPa)
    SMFCF = 0.02 + 0.37 * (clay / 100.0) + 0.15 * (om / 100.0) + 0.10 * (silt / 100.0)

    # Saturation (porosity)
    SM0 = 1.0 - bd / 2.65

    # Saturated hydraulic conductivity (simplified Cosby et al. 1984)
    K0 = 10.0 ** (1.26 - 0.0064 * clay)

    # Clamp to valid ranges
    SMW = max(0.01, min(SMW, 0.50))
    SM0 = max(0.30, min(SM0, 0.62))
    SMFCF = max(SMW + 0.02, min(SMFCF, SM0 - 0.03))
    K0 = max(1.0, min(K0, 100.0))

    return SMW, SMFCF, SM0, K0


def process():
    """Convert HWSD to PCSE soil parameters."""
    # Get texture
    if SAND_PCT is not None and CLAY_PCT is not None:
        sand = SAND_PCT
        clay = CLAY_PCT
        silt = SILT_PCT if SILT_PCT is not None else (100 - sand - clay)
        # 2026-10-15: OC feeds the shared PTF (om = oc x 1.724), so a manual texture without OC
        # stops instead of using a made-up 1.0 %. Bulk density is not used by the PTF: it is
        # recorded as given, or None (no 1.4 placeholder).
        if OC_PCT is None:
            raise ValueError("manual texture (SAND_PCT/CLAY_PCT) needs OC_PCT too: organic carbon feeds "
                             "the pedotransfer function and no default is used")
        oc = OC_PCT
        bd = BULK_DENSITY
        logger.info(f"Using manual texture: sand={sand}%, clay={clay}%, silt={silt}%")
    else:
        texture = get_texture_from_hwsd(LAT, LON)
        sand, clay, silt = texture['sand'], texture['clay'], texture['silt']
        oc, bd = texture['oc'], texture['bd']
        logger.info(f"HWSD texture at ({LAT}, {LON}): sand={sand}%, clay={clay}%, silt={silt}%, OC={oc}%, BD={bd}")

    # Pedotransfer — dt_v007 (2026-09-12): use the SHARED ki_tools_common hydraulics, the same
    # values every other crop KI is meant to use, instead of a private formula that was
    # documented as Wosten (1999) and was not. lookup_hwsd() already computes these; for the
    # manual-texture path we call the same function directly so both paths agree.
    from ki_tools_common.soil_utils import saxton_rawls as _shared_ptf
    hyd = (texture.get('hydraulics') if (SAND_PCT is None or CLAY_PCT is None) else None) \
          or _shared_ptf(sand, clay, om=oc * 1.724)
    SMW   = float(hyd['wilting_point'])
    SMFCF = float(hyd['field_capacity'])
    SM0   = float(hyd['saturation'])
    # UNITS: the shared lookup gives ksat in cm/hr; WOFOST's K0 is cm/DAY. x24, stated here so a
    # silent factor-of-24 cannot hide (the class of mistake this whole investigation is about).
    K0 = float(hyd['ksat_cm_hr']) * 24.0
    _ptf_source = f"ki_tools_common.soil_utils.saxton_rawls (Rawls-1982 class table; class={hyd.get('texture')})"

    # Rootable depth based on texture
    if clay > 60:
        RDMSOL = 80.0
    elif sand > 80:
        RDMSOL = 150.0
    else:
        RDMSOL = 120.0

    # PCSE 6.0: soildata must contain ONLY soil-hydraulic properties. The
    # site-level params (IFUNRN, NOTINF, SSI, SSMAX, WAV, SMLIM) are supplied by
    # WOFOST72SiteDataProvider; including them here raises
    # "Duplicate parameter found" in ParameterProvider (dt_v003).
    # CRAIRC is the critical SOIL AIR CONTENT for aeration stress (typ. ~0.06),
    # NOT the air porosity (SM0-SMFCF, ~0.30). Using air porosity made the crop
    # spuriously oxygen-stressed in wet climates. Use the standard WOFOST value.
    soil_params = {
        'SMW': round(SMW, 4),
        'SMFCF': round(SMFCF, 4),
        'SM0': round(SM0, 4),
        'CRAIRC': 0.06,
        'K0': round(K0, 2),
        'SOPE': 1.0,
        'KSUB': 1.0,
        'RDMSOL': RDMSOL,
    }
    # Provenance goes to a SIDECAR, never into soil_params: this dict is loaded verbatim into
    # PCSE's ParameterProvider(soildata=...), which must hold soil-hydraulic keys only (dt_v003).
    soil_params_provenance = {
        'ptf': _ptf_source,
        'K0_units': 'cm/day (converted from cm/hr x24)',
        'hwsd_component': (texture.get('hwsd_component')
                           if (SAND_PCT is None or CLAY_PCT is None) else 'manual texture'),
        'texture_input': {'sand': sand, 'clay': clay, 'silt': silt, 'oc': oc, 'bd': bd},
        'bd_status': (texture.get('bd_status') if (SAND_PCT is None or CLAY_PCT is None)
                      else ('BULK_DENSITY given' if BULK_DENSITY is not None else 'not given (not used)')),
        'dt': 'dt_v007',
    }
    try:
        _out = os.environ.get('SOIL_PARAMS_JSON') or os.environ.get('OUTPUT_JSON')
        if _out:
            with open(str(_out) + '.provenance.json', 'w') as _f:
                json.dump(soil_params_provenance, _f, indent=2, default=str)
    except Exception as _e:                       # provenance must never break the soil step
        logger.warning(f"could not write provenance sidecar: {_e}")

    logger.info(f"Computed: SMW={SMW:.4f}, SMFCF={SMFCF:.4f}, SM0={SM0:.4f}, K0={K0:.2f}")
    return soil_params


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        LAT = float(sys.argv[1])
        LON = float(sys.argv[2])
    if len(sys.argv) >= 5:
        HWSD_RASTER = sys.argv[3]
        HWSD_MDB = sys.argv[4]

    validate_inputs()

    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    validate_outputs(result)

    print(json.dumps(result, indent=2))
    sys.exit(0)
