"""
climate_scenarios -- pure array/math layer for the climate-scenarios KI
(Framework: "General Framework for Applying Climate-Change Scenarios to
Process-Based Models", KISSPATH_DATA/Climate-Change Scenarios Framework.pdf).

Everything in this subpackage operates on ALREADY-LOADED xarray objects or
plain numpy arrays -- none of it opens raw ISIMIP3b/HiCPC NetCDF files.
Raw file access lives in the standalone, netCDF4-free
climate_scenarios/knowledge_infrastructure/lib/climate_sources_io.py
instead, for a documented reason: importing ki_tools_common (this package)
pulls in netCDF4 via netcdf_utils, and once netCDF4 is loaded in a
process, h5netcdf-engine opens of these particular files fail
deterministically (verified 2026-07-16 -- an HDF5 library ABI clash, not a
flaky filesystem issue). Any script needing both must open/load raw files
FIRST, then import ki_tools_common / this subpackage for unit conversion
and scenario math on the resulting in-memory arrays.

Modules:
    harmonize            -- canonical variable name/unit mapping (Framework §3.3)
    delta_perturbation    -- Mode B: observation-anchored perturbation (Framework §4.2)
    warming_levels         -- Mode C: global-warming-level windows (Framework §4.3)
    direct_transient       -- Mode A: continuous historical+SSP anomalies (Framework §4.1)
    qc                    -- QC gates (Framework §11)
    provenance             -- standardized run ID + metadata (Framework §13)
    uncertainty             -- ensemble uncertainty decomposition (Framework §12)
    hybrid_hicpc_isimip     -- Framework §5.2 Route 2 hybrid forcing builder
"""

# Submodules load on first use, matching the parent package. Importing one of
# these should not require the dependencies of its siblings.

import importlib as _importlib

_SUBMODULES = (
    "harmonize",
    "delta_perturbation",
    "warming_levels",
    "direct_transient",
    "qc",
    "provenance",
    "uncertainty",
    "hybrid_hicpc_isimip",
)


def __getattr__(name):
    if name in _SUBMODULES:
        module = _importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(_SUBMODULES)
__all__ = [
    "harmonize",
    "delta_perturbation",
    "warming_levels",
    "direct_transient",
    "qc",
    "provenance",
    "uncertainty",
    "hybrid_hicpc_isimip",
]
