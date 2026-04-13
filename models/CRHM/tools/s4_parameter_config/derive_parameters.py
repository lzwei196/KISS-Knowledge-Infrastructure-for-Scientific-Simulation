#!/usr/bin/env python3
"""
derive_parameters.py — Derive CRHM parameters from global datasets.

Instead of using hardcoded defaults, this tool derives physically-based
parameter values for each HRU from:
  - HWSD soil database → soil_type, soil_moist_max, soil_rechr_max, gw_max
  - DEM slope analysis → Sdmax (depression storage), route_S0, hru_GSL
  - Land cover → fetch, Ht (already in hru_config from S1)
  - Basin geometry → route_L, order, whereto

CRHM's GreenAmpt module internally derives Ksat from soil_type using its
built-in soilproperties[][] table (GlobalDll.h), so we do NOT need to
compute Ksat — just provide the correct soil_type index.

CRHM soil_type mapping (from ClassGreenAmpt.cpp declparam):
  0=water, 1=sand, 2=loamsand, 3=sandloam, 4=loam, 5=siltloam,
  6=saclloam, 7=clayloam, 8=siclloam, 9=sandclay, 10=siltclay,
  11=clay, 12=pavement

CRHM SetSoilproperties[] (available water per 1m depth, from GlobalDll.h):
  soil_type  avail(mm/m)  wilt(mm/m)  field(mm/m)  pore(mm/m)
  1 sand       84          40          124          395
  2 loamsand   80          60          140          410
  3 sandloam  130         100          230          435
  4 loam      157         110          267          451
  5 siltloam  162         130          292          485
  6 saclloam  170         140          310          420
  7 clayloam  167         150          317          476
  8 siclloam  168         150          318          477
  9 sandclay  140         150          290          426
  10 siltclay 145         160          305          492
  11 clay     133         170          303          482

Usage:
    python derive_parameters.py \\
        --hru_config outputs/<run>/crhm/hru/hru_config.json \\
        --output outputs/<run>/crhm/derived_params.json
"""
import argparse
import json
import sys
import os
import warnings
import numpy as np

sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")

# CRHM SetSoilproperties from GlobalDll.h: [avail, wilt, field, pore] in mm per 1m depth
CRHM_SOIL = {
    0: {'avail': 1000, 'wilt': 0, 'field': 1000, 'pore': 1000, 'name': 'water'},
    1: {'avail': 84, 'wilt': 40, 'field': 124, 'pore': 395, 'name': 'sand'},
    2: {'avail': 80, 'wilt': 60, 'field': 140, 'pore': 410, 'name': 'loamsand'},
    3: {'avail': 130, 'wilt': 100, 'field': 230, 'pore': 435, 'name': 'sandloam'},
    4: {'avail': 157, 'wilt': 110, 'field': 267, 'pore': 451, 'name': 'loam'},
    5: {'avail': 162, 'wilt': 130, 'field': 292, 'pore': 485, 'name': 'siltloam'},
    6: {'avail': 170, 'wilt': 140, 'field': 310, 'pore': 420, 'name': 'saclloam'},
    7: {'avail': 167, 'wilt': 150, 'field': 317, 'pore': 476, 'name': 'clayloam'},
    8: {'avail': 168, 'wilt': 150, 'field': 318, 'pore': 477, 'name': 'siclloam'},
    9: {'avail': 140, 'wilt': 150, 'field': 290, 'pore': 426, 'name': 'sandclay'},
    10: {'avail': 145, 'wilt': 160, 'field': 305, 'pore': 492, 'name': 'siltclay'},
    11: {'avail': 133, 'wilt': 170, 'field': 303, 'pore': 482, 'name': 'clay'},
    12: {'avail': 0, 'wilt': 0, 'field': 0, 'pore': 0, 'name': 'pavement'},
}

