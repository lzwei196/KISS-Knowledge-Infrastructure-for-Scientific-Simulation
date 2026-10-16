#!/usr/bin/env python3
"""
derive_usle_k.py -- Derive USLE K-factor (soil erodibility) from HWSD soil
texture data for wflow_sediment staticmaps.

Computes USLE K using the Wischmeier & Smith (1978) nomograph equation:

    K = [2.1e-4 * M^1.14 * (12 - OM) + 3.25*(s-2) + 2.5*(p-3)] / 100

Where:
    M  = (% silt + 0.2 * % sand) * (100 - % clay)
    OM = organic matter (%) = OC * 1.724 (Van Bemmelen factor)
    s  = soil structure code (1-4, default 2 = medium granular)
    p  = permeability class (1-6, default 3 = slow-to-moderate)

K is in SI units: t*ha*h/(ha*MJ*mm)

Supports two modes:
  1. Grid mode: reads an existing wflow staticmaps.nc, extracts lat/lon grid,
     looks up HWSD for every active cell, computes K, and writes USLE_K into
     a new or patched NetCDF.
  2. Point mode: computes K for a single lat/lon (for testing/verification).

Data source: raw HWSD v1.2 raster/attribute table; strict dominant-component read

Usage:
    # Grid mode (main use case):
    python derive_usle_k.py --staticmaps /path/to/staticmaps.nc \
        --hwsd-crs EPSG:4326 --output /path/to/usle_k.nc

    # Grid mode with patch (writes USLE_K directly into staticmaps_sediment.nc):
    python derive_usle_k.py --staticmaps /path/to/staticmaps.nc \
        --hwsd-crs EPSG:4326 --patch_nc /path/to/staticmaps_sediment.nc

    # Point mode (verification):
    python derive_usle_k.py --lat 32.93 --lon 117.36 --hwsd-crs EPSG:4326

    (--hwsd-crs is needed because the server hwsd.bil has no CRS metadata.
    Active cells on HWSD water/rock/glacier/urban units stop the run with a
    list of those cells; no K value is filled.)

    # Use SoilGrids instead of HWSD (Bengbu region only):
    python derive_usle_k.py --staticmaps /path/to/staticmaps.nc \
        --output /path/to/usle_k.nc --soil_source soilgrids
"""

import argparse
import json
import os
import sys

import netCDF4  # load before xarray for the installed HDF5 stack
import numpy as np

sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")

# ---------------------------------------------------------------------------
# USLE K computation (Wischmeier & Smith 1978)
# ---------------------------------------------------------------------------

# Soil structure codes (Wischmeier & Smith, 1978, Table 2):
#   1 = very fine granular     (clayey, well-aggregated)
#   2 = fine granular          (medium structure, most common)
#   3 = medium/coarse granular (moderate aggregation)
#   4 = blocky/platy/massive   (poor structure)
STRUCTURE_CODE_DEFAULT = 2

# Permeability classes (Wischmeier & Smith, 1978, Table 3):
#   1 = rapid           (sand, loamy sand)
#   2 = moderate-rapid  (sandy loam)
#   3 = moderate        (loam, silt loam)
#   4 = slow-moderate   (clay loam)
#   5 = slow            (silty clay loam)
#   6 = very slow       (clay)
PERMEABILITY_CLASS_DEFAULT = 3


def permeability_class_from_texture(sand, clay):
    """Estimate USDA permeability class from texture percentages.

    Parameters
    ----------
    sand, clay : float or ndarray -- percentages (0-100)

    Returns
    -------
    perm_class : int or ndarray -- permeability class (1-6)
    """
    sand = np.asarray(sand, dtype=np.float64)
    clay = np.asarray(clay, dtype=np.float64)

    perm = np.full_like(sand, 3, dtype=np.int32)  # default moderate
    perm = np.where(sand >= 85, 1, perm)           # rapid (sand)
    perm = np.where((sand >= 65) & (sand < 85) & (clay < 15), 2, perm)  # mod-rapid
    perm = np.where((clay >= 27) & (clay < 40), 4, perm)   # slow-moderate
    perm = np.where((clay >= 40) & (clay < 55), 5, perm)   # slow
    perm = np.where(clay >= 55, 6, perm)                   # very slow

    return perm


