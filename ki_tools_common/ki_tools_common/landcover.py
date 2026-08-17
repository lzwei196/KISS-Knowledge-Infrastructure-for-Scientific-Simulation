"""
landcover.py — Land cover classification crosswalks.

IGBP, USGS, and MODIS classification systems use DIFFERENT numbering for the
same land cover types. Directly using raster pixel values as model class indices
causes silent misclassification (cm_029).

Example: AVHRR uses IGBP (class 12 = Cropland). SUMMA's VEGPARM.TBL uses USGS
(class 12 = Ice). Passing IGBP values to a USGS-based model treats 74% of the
Bengbu basin as ice instead of cropland.

Usage::

    from ki_tools_common.landcover import igbp_to_usgs, igbp_to_modis

    usgs_class = igbp_to_usgs(12)   # IGBP Cropland → USGS 2 (Dryland Crop)
    modis_class = igbp_to_modis(12)  # IGBP Cropland → MODIS 12 (Cropland)
"""

# IGBP-DIS classification (used by AVHRR 1km, GlobCover, MCD12Q1 Type 1)
IGBP_NAMES = {
    0: "Water Bodies",
    1: "Evergreen Needleleaf Forest",
    2: "Evergreen Broadleaf Forest",
    3: "Deciduous Needleleaf Forest",
    4: "Deciduous Broadleaf Forest",
    5: "Mixed Forests",
    6: "Closed Shrublands",
    7: "Open Shrublands",
    8: "Woody Savannas",
    9: "Savannas",
    10: "Grasslands",
    11: "Permanent Wetlands",
    12: "Croplands",
    13: "Urban and Built-up",
    14: "Cropland/Natural Vegetation Mosaic",
    15: "Snow and Ice",
    16: "Barren or Sparsely Vegetated",
}

# USGS 24-category (used by WRF, SUMMA VEGPARM.TBL, WRF-Hydro)
USGS_NAMES = {
    1: "Urban and Built-up Land",
    2: "Dryland Cropland and Pasture",
    3: "Irrigated Cropland and Pasture",
    4: "Mixed Dryland/Irrigated Cropland",
    5: "Cropland/Grassland Mosaic",
    6: "Cropland/Woodland Mosaic",
    7: "Grassland",
    8: "Shrubland",
    9: "Mixed Shrubland/Grassland",
    10: "Savanna",
    11: "Deciduous Broadleaf Forest",
    12: "Deciduous Needleleaf Forest",
    13: "Evergreen Broadleaf Forest",
    14: "Evergreen Needleleaf Forest",
    15: "Mixed Forest",
    16: "Water Bodies",
    17: "Herbaceous Wetland",
    18: "Wooded Wetland",
    19: "Barren or Sparsely Vegetated",
    20: "Herbaceous Tundra",
    21: "Wooded Tundra",
    22: "Mixed Tundra",
    23: "Bare Ground Tundra",
    24: "Snow or Ice",
}

# IGBP → USGS crosswalk (verified against WRF/WPS documentation)
_IGBP_TO_USGS = {
    0: 16,   # Water → Water
    1: 14,   # ENF → ENF
    2: 13,   # EBF → EBF
    3: 12,   # DNF → DNF
    4: 11,   # DBF → DBF
    5: 15,   # Mixed Forest → Mixed Forest
    6: 8,    # Closed Shrub → Shrubland
    7: 9,    # Open Shrub → Mixed Shrub/Grass
    8: 10,   # Woody Savanna → Savanna
    9: 10,   # Savanna → Savanna
    10: 7,   # Grassland → Grassland
    11: 17,  # Wetland → Herbaceous Wetland
    12: 2,   # Cropland → Dryland Crop
    13: 1,   # Urban → Urban
    14: 5,   # Crop/Veg Mosaic → Crop/Grass Mosaic
    15: 24,  # Snow/Ice → Snow/Ice
    16: 19,  # Barren → Barren
}

# IGBP → MODIS "MODIFIED_IGBP_MODIS_NOAH" (the 20-class table Noah-MP/SUMMA read).
#
# Classes 1-16 are numerically identical to IGBP, which is why this was long
# written as a bare identity map. Class 0 is NOT: IGBP numbers water 0, but the
# Noah-MP table is 1-based with ISWATER = 17 (MPTABLE.TBL
# &noah_mp_modis_veg_categories, NVEG = 20). Returning 0 hands SUMMA a
# vegTypeIndex outside 1..NVEG, which indexes the LAIM/HVT arrays out of bounds
# instead of raising.
_IGBP_TO_MODIS = {0: 17}
_IGBP_TO_MODIS.update({i: i for i in range(1, 17)})