# Map USDA texture class names to CRHM soil_type index
USDA_TO_CRHM = {
    'sand': 1, 'loamy sand': 2, 'loamy_sand': 2,
    'sandy loam': 3, 'sandy_loam': 3,
    'loam': 4,
    'silt loam': 5, 'silt_loam': 5, 'silty loam': 5,
    'sandy clay loam': 6, 'sandy_clay_loam': 6,
    'clay loam': 7, 'clay_loam': 7,
    'silty clay loam': 8, 'silty_clay_loam': 8,
    'sandy clay': 9, 'sandy_clay': 9,
    'silty clay': 10, 'silty_clay': 10,
    'clay': 11,
    'silt': 5,  # map silt to silt loam (closest)
}

# Rooting depth by land cover (m)
ROOTING_DEPTH = {
    'open_prairie': 0.5,
    'grassland': 0.5,
    'cropland': 0.8,
    'shrub': 0.8,
    'deciduous_forest': 1.5,
    'coniferous_forest': 1.0,
    'mixed_forest': 1.2,
    'alpine': 0.3,
    'bare': 0.2,
    'water': 0.0,
    'wetland': 0.3,
}


def lookup_soil_type(lat, lon):
    """Get CRHM soil_type index from HWSD."""
    try:
        from ki_tools_common.soil_utils import lookup_hwsd
        soil = lookup_hwsd(lat, lon)
        if soil and 'texture' in soil:
            texture = soil['texture'].lower().strip()
            crhm_type = USDA_TO_CRHM.get(texture, 4)  # default loam
            return crhm_type, soil
        return 4, soil  # default loam
    except Exception as e:
        warnings.warn(f"HWSD lookup failed at ({lat}, {lon}): {e}")
        return 4, {}  # default loam


def derive_soil_params(soil_type, land_cover, mean_elevation_m=0, slope_deg=10,
                       depth_to_bedrock_m=None):
    """Derive soil parameters from CRHM soil_type + landscape.

    Method follows Fang et al. (2013) HESS paper — Marmot Creek setup:
    - soil_rechr_max = porosity × recharge_layer_depth (shallow topsoil)
    - soil_moist_max = porosity × total_soil_depth (recharge + lower layers)
    - gw_max = groundwater storage from hydrogeology (~500mm for Rockies)
    - Sdmax = depression storage (0 for steep mountain, >0 for prairie)

    Reference values from Fang et al. (2013) Table 2:
      Alpine rocks/forest: soil_rechr_max=250, soil_moist_max=550, gw_max=500
      Subalpine forest:    soil_rechr_max=250, soil_moist_max=425, gw_max=500
      Valley/confluence:   soil_rechr_max=250, soil_moist_max=750, gw_max=500

    The key insight: CRHM soil storage is porosity × depth, NOT available
    water (field_cap - wilting_point) × depth. Available water is what plants
    can extract; soil storage is total pore space that holds water.
    """
    props = CRHM_SOIL.get(soil_type, CRHM_SOIL[4])
    porosity = props['pore'] / 1000.0  # convert mm/m to fraction (e.g., 0.410)

    # --- Soil depth by landscape (from field studies) ---
    # Mountain soils are thin at high elevation, deeper in valleys
    # Fang et al.: alpine ~0.5-1.0m, subalpine ~0.8-1.2m, valley ~1.5-2.0m
    SOIL_DEPTH = {
        'alpine': 0.5, 'bare': 0.3,
        'open_prairie': 1.0, 'grassland': 1.0,
        'cropland': 1.2, 'shrub': 0.8,
        'coniferous_forest': 1.0, 'deciduous_forest': 1.2,
        'mixed_forest': 1.1, 'wetland': 0.5, 'water': 0.0,
    }
    soil_depth = SOIL_DEPTH.get(land_cover, 1.0)

    # Elevation adjustment: thinner soils at higher elevation
    if mean_elevation_m > 2500:
        soil_depth *= 0.5  # alpine/rock
    elif mean_elevation_m > 2000:
        soil_depth *= 0.7  # subalpine
    elif mean_elevation_m > 1500:
        soil_depth *= 0.85  # montane

    if depth_to_bedrock_m is not None:
        soil_depth = min(soil_depth, depth_to_bedrock_m)

    # --- Recharge layer (upper ~0.3-0.5m, Fang: 250mm for all HRUs) ---
    rechr_depth = min(0.5, soil_depth)
    soil_rechr_max = porosity * rechr_depth * 1000  # mm
    soil_rechr_max = max(30, min(soil_rechr_max, 350))  # CRHM range

    # --- Total soil moisture (recharge + lower layers) ---
    # Fang: 425-750mm depending on landscape
    soil_moist_max = porosity * soil_depth * 1000  # mm
    soil_moist_max = max(100, min(soil_moist_max, 5000))

    # Ensure soil_rechr_max <= soil_moist_max (CRHM requirement)
    soil_rechr_max = min(soil_rechr_max, soil_moist_max)

    # --- Initial conditions (start near field capacity for cold start) ---
    soil_moist_init = soil_moist_max * 0.5
    soil_rechr_init = soil_rechr_max * 0.5

    # --- Groundwater storage ---
    # Fang et al.: 500mm for Canadian Rockies (from basin hydrogeology)
    # Scale by landscape: deeper GW in valleys, shallower on ridges
    GW_BASE = {
        'alpine': 200, 'bare': 100,
        'open_prairie': 500, 'grassland': 500,
        'cropland': 500, 'shrub': 300,
        'coniferous_forest': 400, 'deciduous_forest': 500,
        'mixed_forest': 450, 'wetland': 300, 'water': 0,
    }
    gw_max = GW_BASE.get(land_cover, 400)
    if mean_elevation_m > 2500:
        gw_max *= 0.5  # thin regolith at high elevation

    # --- Depression storage ---
    # Fang et al.: 0mm for Marmot Creek (steep mountain, no depressions)
    # Prairie: 50-200mm (potholes). Flat valley: 20-50mm
    if slope_deg > 15:
        Sdmax = 0  # steep — no depressions
    elif slope_deg > 5:
        Sdmax = max(0, 30 - slope_deg * 2)
    else:
        # Flat terrain — depends on landscape
        Sdmax = {'open_prairie': 100, 'grassland': 50, 'wetland': 200,
                 'cropland': 30, 'bare': 10}.get(land_cover, 20)

    return {
        'soil_type': soil_type,
        'soil_moist_max': round(soil_moist_max, 1),
        'soil_rechr_max': round(soil_rechr_max, 1),
        'soil_moist_init': round(soil_moist_init, 1),
        'soil_rechr_init': round(soil_rechr_init, 1),
        'gw_max': round(gw_max, 1),
        'gw_init': 0.0,  # cold start
    }