def structure_code_from_texture(sand, clay, om_pct):
    """Estimate soil structure code from texture and organic matter.

    Parameters
    ----------
    sand, clay : float or ndarray -- percentages (0-100)
    om_pct : float or ndarray -- organic matter percentage

    Returns
    -------
    struct_code : int or ndarray -- structure code (1-4)
    """
    sand = np.asarray(sand, dtype=np.float64)
    clay = np.asarray(clay, dtype=np.float64)
    om_pct = np.asarray(om_pct, dtype=np.float64)

    # Default: medium granular (2)
    sc = np.full_like(sand, 2, dtype=np.int32)

    # High clay + high OM -> very fine granular (1)
    sc = np.where((clay >= 35) & (om_pct >= 3.0), 1, sc)

    # Low OM + high sand -> coarse (3)
    sc = np.where((om_pct < 1.0) & (sand >= 50), 3, sc)

    # Very low OM and high clay -> blocky/massive (4)
    sc = np.where((om_pct < 0.5) & (clay >= 40), 4, sc)

    return sc


def compute_usle_k(sand_pct, silt_pct, clay_pct, oc_pct,
                   struct_code=None, perm_class=None):
    """Compute USLE K-factor using Wischmeier & Smith (1978) nomograph.

    Parameters
    ----------
    sand_pct : float or ndarray -- sand content (%)
    silt_pct : float or ndarray -- silt content (%)
    clay_pct : float or ndarray -- clay content (%)
    oc_pct : float or ndarray -- organic carbon (%), converted to OM internally
    struct_code : int or ndarray or None -- soil structure code (1-4)
    perm_class : int or ndarray or None -- permeability class (1-6)

    Returns
    -------
    K : float or ndarray -- USLE K factor in SI units (t*ha*h/(ha*MJ*mm))
        Typical range: 0.001 - 0.1
    """
    sand = np.asarray(sand_pct, dtype=np.float64)
    silt = np.asarray(silt_pct, dtype=np.float64)
    clay = np.asarray(clay_pct, dtype=np.float64)
    oc = np.asarray(oc_pct, dtype=np.float64)

    for values,name in [(sand,"sand"),(silt,"silt"),(clay,"clay"),(oc,"organic carbon")]:
        if not np.isfinite(values).all() or np.any(values<0) or np.any(values>100):
            raise ValueError(f"{name} must be supplied as finite percent in [0,100]; no defaults")
    if np.any(np.abs(sand+silt+clay-100)>0.100001):
        raise ValueError("sand+silt+clay must sum to 100 percent (0.1 tolerance)")
    for values,name,upper in [(struct_code,"structure code",4),(perm_class,"permeability class",6)]:
        if values is not None:
            values=np.asarray(values,dtype=float)
            if not np.isfinite(values).all() or np.any(values<1) or np.any(values>upper) or np.any(values!=np.floor(values)):
                raise ValueError(f"Invalid {name}")

    # Convert organic carbon to organic matter (Van Bemmelen factor)
    om = oc * 1.724
    # Cap OM at 4% for the Wischmeier equation (above 4% the linear
    # approximation overestimates the OM reduction effect)
    om = np.clip(om, 0.0, 4.0)

    # Modified silt factor M
    M = (silt + 0.2 * sand) * (100.0 - clay)

    # Estimate structure and permeability codes from texture if not provided
    if struct_code is None:
        s = structure_code_from_texture(sand, clay, om)
    else:
        s = np.asarray(struct_code, dtype=np.float64)

    if perm_class is None:
        p = permeability_class_from_texture(sand, clay)
    else:
        p = np.asarray(perm_class, dtype=np.float64)

    # Wischmeier & Smith (1978) nomograph equation
    # This gives K in US customary units (ton*acre*h / (100*acre*ft-tonf*in))
    K_us = (
        2.1e-4 * np.power(M, 1.14) * (12.0 - om)
        + 3.25 * (s - 2.0)
        + 2.5 * (p - 3.0)
    ) / 100.0

    # Convert to SI: t*ha*h/(ha*MJ*mm)
    # Conversion factor: 1 US K unit = 0.1317 SI K unit
    # Reference: Foster et al. (1981); Renard et al. (1997) RUSLE handbook
    K = K_us * 0.1317

    # Clamp to physically reasonable range (SI)
    # Typical: 0.001 (clay, resistant) to 0.070 (silt, very erodible)
    K = np.clip(K, 0.001, 0.070)

    return K


