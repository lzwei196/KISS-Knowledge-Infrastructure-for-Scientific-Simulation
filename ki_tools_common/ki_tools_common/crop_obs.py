"""
crop_obs.py — Observed crop yield lookup from SPAM2020 for validation.

Provides gridded crop yield observations at any location for model validation.
Used by EPIC, APEX, DSSAT, WOFOST, AquaCrop, RZWQM2, DayCent.

Data source: SPAM 2020 V2r0 (IFPRI)
  - Global 5 arcmin (~10 km) resolution
  - 46 crops, physical area + yield + production
  - Path: KISSPATH_HOME/Crop_model_dataset/dataverse_files/

Usage::

    from ki_tools_common.crop_obs import get_observed_yield

    obs = get_observed_yield(32.9, 117.4, crop='maize')
    # Returns: {'yield_kgha': 5500, 'area_ha': 12000, 'source': 'SPAM2020'}
"""

import os
import warnings
from typing import Dict, Optional

import numpy as np

# SPAM 2020 V2r0 root. The canonical server location is under KISSPATH_DATA;
# older installs symlinked it under KISSPATH_HOME. Pick the first that exists so
# the lookup actually reads SPAM instead of silently falling through to the
# FAOSTAT national-average fallback (verified 2026-06-05).
_SPAM_DIR_CANDIDATES = [
    "KISSPATH_DATA/Crop_model_dataset/dataverse_files",
    "KISSPATH_HOME/Crop_model_dataset/dataverse_files",
]
SPAM_DIR = next((p for p in _SPAM_DIR_CANDIDATES if os.path.isdir(p)),
                _SPAM_DIR_CANDIDATES[0])

# SPAM crop code mapping
SPAM_CROPS = {
    "maize": "MAIZ", "corn": "MAIZ",
    "wheat": "WHEA",
    "rice": "RICE",
    "soybean": "SOYB", "soy": "SOYB",
    "sorghum": "SORG",
    "cotton": "COTT",
    "barley": "BARL",
    "potato": "POTA",
    "cassava": "CASS",
    "sugarcane": "SUGC",
    "millet": "PMIL",
    "groundnut": "GROU", "peanut": "GROU",
    "rapeseed": "RAPE",
    "sunflower": "SUNF",
}

# FAOSTAT fallback values (national averages, approximate)
FAOSTAT_FALLBACK = {
    "maize": {
        "china": 6000, "usa": 11000, "brazil": 5500,
        "india": 3000, "global": 5800,
    },
    "wheat": {
        "china": 5500, "usa": 3200, "brazil": 2800,
        "india": 3500, "global": 3500,
    },
    "rice": {
        "china": 7000, "usa": 8500, "brazil": 6000,
        "india": 3800, "global": 4600,
    },
    "soybean": {
        "china": 1900, "usa": 3300, "brazil": 3400,
        "india": 1000, "global": 2800,
    },
}


def _load_spam_csv(crop, lat, lon):
    """Load yield from SPAM 2020 CSV files."""
    try:
        import zipfile
        import csv
        import io
    except ImportError:
        return None

    spam_code = SPAM_CROPS.get(crop.lower())
    if not spam_code:
        return None

    # SPAM CSV files are in a zip
    csv_zip = os.path.join(SPAM_DIR, "Global_CSV", "spam2020V2r0_global_yield.csv.zip")
    if not os.path.isfile(csv_zip):
        return None

    try:
        with zipfile.ZipFile(csv_zip) as zf:
            # Find the total-technology yield file
            target = f"spam2020V2r0_global_Y_TA.csv"
            matching = [n for n in zf.namelist() if target in n]
            if not matching:
                return None

            with zf.open(matching[0]) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig'))

                best_dist = float('inf')
                best_row = None

                for row in reader:
                    try:
                        x, y = float(row['x']), float(row['y'])
                        dist = (y - lat) ** 2 + (x - lon) ** 2
                        if dist < best_dist and dist < 0.1:  # within ~0.3 degrees
                            best_dist = dist
                            best_row = row
                    except (KeyError, ValueError):
                        continue

                if best_row:
                    yield_col = f"{spam_code}_A"
                    yld = float(best_row.get(yield_col, 0))
                    if yld > 0:
                        # SPAM2020 CSV yields are in metric tons/ha → convert to kg/ha
                        return {'yield_kgha': round(yld * 1000, 0), 'x': float(best_row['x']),
                                'y': float(best_row['y'])}

        return None
    except Exception:
        return None