def derive_depression_storage(slope_deg, land_cover):
    """Estimate Sdmax from slope and land cover.

    Flat terrain has more depressions; steep terrain sheds water quickly.
    Prairie potholes have large depression storage; forests less.
    """
    # Base: 20mm for 10° slope, increases for flat, decreases for steep
    base = max(0, 100 - slope_deg * 8)

    # Land cover adjustment
    lc_factor = {
        'open_prairie': 1.5,  # prairie potholes
        'grassland': 1.2,
        'cropland': 0.8,  # drained
        'wetland': 3.0,
        'alpine': 0.3,  # steep, rocky
        'coniferous_forest': 0.5,
        'deciduous_forest': 0.6,
        'bare': 0.4,
    }
    factor = lc_factor.get(land_cover, 1.0)
    return round(max(0, base * factor), 1)


def derive_obs_params(hrus, forcing_source='nasa_power', forcing_elev_m=None):
    """Derive obs module parameters from HRU config and forcing metadata.

    Based on Fang et al. (2013): temperature lapse rate 0.75°C/100m,
    precipitation adjusted by "observed seasonal gradients from several
    years of observations at multiple elevations."

    Args:
        hrus: list of HRU dicts from hru_config.json
        forcing_source: 'nasa_power', 'cmfd', 'mswx', or 'station'
        forcing_elev_m: elevation of the forcing data grid point (m)

    Returns dict with per-HRU arrays for obs module parameters.
    """
    n = len(hrus)

    # obs_elev: elevation of the observation/forcing data reference point
    # CRHM uses elev_diff = hru_elev - obs_elev for lapse rate and precip adjustment.
    # Fang et al. (2013): obs_elev = lowest station elevation (1900m for Marmot Creek).
    # For NASA POWER: use the lowest HRU elevation (valley floor). This way:
    #   - Higher HRUs get colder temperatures (lapse rate cooling) ✓
    #   - Higher HRUs get more precipitation (precip_elev_adj > 0) ✓
    if forcing_elev_m is None:
        forcing_elev_m = min(h['mean_elevation_m'] for h in hrus)

    # Temperature lapse rate: 0.75°C/100m (Fang et al. 2013, standard environmental)
    lapse_rate = [0.75] * n

    # Precipitation elevation adjustment
    # CRHM formula: adjusted_p = p * (1 + precip_elev_adj * elev_diff/100)
    # where elev_diff = hru_elev - obs_elev (in m)
    # Belly River validated values: 0.0005 (alpine), 0.0003 (subalpine), 0.0 (valley)
    # This is ~0.05% per 100m — very gentle gradient
    # Higher HRUs get slightly more precip to account for orographic enhancement
    precip_elev_adj = []
    for h in hrus:
        elev = h.get('mean_elevation_m', 1500)
        if elev > 2500:
            precip_elev_adj.append(0.0005)  # alpine — most adjustment
        elif elev > 2000:
            precip_elev_adj.append(0.0003)  # subalpine
        else:
            precip_elev_adj.append(0.0)     # valley — no adjustment

    # Wind undercatch correction
    # 0=none, 1=Nipher, 2=MacDonald-Alter, 3=Smith-Alter, 4=Kochendorfer
    # For NASA POWER/reanalysis: 0 (already corrected)
    # For station gauges: 3 (Smith-Alter, Umax=9.5 m/s)
    if forcing_source in ('nasa_power', 'cmfd', 'mswx'):
        catchadjust = [0] * n  # reanalysis already bias-corrected
    else:
        catchadjust = [3] * n  # Smith-Alter for station data

    # Snow/rain determination
    # 0=air temperature, 1=ice bulb, 2=Harder
    # Harder method (2) is most physically based but needs specific humidity data.
    # Air temperature method (0) is robust and validated (Belly River: 0).
    snow_rain_determination = [0] * n  # air temperature — robust default

    return {
        'obs_elev': round(forcing_elev_m, 1),  # scalar (NDEFN dimension, not per-HRU)
        'lapse_rate': lapse_rate,
        'precip_elev_adj': precip_elev_adj,
        'catchadjust': catchadjust,
        'snow_rain_determination': snow_rain_determination,
    }