# ---------------------------------------------------------------------------
# Grid mode: derive K for every cell in a wflow staticmaps.nc
# ---------------------------------------------------------------------------

def _axes(ds):
    for y,x in [("lat","lon"),("latitude","longitude"),("y","x")]:
        if y in ds.coords and x in ds.coords:
            if ds[y].ndim!=1 or ds[x].ndim!=1:raise ValueError("Require regular one-dimensional geographic axes")
            for name in ["spatial_ref","crs"]:
                if name in ds:
                    from pyproj import CRS
                    attrs=ds[name].attrs;crs=attrs.get("crs_wkt",attrs.get("spatial_ref"))
                    if crs and not CRS.from_user_input(crs).is_geographic:raise ValueError("Projected grids require explicit reprojection before soil lookup")
            return y,x
    raise ValueError("Cannot find geographic coordinate axes")


def lookup_hwsd_strict(lat,lon,hwsd_raster=None,hwsd_csv=None,hwsd_crs=None):
    """Read the dominant HWSD component directly; never borrow a minor component or default."""
    import pandas as pd
    import rasterio
    from rasterio.warp import transform
    from ki_tools_common.soil_utils import HWSD_RASTER,HWSD_CSV
    raster=hwsd_raster or HWSD_RASTER;csv=hwsd_csv or HWSD_CSV
    with rasterio.open(raster) as src:
        explicit=rasterio.crs.CRS.from_user_input(hwsd_crs) if hwsd_crs else None
        if src.crs and explicit and src.crs!=explicit:raise ValueError("Explicit HWSD CRS conflicts with metadata")
        crs=src.crs or explicit
        if crs is None:raise ValueError("HWSD raster lacks CRS; supply verified --hwsd-crs")
        xs,ys=transform("EPSG:4326",crs,[lon],[lat]);row,col=src.index(xs[0],ys[0])
        if not (0<=row<src.height and 0<=col<src.width):raise ValueError("Point outside HWSD coverage")
        cell=src.read(1,window=rasterio.windows.Window(col,row,1,1),masked=True)[0,0]
        if np.ma.is_masked(cell) or not np.isfinite(cell) or cell<=0 or cell!=int(cell):raise ValueError("No valid HWSD map unit at active point")
        mu=int(cell)
    # Cache keyed by the source stat as well as path, never modified source rows.
    from pathlib import Path
    key=(str(csv),Path(csv).stat().st_mtime_ns,Path(csv).stat().st_size)
    if key not in _HWSD_TABLES:
        _HWSD_TABLES.clear();_HWSD_TABLES[key]=pd.read_csv(csv,low_memory=False)
    table=_HWSD_TABLES[key];rows=table[table.MU_GLOBAL==mu]
    if rows.empty:raise ValueError(f"HWSD MU {mu} absent from attribute table")
    shares=pd.to_numeric(rows.SHARE,errors="coerce")
    # HWSD lists unused components with SHARE=0 (e.g. MU 12014: 40/30/20/10/0).
    # They are allowed but never selected; the chosen component must have SHARE>0.
    if not np.isfinite(shares).all() or (shares<0).any() or (shares>100).any() or not (shares.max()>0):
        raise ValueError("Invalid HWSD component shares")
    rows=rows.loc[shares==shares.max()]
    if len(rows)>1:
        seq=pd.to_numeric(rows.SEQ,errors="coerce")
        if not np.isfinite(seq).all():raise ValueError("Ambiguous HWSD component order")
        rows=rows.loc[seq==seq.min()]
    row=rows.iloc[0]
    vals=[float(row.get("T_"+name,np.nan)) for name in ["SAND","SILT","CLAY","OC"]]
    if not np.isfinite(vals).all():
        # Water (WR), rock (RK), glacier (GG/GL), urban (UR), dunes (DS) and
        # similar non-soil units carry no topsoil texture in HWSD v1.2.
        # Stop with a clear message; never invent a K value for them.
        symbol=next((str(row.get(c)) for c in ["SU_SYM90","SU_SYM85","SU_SYM74"] if pd.notna(row.get(c))),"none")
        raise NonSoilHWSDUnit(f"HWSD MU {mu} dominant component has no topsoil texture "
            f"(symbol {symbol}, ISSOIL={row.get('ISSOIL')}, sand/silt/clay/OC={vals}); "
            "likely water/rock/glacier/urban; USLE K is not computed and no value is filled")
    compute_usle_k(*vals)  # Enforce raw fractions/OC before downstream estimates.
    return dict(mu_id=mu,sand=vals[0],silt=vals[1],clay=vals[2],oc=vals[3],texture="raw dominant HWSD component",
        source=dict(raster=str(raster),csv=str(csv),crs=str(crs),share_pct=float(row.SHARE),selection="max SHARE, min SEQ, CSV row order"))


