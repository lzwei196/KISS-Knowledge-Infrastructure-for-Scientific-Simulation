#!/usr/bin/env python3
"""
convert_params_to_ef5.py — Convert soil/land parameters to EF5 parameter grids.

Converts HWSD (Harmonized World Soil Database), STATSGO, or SoilGrids data
into CREST or SAC-SMA parameter grids for EF5.

CREST parameters from soil:
  - WM: max soil water capacity (mm) — from porosity * depth
  - FC/Ksat: saturated hydraulic conductivity (mm/hr)
  - B: variable infiltration curve exponent — from soil texture
  - IM: impervious area ratio (0-100%) — from urban land cover

SAC-SMA parameters from soil:
  - UZTWM, UZFWM: upper zone tensions/free water max (mm)
  - LZTWM, LZFSM, LZFPM: lower zone capacities (mm)
  - UZK, LZSK, LZPK: withdrawal rates (fractional/day)

Pipeline: validate inputs → read soil data → compute parameters → write grids → validate outputs
"""

import argparse
import os
import sys
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# CREST parameter derivation from soil properties
# ---------------------------------------------------------------------------

# Soil texture class -> B exponent (variable infiltration curve)
# Based on Cosby et al. (1984) and CREST literature
TEXTURE_TO_B = {
    "sand": 0.30,
    "loamy_sand": 0.35,
    "sandy_loam": 0.45,
    "silt_loam": 0.55,
    "silt": 0.50,
    "loam": 0.50,
    "sandy_clay_loam": 0.60,
    "silty_clay_loam": 0.65,
    "clay_loam": 0.60,
    "sandy_clay": 0.70,
    "silty_clay": 0.75,
    "clay": 0.80,
}

# Soil texture class -> Ksat (mm/hr), from Rawls et al. (1982)
TEXTURE_TO_KSAT = {
    "sand": 120.0,
    "loamy_sand": 60.0,
    "sandy_loam": 26.0,
    "silt_loam": 6.8,
    "silt": 3.4,
    "loam": 13.0,
    "sandy_clay_loam": 4.3,
    "silty_clay_loam": 1.5,
    "clay_loam": 2.3,
    "sandy_clay": 1.2,
    "silty_clay": 0.9,
    "clay": 0.6,
}