def derive_evap_params(hrus):
    """Derive evaporation module parameters per HRU.

    Fang et al. (2013) §12: Granger evaporation for unsaturated surfaces,
    Priestley-Taylor for saturated surfaces (stream channels, wetlands).
    Vegetation height from site observations (§3.2.3).

    Source: ClassEvap.cpp — evap_type: 0=Granger, 1=P-T, 2=Penman-Monteith
    """
    n = len(hrus)
    evap_type = []
    Ht = []
    F_Qg = []

    for h in hrus:
        lc = h.get('land_cover_name', 'grassland')
        # evap_type: Granger (0) for all land HRUs, P-T (1) for water/wetland
        if lc in ('water', 'wetland'):
            evap_type.append(1)  # Priestley-Taylor for saturated surfaces
        else:
            evap_type.append(0)  # Granger for unsaturated (Fang §12)

        # Vegetation height from land cover (Fang §3.2.3: 15m forest, site obs)
        ht_lookup = {
            'coniferous_forest': 15.0, 'deciduous_forest': 12.0,
            'mixed_forest': 13.0, 'shrub': 1.5,
            'open_prairie': 0.3, 'grassland': 0.3, 'cropland': 0.5,
            'alpine': 0.1, 'bare': 0.01, 'water': 0.001, 'wetland': 0.3,
        }
        Ht.append(ht_lookup.get(lc, 0.3))

        # Ground heat flux fraction — 0.1 standard (Granger and Gray, 1990)
        F_Qg.append(0.1)

    return {
        'evap_type': evap_type,
        'Ht_evap': Ht,  # suffixed to distinguish from pbsm Ht
        'F_Qg': F_Qg,
    }


