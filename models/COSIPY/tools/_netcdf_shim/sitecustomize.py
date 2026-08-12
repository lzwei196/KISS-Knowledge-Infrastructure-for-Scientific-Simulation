"""Auto-loaded shim that routes default-engine xarray netCDF I/O through h5netcdf.

Rationale (verified 2026-06-21): the shared HydroCraft ``python_env`` netCDF4
backend is broken on this host — reading *and* writing multi-variable netCDF
files raises ``OSError: [Errno -101] NetCDF: HDF error`` (libnetcdf 4.9.3 /
HDF5 1.14.6), while the ``h5netcdf`` backend reads and writes the very same
files fine. The COSIPY model (``COSIPY.py`` / ``cosipy/cpkernel/io.py``) calls
``xr.open_dataset`` / ``Dataset.to_netcdf`` with the default engine, so it
cannot run under this env unless the default engine is overridden.

``run_cosipy.py`` injects the directory of this file onto ``PYTHONPATH`` and sets
``COSIPY_FORCE_H5NETCDF=1`` before launching ``COSIPY.py`` as a subprocess.
Python auto-imports ``sitecustomize`` at interpreter startup, so this monkeypatch
is applied to the COSIPY process transparently — no edit to the model source.

If/when the python_env netCDF4 backend is repaired, simply stop setting
``COSIPY_FORCE_H5NETCDF`` and this shim becomes a no-op.
"""

import os

if os.environ.get("COSIPY_FORCE_H5NETCDF") == "1":
    try:
        import xarray as _xr

        _orig_open = _xr.open_dataset
        _orig_open_mf = _xr.open_mfdataset
        _orig_open_da = _xr.open_dataarray
        _orig_to = _xr.Dataset.to_netcdf

        def _force(kwargs):
            if kwargs.get("engine") is None:
                kwargs["engine"] = "h5netcdf"
            return kwargs

        def _open(*a, **k):
            return _orig_open(*a, **_force(k))

        def _open_mf(*a, **k):
            return _orig_open_mf(*a, **_force(k))

        def _open_da(*a, **k):
            return _orig_open_da(*a, **_force(k))

        def _to(self, *a, **k):
            # Only force when writing a real netCDF file (path given, no explicit
            # engine). Writing to an in-memory bytes object (path None) keeps the
            # default so we don't break the scipy/in-memory path.
            path = a[0] if a else k.get("path")
            if path is not None and k.get("engine") is None:
                k["engine"] = "h5netcdf"
            return _orig_to(self, *a, **k)

        _xr.open_dataset = _open
        _xr.open_mfdataset = _open_mf
        _xr.open_dataarray = _open_da
        _xr.Dataset.to_netcdf = _to
    except Exception:
        # Never let the shim crash the host process; fall back to defaults.
        pass
