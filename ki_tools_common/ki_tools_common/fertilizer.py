"""
fertilizer.py — Fertilizer application rate lookup from NPKGRIDS.

Provides data-driven N/P/K application rates for any location and crop.
Used by EPIC, APEX, DSSAT, WOFOST, AquaCrop, RZWQM2, DayCent, LDNDC.

Data source: NPKGRIDS v1.08 (Nguyen et al. 2024)
  - Global 5 arcmin resolution
  - N/P/K application rates per crop (kg/ha/yr)
  - Path: KISSPATH_HOME/Crop_model_dataset/24616050/

Usage::

    from ki_tools_common.fertilizer import get_fertilizer_rates

    fert = get_fertilizer_rates(32.9, 117.4, crop='maize')
    # Returns: {'n_kgha': 180, 'p_kgha': 35, 'k_kgha': 45,
    #           'source': 'npkgrids', 'crop': 'maize'}
"""

import os
import warnings
from typing import Dict, Optional

import numpy as np

# NPKGRIDS lives on the shared dataset mount. The original hard-coded
# KISSPATH_HOME/Crop_model_dataset path does not exist on this host, so every
# lookup returned None and get_fertilizer_rates() silently fell back to the
# generic FALLBACK_N_RATES table (source='fallback') — gridded crop-specific
# fertilizer data was on disk but never used. Resolve over candidates.
_NPKGRIDS_DIR_CANDIDATES = [
    "KISSPATH_DATA/Crop_model_dataset/24616050",
    "KISSPATH_HOME/Crop_model_dataset/24616050",
]
NPKGRIDS_DIR = next(
    (p for p in _NPKGRIDS_DIR_CANDIDATES if os.path.isdir(p)),
    _NPKGRIDS_DIR_CANDIDATES[0],
)

# NPKGRIDS file naming: NPKGRIDSv1.08_{crop}.nc
NPKGRIDS_CROPS = {
    "maize": "maize", "corn": "maize",
    "wheat": "wheat",
    "rice": "rice",
    "soybean": "soybean", "soy": "soybean",
    "sorghum": "sorghum",
    "cotton": "cotton",
    "barley": "barley",
    "potato": "potato",
    "cassava": "cassava",
    "sugarcane": "sugarcane",
    "millet": "millet",
    "groundnut": "groundnut", "peanut": "groundnut",
    "rapeseed": "rapeseed",
    "sunflower": "sunflower",
}

# Fallback N rates by crop (kg/ha) when NPKGRIDS not available
FALLBACK_N_RATES = {
    "maize": 150, "corn": 150,
    "wheat": 120,
    "rice": 120,
    "soybean": 20, "soy": 20,  # legume — low N
    "sorghum": 80,
    "cotton": 100,
    "barley": 80,
    "potato": 150,
    "sugarcane": 100,
    "pasture": 0,
    "alfalfa": 0,  # legume
}


def _sample_npkgrids(ds, lat, lon):
    """Sample N/P/K at a single point. Returns dict or None if all zero/missing."""
    # NPKGRIDS v1.08 variables: Nrate (kg-N/ha), P2O5rate (kg-P2O5/ha), K2Orate (kg-K2O/ha)
    # Convert P2O5 → elemental P (×0.4364), K2O → elemental K (×0.8302)
    var_map = {
        'n_kgha':  ('Nrate', 1.0),
        'p_kgha':  ('P2O5rate', 0.4364),   # P2O5 → P
        'k_kgha':  ('K2Orate', 0.8302),    # K2O → K
    }

    result = {}
    for key, (var_name, factor) in var_map.items():
        if var_name not in ds.data_vars:
            continue
        try:
            val = float(ds[var_name].sel(lat=lat, lon=lon, method='nearest').values)
            if not np.isnan(val) and val > 0:
                result[key] = round(val * factor, 1)
        except Exception:
            pass

    return result if result else None


