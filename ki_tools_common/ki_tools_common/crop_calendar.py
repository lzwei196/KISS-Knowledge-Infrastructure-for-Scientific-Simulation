"""
crop_calendar.py — Crop planting/harvest date lookup from GGCMI and China phenology.

Provides data-driven planting and harvest dates for any location and crop,
replacing hardcoded defaults. Used by EPIC, APEX, DSSAT, WOFOST, AquaCrop,
RZWQM2, DayCent, LDNDC.

Data sources:
  - GGCMI Phase 3 crop calendar (global, 0.5°, ~20 crops)
  - China crop phenology (GeoTIFF, 2000-2019, heading/maturity dates)

Usage::

    from ki_tools_common.crop_calendar import get_planting_harvest

    cal = get_planting_harvest(32.9, 117.4, crop='maize')
    # Returns: {'plant_doy': 152, 'harvest_doy': 274, 'plant_month': 6,
    #           'plant_day': 1, 'harvest_month': 10, 'harvest_day': 1,
    #           'source': 'ggcmi', 'crop': 'maize'}
"""

import os
import warnings
from datetime import datetime, timedelta
from typing import Dict, Optional

import numpy as np

# Data paths
# NOTE (2026-07-01): the coded KISSPATH_HOME/Crop_model_dataset/... path does not
# exist on this server; the GGCMI Phase-3 crop calendars actually live under
# KISSPATH_DATA/Crop_model_dataset/. With the wrong path _load_ggcmi() always
# returned None and get_planting_harvest() silently fell back to the
# hemisphere-UNAWARE latitude-band default (_get_fallback uses abs(lat)), which
# plants Southern-Hemisphere maize in the austral WINTER (e.g. DOY 152 = June) —
# a wrong-season artifact, not a model verdict. Pick the first path that exists
# so real, hemisphere-correct GGCMI dates are used (SA maize -> plant DOY ~285
# Oct, harvest ~124 May; verified).
def _first_existing(paths, default):
    for p in paths:
        if os.path.isdir(p):
            return p
    return default

GGCMI_DIR = _first_existing([
    "KISSPATH_DATA/Crop_model_dataset/GGCMI_phase3_crop_calendar",
    "KISSPATH_HOME/Crop_model_dataset/GGCMI_phase3_crop_calendar",
], "KISSPATH_DATA/Crop_model_dataset/GGCMI_phase3_crop_calendar")
CHINA_PHENOLOGY_DIR = _first_existing([
    "KISSPATH_DATA/Crop_model_dataset/8313530",
    "KISSPATH_HOME/Crop_model_dataset/8313530",
], "KISSPATH_HOME/Crop_model_dataset/8313530")

# GGCMI crop name mapping (file prefix → common name)
GGCMI_CROPS = {
    "maize": "mai", "corn": "mai",
    "wheat": "whe", "winter_wheat": "wwh", "spring_wheat": "swh",
    "rice": "ric",
    "soybean": "soy", "soy": "soy",
    "sorghum": "sor",
    "cotton": "cot",
    "barley": "bar",
    "potato": "pot",
    "cassava": "cas",
    "sugarcane": "sgc",
    "millet": "mil",
    "groundnut": "gro", "peanut": "gro",
    "bean": "bea",
    "rapeseed": "rap",
    "sunflower": "sun",
}