def derive_walmsley_params(hrus):
    """Derive Walmsley wind speed adjustment parameters per HRU.

    Walmsley et al. (1989) coefficients for wind speed change due to topography.
    Values from ClassWalmsley_wind.cpp declparam comments:
      A: 0.0=flat, 2.5=2D escarpments, 3.0=2D hills, 3.5=2D rolling, 4.0=3D hills, 4.4=3D rolling
      B: 0.0=flat, 0.8=2D escarpments, 1.1=3D rolling, 1.55=2D rolling, 1.6=3D hills, 2.0=2D hills
      L: upwind length at half height of topographic feature (m)
      Walmsley_Ht: height of HRU relative to reference (m)
    """
    n = len(hrus)
    A = []
    B = []
    L = []
    Walmsley_Ht = []
    min_elev = min(h['mean_elevation_m'] for h in hrus)

    for h in hrus:
        lc = h.get('land_cover_name', 'grassland')
        slope = h.get('mean_slope_deg', 10)
        elev = h.get('mean_elevation_m', 1500)

        # Terrain classification → Walmsley coefficients
        if slope > 25:
            # Steep mountain: 3D hills
            A.append(4.0); B.append(1.6)
        elif slope > 10:
            # Moderate terrain: 3D rolling
            A.append(4.4); B.append(1.1)
        elif slope > 3:
            # Gentle rolling: 2D rolling
            A.append(3.5); B.append(1.55)
        else:
            # Flat (prairie, valley floor)
            A.append(0.0); B.append(0.0)

        # L: upwind length scale — approximate from basin geometry
        area_km2 = h.get('area_km2', 10)
        L.append(max(500, min(np.sqrt(area_km2) * 1000, 10000)))

        # Walmsley_Ht: height above reference (lowest HRU)
        Walmsley_Ht.append(round(elev - min_elev, 1))

    return {'A': A, 'B': B, 'L': L, 'Walmsley_Ht': Walmsley_Ht}


def derive_pbsm_params(hrus):
    """Derive Prairie Blowing Snow Model parameters per HRU.

    Fang et al. (2013) §3.2.3: "fetch distance, 300m (minimum value) was used
    for all HRUs in the basin due to the short upwind distance. The blowing snow
    sequence was decided based on the predominant wind direction."

    Source: ClassPBSM.cpp — fetch range [300, 10000]m
    """
    n = len(hrus)
    fetch = []
    distrib = []

    for h in hrus:
        lc = h.get('land_cover_name', 'grassland')
        # Fetch distance from land cover (Fang: 300m for mountain)
        # Open terrain: longer fetch. Forest: short fetch (trees block wind)
        fetch_lookup = {
            'alpine': 300, 'bare': 500, 'open_prairie': 2000,
            'grassland': 1000, 'cropland': 1500, 'shrub': 500,
            'coniferous_forest': 300, 'deciduous_forest': 300,  # minimum
            'mixed_forest': 300, 'water': 3000, 'wetland': 1000,
        }
        fetch.append(fetch_lookup.get(lc, 300))

        # distrib: snow redistribution fraction
        # Positive = receives blown snow, negative = loses snow
        # High exposed HRUs lose snow, low sheltered HRUs gain
        # Sum of distrib for receiving HRUs should ≈ 1.0
        # Default: 0 = no redistribution (conservative)
        distrib.append(0.0)

    # Set distrib based on elevation: highest HRUs lose, lowest gains
    elevs = [h['mean_elevation_m'] for h in hrus]
    if max(elevs) - min(elevs) > 200:  # only if significant elevation range
        median_elev = np.median(elevs)
        for i, e in enumerate(elevs):
            if e > median_elev + 200:
                distrib[i] = 0.0  # exposed — source (0 means no transport to here)
            elif e < median_elev - 200:
                distrib[i] = 1.0  # sheltered — sink (receives blown snow)
            else:
                distrib[i] = 0.0  # neutral

    return {'fetch': fetch, 'distrib': distrib}