def _load_spam_geotiff(crop, lat, lon):
    """Load yield from SPAM 2020 GeoTIFF."""
    try:
        import rasterio
    except ImportError:
        return None

    spam_code = SPAM_CROPS.get(crop.lower())
    if not spam_code:
        return None

    # GeoTIFF path pattern
    tif_dir = os.path.join(SPAM_DIR, "Global_Geotiff")
    if not os.path.isdir(tif_dir):
        return None

    # Find yield file
    import glob
    pattern = os.path.join(tif_dir, f"*{spam_code}*Y*TA*.tif")
    matches = glob.glob(pattern)
    if not matches:
        return None

    try:
        with rasterio.open(matches[0]) as src:
            row, col = src.index(lon, lat)
            val = float(src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
            # SPAM2020 V2r0 yield rasters are in metric tons/ha (same as the CSV,
            # see Readme unit field 'mt/ha') -> convert to kg/ha for consistency
            # with _load_spam_csv. Without this the GeoTIFF path (tried first in
            # get_observed_yield) returned ~5.7 instead of 5700.
            if val > 0 and val < 50:
                return {'yield_kgha': round(val * 1000, 0)}
        return None
    except Exception:
        return None


def _get_fallback(crop, lat, lon):
    """Get FAOSTAT fallback yield."""
    crop_lower = crop.lower()
    if crop_lower in ('corn',):
        crop_lower = 'maize'

    defaults = FAOSTAT_FALLBACK.get(crop_lower, {})

    # Determine country from lat/lon (rough)
    if 18 < lat < 55 and 73 < lon < 135:
        country = 'china'
    elif 24 < lat < 50 and -130 < lon < -60:
        country = 'usa'
    elif -34 < lat < 5 and -75 < lon < -35:
        country = 'brazil'
    elif 8 < lat < 37 and 68 < lon < 97:
        country = 'india'
    else:
        country = 'global'

    return defaults.get(country, defaults.get('global', 5000))


def get_observed_yield(lat: float, lon: float, crop: str = 'maize') -> Dict:
    """Look up observed crop yield at a location.

    Tries SPAM2020 GeoTIFF, then CSV, then FAOSTAT fallback.

    Args:
        lat: Latitude
        lon: Longitude
        crop: Crop name

    Returns:
        dict with: yield_kgha, source, crop
    """
    # Try GeoTIFF first (faster for single point)
    result = _load_spam_geotiff(crop, lat, lon)
    if result:
        return {**result, 'source': 'SPAM2020_geotiff', 'crop': crop.lower()}

    # Try CSV
    result = _load_spam_csv(crop, lat, lon)
    if result:
        return {**result, 'source': 'SPAM2020_csv', 'crop': crop.lower()}

    # Fallback
    yld = _get_fallback(crop, lat, lon)
    return {'yield_kgha': yld, 'source': 'FAOSTAT_fallback', 'crop': crop.lower()}


def _load_spam_box(crop, lat_range, lon_range):
    """Native ~5-arcmin SPAM 2020 cells inside a lat/lon box.

    Returns [(x, y, yield_kgha, harvested_area_ha), ...] for every SPAM cell with
    BOTH yield>0 and harvested area>0. All-technology totals: yield from Y_TA.csv
    (t/ha -> kg/ha) and harvested area from H_TA.csv (ha), keyed on the shared
    (x,y) grid. Basis for an area-weighted regional aggregate that mosaics the
    cropland mask at native resolution (added 2026-07-02).
    """
    import zipfile, csv, io
    code = SPAM_CROPS.get(crop.lower())
    if not code:
        return []
    col = f"{code}_A"  # all-technology column in both Y_TA and H_TA
    lat_min, lat_max = float(lat_range[0]), float(lat_range[1])
    lon_min, lon_max = float(lon_range[0]), float(lon_range[1])

    def _read(zip_name, member_key):
        path = os.path.join(SPAM_DIR, "Global_CSV", zip_name)
        out = {}
        if not os.path.isfile(path):
            return out
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if member_key in n]
            if not members:
                return out
            with zf.open(members[0]) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                for row in reader:
                    try:
                        x = float(row["x"]); y = float(row["y"])
                    except (KeyError, ValueError):
                        continue
                    if not (lat_min - 1e-6 <= y <= lat_max + 1e-6 and
                            lon_min - 1e-6 <= x <= lon_max + 1e-6):
                        continue
                    try:
                        v = float(row.get(col, 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    out[(round(x, 4), round(y, 4))] = v
        return out

    ylds = _read("spam2020V2r0_global_yield.csv.zip", "Y_TA.csv")            # t/ha
    hareas = _read("spam2020V2r0_global_harvested_area.csv.zip", "H_TA.csv")  # ha
    cells = []
    for key, yv in ylds.items():
        if yv <= 0:
            continue
        av = hareas.get(key, 0.0)
        if av <= 0:
            continue
        x, y = key
        cells.append((x, y, yv * 1000.0, av))
    return cells


def get_spam_regional_yield(crop: str,
                            lat_range,
                            lon_range,
                            step: float = 0.5) -> Dict:
    """SPAM 2020 regional-aggregate yield for a crop over a lat/lon box.

    SPAM 2020 is a SINGLE-YEAR (2020) gridded SPATIAL product. The AquaCrop dag
    (outputs.DryYield.observability) does NOT list ``spatial_snapshot`` as a
    comparable obs_shape — it lists ``point_snapshot`` (magnitude_accuracy) and
    ``regional_aggregate_time_series``. The scale-comparable, dag-valid move for
    validating a 0-D point crop model against SPAM is therefore to AGGREGATE the
    SPAM gridded yields over a coherent agricultural region to ONE regional-mean
    value, run the model multi-site over the same region/season, aggregate the
    sim to one regional-mean, and compare MAGNITUDE (PBIAS). This helper builds
    the obs side of that workflow (added 2026-06-30; prior SPAM runs had to
    hand-build the multi-site -> regional-mean aggregation because no helper
    existed).

    Reads ONLY the SPAM loaders (geotiff then csv) — it never falls through to
    the FAOSTAT national-average fallback, so the regional mean is not silently
    contaminated by non-SPAM cells.

    Args:
        crop: crop name (see SPAM_CROPS keys: maize, wheat, rice, soybean, ...)
        lat_range: (lat_min, lat_max) inclusive, degrees
        lon_range: (lon_min, lon_max) inclusive, degrees
        step: grid spacing in degrees (default 0.5)

    Returns:
        dict with:
          - ``mean_kgha``: unweighted mean of per-cell SPAM yields (cells with
            crop yield > 0), or None if no cell has the crop
          - ``n_cells``: number of cells with SPAM crop yield > 0
          - ``cells``: list of (lat, lon, yield_kgha) for those cells
          - ``crop``, ``step``, ``lat_range``, ``lon_range``
    """
    lat_min, lat_max = float(lat_range[0]), float(lat_range[1])
    lon_min, lon_max = float(lon_range[0]), float(lon_range[1])
    # Read EVERY native ~5-arcmin SPAM maize cell (yield>0 AND harvested-area>0)
    # inside the box so the aggregate mosaics the cropland mask at native
    # resolution instead of nearest-sampling one cell per coarse grid point.
    native = _load_spam_box(crop, (lat_min, lat_max), (lon_min, lon_max))
    if not native:
        return {'mean_kgha': None, 'area_weighted_mean_kgha': None,
                'unweighted_mean_kgha': None, 'n_cells': 0, 'cells': [],
                'areas': [], 'crop': crop.lower(), 'step': step,
                'lat_range': (lat_min, lat_max), 'lon_range': (lon_min, lon_max)}
    # Bin native cells into coarse `step`-degree boxes. Each box is one HLU
    # representative: its yield is the harvested-area-weighted mean of the native
    # cells in the box; its weight is the summed native maize harvested area (ha).
    boxes = {}
    for x, y, yld, area in native:
        i = int(np.floor((y - lat_min) / step))
        j = int(np.floor((x - lon_min) / step))
        b = boxes.setdefault((i, j), [0.0, 0.0])
        b[0] += yld * area
        b[1] += area
    cells, areas = [], []
    for (i, j), (wy, wa) in sorted(boxes.items()):
        if wa <= 0:
            continue
        clat = round(lat_min + (i + 0.5) * step, 4)
        clon = round(lon_min + (j + 0.5) * step, 4)
        cells.append((clat, clon, wy / wa))
        areas.append(wa)
    # Regional obs mean = harvested-area-weighted over ALL native cells =
    # total production / total harvested area (the true SPAM regional yield).
    tot_wy = sum(yld * area for _, _, yld, area in native)
    tot_wa = sum(area for _, _, _, area in native)
    area_weighted_mean = (tot_wy / tot_wa) if tot_wa > 0 else None
    unweighted_mean = float(np.mean([c[2] for c in cells])) if cells else None
    return {
        'mean_kgha': area_weighted_mean,
        'area_weighted_mean_kgha': area_weighted_mean,
        'unweighted_mean_kgha': unweighted_mean,
        'n_cells': len(cells),
        'cells': cells,
        'areas': areas,
        'crop': crop.lower(),
        'step': step,
        'lat_range': (lat_min, lat_max),
        'lon_range': (lon_min, lon_max),
    }


def get_observed_yield_series(lat: float, lon: float, crop: str = 'maize', years=None) -> Dict:
    """Annual observed yield series from GDHY (Iizumi) 0.5deg gridded product.

    Returns {year: yield_kgha}. UNLIKE get_observed_yield (single-year SPAM scalar),
    this provides a multi-year sample so Pearson r / NSE / KGE are DEFINED (>=2 pairs).
    GDHY files: <root>/<crop>/yield_<YYYY>.nc4, var 'var', dims (lat,lon),
    lon 0-360, units t/ha, fill -9.99e8, coverage 1981-2016.
    """
    import glob
    try:
        import netCDF4 as _nc
        import numpy as _np
    except ImportError:
        return {}
    roots = ['KISSPATH_DATA/Crop_model_dataset/GDHY_v1.2_v1.3']
    root = next((r for r in roots if os.path.isdir(r)), None)
    if root is None:
        return {}
    gmap = {'maize':'maize','corn':'maize','wheat':'wheat','rice':'rice',
            'soybean':'soybean','soy':'soybean'}
    sub = gmap.get(crop.lower())
    if not sub or not os.path.isdir(os.path.join(root, sub)):
        return {}
    cdir = os.path.join(root, sub)
    lon360 = lon % 360.0
    want = set(int(y) for y in years) if years is not None else None
    out = {}
    for f in sorted(glob.glob(os.path.join(cdir, 'yield_*.nc4'))):
        try:
            yr = int(os.path.basename(f).split('_')[1].split('.')[0])
        except (IndexError, ValueError):
            continue
        if want is not None and yr not in want:
            continue
        try:
            d = _nc.Dataset(f)
            latv = d.variables['lat'][:]; lonv = d.variables['lon'][:]
            iy = int(_np.argmin(_np.abs(_np.asarray(latv) - lat)))
            ix = int(_np.argmin(_np.abs(_np.asarray(lonv) - lon360)))
            val = float(d.variables['var'][iy, ix])
            d.close()
        except Exception:
            continue
        if _np.isfinite(val) and 0 < val < 50:
            out[yr] = round(val * 1000.0, 1)  # t/ha -> kg/ha
    return out


# ---------------------------------------------------------------------------
# FAOSTAT national-yield time series (Production_Crops_Livestock bulk download)
# ---------------------------------------------------------------------------
# Unlike GDHY (gridded, 1981-2016) and SPAM (single snapshot year), FAOSTAT
# gives a full 1961-2024 national annual yield series — the canonical reference
# for country-level crop-yield validation. Added 2026-06-06: prior to this the
# only FAOSTAT access was the hard-coded FAOSTAT_FALLBACK dict, which has no
# year axis so NSE/KGE/r against FAOSTAT were undefined.
_FAOSTAT_DIR_CANDIDATES = [
    "KISSPATH_OBS/faostat/Production_Crops_Livestock_E_All_Data",
]
FAOSTAT_DIR = next((p for p in _FAOSTAT_DIR_CANDIDATES if os.path.isdir(p)),
                   _FAOSTAT_DIR_CANDIDATES[0])

# crop alias -> FAOSTAT primary-crop Item label (yield element 5412, unit kg/ha)
FAOSTAT_ITEM = {
    "maize": "Maize (corn)", "corn": "Maize (corn)",
    "wheat": "Wheat",
    "rice": "Rice", "paddy": "Rice",
    "soybean": "Soya beans", "soy": "Soya beans",
    "sorghum": "Sorghum",
    "barley": "Barley",
    "potato": "Potatoes",
    "cotton": "Seed cotton, unginned",
}


def get_faostat_yield_series(crop: str = "maize",
                             country: str = "China, mainland",
                             years=None,
                             units: str = "t/ha") -> Dict:
    """Annual national crop-yield series from the FAOSTAT bulk download.

    Reads ``Production_Crops_Livestock_E_All_Data_NOFLAG.csv`` and returns the
    yield time series (element ``Yield`` = code 5412, native unit kg/ha) for one
    country/crop. This is the canonical country-level validation reference and,
    being multi-year, makes Pearson r / NSE / KGE defined.

    Args:
        crop: crop alias (see FAOSTAT_ITEM). Mapped to the FAOSTAT Item label.
        country: FAOSTAT ``Area`` label exactly as in the file, e.g.
            'China, mainland', 'China', 'United States of America', 'World'.
        years: optional iterable of years to keep (default: all available).
        units: 't/ha' (default) or 'kg/ha'. FAOSTAT stores kg/ha; 't/ha'
            divides by 1000.

    Returns:
        {year:int -> yield:float} in the requested units. Empty dict if the
        file is missing or no matching row is found.
    """
    import csv as _csv
    path = os.path.join(FAOSTAT_DIR,
                        "Production_Crops_Livestock_E_All_Data_NOFLAG.csv")
    if not os.path.isfile(path):
        warnings.warn(f"FAOSTAT file not found: {path}")
        return {}
    item = FAOSTAT_ITEM.get(crop.lower(), crop)
    want = set(int(y) for y in years) if years is not None else None
    div = 1000.0 if units == "t/ha" else 1.0
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = _csv.reader(fh)
        header = next(reader)
        # Year columns are 'Y1961'..'Y2024'; map column index -> year int.
        ycol = {i: int(h[1:]) for i, h in enumerate(header)
                if h.startswith("Y") and h[1:].isdigit()}
        # Locate the key columns by name (robust to layout changes).
        try:
            ai = header.index("Area")
            ii = header.index("Item")
            ei = header.index("Element")
        except ValueError:
            ai, ii, ei = 2, 5, 7  # documented fixed layout fallback
        for row in reader:
            if len(row) <= max(ycol):
                continue
            if row[ai] != country or row[ii] != item or row[ei] != "Yield":
                continue
            for i, yr in ycol.items():
                if want is not None and yr not in want:
                    continue
                cell = row[i].strip()
                if not cell:
                    continue
                try:
                    v = float(cell)
                except ValueError:
                    continue
                if v > 0:
                    out[yr] = round(v / div, 4)
            break
    return out