# Fallback defaults by latitude band (when data not available)
FALLBACK_CALENDARS = {
    "maize": {
        (0, 15):   {"plant_doy": 120, "harvest_doy": 270},   # Tropics
        (15, 25):  {"plant_doy": 150, "harvest_doy": 290},   # Subtropical
        (25, 35):  {"plant_doy": 152, "harvest_doy": 274},   # Warm temperate (China summer maize)
        (35, 45):  {"plant_doy": 130, "harvest_doy": 270},   # Temperate (US Corn Belt)
        (45, 60):  {"plant_doy": 140, "harvest_doy": 260},   # Cool temperate
    },
    "wheat": {
        (0, 25):   {"plant_doy": 305, "harvest_doy": 150},   # Tropical winter wheat
        (25, 40):  {"plant_doy": 288, "harvest_doy": 161},   # Warm temp (China winter wheat, Oct→Jun)
        (40, 55):  {"plant_doy": 274, "harvest_doy": 182},   # Temperate
        (55, 65):  {"plant_doy": 100, "harvest_doy": 230},   # Spring wheat (high lat)
    },
    "rice": {
        (0, 20):   {"plant_doy": 152, "harvest_doy": 305},   # Tropical
        (20, 35):  {"plant_doy": 121, "harvest_doy": 274},   # Subtropical (China)
        (35, 45):  {"plant_doy": 130, "harvest_doy": 260},   # Temperate
    },
    "soybean": {
        (0, 25):   {"plant_doy": 305, "harvest_doy": 60},    # Tropical (Brazil)
        (25, 40):  {"plant_doy": 152, "harvest_doy": 274},   # Warm temperate
        (40, 50):  {"plant_doy": 140, "harvest_doy": 270},   # Temperate (US)
    },
}


def _doy_to_monthday(doy, year=2000):
    """Convert day-of-year to (month, day). Handles DOY > 365 for winter crops."""
    doy = int(doy)
    if doy > 365:
        doy = doy - 365  # wrap into next calendar year
    doy = max(1, min(doy, 365))
    dt = datetime(year, 1, 1) + timedelta(days=doy - 1)
    return dt.month, dt.day


def _load_ggcmi(crop, lat, lon, irrigation='rf'):
    """Load planting/harvest from GGCMI NetCDF."""
    try:
        import xarray as xr
    except ImportError:
        return None

    prefix = GGCMI_CROPS.get(crop.lower())
    if not prefix:
        return None

    fname = f"{prefix}_{irrigation}_ggcmi_crop_calendar_phase3_v1.01.nc4"
    path = os.path.join(GGCMI_DIR, fname)

    if not os.path.isfile(path):
        # Try other irrigation types
        for irr in ['rf', 'ir']:
            alt = os.path.join(GGCMI_DIR, f"{prefix}_{irr}_ggcmi_crop_calendar_phase3_v1.01.nc4")
            if os.path.isfile(alt):
                path = alt
                break
        else:
            return None

    try:
        ds = xr.open_dataset(path)
        plant_var = [v for v in ds.data_vars if 'plant' in v.lower()]
        harvest_var = [v for v in ds.data_vars if 'matur' in v.lower() or 'harvest' in v.lower()]

        if not plant_var or not harvest_var:
            ds.close()
            return None

        plant_doy = float(ds[plant_var[0]].sel(lat=lat, lon=lon, method='nearest').values)
        harvest_doy = float(ds[harvest_var[0]].sel(lat=lat, lon=lon, method='nearest').values)
        ds.close()

        if np.isnan(plant_doy) or np.isnan(harvest_doy) or plant_doy <= 0:
            return None

        return {"plant_doy": int(plant_doy), "harvest_doy": int(harvest_doy)}
    except Exception:
        return None


