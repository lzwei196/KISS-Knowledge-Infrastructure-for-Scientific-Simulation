#!/usr/bin/env python3
"""dt_v010 -- HDF5 load-order-safe NetCDF access for the CRHM KI.

Under the canonical interpreter (KISSPATH_PYTHON_ENV),
h5py 3.16.0 and netCDF4 1.7.4 each ship their OWN bundled libhdf5 (both
report 1.14.6). ``import xarray`` runs a backend-entrypoint scan that imports
h5netcdf -> h5py, so h5py's libhdf5 initialises FIRST; netCDF4's nc_open then
fails inside the second HDF5 instance with:

    OSError: [Errno -101] NetCDF: HDF error: <path>

Verified 2026-07-26 under python_env:
  * import xarray; xr.open_dataset(elev_CMFD_V0200_B-00_fx_010deg.nc) -> -101
  * import netCDF4 FIRST, then the same call -> opens, elev = 663.0 m
  * netCDF4.Dataset direct, unguarded        -> elev = 663.0 m
  * xr.open_dataset(..., engine="h5netcdf")  -> elev = 663.0 m
  * a .nc xarray itself WROTE is unreadable unguarded, readable guarded --
    so this also bites reading back the parsed CRHM NetCDF.

ki_tools_common.load_forcing is NOT affected: load_forcing.py:414-420 already
tries engine="h5netcdf" before the default, and h5netcdf rides h5py's libhdf5
-- the one that initialised. Verified: load_hourly_forcing("cmfd", 49.4,
120.4, 2009, 2009) returns 2920-point arrays with no guard. The exposure is
bare xr.open_dataset() calls with no engine ladder.

This module is the ONE implementation of both remedies for this KI. Every
entry point that will touch NetCDF imports it -- IMPORTING IT IS THE GUARD --
and nothing re-implements the read.

CONTRACT
========
Three public entry points -- ``open_dataset``, ``cell_value``,
``cmfd_cell_elevation`` -- and ALL THREE are bound by the two rules below.
``cmfd_cell_elevation`` delegates to ``cell_value``; ``cell_value`` falls back
to ``open_dataset``; each rule is enforced by ONE shared helper called from
every path, so the fallback can never accept what the primary path refuses.

RULE 1 -- grid geometry is checked, never guessed (``_grid_gate``).
  * A lat/lon coordinate pair that IS PRESENT must be 1-D (rectilinear).
    A 2-D / curvilinear pair raises ``UnsupportedGridError`` (a KeyError
    subclass) from every entry point, INCLUDING ``open_dataset``, which
    closes the dataset before raising rather than handing back an object
    this module will not index. Rationale: with 2-D coords,
    ``np.abs(latv - lat).argmin()`` returns a FLAT index into the 2-D array;
    using it as a row index either raises IndexError or -- when the flat
    index happens to be < nrows -- returns an ARBITRARY WRONG CELL. Probed
    2026-07-26 on a 40x3 curvilinear grid: true nearest cell (5,1) value 51,
    returned value 151 (cell (15,1)), no exception, no warning.
  * A file with NO lat/lon pair at all is NOT a rejection for
    ``open_dataset``: there is no grid to misinterpret. This is what keeps
    the time-only parsed CRHM output (docs/s5_execution_skill.md:112)
    readable. ``cell_value`` still rejects it -- there is nothing to index.
  * ``open_dataset(path, require_rectilinear=False)`` is the ONE documented
    way to obtain a Dataset for a geometry this module will not index. It is
    explicit at the call site, it is never the default, and no cell lookup
    uses it.
  * A structural rejection is NOT a fallback trigger: ``UnsupportedGridError``
    propagates out of ``cell_value`` untouched. xarray cannot rescue a grid
    geometry this module refuses to interpret, and retrying there would only
    convert a clear KeyError into a ValueError or a wrong number.

RULE 2 -- the data array must reduce to exactly (lat.size, lon.size)
(``_resolve_axes``, called by BOTH read paths).
  * Axes are resolved BY DIMENSION NAME, not by position, and the resolved
    lat/lon axis lengths must equal the lat/lon coordinate lengths. A
    positional peel cannot coincidentally land on a shape that matches.
  * Every remaining axis is taken at index 0 (elev is ("time","lat","lon")
    = (1,400,700)). A non-singleton extra axis is a warning, not a silent
    choice.
  * Anything that does not reduce this way -- no distinct lat/lon axis,
    mismatched axis length, a residual that is not scalar -- raises
    ``UnsupportedGridError`` on BOTH paths.

STDERR is written on exactly these occasions, and none of them is silent:
  1. netCDF4 is not importable, so the dt_v010 guard is INACTIVE -- warned by
     EVERY entry point, on EVERY call, under its OWN name. ``open_dataset``,
     ``cell_value`` AND ``cmfd_cell_elevation`` each call ``_guard_state``
     themselves; none of them relies on a callee's line to speak for it,
     because a delegated line names the helper, not the entry point the
     caller actually invoked. Delegation therefore STACKS lines
     (cmfd_cell_elevation -> cell_value -> open_dataset emits three), which
     is duplication, not silence. ``cmfd_cell_elevation`` warns BEFORE its
     file-existence check, so even a call ending in FileNotFoundError
     reports the guard state.
  2. the netCDF4-direct read failed and the xarray fallback is being used.
  3. ``open_dataset``'s default engine failed and a named engine succeeded.
  4. a non-singleton extra axis was taken at index 0.
"""