def derive_crack_params(hrus):
    """Derive frozen soil infiltration (crack module) parameters per HRU.

    Fang et al. (2013) §3.2.5: "initial soil saturation was determined from
    autumn soil moisture measurements, and initial soil temperature was taken
    from the measured value prior to snowmelt."

    Source: ClassCrack.cpp — fallstat: fall soil saturation (%), Major: melt threshold (mm/d)
    Gray's parametric equation (Zhao and Gray, 1999) for infiltration into frozen soils.
    """
    n = len(hrus)
    fallstat = []

    for h in hrus:
        lc = h.get('land_cover_name', 'grassland')
        # fallstat: 0=unlimited infiltration (dry), 100=restricted (saturated)
        # Typical autumn conditions: 50% for well-drained soils
        # Fang: "determined from autumn soil moisture measurements"
        # Without measurements, use texture-based estimate
        fs_lookup = {
            'open_prairie': 50, 'grassland': 50, 'cropland': 40,
            'coniferous_forest': 60, 'deciduous_forest': 50,
            'mixed_forest': 55, 'shrub': 45,
            'alpine': 30, 'bare': 20, 'water': 100, 'wetland': 80,
        }
        fallstat.append(fs_lookup.get(lc, 50))

    # Major: threshold for major melt event — 5 mm/d default (from source)
    Major = [5] * n

    return {'fallstat': fallstat, 'Major': Major}


def derive_routing_params(hrus, basin_area_km2):
    """Derive Netroute parameters from HRU geometry.

    Returns per-HRU: order, whereto, Kstorage, ssrKstorage, gwKstorage,
    runKstorage, route_S0
    """
    n = len(hrus)
    # Sort by elevation (highest first = upstream)
    sorted_hrus = sorted(enumerate(hrus), key=lambda x: -x[1]['mean_elevation_m'])

    order = [0] * n
    whereto = [0] * n  # 0 = basin outlet
    route_S0 = [0.001] * n

    for rank, (idx, hru) in enumerate(sorted_hrus):
        order[idx] = rank + 1
        # Route to next lower HRU, lowest routes to outlet (0)
        if rank < n - 1:
            next_idx = sorted_hrus[rank + 1][0]
            whereto[idx] = next_idx + 1  # 1-based HRU ID
        else:
            whereto[idx] = 0  # outlet

    # Storage constants — rough estimates from basin response
    # Larger basins have longer storage; steeper terrain has shorter storage
    for idx, hru in enumerate(hrus):
        elev = hru['mean_elevation_m']
        area = hru['area_km2']
        # Channel length ~ sqrt(area) km
        L_km = np.sqrt(area)
        # Slope from elevation band range
        elev_range = hru.get('elevation_band_range_m', [elev - 100, elev + 100])
        if isinstance(elev_range, (list, tuple)) and len(elev_range) >= 2:
            slope = (elev_range[1] - elev_range[0]) / (L_km * 1000) if L_km > 0 else 0.01
        else:
            slope = 0.01
        route_S0[idx] = max(0.0001, min(slope, 0.5))

    # Storage constants scale with sqrt(area)
    base_K = np.sqrt(basin_area_km2) * 0.1  # days
    runKstorage = [round(base_K * 0.5, 1)] * n   # fast: surface runoff
    ssrKstorage = [round(base_K * 1.0, 1)] * n   # medium: subsurface
    gwKstorage = [round(base_K * 3.0, 1)] * n    # slow: groundwater

    return {
        'order': order,
        'whereto': whereto,
        'route_S0': [round(s, 4) for s in route_S0],
        'runKstorage': runKstorage,
        'ssrKstorage': ssrKstorage,
        'gwKstorage': gwKstorage,
    }