# Soil texture class -> porosity (fraction), from Rawls et al. (1982)
TEXTURE_TO_POROSITY = {
    "sand": 0.437,
    "loamy_sand": 0.437,
    "sandy_loam": 0.453,
    "silt_loam": 0.501,
    "silt": 0.480,
    "loam": 0.463,
    "sandy_clay_loam": 0.398,
    "silty_clay_loam": 0.471,
    "clay_loam": 0.464,
    "sandy_clay": 0.430,
    "silty_clay": 0.479,
    "clay": 0.475,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(soil_dir, dem_path, output_dir):
    """Validate input files exist."""
    errors = []
    if soil_dir and not os.path.isdir(soil_dir):
        errors.append(f"Soil data directory not found: {soil_dir}")
    if dem_path and not os.path.isfile(dem_path):
        errors.append(f"DEM file not found: {dem_path}")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        return False
    return True


PARAM_RANGES = {
    "crest": {"wm": (10., 2000.), "b": (.01, 2.), "im": (0., 100.), "ksat": (.01, 500.)},
    "sac": {"uztwm": (1., 500.), "uzfwm": (1., 200.), "lztwm": (1., 1000.),
            "lzfsm": (1., 500.), "lzfpm": (1., 1000.), "uzk": (.1, .7),
            "lzsk": (.01, .3), "lzpk": (.001, .05)},
}


def validate_param_grid(data, param_name, valid_range):
    """Validate finite active-domain values against the existing parameter bounds."""
    values = np.asarray(data)
    lo, hi = valid_range
    if not values.size or not np.isfinite(values).all() or np.any((values < lo) | (values > hi)):
        print(f"[ERROR] {param_name}: missing/nonfinite or outside [{lo}, {hi}]", file=sys.stderr)
        return False
    print(f"[OK] {param_name}: range [{values.min():.3f}, {values.max():.3f}]")
    return True


def validate_outputs(output_dir, model="crest", active_mask=None):
    """Require every expected GeoTIFF and validate all active-domain values."""
    if model not in PARAM_RANGES:
        return False
    ok = True
    reference = None
    for param, limits in PARAM_RANGES[model].items():
        path = Path(output_dir)/f"{param}.tif"
        if not path.is_file():
            print(f"[ERROR] missing parameter grid: {path}", file=sys.stderr)
            ok = False
            continue
        try:
            data, transform, crs = _read_spatial(path)
            meta = (data.shape, transform, crs)
            if reference is not None and meta != reference:
                raise ValueError("parameter grids are not aligned")
            reference = meta
            if active_mask is not None and active_mask.shape != data.shape:
                raise ValueError("active-domain shape does not match output")
            values = data if active_mask is None else data[active_mask]
            ok = validate_param_grid(values, param, limits) and ok
        except (ValueError, OSError) as exc:
            print(f"[ERROR] {path}: {exc}", file=sys.stderr)
            ok = False
    return ok


def _check_georef(transform, crs, label):
    # EF5's raster lookup uses numeric coordinates, without CRS transformation.
    # This converter supports its WGS84 geographic grid route only.
    import rasterio
    if crs is None or crs != rasterio.crs.CRS.from_epsg(4326):
        raise ValueError(f"{label}: explicit EPSG:4326 CRS required. A file with no CRS can be "
                         f"declared with --dem-crs / --hwsd-crs EPSG:4326 if it really is WGS84 "
                         f"lon/lat; any other CRS must be reprojected first (found {crs})")
    if (not np.isfinite(tuple(transform)).all() or transform.is_identity or
            transform.a <= 0 or transform.e >= 0 or transform.b != 0 or transform.d != 0 or
            not np.isclose(transform.a, -transform.e, rtol=1e-8, atol=0.)):
        raise ValueError(f"{label}: north-up square-cell georeference required; no inferred origin")


# CRS declared on the command line for files that carry none (the shared
# hwsd.bil has no .prj; prepare_basic_grids writes dem.asc without one).
# Only EPSG:4326 can be declared: EF5 runs this route with PROJ=geographic.
_DECLARED_CRS = {}


def declare_crs(path, crs_text):
    """Record an explicit CRS for a file that has none. Never guessed."""
    import rasterio
    if not crs_text:
        return
    crs = rasterio.crs.CRS.from_user_input(crs_text)
    if crs != rasterio.crs.CRS.from_epsg(4326):
        raise ValueError(f"{path}: only EPSG:4326 can be declared (EF5 PROJ=geographic), got {crs_text}")
    _DECLARED_CRS[os.path.realpath(path)] = crs


def _effective_crs(path, file_crs):
    """The file's own CRS, or the one declared for it. A declaration never
    overrides a CRS the file already has; a mismatch stops the tool."""
    declared = _DECLARED_CRS.get(os.path.realpath(path))
    if file_crs is None:
        return declared
    if declared is not None and file_crs != declared:
        raise ValueError(f"{path}: file CRS {file_crs} differs from declared {declared}")
    return file_crs


def _read_spatial(path):
    import rasterio
    with rasterio.open(path) as src:
        crs = _effective_crs(path, src.crs)
        _check_georef(src.transform, crs, path)
        return src.read(1, masked=True).astype('float32').filled(np.nan), src.transform, crs


def _ef5_lookup(dem_transform, rows, cols, transform, shape):
    """Parameter-grid cell EF5 reads for DEM nodes (rows, cols), copied step by
    step from the EF5 source (src/Grid.h, src/BasicGrids.cpp):
      - node coordinate: Grid::GetRefLoc, refLoc = (float)x*cellSize + left,
        top - (float)y*cellSize, stored as float. This is the cell's UPPER-LEFT
        CORNER, not its centre (BasicGrids.cpp: g_DEM->GetRefLoc(x, y, &refLoc)).
      - lookup: Grid::GetGridLoc, xDiff = (float)(lon - left),
        xLoc = (float)(xDiff / cellSize), index = (long)xLoc (truncation),
        clamped to the grid; returns false when the point is outside the extent
        (then EF5 silently keeps the scalar parameter, so we stop instead).
    float/double steps follow C++ rules (float*double is done in double, then
    stored as float); the EF5 build uses no fast-math. Returns (r, c, inside)."""
    f32, f64 = np.float32, np.float64
    dem_cs, dem_left, dem_top = f64(dem_transform.a), f64(dem_transform.c), f64(dem_transform.f)
    lon = (f64(cols.astype(f32)) * dem_cs + dem_left).astype(f32)
    lat = (dem_top - f64(rows.astype(f32)) * dem_cs).astype(f32)
    cs, left, top = f64(transform.a), f64(transform.c), f64(transform.f)
    nrows, ncols = shape
    right, bottom = left + cs * float(ncols), top - cs * float(nrows)  # TifGrid.cpp extent
    x_loc = ((f64(lon) - left).astype(f32).astype(f64) / cs).astype(f32)
    y_loc = ((top - f64(lat)).astype(f32).astype(f64) / cs).astype(f32)
    c = np.clip(np.trunc(x_loc).astype(np.int64), 0, ncols - 1)
    r = np.clip(np.trunc(y_loc).astype(np.int64), 0, nrows - 1)
    inside = ~((left > f64(lon)) | (right < f64(lon)) | (bottom > f64(lat)) | (top < f64(lat)))
    return r, c, inside


def _raw_tiff_georef(path, with_nodata=False):
    """Raw ModelTiepoint (33922), ModelPixelScale (33550) and
    ModelTransformation (34264) of the first IFD, read the way libtiff hands
    them to EF5 (TifGrid.cpp). Classic TIFF and BigTIFF; no dependency.
    with_nodata=True also returns the raw GDAL_NODATA tag (42113) text, which
    is all EF5 reads (never a .aux.xml sidecar)."""
    import struct
    with open(path, "rb") as fh:
        head = fh.read(16)
        order = {b"II": "<", b"MM": ">"}.get(head[:2])
        if order is None:
            raise ValueError(f"{path}: not a TIFF file")
        magic = struct.unpack(order + "H", head[2:4])[0]
        if magic == 42:
            big, ifd = False, struct.unpack(order + "I", head[4:8])[0]
        elif magic == 43:
            big, ifd = True, struct.unpack(order + "Q", head[8:16])[0]
        else:
            raise ValueError(f"{path}: not a TIFF file")
        fh.seek(ifd)
        n = struct.unpack(order + ("Q" if big else "H"), fh.read(8 if big else 2))[0]
        entry, cfmt = (20, "Q") if big else (12, "I")
        tags = {}
        for _ in range(n):
            raw = fh.read(entry)
            tag, typ = struct.unpack(order + "HH", raw[:4])
            count = struct.unpack(order + cfmt, raw[4:4 + struct.calcsize(cfmt)])[0]
            if tag not in (33922, 33550, 34264, 42113):
                continue
            if tag == 42113:
                if typ != 2:
                    raise ValueError(f"{path}: GDAL_NODATA tag is not ASCII")
            elif typ != 12:  # DOUBLE, as the GeoTIFF spec requires
                raise ValueError(f"{path}: GeoTIFF tag {tag} is not DOUBLE")
            off = 4 + struct.calcsize(cfmt)
            nbytes = count if tag == 42113 else 8 * count
            if nbytes <= (8 if big else 4):
                data = raw[off:off + nbytes]
            else:
                pos = fh.tell()
                fh.seek(struct.unpack(order + cfmt, raw[off:off + struct.calcsize(cfmt)])[0])
                data = fh.read(nbytes)
                fh.seek(pos)
            if tag == 42113:
                tags[tag] = data.split(b"\0")[0].decode("ascii", "replace")
            else:
                tags[tag] = struct.unpack(order + "d" * count, data)
    if with_nodata:
        return tags.get(33922), tags.get(33550), tags.get(34264), tags.get(42113)
    return tags.get(33922), tags.get(33550), tags.get(34264)


def _check_ef5_dem_georef(dem_path):
    """Stop on DEM georeference conventions that EF5 reads differently from
    rasterio, so the mask is built on the same origin EF5 uses.
    - TIFF (TifGrid.cpp ReadFloatTifGrid): extent.left/top = raw ModelTiepoint
      X/Y, cellSize = ModelPixelScale, no PixelIsPoint half-cell shift and no
      raster tiepoint offset. rasterio shifts PixelIsPoint files by half a cell
      and applies raster offsets, so the raw tags must equal rasterio's
      transform (one tiepoint at raster 0,0, no ModelTransformation).
    - ESRI ASCII (AscGrid.cpp ReadFloatAscGrid): reads six header values in a
      fixed order and ignores the key names, so xllcenter would be taken as the
      lower-left CORNER; rasterio shifts it by half a cell.
    Unsupported files must be rewritten as PixelIsArea / xllcorner first."""
    import rasterio
    if str(dem_path).lower().endswith(".asc"):
        with open(dem_path) as fh:
            keys = [fh.readline().split()[:1] for _ in range(6)]
        keys = [k[0].lower() if k else "" for k in keys]
        want = ["ncols", "nrows", "xllcorner", "yllcorner", "cellsize", "nodata_value"]
        if keys != want:
            raise ValueError(f"{dem_path}: EF5 reads the ASCII header as {want} in this order "
                             f"(key names ignored); found {keys}. Rewrite the header: xllcenter/"
                             f"yllcenter would be read as corners, and a missing NODATA_value "
                             f"line shifts every value")
        return
    with rasterio.open(dem_path) as src:
        if src.driver == "GTiff":
            if str(src.tags().get("AREA_OR_POINT", "Area")).lower() == "point":
                raise ValueError(f"{dem_path}: PixelIsPoint GeoTIFF. EF5 reads the raw tiepoint as "
                                 f"the upper-left corner (TifGrid.cpp), rasterio shifts it by half a "
                                 f"cell; rewrite the DEM as PixelIsArea first")
            gcps, _ = src.gcps
            if gcps:
                raise ValueError(f"{dem_path}: GCP-georeferenced GeoTIFF is not supported by EF5")
            transform = src.transform
            # EF5 uses tiepoint X/Y as the upper-left corner and ignores the
            # raster I/J offsets; it needs one tiepoint + a pixel scale.
            tie, scale, model_tr = _raw_tiff_georef(dem_path)
            if model_tr is not None or tie is None or scale is None:
                raise ValueError(f"{dem_path}: EF5 needs a ModelTiepoint + ModelPixelScale GeoTIFF "
                                 f"(no ModelTransformation); rewrite the DEM")
            if len(tie) != 6 or tie[0] != 0 or tie[1] != 0:
                raise ValueError(f"{dem_path}: GeoTIFF tiepoint {tie} is not one tiepoint at raster "
                                 f"(0,0); EF5 ignores the raster offset and would misplace the DEM")
            if len(scale) < 2 or scale[0] != scale[1]:
                raise ValueError(f"{dem_path}: EF5 needs square pixels, ModelPixelScale {scale}")
            if not np.allclose([tie[3], tie[4], scale[0], -scale[1]],
                               [transform.c, transform.f, transform.a, transform.e],
                               rtol=0., atol=1e-12):
                raise ValueError(f"{dem_path}: raw GeoTIFF origin ({tie[3]}, {tie[4]}) differs from "
                                 f"the georeference GDAL reports ({transform.c}, {transform.f}); "
                                 f"EF5 uses the raw one, so rewrite the DEM")
        elif src.driver != "AAIGrid":
            raise ValueError(f"{dem_path}: EF5 reads DEMs only as .asc or .tif (driver {src.driver})")


def _ef5_dem_valid(dem_path):
    """DEM cells EF5 counts as data. EF5 reads raw pixels (TifGrid.cpp /
    AscGrid.cpp, as float) and only compares them with the numeric NoData
    (GDAL_NODATA tag or the ASCII NODATA_value, as float; no tag -> NaN, so
    every cell counts; BasicGrids.cpp `data == noData`). Internal/per-dataset
    masks are ignored by EF5, so they are ignored here too. NoData is taken
    from the file itself, never from GDAL (which may use a .aux.xml sidecar)."""
    import rasterio
    with rasterio.open(dem_path) as src:
        raw = src.read(1, masked=False).astype(np.float32)
    if str(dem_path).lower().endswith(".asc"):
        with open(dem_path) as fh:
            text = [fh.readline().split() for _ in range(6)][5]
        nodata_text = text[1] if len(text) > 1 else None
    else:
        nodata_text = _raw_tiff_georef(dem_path, with_nodata=True)[3]
    if nodata_text is None:
        nodata = None
    else:
        try:
            nodata = float(nodata_text.strip())
        except ValueError:
            raise ValueError(f"{dem_path}: NoData value {nodata_text!r} is not a number")
    valid = np.ones(raw.shape, dtype=bool) if nodata is None else (raw != np.float32(nodata))
    if not np.isfinite(raw[valid]).all():
        cell = np.argwhere(valid & ~np.isfinite(raw))[0].tolist()
        raise ValueError(f"{dem_path}: non-finite DEM value at row/column {cell} that EF5 would "
                         f"count as data (it is not the numeric NoData {nodata})")
    return valid


def _domain_mask(shape, transform, crs, dem_path=None, model="crest"):
    """Cells EF5 itself will read for valid DEM cells; NoData is never treated as soil.

    CREST (CRESTModel.cpp InitializeParameters): a grid with the DEM's
    row/column count (Grid::IsSpatialMatch) is read by the node's own row and
    column, with no georeference; any other grid by GetGridLoc(node->refLoc).
    SAC-SMA (SAC.cpp InitializeParameters) always uses GetGridLoc(node->refLoc).
    """
    if dem_path is None:
        return np.ones(shape, dtype=bool)
    _check_ef5_dem_georef(dem_path)
    dem, dem_transform, dem_crs = _read_spatial(dem_path)
    if dem_crs != crs:
        raise ValueError("soil CRS differs from DEM CRS")
    rows, cols = np.where(_ef5_dem_valid(dem_path))
    if not len(rows):
        raise ValueError("DEM has no active cells")
    mask = np.zeros(shape, dtype=bool)
    if model == "crest" and tuple(shape) == tuple(dem.shape):
        if not dem_transform.almost_equals(transform, precision=1e-9):
            raise ValueError("grid has the DEM's row/column count but another georeference: "
                             "EF5 CREST reads such a grid by row/column, so it must share the "
                             "DEM's transform")
        mask[rows, cols] = True
        return mask
    r, c, inside = _ef5_lookup(dem_transform, rows, cols, transform, shape)
    if not inside.all():
        raise ValueError("soil grid does not cover every active DEM node (EF5 corner lookup)")
    mask[r, c] = True
    return mask


def _validate_texture(sand, silt, clay, active):
    arrays = [np.asarray(v) for v in (sand, silt, clay)]
    if any(v.shape != active.shape for v in arrays) or not active.any():
        raise ValueError("soil texture grids must share shape and have active cells")
    for name, arr in zip(("sand", "silt", "clay"), arrays):
        bad = active & (~np.isfinite(arr) | (arr < 0) | (arr > 100))
        if bad.any():
            cell = np.argwhere(bad)[0].tolist()
            raise ValueError(f"{name}: missing/invalid texture at active row/column {cell}")
    total = sum(arrays)
    # Percentages are provided to whole/decimal percent precision; allow only
    # rounding error, never renormalize or supply a made-up texture.
    bad = active & ~np.isclose(total, 100., rtol=0., atol=.1)
    if bad.any():
        raise ValueError(f"soil texture must sum to 100 percent at {np.argwhere(bad)[0].tolist()}")


# ---------------------------------------------------------------------------
# Grid I/O
# ---------------------------------------------------------------------------
def read_grid(filepath):
    """Read ASC or TIF grid."""
    if filepath.endswith(".asc"):
        return read_asc_grid(filepath)
    elif filepath.endswith(".tif") or filepath.endswith(".tiff"):
        return read_tif_grid(filepath)
    return None


def read_asc_grid(filepath):
    """Read ESRI ASCII grid."""
    with open(filepath, "r") as f:
        header = {}
        for _ in range(6):
            parts = f.readline().strip().split()
            if len(parts) >= 2:
                header[parts[0].lower()] = float(parts[1])
        ncols = int(header.get("ncols", 0))
        nrows = int(header.get("nrows", 0))
        nodata = header.get("nodata_value", -9999)
        data = np.loadtxt(f, dtype=np.float32).reshape(nrows, ncols)
        data[data == nodata] = np.nan
    return data


def read_tif_grid(filepath):
    """Read float32 GeoTIFF."""
    try:
        from osgeo import gdal
        ds = gdal.Open(filepath)
        if not ds:
            return None
        band = ds.GetRasterBand(1)
        data = band.ReadAsArray().astype(np.float32)
        nd = band.GetNoDataValue()
        if nd is not None:
            data[data == nd] = np.nan
        gt = ds.GetGeoTransform()
        ds = None
        return data
    except ImportError:
        try:
            import rasterio
            with rasterio.open(filepath) as src:
                data = src.read(1).astype(np.float32)
                if src.nodata is not None:
                    data[data == src.nodata] = np.nan
                return data
        except ImportError:
            print("[ERROR] GDAL or rasterio required", file=sys.stderr)
            return None


def write_tif_grid(filepath, data, geo_transform, nodata=-9999.0, *, crs=None):
    """Write a striped float32 GeoTIFF with verified source spatial metadata."""
    from rasterio.transform import Affine
    _check_georef(Affine.from_gdal(*geo_transform), crs, filepath)
    if np.isinf(data).any():
        raise ValueError("infinite parameter grid values")
    try:
        from osgeo import gdal, osr
        nrows, ncols = data.shape
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(filepath, ncols, nrows, 1, gdal.GDT_Float32)
        ds.SetGeoTransform(geo_transform)
        srs = osr.SpatialReference()
        srs.ImportFromWkt(crs.to_wkt())
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        out = data.copy()
        out[np.isnan(out)] = nodata
        band.WriteArray(out)
        ds.FlushCache()
        ds = None
    except ImportError:
        # EF5 loads *_grid parameter files ONLY through ReadFloatTifGrid
        # (src/Simulator.cpp InitializeGridParams -> src/TifGrid.cpp: float32
        # IEEE, STRIPED GeoTIFF with a GDAL_NODATA tag). The project python env
        # has no osgeo bindings, so the former ASC fallback silently produced
        # files EF5 cannot open ("Failed to load water balance parameter grid
        # ..."). Write the same striped float32 GeoTIFF with rasterio instead.
        try:
            import rasterio
            from rasterio.transform import Affine
        except ImportError:
            raise RuntimeError(
                "GDAL or rasterio is required: EF5 reads *_grid files only as "
                "float32 GeoTIFF (ASC parameter grids are NOT supported by "
                "src/TifGrid.cpp).")
        nrows, ncols = data.shape
        out = data.astype(np.float32).copy()
        out[np.isnan(out)] = nodata
        tr = Affine.from_gdal(*geo_transform)
        with rasterio.open(filepath, "w", driver="GTiff", height=nrows, width=ncols,
                           count=1, dtype="float32", crs=crs, transform=tr,
                           nodata=nodata, tiled=False) as dst:
            dst.write(out, 1)


def build_hwsd_texture_grids(dem_path, soil_dir, hwsd_raster=None, hwsd_csv=None,
                             margin_deg=0.05, hwsd_crs=None, model="crest"):
    """Derive sand/clay/silt (%) GeoTIFFs over the DEM extent from HWSD v1.2.

    Uses the same HWSD raster (MU_GLOBAL, 30 arcsec) + HWSD_DATA.csv that
    ki_tools_common.soil_utils.lookup_hwsd uses point-wise, but reads the
    window ONCE (lookup_hwsd re-reads the CSV per point, far too slow for a
    grid). Per mapping unit the dominant component (max SHARE) supplies
    T_SAND/T_SILT/T_CLAY. Missing/invalid units on the cells EF5 will read
    (see _domain_mask: DEM node upper-left corners for `model`) stop
    conversion. Grids are written on the HWSD window grid with their own
    georeference; EF5 samples parameter grids by lat/lon (CRESTModel.cpp
    InitializeParameters -> grid->GetGridLoc) so they need not match the DEM
    cell size.
    """
    import rasterio
    from rasterio.windows import from_bounds
    try:
        from ki_tools_common import soil_utils as _su
        hwsd_raster = hwsd_raster or _su.HWSD_RASTER
        hwsd_csv = hwsd_csv or _su.HWSD_CSV
    except ImportError:
        pass
    if not (hwsd_raster and os.path.isfile(hwsd_raster)):
        raise FileNotFoundError(f"HWSD raster not found: {hwsd_raster}")
    declare_crs(hwsd_raster, hwsd_crs)
    if not (hwsd_csv and os.path.isfile(hwsd_csv)):
        raise FileNotFoundError(f"HWSD_DATA.csv not found: {hwsd_csv}")
    if not np.isfinite(margin_deg) or margin_deg < 0:
        raise ValueError("margin_deg must be finite and nonnegative")
    with rasterio.open(dem_path) as d:
        _check_georef(d.transform, _effective_crs(dem_path, d.crs), dem_path)
        w, s, e, n = d.bounds
    with rasterio.open(hwsd_raster) as src:
        win = from_bounds(w - margin_deg, s - margin_deg, e + margin_deg,
                          n + margin_deg, src.transform).round_offsets().round_lengths()
        _check_georef(src.transform, _effective_crs(hwsd_raster, src.crs), hwsd_raster)
        # Boundless reads retain the requested window transform at data edges;
        # absent source coverage remains masked and is rejected if active.
        mu = src.read(1, window=win, boundless=True, masked=True).astype('float64').filled(np.nan)
        tr = src.window_transform(win)
        crs = _effective_crs(hwsd_raster, src.crs)
    active = _domain_mask(mu.shape, tr, crs, dem_path, model=model)
    if not np.isfinite(mu[active]).all():
        raise ValueError("HWSD mapping units missing on active DEM cells")
    import pandas as pd
    df = pd.read_csv(hwsd_csv, low_memory=False,
                     usecols=["MU_GLOBAL", "SHARE", "T_SAND", "T_SILT", "T_CLAY"])
    df = df.sort_values("SHARE", ascending=False).drop_duplicates("MU_GLOBAL")
    lut = {int(r.MU_GLOBAL): (r.T_SAND, r.T_SILT, r.T_CLAY) for r in df.itertuples()}
    out = {k: np.full(mu.shape, np.nan, dtype=np.float32) for k in ("sand", "silt", "clay")}
    for u in np.unique(mu[active]):
        vals = lut.get(int(u))
        if u != int(u) or vals is None:
            raise ValueError(f"HWSD mapping unit {u}: no dominant texture row for active DEM cells")
        m = active & (mu == u)
        out["sand"][m], out["silt"][m], out["clay"][m] = vals
    _validate_texture(out["sand"], out["silt"], out["clay"], active)
    os.makedirs(soil_dir, exist_ok=True)
    gt = list(tr.to_gdal())
    for k, arr in out.items():
        write_tif_grid(os.path.join(soil_dir, f"{k}.tif"), arr, gt, crs=crs)
    print(f"[OK] HWSD texture grids {mu.shape}: {int(active.sum())} source-backed active cells")
    return gt


def write_asc_grid(filepath, data, xll=0.0, yll=0.0, cellsize=0.1, nodata=-9999.0):
    """Write ESRI ASCII grid."""
    nrows, ncols = data.shape
    out = data.copy()
    out[np.isnan(out)] = nodata
    with open(filepath, "w") as f:
        f.write(f"ncols         {ncols}\n")
        f.write(f"nrows         {nrows}\n")
        f.write(f"xllcorner     {xll}\n")
        f.write(f"yllcorner     {yll}\n")
        f.write(f"cellsize      {cellsize}\n")
        f.write(f"NODATA_value  {nodata}\n")
        for row in range(nrows):
            f.write(" ".join(f"{v:.4f}" for v in out[row]) + "\n")


# ---------------------------------------------------------------------------
# Parameter derivation
# ---------------------------------------------------------------------------
def compute_crest_params(sand_pct, clay_pct, silt_pct, depth_cm, urban_pct=None, impervious="grid"):
    """
    Derive CREST parameter grids from soil texture percentages and depth.

    Parameters
    ----------
    sand_pct : ndarray — Sand percentage (0-100)
    clay_pct : ndarray — Clay percentage (0-100)
    silt_pct : ndarray — Silt percentage (0-100)
    depth_cm : ndarray or float — Soil depth in cm
    urban_pct : ndarray or None — Urban land cover percentage for IM

    Returns
    -------
    dict of parameter name -> ndarray
    """
    # Determine texture class per pixel (simplified)
    # Using Rawls pedotransfer functions
    _validate_texture(sand_pct, silt_pct, clay_pct, np.ones(np.shape(sand_pct), dtype=bool))
    total = sand_pct + clay_pct + silt_pct
    sand_frac = sand_pct / total
    clay_frac = clay_pct / total

    # Porosity from Rawls: theta_s = 0.332 - 7.251e-4*sand + 0.1276*log10(clay)
    porosity = 0.332 - 7.251e-4 * sand_pct + 0.1276 * np.log10(np.clip(clay_pct, 1, 100))
    porosity = np.clip(porosity, 0.2, 0.6)

    # WM = porosity * depth (converted to mm)
    depth_mm = np.float32(depth_cm) * 10.0 if isinstance(depth_cm, (int, float)) else depth_cm * 10.0
    wm = porosity * depth_mm
    wm = np.clip(wm, 10.0, 2000.0)

    # B exponent: Cosby (1984): B = 3.10 + 15.7*clay_frac - 0.3*sand_frac
    # (Clapp-Hornberger b, range ~2.8-18), scaled /10 to the CREST VIC-curve
    # range (0.1-1.5, cf. TEXTURE_TO_B above). The scale-down MUST precede the
    # clip: clipping the raw Cosby b to [0.01, 2.0] first pinned it at 2.0 for
    # every texture (raw b >= 2.8 always) and the /10 then made B == 0.2
    # everywhere, i.e. the grid carried no texture information.
    b = 3.10 + 15.7 * clay_frac - 0.3 * sand_frac
    b = b / 10.0  # Scale down from Cosby raw
    b = np.clip(b, 0.05, 1.5)

    # Ksat from Cosby: log10(Ksat) = -0.6 + 1.26*sand_frac - 0.64*clay_frac (cm/hr)
    log_ksat = -0.6 + 1.26 * (sand_pct / 100.0) - 0.64 * (clay_pct / 100.0)
    ksat = np.power(10.0, log_ksat) * 10.0  # cm/hr -> mm/hr
    ksat = np.clip(ksat, 0.01, 500.0)

    # IM: impervious area. The stated option decides the source: 'zero' is
    # zero everywhere even if an urban grid exists; 'grid' needs the grid.
    if impervious == "zero":
        im = np.zeros_like(wm)
    elif impervious != "grid":
        raise ValueError(f"unknown impervious option: {impervious!r} (use 'grid' or 'zero')")
    elif urban_pct is None:
        raise ValueError("no urban/impervious grid (urban.tif or impervious.tif in --soil-dir); "
                         "pass --impervious zero to state that IM is 0 everywhere")
    else:
        im = np.clip(urban_pct, 0, 100).astype(np.float32)

    return {
        "wm": wm.astype(np.float32),
        "b": b.astype(np.float32),
        "im": im.astype(np.float32),
        "ksat": ksat.astype(np.float32),
    }


def compute_sac_params(sand_pct, clay_pct, silt_pct, depth_cm):
    """
    Derive SAC-SMA parameter grids from soil texture.

    Uses Anderson (2002) pedotransfer relationships for SAC-SMA.
    """
    _validate_texture(sand_pct, silt_pct, clay_pct, np.ones(np.shape(sand_pct), dtype=bool))
    total = sand_pct + clay_pct + silt_pct
    sand_frac = sand_pct / total
    clay_frac = clay_pct / total

    porosity = 0.332 - 7.251e-4 * sand_pct + 0.1276 * np.log10(np.clip(clay_pct, 1, 100))
    porosity = np.clip(porosity, 0.2, 0.6)

    depth_mm = np.float32(depth_cm) * 10.0 if isinstance(depth_cm, (int, float)) else depth_cm * 10.0

    # Upper zone: ~top 20% of soil
    uz_depth = depth_mm * 0.2
    uztwm = porosity * uz_depth * 0.6  # tension water
    uzfwm = porosity * uz_depth * 0.3  # free water

    # Lower zone: ~bottom 80% of soil
    lz_depth = depth_mm * 0.8
    lztwm = porosity * lz_depth * 0.5
    lzfsm = porosity * lz_depth * 0.15
    lzfpm = porosity * lz_depth * 0.20

    # Withdrawal rates from texture
    uzk = np.clip(0.2 + 0.3 * sand_frac, 0.1, 0.7)
    lzsk = np.clip(0.02 + 0.1 * sand_frac, 0.01, 0.3)
    lzpk = np.clip(0.005 + 0.02 * sand_frac, 0.001, 0.05)

    return {
        "uztwm": np.clip(uztwm, 1, 500).astype(np.float32),
        "uzfwm": np.clip(uzfwm, 1, 200).astype(np.float32),
        "uzk": uzk.astype(np.float32),
        "lztwm": np.clip(lztwm, 1, 1000).astype(np.float32),
        "lzfsm": np.clip(lzfsm, 1, 500).astype(np.float32),
        "lzfpm": np.clip(lzfpm, 1, 1000).astype(np.float32),
        "lzsk": lzsk.astype(np.float32),
        "lzpk": lzpk.astype(np.float32),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def convert_params(soil_dir, output_dir, model="crest", dem_path=None, depth_cm=100,
                   hwsd=False, dem_crs=None, hwsd_crs=None, impervious="grid"):
    """
    Convert soil property grids to EF5 parameter grids.

    Parameters
    ----------
    soil_dir : str — Directory with sand.tif, clay.tif, silt.tif
    output_dir : str — Output directory for parameter grids
    model : str — "crest" or "sac"
    dem_path : str — DEM file for geo-reference
    depth_cm : float — Soil depth in cm (default 100)
    hwsd : bool — build sand/clay/silt.tif in soil_dir from HWSD over the
        DEM extent first (requires dem_path; see build_hwsd_texture_grids)
    dem_crs, hwsd_crs : str — explicit CRS ("EPSG:4326") for a DEM / HWSD raster
        that carries none. Never inferred; a file's own CRS is never overridden.
    """
    try:
        import rasterio
        if dem_path:
            declare_crs(dem_path, dem_crs)
        if model not in PARAM_RANGES:
            raise ValueError(f"unknown model: {model}")
        if not np.isfinite(depth_cm) or depth_cm <= 0:
            raise ValueError("depth_cm must be finite and positive")
        if hwsd:
            if not dem_path:
                raise ValueError("--hwsd requires --dem to define the active domain")
            build_hwsd_texture_grids(dem_path, soil_dir, hwsd_crs=hwsd_crs, model=model)
        if impervious not in ("grid", "zero"):
            raise ValueError(f"unknown impervious option: {impervious!r} (use 'grid' or 'zero')")
        if not validate_inputs(soil_dir, dem_path, output_dir):
            return False
        arrays = {}
        metadata = None
        # The urban grid is read only when it is the requested IM source
        # (CREST with --impervious grid); a stale one never overrides 'zero'
        # and never blocks a run that does not use it.
        names = ["sand", "clay", "silt"]
        if model == "crest" and impervious == "grid":
            names.append("urban")
        for name in names:
            candidates = [Path(soil_dir)/(name + ext) for ext in (".tif", ".tiff", ".asc")]
            if name == "urban":
                candidates.append(Path(soil_dir)/"impervious.tif")
            path = next((p for p in candidates if p.is_file()), None)
            if path is None:
                if name in ("sand", "clay"):
                    raise FileNotFoundError(f"missing required {name} grid in {soil_dir}")
                continue
            data, transform, crs = _read_spatial(path)
            current = (data.shape, transform, crs)
            if metadata is not None and current != metadata:
                raise ValueError(f"{name} grid is not aligned with sand grid (shape/transform/CRS)")
            metadata = current
            arrays[name] = data
        shape, transform, crs = metadata
        sand, clay = arrays["sand"], arrays["clay"]
        silt = arrays.get("silt", 100. - sand - clay)
        active = _domain_mask(shape, transform, crs, dem_path, model=model)
        _validate_texture(sand, silt, clay, active)
        urban = arrays.get("urban")
        if urban is not None:
            vals = urban[active]
            if not np.isfinite(vals).all() or np.any((vals < 0) | (vals > 100)):
                raise ValueError("urban: missing/invalid percentage on active cells")
        # Compute only on verified cells. Outside-domain NoData stays NoData.
        if model == "crest":
            computed = compute_crest_params(sand[active], clay[active], silt[active], depth_cm,
                                             urban[active] if urban is not None else None,
                                             impervious=impervious)
        else:
            computed = compute_sac_params(sand[active], clay[active], silt[active], depth_cm)
        if not all(validate_param_grid(v, k, PARAM_RANGES[model][k]) for k, v in computed.items()):
            return False
        os.makedirs(output_dir, exist_ok=True)
        for name, values in computed.items():
            data = np.full(shape, np.nan, dtype=np.float32)
            data[active] = values
            path = os.path.join(output_dir, name + ".tif")
            write_tif_grid(path, data, list(transform.to_gdal()), crs=crs)
            print(f"[OK] Wrote {path}")
        import json as _json
        prov = {"model": model, "depth_cm": depth_cm, "hwsd": bool(hwsd),
                "silt_source": "grid" if "silt" in arrays else "100 - sand - clay",
                "im_source": ("urban grid" if impervious == "grid" else
                              "zero everywhere (--impervious zero)") if model == "crest" else "n/a"}
        if model == "crest" and impervious == "zero":
            # EF5 CRESTModel.cpp InitializeParameters turns grid zeros into 0.01
            # before multiplying by the scalar IM, so im.tif zeros alone are not
            # IM = 0 in the model.
            prov["ef5_config_required"] = ("set IM=0 in the CrestParamSet (with or without "
                                           "im_grid); with IM=0.01 EF5 runs IM=0.0001")
        with open(os.path.join(output_dir, "params_provenance.json"), "w") as fh:
            _json.dump(prov, fh, indent=2)
        print(f"[OK] Provenance: {prov}")
        return validate_outputs(output_dir, model, active_mask=active)
    except ImportError as exc:
        print(f"[ERROR] required raster dependency unavailable: {exc}", file=sys.stderr)
        return False
    except (ValueError, OSError, rasterio.errors.RasterioError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Convert soil data to EF5 parameter grids")
    parser.add_argument("--soil-dir", required=True, help="Directory with soil texture grids")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--model", default="crest", choices=["crest", "sac"])
    parser.add_argument("--dem", help="DEM file for geo-reference")
    parser.add_argument("--depth", type=float, default=100, help="Soil depth in cm")
    parser.add_argument("--hwsd", action="store_true",
                        help="Build sand/clay/silt.tif in --soil-dir from HWSD v1.2 over "
                             "the --dem extent first (HWSD_RASTER/HWSD_DATA.csv from "
                             "ki_tools_common.soil_utils)")
    parser.add_argument("--dem-crs", default=None,
                        help="Declare the CRS of a --dem that has none (e.g. dem.asc from "
                             "prepare_basic_grids). Only EPSG:4326 (EF5 PROJ=geographic).")
    parser.add_argument("--hwsd-crs", default=None,
                        help="Declare the CRS of the HWSD raster when it has none (the shared "
                             "hwsd.bil is WGS84 lon/lat without a .prj): EPSG:4326.")
    parser.add_argument("--impervious", choices=["grid", "zero"], default="grid",
                        help="CREST IM source: 'grid' needs urban.tif/impervious.tif in --soil-dir "
                             "(stops if absent); 'zero' states IM = 0 everywhere (recorded in "
                             "params_provenance.json)")
    args = parser.parse_args()

    success = convert_params(args.soil_dir, args.output_dir, args.model, args.dem, args.depth,
                             hwsd=args.hwsd, dem_crs=args.dem_crs, hwsd_crs=args.hwsd_crs,
                             impervious=args.impervious)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