def _load_npkgrids(crop, lat, lon):
    """Load N/P/K from NPKGRIDS NetCDF. Searches neighbors if center cell is empty."""
    try:
        import xarray as xr
    except ImportError:
        return None

    crop_file = NPKGRIDS_CROPS.get(crop.lower())
    if not crop_file:
        return None

    path = os.path.join(NPKGRIDS_DIR, f"NPKGRIDSv1.08_{crop_file}.nc")
    if not os.path.isfile(path):
        return None

    try:
        ds = xr.open_dataset(path)

        # Try exact point first
        result = _sample_npkgrids(ds, lat, lon)

        # If center cell is empty, search neighbors (5 arcmin ≈ 0.083°)
        if result is None:
            step = 0.0833
            for dlat in [-step, 0, step]:
                for dlon in [-step, 0, step]:
                    if dlat == 0 and dlon == 0:
                        continue
                    result = _sample_npkgrids(ds, lat + dlat, lon + dlon)
                    if result:
                        break
                if result:
                    break

        ds.close()
        return result
    except Exception:
        return None


def get_fertilizer_rates(lat: float, lon: float, crop: str = 'maize') -> Dict:
    """Look up N/P/K fertilizer application rates for a crop at a location.

    Tries NPKGRIDS first, falls back to crop-type defaults.

    Args:
        lat: Latitude (degrees)
        lon: Longitude (degrees)
        crop: Crop name

    Returns:
        dict with: n_kgha, p_kgha, k_kgha, source, crop
    """
    result = _load_npkgrids(crop, lat, lon)
    source = 'npkgrids' if result else 'fallback'

    if result is None:
        crop_lower = crop.lower()
        if crop_lower in ('corn',):
            crop_lower = 'maize'
        n_rate = FALLBACK_N_RATES.get(crop_lower, 100)
        result = {
            'n_kgha': n_rate,
            'p_kgha': round(n_rate * 0.25, 1),  # typical P:N ratio
            'k_kgha': round(n_rate * 0.3, 1),   # typical K:N ratio
        }

    result.setdefault('n_kgha', 100)
    result.setdefault('p_kgha', 25)
    result.setdefault('k_kgha', 30)
    result['source'] = source
    result['crop'] = crop.lower()

    return result


def get_split_schedule(n_total_kgha: float, crop: str = 'maize',
                       plant_doy: int = 150) -> list:
    """Generate a split fertilizer application schedule.

    Most crops need split N application for efficiency.

    Returns:
        list of dicts: [{'doy': 150, 'n_kgha': 60, 'type': 'at_planting'},
                        {'doy': 180, 'n_kgha': 90, 'type': 'sidedress'}]
    """
    crop_lower = crop.lower()

    if crop_lower in ('soybean', 'soy', 'groundnut', 'peanut', 'alfalfa', 'bean'):
        # Legumes: minimal N, all at planting
        return [{'doy': plant_doy, 'n_kgha': n_total_kgha, 'type': 'at_planting'}]

    if crop_lower in ('wheat', 'winter_wheat'):
        # Winter wheat: split 3 ways (fall, spring greenup, heading)
        return [
            {'doy': plant_doy, 'n_kgha': round(n_total_kgha * 0.3, 1), 'type': 'at_planting'},
            {'doy': 75, 'n_kgha': round(n_total_kgha * 0.4, 1), 'type': 'spring_greenup'},
            {'doy': 120, 'n_kgha': round(n_total_kgha * 0.3, 1), 'type': 'heading'},
        ]

    if crop_lower in ('rice',):
        # Rice: split 3 ways (basal, tillering, panicle)
        return [
            {'doy': plant_doy, 'n_kgha': round(n_total_kgha * 0.4, 1), 'type': 'basal'},
            {'doy': plant_doy + 25, 'n_kgha': round(n_total_kgha * 0.3, 1), 'type': 'tillering'},
            {'doy': plant_doy + 60, 'n_kgha': round(n_total_kgha * 0.3, 1), 'type': 'panicle'},
        ]

    # Default (maize, sorghum, cotton): split 2 ways
    return [
        {'doy': plant_doy, 'n_kgha': round(n_total_kgha * 0.4, 1), 'type': 'at_planting'},
        {'doy': plant_doy + 30, 'n_kgha': round(n_total_kgha * 0.6, 1), 'type': 'sidedress'},
    ]
