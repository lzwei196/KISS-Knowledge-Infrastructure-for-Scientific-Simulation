"""
ki_tools_common -- Shared utility library for the Knowledge Dissection Toolkit.

Consolidates duplicated code found across 435+ model tool scripts into 15
tested modules. Provides canonical implementations for unit conversions,
humidity calculations, NetCDF helpers, forcing data loading, soil property
lookup, land cover crosswalks, validation checks, performance metrics,
I/O helpers, forcing-source metadata, cross-platform binary execution,
debugging utilities, crop calendars, fertilizer rates, and observed yields.

Usage::

    from ki_tools_common import units, metrics, humidity, validation
    from ki_tools_common.units import convert, celsius_to_kelvin
    from ki_tools_common.metrics import nse, kge, all_metrics
    from ki_tools_common.load_forcing import load_daily_forcing, load_hourly_forcing
    from ki_tools_common.soil_utils import lookup_hwsd, rosetta_vgn
    from ki_tools_common.landcover import igbp_to_usgs
    from ki_tools_common.validation import validate_water_balance
    from ki_tools_common.cross_platform import detect_binary_type, run_binary
    from ki_tools_common.crop_calendar import get_planting_harvest
    from ki_tools_common.fertilizer import get_fertilizer_rates, get_split_schedule
    from ki_tools_common.crop_obs import get_observed_yield
    from ki_tools_common.terrain import get_terrain
    from ki_tools_common.climate_scenarios import harmonize, delta_perturbation, warming_levels

NOTE on climate_scenarios: importing ki_tools_common (this package, any
submodule) eagerly imports netCDF4 via netcdf_utils below. If a script
also needs to open raw ISIMIP3b/HiCPC files via
climate_scenarios/knowledge_infrastructure/lib/climate_sources_io.py
(standalone, h5netcdf-based), that file-opening MUST happen BEFORE this
package is imported in the same process -- see
ki_tools_common.climate_scenarios's docstring and
climate_sources_io.py's docstring for why (a verified HDF5 library ABI
clash between netCDF4 and h5py, not a flaky-filesystem issue).
"""

from ki_tools_common import (
    units,
    humidity,
    netcdf_utils,
    validation,
    metrics,
    io_helpers,
    forcing_sources,
    load_forcing,
    soil_utils,
    landcover,
    debug_framework,
    cross_platform,
    crop_calendar,
    fertilizer,
    crop_obs,
    terrain,
    climate_scenarios,
)

__version__ = "5.2.0"

__all__ = [
    "units",
    "humidity",
    "netcdf_utils",
    "validation",
    "metrics",
    "io_helpers",
    "forcing_sources",
    "load_forcing",
    "soil_utils",
    "landcover",
    "debug_framework",
    "cross_platform",
    "crop_calendar",
    "fertilizer",
    "crop_obs",
    "terrain",
    "climate_scenarios",
]