_HWSD_TABLES={}


class NonSoilHWSDUnit(ValueError):
    """Dominant HWSD component has no texture (water, rock, glacier, urban ...)."""


def derive_k_grid(staticmaps_path, soil_source="hwsd", **hwsd_options):
    """Derive USLE K factor for every active cell in a wflow staticmaps.nc.

    Parameters
    ----------
    staticmaps_path : str -- path to wflow staticmaps.nc
    soil_source : str -- "hwsd" or "soilgrids"

    Returns
    -------
    dict with keys: K_array (2D ndarray), lats, lons, mask, stats
    """
    import xarray as xr

    ds = xr.open_dataset(staticmaps_path)

    y_name,x_name=_axes(ds)
    lats,lons=ds[y_name].values,ds[x_name].values

    # Get basin mask
    if "wflow_subcatch" in ds:
        # Force (lat, lon) order so mask[i, j] matches lats[i], lons[j].
        ids=ds["wflow_subcatch"].transpose(y_name,x_name).values
        if np.isinf(ids).any() or np.any(np.isfinite(ids)&(ids<=0)):
            raise ValueError("wflow_subcatch requires positive IDs and NaN padding")
        mask = ids > 0
    else:
        raise ValueError("wflow_subcatch is required; cannot infer active soil cells from an arbitrary field")

    ny, nx = mask.shape
    if not mask.any():raise ValueError("No active cells")
    if np.any(abs(lats)>90) or np.any(abs(lons)>180):raise ValueError("Expected geographic latitude/longitude grid")
    print(f"  Grid: {nx} x {ny}, active cells: {mask.sum()}", file=sys.stderr)

    # Initialize output arrays
    K_array = np.full((ny, nx), np.nan, dtype=np.float32)
    sand_array = np.full((ny, nx), np.nan, dtype=np.float32)
    silt_array = np.full((ny, nx), np.nan, dtype=np.float32)
    clay_array = np.full((ny, nx), np.nan, dtype=np.float32)
    oc_array = np.full((ny, nx), np.nan, dtype=np.float32)
    source_records=[]

    if soil_source == "hwsd":
        non_soil=[]
        for i,j in np.argwhere(mask):
            try:
                props=lookup_hwsd_strict(float(lats[i]),float(lons[j]),**hwsd_options)
            except NonSoilHWSDUnit as exc:
                # Collect every such active cell, then stop (nothing is written).
                non_soil.append(f"row {int(i)} col {int(j)} lat {float(lats[i]):.5f} lon {float(lons[j]):.5f}: {exc}")
                continue
            source_records.append(dict(row=int(i),column=int(j),**props))
            sand_array[i,j]=props["sand"];silt_array[i,j]=props["silt"]
            clay_array[i,j]=props["clay"];oc_array[i,j]=props["oc"]
        if non_soil:
            ds.close()
            raise NonSoilHWSDUnit(f"{len(non_soil)} active cell(s) fall on HWSD units with no soil texture "
                "(water/rock/glacier/urban etc.). USLE K is not computed for them and no value is filled. "
                "Remove these cells from wflow_subcatch or use another soil source, then rerun:\n  "
                +"\n  ".join(non_soil))

    elif soil_source == "soilgrids":
        # SoilGrids 250m (Bengbu region only: 113-118E, 31-35N)
        _derive_k_from_soilgrids(lats, lons, mask, sand_array, silt_array,
                                  clay_array, oc_array)
    else:
        raise ValueError(f"Unknown soil_source: {soil_source}. Use 'hwsd' or 'soilgrids'.")

    # Validate only active cells; inactive padding remains masked.
    K_values=compute_usle_k(sand_array[mask],silt_array[mask],clay_array[mask],oc_array[mask])
    K_array[mask]=K_values.astype(np.float32)

    # Statistics
    valid_K = K_array[mask]
    stats = {
        "mean_K": round(float(np.nanmean(valid_K)), 5),
        "min_K": round(float(np.nanmin(valid_K)), 5),
        "max_K": round(float(np.nanmax(valid_K)), 5),
        "std_K": round(float(np.nanstd(valid_K)), 5),
        "n_cells": int(mask.sum()),
        "soil_source": soil_source,
        "filled_cells": 0,
        "parameter_assumptions": "texture-estimated structure/permeability, OM capped at 4%, K bounded [0.001,0.070]; no source data defaults",
    }

    ds.close()

    return {
        "K_array": K_array,
        "sand_array": sand_array,
        "silt_array": silt_array,
        "clay_array": clay_array,
        "oc_array": oc_array,
        "lats": lats,
        "lons": lons,
        "mask": mask,
        "stats": stats,
        "source_records": source_records,
    }