def main():
    parser = argparse.ArgumentParser(description='Derive CRHM parameters from global datasets')
    parser.add_argument('--hru_config', required=True, help='HRU config JSON from S1')
    parser.add_argument('--output', required=True, help='Output derived parameters JSON')
    args = parser.parse_args()

    with open(args.hru_config) as f:
        cfg = json.load(f)

    hrus = cfg['hrus']
    nhru = cfg['nhru']
    basin_area = cfg['basin_area_km2']
    print(f"Deriving parameters for {nhru} HRUs, basin area {basin_area:.1f} km²")

    # Per-HRU soil parameters
    soil_types = []
    soil_moist_maxs = []
    soil_rechr_maxs = []
    soil_moist_inits = []
    soil_rechr_inits = []
    gw_maxs = []
    sdmaxs = []

    for hru in hrus:
        lat = hru.get('center_lat', hru.get('mean_lat', 51.0))
        lon = hru.get('center_lon', hru.get('mean_lon', -115.0))
        lc = hru.get('land_cover_name', 'grassland')
        slope = hru.get('mean_slope_deg', 10.0)
        elev = hru.get('mean_elevation_m', 1000)

        # Soil type from HWSD
        st, soil_info = lookup_soil_type(lat, lon)

        # Derive soil storage params using Fang et al. (2013) method
        soil_params = derive_soil_params(st, lc, mean_elevation_m=elev, slope_deg=slope)

        soil_types.append(soil_params['soil_type'])
        soil_moist_maxs.append(soil_params['soil_moist_max'])
        soil_rechr_maxs.append(soil_params['soil_rechr_max'])
        soil_moist_inits.append(soil_params['soil_moist_init'])
        soil_rechr_inits.append(soil_params['soil_rechr_init'])
        gw_maxs.append(soil_params['gw_max'])
        sdmaxs.append(soil_params.get('Sdmax', 0))

        texture_name = CRHM_SOIL.get(st, {}).get('name', '?')
        print(f"  HRU {hru.get('hru_id', '?')}: elev={elev:.0f}m, soil_type={st} ({texture_name}), "
              f"soil_moist_max={soil_params['soil_moist_max']:.0f}, "
              f"soil_rechr_max={soil_params['soil_rechr_max']:.0f}, "
              f"gw_max={soil_params['gw_max']:.0f}, Sdmax={soil_params.get('Sdmax', 0):.0f}")

    # Obs module parameters (Fang 2013: lapse 0.75°C/100m, precip elev adj)
    obs_params = derive_obs_params(hrus)
    print(f"\n  obs: lapse=0.75°C/100m, obs_elev={obs_params['obs_elev']:.0f}m, "
          f"catchadjust={obs_params['catchadjust'][0]}, snow_rain={obs_params['snow_rain_determination'][0]}")

    # Evap module (Fang 2013 §12: Granger for land, P-T for water)
    evap_params = derive_evap_params(hrus)
    print(f"  evap: types={set(evap_params['evap_type'])}")

    # Walmsley wind (Walmsley et al. 1989: terrain coefficients)
    walmsley_params = derive_walmsley_params(hrus)
    print(f"  walmsley: A={set(walmsley_params['A'])}, B={set(walmsley_params['B'])}")

    # PBSM blowing snow (Fang 2013 §3.2.3: fetch=300m minimum for mountains)
    pbsm_params = derive_pbsm_params(hrus)
    print(f"  pbsm: fetch={set(pbsm_params['fetch'])}")

    # Crack frozen soil infiltration (Fang 2013 §3.2.5: fallstat from autumn SM)
    crack_params = derive_crack_params(hrus)
    print(f"  crack: fallstat={set(crack_params['fallstat'])}")

    # Routing parameters (Fang 2013 §14: Muskingum from basin geometry)
    routing = derive_routing_params(hrus, basin_area)

    # Assemble output
    result = {
        'nhru': nhru,
        'basin_area_km2': basin_area,
        'obs': obs_params,
        'evap': evap_params,
        'walmsley_wind': walmsley_params,
        'pbsm': pbsm_params,
        'crack': crack_params,
        'soil': {
            'soil_type': soil_types,
            'soil_moist_max': soil_moist_maxs,
            'soil_rechr_max': soil_rechr_maxs,
            'soil_moist_init': soil_moist_inits,
            'soil_rechr_init': soil_rechr_inits,
            'gw_max': gw_maxs,
            'gw_init': [0.0] * nhru,  # cold start
            'Sdmax': sdmaxs,
        },
        'routing': routing,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\nSaved: {args.output}")
    print(f"Next: use these values in create_prj_file.py or patch into existing .prj")


if __name__ == '__main__':
    main()
