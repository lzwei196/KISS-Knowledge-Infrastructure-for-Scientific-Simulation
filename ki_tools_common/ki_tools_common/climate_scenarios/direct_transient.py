"""
direct_transient.py -- Mode A: direct transient GCM forcing (Framework
§4.1). Pure xarray math over already-loaded arrays -- safe to import
alongside ki_tools_common.

Framework §4.1 formula:
    Y_g,s(t) = M[F_g,historical+SSP_s(t), theta]
    Delta I_g,s,p = I_g,s,p - I_g,baseline
    "The baseline and future values must come from the same GCM forcing trajectory."

LOCAL DATA GAP (documented, not silently worked around): ISIMIP3b on this
server has NO 1850-2014 historical segment (verified 2026-07-16 -- see
registry/climate_sources/isimip3b.yaml, caveat isimip3b_no_historical).
concatenate_historical_and_ssp() below implements the general Framework
algorithm and works correctly once a historical DataArray is supplied
(e.g. from a future ISIMIP3b historical download, or another GCM archive
for the SAME GCM/member) -- it does not fabricate one. HiCPC files are
already continuous 1979-2100 (historical embedded by the data provider)
and do NOT need this function at all -- use them directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr


class InconsistentTrajectoryError(ValueError):
    """Historical and future segments do not share the same GCM/member, or overlap/gap in time."""


def concatenate_historical_and_ssp(
    historical: xr.DataArray, future: xr.DataArray, max_gap_days: int = 1
) -> xr.DataArray:
    """Framework §4.1 steps 1-3: concatenate matching GCM historical and SSP data, preserving
    the member identifier, for a continuous transient run.

    Enforces (rather than silently trusting) two Framework requirements:
      - same GCM AND member on both segments (a mismatched pair is not "the same GCM
        forcing trajectory" the Framework requires for baseline/future comparison);
      - no unexplained gap or overlap between the two segments' time axes.
    """
    hist_gcm = historical.attrs.get("gcm")
    fut_gcm = future.attrs.get("gcm")
    if hist_gcm and fut_gcm and hist_gcm != fut_gcm:
        raise InconsistentTrajectoryError(
            f"historical GCM={hist_gcm!r} != future GCM={fut_gcm!r}. Framework §4.1: "
            f"'The baseline and future values must come from the same GCM forcing trajectory' -- "
            f"never concatenate segments from two different GCMs."
        )
    hist_member = historical.attrs.get("member")
    fut_member = future.attrs.get("member")
    if hist_member and fut_member and hist_member != fut_member:
        raise InconsistentTrajectoryError(f"historical member={hist_member!r} != future member={fut_member!r}.")

    hist_end = pd.Timestamp(historical["time"].values[-1])
    fut_start = pd.Timestamp(future["time"].values[0])
    gap = (fut_start - hist_end).days
    if gap > max_gap_days + 1 or gap < 1:
        raise InconsistentTrajectoryError(
            f"historical segment ends {hist_end.date()}, future segment starts {fut_start.date()} "
            f"({gap} day gap; expected exactly 1 day for a daily series with no overlap/gap). "
            f"Framework §11.3: 'no unexplained jump at historical-SSP transition' starts with the "
            f"time axes actually being contiguous."
        )

    out = xr.concat([historical, future], dim="time")
    out.attrs = dict(future.attrs)
    out.attrs["forcing_mode"] = "direct_transient"
    return out


def compute_baseline(da: xr.DataArray, baseline_start: str, baseline_end: str) -> xr.DataArray:
    """Mean of da over the project baseline period (Framework §9 default: 1995-2014)."""
    sub = da.sel(time=slice(baseline_start, baseline_end))
    if sub.sizes.get("time", 0) == 0:
        raise ValueError(f"No data in baseline period {baseline_start}..{baseline_end} for this DataArray.")
    return sub.mean(dim="time")


def future_change(
    da: xr.DataArray, baseline_start: str, baseline_end: str, future_start: str, future_end: str
) -> xr.DataArray:
    """Framework §4.1: Delta I_g,s,p = I_g,s,p - I_g,baseline, both from the SAME continuous
    GCM trajectory (i.e. call this on the output of concatenate_historical_and_ssp, or
    directly on a HiCPC series which is already continuous).
    """
    baseline = compute_baseline(da, baseline_start, baseline_end)
    future_sub = da.sel(time=slice(future_start, future_end))
    if future_sub.sizes.get("time", 0) == 0:
        raise ValueError(f"No data in future period {future_start}..{future_end} for this DataArray.")
    delta = future_sub.mean(dim="time") - baseline
    delta.attrs = dict(da.attrs)
    delta.attrs["baseline_period"] = f"{baseline_start}:{baseline_end}"
    delta.attrs["future_period"] = f"{future_start}:{future_end}"
    return delta