import os
import sys

DEFAULT_CMFD_ELEV = ("KISSPATH_DATA/elev/"
                     "elev_CMFD_V0200_B-00_fx_010deg.nc")

_LAT_NAMES = ("lat", "latitude", "y")
_LON_NAMES = ("lon", "longitude", "x")
_SKIP_VARS = set(_LAT_NAMES) | set(_LON_NAMES) | {"time", "time_bnds", "crs"}

try:                 # THE GUARD. Must stay at module level: importing this
    import netCDF4   # module is what callers rely on to win the libhdf5 race,
except ImportError:  # so it cannot be deferred into a function.
    netCDF4 = None


class UnsupportedGridError(KeyError):
    """Grid geometry this module refuses to guess at (2-D/curvilinear coords,
    no lat/lon variable, or a data array that does not reduce to (lat, lon)).

    Subclasses KeyError so the documented contract -- "raise KeyError rather
    than return a wrong cell" -- holds for callers that catch KeyError.
    Deliberately NOT caught by the xarray fallback in cell_value().
    """


def _warn(msg):
    """Single stderr channel for this module. The fallback is never silent."""
    sys.stderr.write("[netcdf_safe] %s\n" % msg)
    try:
        sys.stderr.flush()
    except Exception:
        pass


def ensure_netcdf4_first():
    """Idempotent. True when netCDF4's libhdf5 is initialised in this process."""
    global netCDF4
    if netCDF4 is None:
        try:
            import netCDF4 as _n
            netCDF4 = _n
        except ImportError:
            return False
    return True


def _guard_state(where, path):
    """Warn (never silently proceed) when the dt_v010 guard is INACTIVE.

    Called by every public entry point, so no caller can run unprotected
    without being told which entry point let it through.
    """
    if ensure_netcdf4_first():
        return True
    _warn("netCDF4 is not importable in this interpreter, so the dt_v010 "
          "load-order guard is INACTIVE in %s(%s); proceeding through xarray "
          "unprotected" % (where, path))
    return False


def _first(names, pool):
    for n in names:
        if n in pool:
            return n
    return None


def _grid_gate(path, names, get):
    """RULE 1, in one place. Used by open_dataset AND both read paths.

    ``names`` is the variable names present in the file; ``get`` maps a name
    to a numpy array. Returns (latn, latv, lonn, lonv), or four Nones when the
    file carries no lat/lon pair at all (no grid to misinterpret -- the caller
    decides whether that is fatal). Raises UnsupportedGridError when a pair IS
    present and either member is not 1-D, BEFORE any argmin can be taken.
    """
    import numpy as np
    latn = _first(_LAT_NAMES, names)
    lonn = _first(_LON_NAMES, names)
    if latn is None or lonn is None:
        return None, None, None, None
    latv = np.asarray(get(latn))
    lonv = np.asarray(get(lonn))
    if latv.ndim != 1 or lonv.ndim != 1:
        raise UnsupportedGridError(
            "curvilinear/2-D coordinate grid in %s: %s.ndim=%d %s.ndim=%d "
            "(only 1-D rectilinear lat/lon are supported; a flat argmin index "
            "would select an arbitrary cell)"
            % (path, latn, latv.ndim, lonn, lonv.ndim))
    return latn, latv, lonn, lonv