def _derive_k_from_soilgrids(lats, lons, mask, sand_array, silt_array,
                               clay_array, oc_array):
    """Fill texture arrays from SoilGrids GeoTIFFs (Bengbu region only)."""
    try:
        import rasterio
    except ImportError:
        print("ERROR: rasterio required for SoilGrids. "
              "Install with: pip install rasterio", file=sys.stderr)
        sys.exit(1)

    soilgrids_dir = "KISSPATH_HOME/Crop_model_dataset/SoilGrids_Bengbu"
    depth = "0-5cm"  # topsoil for USLE

    files = {
        "sand": os.path.join(soilgrids_dir, f"sand_{depth}_mean.tif"),
        "silt": os.path.join(soilgrids_dir, f"silt_{depth}_mean.tif"),
        "clay": os.path.join(soilgrids_dir, f"clay_{depth}_mean.tif"),
        "soc": os.path.join(soilgrids_dir, f"soc_{depth}_mean.tif"),
    }

    for name, path in files.items():
        if not os.path.exists(path):
            raise FileNotFoundError(f"Required SoilGrids file not found: {path}")

    ny, nx = mask.shape

    for name, path in files.items():
        with rasterio.open(path) as src:
            for i in range(ny):
                for j in range(nx):
                    if not mask[i, j]:
                        continue
                    lat = float(lats[i])
                    lon = float(lons[j])

                    if src.crs is None:raise ValueError(f"SoilGrids CRS missing: {path}")
                    from rasterio.warp import transform
                    xx,yy=transform("EPSG:4326",src.crs,[lon],[lat])
                    row,col=src.index(xx[0],yy[0])
                    if not (0<=row<src.height and 0<=col<src.width):raise ValueError(f"Active cell outside SoilGrids coverage: {lat},{lon}")
                    val=src.read(1,window=rasterio.windows.Window(col,row,1,1),masked=True)[0,0]
                    if np.ma.is_masked(val) or not np.isfinite(val) or val<0:raise ValueError(f"Missing SoilGrids {name} at active cell {lat},{lon}")
                    val=float(val)

                    # SoilGrids units: sand/silt/clay in g/kg -> % (/10)
                    # SOC in dg/kg -> % (/100, since OC% = g/kg / 10)
                    if name == "sand":
                        sand_array[i, j] = val / 10.0
                    elif name == "silt":
                        silt_array[i, j] = val / 10.0
                    elif name == "clay":
                        clay_array[i, j] = val / 10.0
                    elif name == "soc":
                        # dg/kg -> g/kg: /10, then g/kg -> %: /10 => /100
                        oc_array[i, j] = val / 100.0

    print(f"  SoilGrids lookup complete (depth={depth})", file=sys.stderr)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_output(result, output_path, staticmaps_path):
    """Write USLE_K as a standalone NetCDF file."""
    import xarray as xr

    ds_ref = xr.open_dataset(staticmaps_path)

    # Determine coordinate names
    y_name,x_name=_axes(ds_ref)

    coords = {
        y_name: result["lats"],
        x_name: result["lons"],
    }

    ds_out = xr.Dataset(
        {
            "USLE_K": ([y_name, x_name], result["K_array"],
                       {"long_name": "USLE K factor (soil erodibility)",
                        "units": "t*ha*h/(ha*MJ*mm)",
                        "source": f"Wischmeier-Smith 1978, soil={result['stats']['soil_source']}",
                        "valid_range": [0.001, 0.070]}),
        },
        coords=coords,
    )

    for field in ["sand","silt","clay","oc"]:
        ds_out[field+"_pct"]=xr.DataArray(result[field+"_array"],dims=[y_name,x_name],attrs={"units":"percent","source":"actual source values before K estimation"})
    ds_out.attrs["filled_cells"]=0
    ds_out.attrs["parameter_assumptions"]=result["stats"]["parameter_assumptions"]
    ds_out.attrs["source_records"]=json.dumps(result.get("source_records",[]))
    ds_out.attrs["title"] = "USLE K-factor derived from soil texture"
    ds_out.attrs["method"] = "Wischmeier-Smith (1978) nomograph equation"
    ds_out.attrs["tool"] = "derive_usle_k.py (wflow KI)"

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    ds_out.to_netcdf(output_path)
    ds_ref.close()

    print(f"  Written USLE_K to {output_path}", file=sys.stderr)


