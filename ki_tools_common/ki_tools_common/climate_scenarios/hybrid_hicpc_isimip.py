"""
hybrid_hicpc_isimip.py -- Framework §5.2 "Route 2: Full-forcing process
models" -- pairs HiCPC (pr/tas/tasmax/tasmin, 0.1deg China) with ISIMIP3b
(rsds/rlds/sfcWind/ps/hurs|huss, 0.5deg global) for the SAME GCM/member/SSP
to build one full-variable-set forcing product at HiCPC's resolution.

Pure xarray math over already-loaded arrays -- safe to import alongside
ki_tools_common. Raw file access is climate_sources_io.py (see that
module's docstring for the netCDF4/h5netcdf ordering constraint); load
both sources with that module FIRST, then pass the in-memory arrays here.

LOCAL DATA GAP: our ISIMIP3b copy has no prsn (snowfall) variable
(verified 2026-07-16), so the Framework §5.2 "Precipitation-phase
coupling" snow-fraction transfer (delta_perturbation.derive_snowfall_from_fraction)
cannot run end-to-end from local data alone. build_hybrid_forcing() below
accepts prsn_isimip as optional and clearly reports its absence rather
than fabricating a snow fraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import xarray as xr

from ki_tools_common.climate_scenarios import harmonize
from ki_tools_common.climate_scenarios.delta_perturbation import derive_snowfall_from_fraction

HICPC_NATIVE_VARIABLES = ("pr", "tas", "tasmax", "tasmin")
ISIMIP_AUXILIARY_VARIABLES = ("rsds", "rlds", "sfcwind", "ps", "hurs", "huss")


@dataclass
class HybridForcingResult:
    dataset: xr.Dataset
    warnings: list[str] = field(default_factory=list)


def regrid_isimip_to_hicpc_grid(da_isimip: xr.DataArray, target_lat: xr.DataArray, target_lon: xr.DataArray) -> xr.DataArray:
    """Framework §5.2 step 13: 'regrid ISIMIP auxiliary variables to 0.1deg'.

    Bilinear interpolation from ISIMIP3b's 0.5deg grid onto HiCPC's 0.1deg
    grid. Framework §5.1 'Regridding' rule: precipitation/snowfall need
    conservative remapping, everything else (temperature, humidity,
    pressure, wind, radiation) uses bilinear -- all Route-2 auxiliary
    variables (rsds, rlds, sfcWind, ps, hurs, huss) fall in the bilinear
    category, so a single interp() call is correct here. This does NOT
    create genuine 0.1deg information (Framework §5.1: 'Interpolating
    0.5deg data to 0.1deg creates a finer computational grid but does not
    create genuine 0.1deg meteorological information') -- callers must
    retain that distinction in metadata, which regrid_isimip_to_hicpc_grid
    does via the 'spatial_refinement_only' attr.
    """
    out = da_isimip.interp(lat=target_lat, lon=target_lon, method="linear", kwargs={"fill_value": "extrapolate"})
    out.attrs = dict(da_isimip.attrs)
    out.attrs["spatial_refinement_only"] = True
    out.attrs["regridding_method"] = "bilinear_interp_0.5deg_to_0.1deg"
    return out


def build_hybrid_forcing(
    pr_hicpc: xr.DataArray,
    tas_hicpc: xr.DataArray,
    tasmax_hicpc: xr.DataArray,
    tasmin_hicpc: xr.DataArray,
    aux_isimip: dict[str, xr.DataArray],
    prsn_isimip: xr.DataArray | None = None,
    pr_isimip: xr.DataArray | None = None,
) -> HybridForcingResult:
    """Framework §5.2 Route 2 hybrid builder.

    Args:
        pr_hicpc, tas_hicpc, tasmax_hicpc, tasmin_hicpc: HiCPC canonical-unit
            arrays, already on the same time axis.
        aux_isimip: dict of canonical-unit ISIMIP3b arrays keyed by
            'rsds','rlds','sfcWind','ps', and one of 'hurs'/'huss' --
            already regridded onto the HiCPC grid via
            regrid_isimip_to_hicpc_grid and time-aligned to pr_hicpc.
        prsn_isimip, pr_isimip: optional ISIMIP3b snowfall + precipitation
            (for the snow-fraction transfer). Framework §5.2
            'Precipitation-phase coupling' -- if either is missing (true
            for our local ISIMIP3b copy, which has no prsn), prsn is
            omitted from the output and a warning is recorded rather than
            fabricated.

    Returns:
        HybridForcingResult with the combined xr.Dataset and a list of
        warnings (e.g. missing prsn, missing humidity variable).
    """
    warnings: list[str] = []

    tas, tasmin, tasmax = harmonize.enforce_temperature_consistency(tas_hicpc, tasmin_hicpc, tasmax_hicpc)

    data_vars = {
        "pr": pr_hicpc,
        "tas": tas,
        "tasmin": tasmin,
        "tasmax": tasmax,
    }

    for v in ("rsds", "rlds", "sfcWind", "ps"):
        key = v if v in aux_isimip else v.lower()
        if key in aux_isimip:
            data_vars[v] = aux_isimip[key]
        else:
            warnings.append(f"aux_isimip is missing {v!r} -- Route 2 output will not include it.")

    if "hurs" in aux_isimip:
        data_vars["hurs"] = aux_isimip["hurs"]
    elif "huss" in aux_isimip and "ps" in data_vars:
        data_vars["hurs"] = harmonize.huss_to_hurs(aux_isimip["huss"], tas, data_vars["ps"])
        warnings.append("hurs derived from huss+tas+ps (Framework §5.2 humidity coupling) -- huss was primary, not independently bias-adjusted alongside hurs (per the Framework's own rule against bias-adjusting both).")
    else:
        warnings.append("Neither 'hurs' nor 'huss'(+ps) available in aux_isimip -- no humidity variable in Route 2 output.")

    if prsn_isimip is not None and pr_isimip is not None:
        prsn_hybrid, pr_rain = derive_snowfall_from_fraction(pr_hicpc, pr_isimip, prsn_isimip)
        data_vars["prsn"] = prsn_hybrid
        data_vars["pr"] = pr_hicpc  # total precip unchanged; prsn is a phase split, not an addition
        warnings.append("prsn derived via snow-fraction transfer from ISIMIP3b.")
    else:
        warnings.append(
            "prsn NOT included -- ISIMIP3b prsn/pr not supplied (our local ISIMIP3b copy has no "
            "snowfall variable, verified 2026-07-16). Models needing explicit snowfall must source "
            "prsn separately or use a temperature-threshold rain/snow partition inside their own KI."
        )

    ds = xr.Dataset(data_vars)
    ds.attrs["forcing_mode"] = "direct_hybrid"
    ds.attrs["primary_source"] = "hicpc_v1_local"
    ds.attrs["auxiliary_source"] = "isimip3b_w5e5_local"

    range_problems = []
    for var in ds.data_vars:
        range_problems.extend(harmonize.validate_ranges(ds[var], var))
    warnings.extend(range_problems)

    return HybridForcingResult(dataset=ds, warnings=warnings)
