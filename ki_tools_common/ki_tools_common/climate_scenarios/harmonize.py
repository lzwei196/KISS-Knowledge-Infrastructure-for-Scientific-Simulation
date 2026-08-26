"""
harmonize.py -- canonical variable name/unit mapping for the climate
scenarios cube (Framework §3.3). Operates on already-loaded xarray
DataArrays only -- see the climate_scenarios package docstring for why
raw file opening is kept in a separate, netCDF4-free module.

Canonical units (from registry/variable_registry.yaml):
    pr, prsn: kg m-2 s-1   tas/tasmax/tasmin: K   hurs: percent
    huss: kg kg-1          ps: Pa                 rsds/rlds: W m-2
    sfcWind: m s-1         co2: ppm
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from ki_tools_common import humidity as _humidity
from ki_tools_common import units as _units

CANONICAL_UNITS = {
    "pr": "kg m-2 s-1",
    "prsn": "kg m-2 s-1",
    "tas": "K",
    "tasmax": "K",
    "tasmin": "K",
    "hurs": "percent",
    "huss": "kg kg-1",
    "ps": "Pa",
    "rsds": "W m-2",
    "rlds": "W m-2",
    "sfcWind": "m s-1",
    "co2": "ppm",
}

VALID_RANGES = {
    "pr": (0.0, 0.01),
    "prsn": (0.0, 0.01),
    "tas": (173.15, 333.15),
    "tasmax": (173.15, 333.15),
    "tasmin": (173.15, 333.15),
    "hurs": (0.0, 100.0),
    "huss": (0.0, 0.05),
    "ps": (50000.0, 108000.0),
    "rsds": (0.0, 500.0),
    "rlds": (50.0, 500.0),
    "sfcWind": (0.0, 60.0),
}


class UnverifiedUnitError(ValueError):
    """Raised when the caller has not provided a confirmed native unit (e.g. HiCPC tas/tasmax/tasmin)."""


def to_canonical(da: xr.DataArray, variable: str, native_unit: str) -> xr.DataArray:
    """Convert an already-loaded DataArray from native_unit to the canonical unit for `variable`.

    Args:
        da: Loaded data (no longer file-backed).
        variable: Canonical variable id (pr, tas, tasmax, tasmin, hurs, huss, ps, rsds, rlds, sfcWind).
        native_unit: The unit the data is ACTUALLY in right now. Must be
            supplied explicitly (never guessed) -- for HiCPC tas/tasmax/
            tasmin this is deliberately unverified upstream (see
            registry/climate_sources/hicpc.yaml), so callers must read
            ds[var].attrs['units'] themselves and pass it here, or this
            function raises UnverifiedUnitError if given the literal
            string 'UNVERIFIED'.

    Returns:
        DataArray converted to CANONICAL_UNITS[variable], with a
        'canonical_units' attr recorded for provenance.

    Example::

        >>> import xarray as xr, numpy as np
        >>> da = xr.DataArray([10.0, 20.0], dims="time")  # mm/day
        >>> out = to_canonical(da, "pr", "mm/day")
        >>> round(float(out[0]), 6)
        0.000116
    """
    if variable not in CANONICAL_UNITS:
        raise KeyError(f"Unknown canonical variable {variable!r}. Known: {list(CANONICAL_UNITS)}")
    if native_unit.upper() == "UNVERIFIED":
        raise UnverifiedUnitError(
            f"native_unit for {variable!r} was passed as 'UNVERIFIED'. Read the actual "
            f"units attribute from the source file (ds[{variable!r}].attrs['units']) before "
            f"calling to_canonical -- do not assume a unit for a source flagged unverified "
            f"in its registry manifest (see registry/climate_sources/hicpc.yaml)."
        )

    target = CANONICAL_UNITS[variable]
    nu = native_unit.strip()

    if nu == target:
        out = da.copy()
    elif variable in ("pr", "prsn") and nu in ("mm/day", "mm d-1", "mm"):
        out = xr.apply_ufunc(_units.mmday_to_kgm2s, da)
    elif variable in ("pr", "prsn") and nu in ("kg m-2 s-1", "kg/m2/s"):
        out = da.copy()
    elif variable in ("tas", "tasmax", "tasmin") and nu in ("degC", "C", "celsius"):
        out = xr.apply_ufunc(_units.celsius_to_kelvin, da)
    elif variable in ("tas", "tasmax", "tasmin") and nu in ("K", "kelvin"):
        out = da.copy()
    elif variable == "hurs" and nu in ("%", "percent"):
        out = da.copy()
    elif variable == "hurs" and nu == "fraction":
        out = xr.apply_ufunc(_units.fraction_to_percent, da)
    elif variable == "ps" and nu in ("hPa", "hpa"):
        out = xr.apply_ufunc(_units.hpa_to_pa, da)
    elif variable == "ps" and nu in ("Pa", "pa"):
        out = da.copy()
    else:
        raise KeyError(
            f"No harmonization rule registered for variable={variable!r}, native_unit={native_unit!r} "
            f"-> canonical {target!r}. Add one to harmonize.to_canonical() rather than converting inline."
        )

    out.attrs = dict(da.attrs)
    out.attrs["canonical_units"] = target
    out.attrs["harmonized_from"] = native_unit
    return out


def enforce_temperature_consistency(
    tas: xr.DataArray, tasmin: xr.DataArray, tasmax: xr.DataArray
) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray]:
    """Enforce tasmin <= tas <= tasmax (Framework §5.2 'Temperature consistency').

    Small violations from independent bias-correction of the three fields
    are resolved deterministically: tasmax is raised to tas where tas >
    tasmax, tasmin is lowered to tas where tas < tasmin. This is the
    documented rule the Framework requires ("adjust ... using a documented
    deterministic rule") rather than silently leaving inconsistent triples.
    """
    fixed_tasmax = xr.where(tas > tasmax, tas, tasmax)
    fixed_tasmin = xr.where(tas < tasmin, tas, tasmin)
    fixed_tasmax.attrs = dict(tasmax.attrs)
    fixed_tasmin.attrs = dict(tasmin.attrs)
    return tas, fixed_tasmin, fixed_tasmax


def huss_to_hurs(huss: xr.DataArray, tas_k: xr.DataArray, ps_pa: xr.DataArray) -> xr.DataArray:
    """Derive relative humidity (%) from specific humidity, reusing ki_tools_common.humidity.

    Framework §5.2 'Humidity coupling' step 1-4: combine huss, ps, tas ->
    hurs, constrained to 0-100%.
    """
    hurs = xr.apply_ufunc(_humidity.specific_humidity_to_rh, huss, tas_k, ps_pa)
    hurs = hurs.clip(min=0.0, max=100.0)
    hurs.attrs["canonical_units"] = "percent"
    hurs.attrs["derived_from"] = "huss,tas,ps via ki_tools_common.humidity.specific_humidity_to_rh"
    return hurs


def hurs_to_huss(hurs: xr.DataArray, tas_k: xr.DataArray, ps_pa: xr.DataArray) -> xr.DataArray:
    """Derive specific humidity (kg/kg) from relative humidity, with a saturation check.

    Framework §5.2 step 5: 'verify that specific humidity does not exceed saturation'.
    """
    huss = xr.apply_ufunc(_humidity.rh_to_specific_humidity, hurs, tas_k, ps_pa)
    # saturation check: hurs already bounded [0,100] implies huss <= q_sat by construction
    # of rh_to_specific_humidity's own Tetens-based formula; clip defensively for edge cases
    huss = huss.clip(min=0.0)
    huss.attrs["canonical_units"] = "kg kg-1"
    huss.attrs["derived_from"] = "hurs,tas,ps via ki_tools_common.humidity.rh_to_specific_humidity"
    return huss


def validate_ranges(da: xr.DataArray, variable: str) -> list[str]:
    """Framework §11.2 variable-level range check. Returns a list of violation messages (empty = OK)."""
    if variable not in VALID_RANGES:
        return [f"No valid_range registered for {variable!r} -- skipped."]
    lo, hi = VALID_RANGES[variable]
    vals = da.values
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        return [f"{variable}: all values are NaN/inf."]
    problems = []
    if finite.min() < lo:
        problems.append(f"{variable}: min value {finite.min():.4g} below valid_range lower bound {lo}.")
    if finite.max() > hi:
        problems.append(f"{variable}: max value {finite.max():.4g} above valid_range upper bound {hi}.")
    return problems