def _resolve_axes(path, name, dims, shape, latn, latv, lonn, lonv):
    """RULE 2, in one place. Used by BOTH read paths so they cannot diverge.

    Resolves the lat/lon axes of ``name`` BY DIMENSION NAME and verifies the
    array reduces to exactly (latv.size, lonv.size) once every other axis is
    taken at index 0. Returns (lat_dim, lon_dim, extra) where ``extra`` is the
    ordered [(dim, size)] of those other axes. Raises UnsupportedGridError
    otherwise -- never a positional guess.
    """
    size = dict(zip(dims, shape))
    latd = latn if latn in dims else _first(_LAT_NAMES, dims)
    lond = lonn if lonn in dims else _first(_LON_NAMES, dims)
    if latd is None or lond is None or latd == lond:
        raise UnsupportedGridError(
            "%s in %s has dims %r: no distinct lat/lon axis to index "
            "(need one of %r and one of %r)"
            % (name, path, tuple(dims), _LAT_NAMES, _LON_NAMES))
    if size[latd] != latv.size or size[lond] != lonv.size:
        raise UnsupportedGridError(
            "%s in %s does not reduce to (lat, lon): axis %r has length %d "
            "but the lat coordinate has %d, axis %r has length %d but the lon "
            "coordinate has %d"
            % (name, path, latd, size[latd], latv.size,
               lond, size[lond], lonv.size))
    extra = [(d, size[d]) for d in dims if d not in (latd, lond)]
    for d, n in extra:
        if n != 1:
            _warn("%s: %s has extra dimension %r of length %d; taking index 0 "
                  "of it" % (path, name, d, n))
    return latd, lond, extra


def _scalar(path, name, val):
    """Final reduction check shared by both paths: the residual is scalar."""
    import numpy as np
    a = np.asarray(val)
    if a.size != 1:
        raise UnsupportedGridError(
            "%s in %s did not reduce to a single cell: residual shape %r"
            % (name, path, tuple(a.shape)))
    return float(a.reshape(-1)[0])


def open_dataset(path, require_rectilinear=True, **kw):
    """xarray open with an engine ladder, netCDF4 pre-imported.

    Mirrors the idiom already proven on disk at
    ki_tools_common/load_forcing.py:414-420 (_open), which is why CMFD forcing
    reads survive this defect and a bare xr.open_dataset does not.

    Bound by RULE 1 like every other entry point: with the default
    ``require_rectilinear=True`` a curvilinear/2-D coordinate pair raises
    UnsupportedGridError and the dataset is CLOSED before raising, so this
    entry point cannot hand back a geometry cell_value would refuse. A file
    with no lat/lon pair (the time-only parsed CRHM output) opens normally.
    Pass ``require_rectilinear=False`` to deliberately obtain such a dataset
    for raw inspection -- explicit, never default, never used by a cell read.
    """
    _guard_state("open_dataset", path)
    import xarray as xr
    last = None
    for eng in (None, "netcdf4", "h5netcdf"):
        try:
            ds = (xr.open_dataset(path, **kw) if eng is None
                  else xr.open_dataset(path, engine=eng, **kw))
        except Exception as exc:
            last = exc
            continue
        if eng is not None:
            _warn("xr.open_dataset(%s) default engine failed (%s); succeeded "
                  "with engine=%r" % (path, last, eng))
        if require_rectilinear:
            try:
                _grid_gate(path, ds.variables, lambda n: ds[n].values)
            except BaseException:
                try:
                    ds.close()
                except Exception:
                    pass
                raise
        return ds
    raise last