def patch_netcdf(result, patch_nc_path):
    """Write USLE_K into an existing staticmaps_sediment.nc."""
    import xarray as xr

    ds = xr.open_dataset(patch_nc_path)

    # Determine coordinate names
    y_name,x_name=_axes(ds)

    if not np.array_equal(ds[y_name].values,result["lats"]) or not np.array_equal(ds[x_name].values,result["lons"]):
        ds.close();raise ValueError("Patch grid coordinates differ from derived K grid")
    if "wflow_subcatch" not in ds:
        ds.close();raise ValueError("Patch file lacks wflow_subcatch")
    ids=ds.wflow_subcatch.transpose(y_name,x_name).values
    if np.isinf(ids).any() or np.any(np.isfinite(ids)&(ids<=0)):
        # Wflow treats any non-missing ID (also 0) as active; such a cell would get NaN K.
        ds.close();raise ValueError("Patch wflow_subcatch requires positive IDs and NaN padding")
    if not np.array_equal(np.isfinite(ids)&(ids>0),result["mask"]):
        ds.close();raise ValueError("Patch active mask differs from derived K mask")
    if not np.isfinite(result["K_array"][result["mask"]]).all():
        ds.close();raise ValueError("Nonfinite K at active cells")

    ds["USLE_K"] = xr.DataArray(
        result["K_array"],
        dims=[y_name, x_name],
        attrs={
            "long_name": "USLE K factor (soil erodibility)",
            "units": "t*ha*h/(ha*MJ*mm)",
            "source": f"Wischmeier-Smith 1978, soil={result['stats']['soil_source']}",
        },
    )

    ds.attrs["USLE_K_derivation"]=json.dumps(dict(stats=result["stats"],source_records=result.get("source_records",[])))
    ds.to_netcdf(patch_nc_path + ".tmp")
    ds.close()

    os.replace(patch_nc_path + ".tmp", patch_nc_path)
    print(f"  Patched USLE_K into {patch_nc_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Point mode
# ---------------------------------------------------------------------------

def point_mode(lat, lon, soil_source="hwsd", **hwsd_options):
    """Compute USLE K for a single point (verification mode)."""
    if soil_source == "hwsd":
        props = lookup_hwsd_strict(lat, lon, **hwsd_options)
        sand, silt, clay = props["sand"], props["silt"], props["clay"]
        oc = props["oc"]
        texture = props["texture"]
        mu_id = props["mu_id"]
    else:
        raise ValueError("Point mode only supports 'hwsd' soil source")

    om = oc * 1.724
    K = float(compute_usle_k(sand, silt, clay, oc))

    result = {
        "lat": lat,
        "lon": lon,
        "soil_source": soil_source,
        "mu_id": mu_id,
        "source": props["source"],
        "filled_properties": 0,
        "sand_pct": round(sand, 1),
        "silt_pct": round(silt, 1),
        "clay_pct": round(clay, 1),
        "oc_pct": round(oc, 2),
        "om_pct": round(min(om, 4.0), 2),
        "texture": texture,
        "USLE_K": round(K, 5),
        "K_interpretation": _interpret_k(K),
    }
    return result


def _interpret_k(K):
    """Interpret K factor value."""
    if K < 0.01:
        return "very low erodibility (resistant soil)"
    elif K < 0.025:
        return "low erodibility"
    elif K < 0.04:
        return "moderate erodibility"
    elif K < 0.06:
        return "high erodibility"
    else:
        return "very high erodibility (silt-rich soil)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Derive USLE K-factor from soil texture (HWSD or SoilGrids) "
                    "for wflow_sediment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Grid mode: derive K for all cells
    python derive_usle_k.py --staticmaps staticmaps.nc --hwsd-crs EPSG:4326 --output usle_k.nc

    # Grid mode: patch into existing sediment staticmaps
    python derive_usle_k.py --staticmaps staticmaps.nc --hwsd-crs EPSG:4326 \\
        --patch_nc staticmaps_sediment.nc

    # Point mode: check single location
    python derive_usle_k.py --lat 32.93 --lon 117.36 --hwsd-crs EPSG:4326

    # Use SoilGrids (Bengbu only, 250m resolution)
    python derive_usle_k.py --staticmaps staticmaps.nc --output usle_k.nc \\
        --soil_source soilgrids

Method:
    Wischmeier & Smith (1978) nomograph equation:
    K = [2.1e-4 * M^1.14 * (12-OM) + 3.25*(s-2) + 2.5*(p-3)] / 100

    Where M = (%silt + 0.2*%sand) * (100 - %clay)
    OM = organic matter (%), s = structure code (1-4), p = permeability (1-6)

    Output range: 0.001 - 0.070 t*ha*h/(ha*MJ*mm) (SI units)

Reference:
    Wischmeier, W.H. and Smith, D.D. (1978). Predicting Rainfall Erosion
    Losses. Agriculture Handbook No. 537, USDA.
        """,
    )
    parser.add_argument("--staticmaps", type=str,
                        help="Path to wflow staticmaps.nc (grid mode)")
    parser.add_argument("--output", type=str,
                        help="Output NetCDF file for USLE_K (grid mode)")
    parser.add_argument("--patch_nc", type=str,
                        help="Existing staticmaps_sediment.nc to patch with USLE_K")
    parser.add_argument("--lat", type=float,
                        help="Latitude for point mode")
    parser.add_argument("--lon", type=float,
                        help="Longitude for point mode")
    parser.add_argument("--soil_source", type=str, default="hwsd",
                        choices=["hwsd", "soilgrids"],
                        help="Soil data source (default: hwsd)")

    parser.add_argument("--hwsd-raster",help="Explicit HWSD map raster")
    parser.add_argument("--hwsd-csv",help="Explicit HWSD raw attribute table")
    parser.add_argument("--hwsd-crs",help="Verified CRS when HWSD raster metadata lacks it")
    args = parser.parse_args()
    hwsd_options=dict(hwsd_raster=args.hwsd_raster,hwsd_csv=args.hwsd_csv,hwsd_crs=args.hwsd_crs)


    # --- Point mode ---
    if args.lat is not None and args.lon is not None:
        result = point_mode(args.lat, args.lon, args.soil_source, **hwsd_options)
        print(json.dumps(result, indent=2))
        return

    # --- Grid mode ---
    if not args.staticmaps:
        parser.error("Provide --staticmaps (grid mode) or --lat/--lon (point mode)")
    if not args.output and not args.patch_nc:
        parser.error("Provide --output or --patch_nc for grid mode")

    if not os.path.exists(args.staticmaps):
        print(f"ERROR: staticmaps not found: {args.staticmaps}", file=sys.stderr)
        sys.exit(1)

    print(f"Deriving USLE K-factor from {args.soil_source.upper()}...",
          file=sys.stderr)

    result = derive_k_grid(args.staticmaps, args.soil_source, **hwsd_options)
    stats = result["stats"]

    if args.output:
        write_output(result, args.output, args.staticmaps)

    if args.patch_nc:
        if not os.path.exists(args.patch_nc):
            print(f"ERROR: patch target not found: {args.patch_nc}", file=sys.stderr)
            sys.exit(1)
        patch_netcdf(result, args.patch_nc)

    # Print summary
    output = {
        "status": "success",
        "soil_source": args.soil_source,
        "stats": stats,
    }
    if args.output:
        output["output_file"] = args.output
    if args.patch_nc:
        output["patched_file"] = args.patch_nc

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