def igbp_to_usgs(igbp_class, nodata=255):
    """Convert IGBP class number to USGS 24-category.

    Args:
        igbp_class: int or array-like of IGBP class numbers (0-16)
        nodata: NoData value in input (default 255). Pixels with this value,
                negative values, or values > 16 are preserved as nodata in output.

    Returns:
        USGS class number(s) (1-24). NoData pixels retain the nodata value.

    Note:
        Output may contain NoData values that must be handled downstream
        (e.g., masked before passing to model parameter tables).
    """
    try:
        import numpy as np
        if isinstance(igbp_class, (np.ndarray, list)):
            arr = np.asarray(igbp_class, dtype=int)
            # Identify NoData: explicit nodata value, negative, or out of IGBP range
            nodata_mask = (arr == nodata) | (arr < 0) | (arr > 16)
            result = np.zeros_like(arr)
            for igbp, usgs in _IGBP_TO_USGS.items():
                result[arr == igbp] = usgs
            # Unmapped valid pixels (should not exist if IGBP 0-16 covers all) → Barren
            unmapped = (result == 0) & ~nodata_mask
            result[unmapped] = 19
            # Restore NoData
            result[nodata_mask] = nodata
            return result
    except ImportError:
        pass
    if int(igbp_class) == nodata or int(igbp_class) < 0 or int(igbp_class) > 16:
        return nodata
    return _IGBP_TO_USGS.get(int(igbp_class), 19)


def igbp_to_modis(igbp_class, nodata=255):
    """Convert IGBP class number to the MODIFIED_IGBP_MODIS_NOAH 20-category table.

    Classes 1-16 pass through unchanged; only water is renumbered (IGBP 0 →
    MODIS 17 = ISWATER). The identity shortcut this function used to be leaked
    class 0 into SUMMA, where the Noah-MP LAIM/HVT arrays are indexed 1..NVEG.

    Args:
        igbp_class: int or array-like of IGBP class numbers (0-16)
        nodata: NoData value in input (default 255). Pixels with this value,
                negative values, or values > 16 are preserved as nodata in output.

    Returns:
        MODIS class number(s) (1-17). NoData pixels retain the nodata value.
    """
    try:
        import numpy as np
        if isinstance(igbp_class, (np.ndarray, list)):
            arr = np.asarray(igbp_class, dtype=int)
            nodata_mask = (arr == nodata) | (arr < 0) | (arr > 16)
            result = np.zeros_like(arr)
            for igbp, modis in _IGBP_TO_MODIS.items():
                result[arr == igbp] = modis
            result[nodata_mask] = nodata
            return result
    except ImportError:
        pass
    if int(igbp_class) == nodata or int(igbp_class) < 0 or int(igbp_class) > 16:
        return nodata
    return _IGBP_TO_MODIS[int(igbp_class)]


def usgs_to_igbp(usgs_class, nodata=255):
    """Convert USGS 24-category to IGBP (approximate reverse mapping).

    WARNING: This mapping is LOSSY. USGS has 24 classes but IGBP only 17.
    Ambiguous mappings:
      - USGS 2/3/4 (Dryland/Irrigated/Mixed Crop) all → IGBP 12 (Cropland)
      - USGS 5/6 (Crop/Grass, Crop/Woodland Mosaic) → IGBP 14 (Crop/Veg Mosaic)
      - USGS 20-23 (Tundra variants) → IGBP 16 (Barren) — no tundra in IGBP
      - USGS 17/18 (Herbaceous/Wooded Wetland) both → IGBP 11 (Wetland)

    Use igbp_to_usgs() for the forward (lossless) direction.
    """
    _reverse = {v: k for k, v in _IGBP_TO_USGS.items()}
    try:
        import numpy as np
        if isinstance(usgs_class, (np.ndarray, list)):
            arr = np.asarray(usgs_class, dtype=int)
            result = np.zeros_like(arr)
            for usgs, igbp in _reverse.items():
                result[arr == usgs] = igbp
            return result
    except ImportError:
        pass
    return _reverse.get(int(usgs_class), 16)


def get_canopy_height(usgs_class):
    """Return typical canopy height (m) for USGS class. Useful for sanity checks.

    If cropland gets 20m canopy height, the land cover mapping is wrong.
    """
    _heights = {
        1: 10, 2: 0.5, 3: 0.5, 4: 0.5, 5: 1.0, 6: 3.0, 7: 0.3,
        8: 1.0, 9: 0.5, 10: 5.0, 11: 20.0, 12: 15.0, 13: 25.0,
        14: 20.0, 15: 18.0, 16: 0, 17: 0.5, 18: 10.0, 19: 0.05,
        20: 0.1, 21: 3.0, 22: 1.0, 23: 0.05, 24: 0,
    }
    return _heights.get(int(usgs_class), 0.5)