def _load_china_phenology(crop, lat, lon):
    """Load from China crop phenology GeoTIFF."""
    try:
        import rasterio
    except ImportError:
        return None

    # China phenology has: CHN_{Crop}_HE_{year}.tif (heading date)
    # and CHN_{Crop}_MA_{year}.tif (maturity date)
    crop_map = {"maize": "Maize", "corn": "Maize", "wheat": "Wheat", "rice": "Rice"}
    crop_name = crop_map.get(crop.lower())
    if not crop_name:
        return None

    # Use 2010 as reference
    he_path = os.path.join(CHINA_PHENOLOGY_DIR, f"CHN_{crop_name}_HE_2010.tif")
    ma_path = os.path.join(CHINA_PHENOLOGY_DIR, f"CHN_{crop_name}_MA_2010.tif")

    if not os.path.isfile(he_path):
        return None

    try:
        with rasterio.open(he_path) as src:
            row, col = src.index(lon, lat)
            raw = src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0]
            he_nodata = src.nodata
            heading_doy = int(raw)
            if he_nodata is not None and raw == he_nodata:
                return None

        if heading_doy <= 0 or heading_doy > 366:
            return None

        if os.path.isfile(ma_path):
            with rasterio.open(ma_path) as src:
                row, col = src.index(lon, lat)
                raw = src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0]
                ma_nodata = src.nodata
                maturity_doy = int(raw)
                if ma_nodata is not None and raw == ma_nodata:
                    maturity_doy = heading_doy + 30
                elif maturity_doy <= 0 or maturity_doy > 366:
                    maturity_doy = heading_doy + 30
        else:
            maturity_doy = heading_doy + 30

        # Estimate planting from heading (typically heading = plant + 60-90 days)
        plant_doy = max(1, heading_doy - 75)

        return {"plant_doy": plant_doy, "harvest_doy": maturity_doy}
    except Exception:
        return None


def _get_fallback(crop, lat):
    """Get fallback calendar from latitude defaults."""
    crop_lower = crop.lower()
    if crop_lower in ('corn',):
        crop_lower = 'maize'

    defaults = FALLBACK_CALENDARS.get(crop_lower, FALLBACK_CALENDARS.get('maize'))
    if not defaults:
        return {"plant_doy": 120, "harvest_doy": 270}

    abs_lat = abs(lat)
    for (min_lat, max_lat), cal in sorted(defaults.items()):
        if min_lat <= abs_lat < max_lat:
            return cal

    # Closest match
    return list(defaults.values())[0]


def get_planting_harvest(lat: float, lon: float, crop: str = 'maize',
                         irrigation: str = 'rf') -> Dict:
    """Look up planting and harvest dates for a crop at a location.

    Tries sources in order: China phenology (if in China), GGCMI, fallback defaults.

    Args:
        lat: Latitude (degrees, positive N)
        lon: Longitude (degrees, positive E)
        crop: Crop name (maize/corn, wheat, rice, soybean, sorghum, cotton, etc.)
        irrigation: 'rf' (rainfed) or 'ir' (irrigated) for GGCMI

    Returns:
        dict with: plant_doy, harvest_doy, plant_month, plant_day,
                   harvest_month, harvest_day, source, crop
    """
    result = None
    source = 'fallback'

    # Try China phenology first for Chinese locations
    if 18 < lat < 55 and 73 < lon < 135:
        result = _load_china_phenology(crop, lat, lon)
        if result:
            source = 'china_phenology'

    # Try GGCMI
    if result is None:
        result = _load_ggcmi(crop, lat, lon, irrigation)
        if result:
            source = 'ggcmi'

    # Fallback
    if result is None:
        result = _get_fallback(crop, lat)
        source = 'fallback'

    plant_doy = result['plant_doy']
    harvest_doy = result['harvest_doy']

    plant_month, plant_day = _doy_to_monthday(plant_doy)
    harvest_month, harvest_day = _doy_to_monthday(harvest_doy)

    return {
        'plant_doy': plant_doy,
        'harvest_doy': harvest_doy,
        'plant_month': plant_month,
        'plant_day': plant_day,
        'harvest_month': harvest_month,
        'harvest_day': harvest_day,
        'source': source,
        'crop': crop.lower(),
    }


def list_available_crops():
    """List crops available in GGCMI."""
    available = []
    if os.path.isdir(GGCMI_DIR):
        for f in os.listdir(GGCMI_DIR):
            if f.endswith('.nc4'):
                prefix = f.split('_')[0]
                name = next((k for k, v in GGCMI_CROPS.items() if v == prefix), prefix)
                if name not in available:
                    available.append(name)
    return sorted(available)