def _cell_value_netcdf4(path, lat, lon, var=None):
    import numpy as np
    d = netCDF4.Dataset(path)
    try:
        latn, latv, lonn, lonv = _grid_gate(
            path, d.variables, lambda n: d.variables[n][:])
        if latn is None:
            raise UnsupportedGridError(
                "no lat/lon coordinate variable in %s" % path)
        name = var
        if name is None:
            cands = [k for k in d.variables if k not in _SKIP_VARS]
            if not cands:
                raise UnsupportedGridError("no data variable in %s" % path)
            name = cands[0]
        v = d.variables[name]
        dims = tuple(v.dimensions)
        latd, lond, _extra = _resolve_axes(
            path, name, dims, tuple(v.shape), latn, latv, lonn, lonv)
        i = int(np.abs(latv - lat).argmin())
        j = int(np.abs(lonv - lon).argmin())
        idx = tuple(i if dd == latd else j if dd == lond else 0 for dd in dims)
        return _scalar(path, name, v[idx])
    finally:
        try:
            d.close()
        except Exception:
            pass


def _cell_value_xarray(path, lat, lon, var=None):
    """The FALLBACK. Enforces the SAME two rules as the netCDF4 path, via the
    same helpers -- it must not accept a grid or a shape the primary refuses.
    """
    ds = open_dataset(path)          # RULE 1 gate fires inside open_dataset
    try:
        name = var or (list(ds.data_vars) or [None])[0]
        if name is None:
            raise UnsupportedGridError("no data variable in %s" % path)
        latn, latv, lonn, lonv = _grid_gate(
            path, ds.variables, lambda n: ds[n].values)
        if latn is None:
            raise UnsupportedGridError(
                "no lat/lon coordinate variable in %s" % path)
        da = ds[name]
        latd, lond, extra = _resolve_axes(
            path, name, tuple(da.dims), tuple(da.shape),
            latn, latv, lonn, lonv)
        if extra:
            da = da.isel(**{d: 0 for d, _n in extra})
        sel = da.sel(**{latd: lat, lond: lon}, method="nearest")
        return _scalar(path, name, sel.values)
    finally:
        try:
            ds.close()
        except Exception:
            pass


def cell_value(path, lat, lon, var=None):
    """Nearest-cell value at (lat, lon). netCDF4-direct FIRST, never xarray
    first; falls back to the engine ladder and ALWAYS says so on stderr.

    Raises UnsupportedGridError (a KeyError) for curvilinear/2-D coordinate
    grids and for arrays that do not reduce to (lat, lon), on EITHER path,
    instead of returning a wrong cell -- those rejections are structural and
    are NOT retried through xarray.
    """
    if _guard_state("cell_value", path):
        try:
            return _cell_value_netcdf4(path, lat, lon, var)
        except UnsupportedGridError:
            raise                       # structural: xarray cannot rescue it
        except Exception as exc:
            _warn("netCDF4-direct read of %s failed (%s); falling back to "
                  "xarray" % (path, exc))
    return _cell_value_xarray(path, lat, lon, var)


def cmfd_cell_elevation(lat, lon, path=None):
    """CMFD forcing-source cell elevation (m). 663.0 at (49.4 N, 120.4 E).

    A public entry point, so it reports the dt_v010 guard state ITSELF, under
    its own name, on EVERY call -- before the file-existence check and before
    delegating to cell_value. It does NOT let the delegated cell_value line
    stand in for it: that line names cell_value, so a caller who only ever
    called cmfd_cell_elevation would have to infer that its own lookup ran
    unprotected.
    """
    p = path or DEFAULT_CMFD_ELEV
    _guard_state("cmfd_cell_elevation", p)
    if not os.path.exists(p):
        raise FileNotFoundError("CMFD elevation grid not found: %s" % p)
    return cell_value(p, lat, lon)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="dt_v010 HDF5-load-order-safe NetCDF cell reader")
    ap.add_argument("--path", default=None,
                    help="NetCDF file (default: the CMFD elevation grid)")
    ap.add_argument("--var", default=None, help="variable name (default: first)")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    a = ap.parse_args()
    if a.path:
        print(cell_value(a.path, a.lat, a.lon, a.var))
    else:
        print(cmfd_cell_elevation(a.lat, a.lon))
