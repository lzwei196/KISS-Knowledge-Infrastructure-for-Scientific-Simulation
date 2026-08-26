#!/usr/bin/env python3
"""
Fetch an INDEPENDENT gridded 10 m ocean wind field for SWAN.

Pipeline stage: 3 - Wind forcing preparation (gridded source)
Pattern: validate_inputs -> process -> validate_outputs

Why this tool exists
--------------------
``docs/03_wind_forcing.md`` names "ERA5, CFSR, GFS" as the wind source and
SKILL.md's pipeline table lists ``convert_wind_forcing`` as the stage-3 tool,
but ``convert_wind_forcing`` only accepts STATION series.  With no gridded
ingest in ``tools/`` and no marine wind product in
``KISSPATH_DATA_KI/dataset_index.yaml``, a run at a buoy
site had exactly one wind option left: the buoy's own anemometer, broadcast as
a domain constant.  That makes the model's HIGHEST-sensitivity driver of HSIGN
an in-situ measurement taken AT the validation point, which is not an
independent hindcast (SWAN dag: influence.edges 'wind input field' -> 'HSIGN',
sensitivity_grade HIGH in deep/open water).

This tool closes that gap with a credential-free NOAA CoastWatch ERDDAP
griddap subset - the same route SKILL.md already documents for etopo180
bathymetry.

Source
------
``ccmp_31_LonPM180`` - RSS Cross-Calibrated Multi-Platform (CCMP) V3.1
6-hourly Level-4 ocean surface wind analysis, 0.25 deg global,
1993-01-02 .. 2024-01-31, variables ``uwnd``/``vwnd`` (m/s, "10 meters above
sea-surface", ``_FillValue`` -9999).  A fallback dataset id list is provided
because ERDDAP retires ids; the first that answers is used.

Traps handled
-------------
* The ERDDAP ``time`` variable advertises ``valid_min``/``valid_max`` in DAYS
  (325056..325074) while its values are SECONDS since 1970.  netCDF4's
  automatic valid-range masking therefore masks EVERY timestamp; the array
  reads back as ``[-- -- --]``.  This module reads with
  ``set_auto_mask(False)`` and applies ``_FillValue`` by hand.
* griddap resolves an off-axis ``(value)`` time constraint to the NEAREST
  available level rather than erroring, so asking for 03:00Z..09:00Z on a
  6-hourly analysis returns 06:00Z..12:00Z - the first requested hours are
  silently absent and the SWAN window is no longer covered.  The real axis is
  therefore PROBED by index (``.csv?time[0:1:1]`` and ``.csv?time[last]``) and
  the requested window is snapped OUTWARD onto it before any subset is built;
  chunk boundaries advance by a whole number of axis levels so every boundary
  stays on-axis.
* A full year is ~1460 time levels; requested in one shot the transfer is slow
  and a truncated body is indistinguishable from a short record.  The fetch is
  chunked (default 30 days) and cached per chunk.  A cached chunk is reused
  ONLY when its manifest sidecar records the identical request URL and domain
  AND the file itself still contains exactly the source time levels that chunk
  covers; anything else is discarded and refetched, so a reused cache directory
  cannot return a stale or short subset.
* Separately from the axis: this ERDDAP endpoint intermittently answers 200
  with a ZERO-length body for a request that is perfectly well formed and
  on-axis (observed repeatedly on 2026-08-09 for
  ``uwnd[(2020-01-02T00:00:00Z):1:(2020-01-03T00:00:00Z)]``, which succeeds on
  a later attempt).  The truncation is transient and unrelated to the time
  constraint, so ``_download`` retries with a ramp before the caller is told
  the dataset is dead - otherwise one flaky chunk silently demotes the whole
  fetch to a near-real-time fallback product.
* CCMP is an OCEAN analysis; cells masked over land come back as ``_FillValue``
  and would inject NaN into the SWAN field (SWAN then stops growing waves
  silently).  Land/missing cells are nearest-neighbour filled from the wet
  cells of the same time level, and the fill fraction is reported.
* CCMP is 6-hourly; SWAN's NONSTATIONARY wind grid carries a single ``[dt]``.
  ``interp_to_times`` linearly interpolates the U and V COMPONENTS (never
  speed/direction, which would rotate through the wrong quadrant).
"""

import datetime
import json
import os
import time
import urllib.request

import numpy as np

ERDDAP_BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap"

#: Candidate ERDDAP dataset ids, best first.  All are credential-free,
#: 10 m ocean winds on a regular lon/lat grid with -180..180 longitude.
WIND_DATASETS = (
    # (dataset_id, u_var, v_var, nominal_deg, nominal_hours, note)
    ("ccmp_31_LonPM180", "uwnd", "vwnd", 0.25, 6,
     "RSS CCMP V3.1 6-hourly L4 ocean surface winds, 1993-2024"),
    ("pifscCcmpDailyV21NRT_LonPM180", "uwnd", "vwnd", 0.25, 6,
     "CCMP V2.1 NRT 6-hourly, 2016-present"),
    ("erdNavgem05D10mWind_LonPM180", "wnd_ucmp_height_above_ground",
     "wnd_vcmp_height_above_ground", 0.5, 3,
     "NAVGEM 0.5 deg 10 m wind, 2013-present"),
)

FILL_VALUE = -9999.0


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def griddap_url(dataset_id, variables, t0, t1, lat0, lat1, lon0, lon1):
    """Build a griddap .nc subset URL for a [time][lat][lon] gridded dataset.

    ERDDAP wants the constraint list repeated per variable and the ``(value)``
    form for coordinate lookups; ``lat0``/``lon0`` must be the LOW edge because
    a descending range returns an error, not an empty set.
    """
    if lat1 < lat0:
        lat0, lat1 = lat1, lat0
    if lon1 < lon0:
        lon0, lon1 = lon1, lon0
    sub = (f"%5B({t0.strftime('%Y-%m-%dT%H:%M:%SZ')}):1:"
           f"({t1.strftime('%Y-%m-%dT%H:%M:%SZ')})%5D"
           f"%5B({lat0:.4f}):1:({lat1:.4f})%5D"
           f"%5B({lon0:.4f}):1:({lon1:.4f})%5D")
    query = ",".join(f"{v}{sub}" for v in variables)
    return f"{ERDDAP_BASE}/{dataset_id}.nc?{query}"


# ---------------------------------------------------------------------------
# Low-level chunk fetch
# ---------------------------------------------------------------------------

def _download(url, path, timeout=600, min_bytes=5000, attempts=8,
              backoff_s=15.0, max_backoff_s=120.0):
    """Download to ``path`` atomically; reject a short/empty body, then retry.

    ERDDAP answers 200 with a ZERO-length body when a streamed response is
    interrupted, so the size check is the only thing standing between a
    truncated download and a silently short wind record.  This is a TRANSIENT
    server-side truncation, not a malformed request: the same on-axis URL that
    returns 0 B returns a full subset on a later attempt, so the budget has to
    be large enough (8 attempts, 15 s ramp capped at 120 s ~= 8 min of
    patience) that a year-long fetch is not aborted by one bad few minutes.
    Measured 2026-08-09: five consecutive attempts on one chunk returned 0 B or
    503 over ~2.5 min, and the identical URL then served 13720 B three times in
    a row.  The truncation is
    transient, so a short body is retried before the caller is told the whole
    dataset is unusable - otherwise one flaky chunk demotes the reprocessed
    product to a near-real-time fallback.
    """
    tmp = path + ".part"
    last = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r, \
                    open(tmp, "wb") as f:
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    f.write(block)
            size = os.path.getsize(tmp)
            if size < min_bytes:
                raise RuntimeError(
                    f"ERDDAP returned only {size} B - a 200 with a short body "
                    "is a truncated stream, not a small subset")
            os.replace(tmp, path)
            return path
        except Exception as exc:
            last = exc
            if os.path.exists(tmp):
                os.remove(tmp)
            if attempt < attempts:
                wait = min(backoff_s * attempt, max_backoff_s)
                print(f"[WARNING] fetch attempt {attempt}/{attempts} failed "
                      f"({exc}); retrying in {wait:.0f} s")
                time.sleep(wait)
    raise RuntimeError(f"download failed after {attempts} attempts for {url}: {last}")


def read_wind_nc(path, u_var, v_var):
    """Read one downloaded chunk into (times, lat, lon, u, v).

    ``set_auto_mask(False)`` is mandatory: the ERDDAP ``time`` variable carries
    ``valid_min``/``valid_max`` expressed in DAYS while its values are SECONDS,
    so netCDF4's automatic valid-range masking blanks every timestamp.
    """
    import netCDF4 as nc4
    ds = nc4.Dataset(path)
    ds.set_auto_mask(False)
    try:
        tvar = ds.variables["time"]
        units = tvar.units
        if "since" not in units:
            raise ValueError(f"unexpected time units '{units}' in {path}")
        epoch_txt = units.split("since", 1)[1].strip().replace("Z", "")
        epoch = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                epoch = datetime.datetime.strptime(epoch_txt, fmt)
                break
            except ValueError:
                continue
        if epoch is None:
            raise ValueError(f"cannot parse time origin '{epoch_txt}'")
        scale = {"seconds": 1.0, "second": 1.0, "secs": 1.0,
                 "hours": 3600.0, "hour": 3600.0,
                 "days": 86400.0, "day": 86400.0}[units.split()[0].lower()]
        times = [epoch + datetime.timedelta(seconds=float(x) * scale)
                 for x in np.asarray(tvar[:], dtype=float)]

        lat_name = "latitude" if "latitude" in ds.variables else "lat"
        lon_name = "longitude" if "longitude" in ds.variables else "lon"
        lat = np.asarray(ds.variables[lat_name][:], dtype=float)
        lon = np.asarray(ds.variables[lon_name][:], dtype=float)

        def _field(name):
            arr = np.asarray(ds.variables[name][:], dtype=float)
            # Drop any degenerate singleton axis (NAVGEM carries an altitude
            # dimension between time and latitude).
            while arr.ndim > 3:
                axes = [i for i, s in enumerate(arr.shape) if s == 1]
                if not axes:
                    raise ValueError(
                        f"{name} has shape {arr.shape}; expected [time][lat][lon]")
                arr = np.squeeze(arr, axis=axes[0])
            fv = getattr(ds.variables[name], "_FillValue", FILL_VALUE)
            arr[arr == float(fv)] = np.nan
            arr[np.abs(arr) > 200.0] = np.nan
            return arr

        u = _field(u_var)
        v = _field(v_var)
    finally:
        ds.close()

    if u.shape != (len(times), lat.size, lon.size):
        raise ValueError(
            f"{path}: {u_var} shape {u.shape} != "
            f"({len(times)}, {lat.size}, {lon.size})")
    return times, lat, lon, u, v


# ---------------------------------------------------------------------------
# Source time axis
# ---------------------------------------------------------------------------

#: Probed axes, keyed by dataset id, so a multi-chunk fetch probes once.
_AXIS_CACHE = {}

#: Slack when COMPARING two timestamps that should be the same source level.
TIME_TOL_S = 60.0

#: Slack when deciding whether a requested edge is already ON the axis.  It has
#: to be tight: a generous tolerance would swallow a genuinely off-axis edge and
#: snap it INWARD, which is the failure this revision exists to remove.
SNAP_TOL_S = 1.0


def _download_text(url, timeout=120, attempts=3, backoff_s=5.0):
    """Fetch a short ERDDAP text response (used for axis probes)."""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            if not body.strip():
                raise RuntimeError("empty body")
            return body
        except Exception as exc:
            last = exc
            if attempt < attempts:
                time.sleep(backoff_s * attempt)
    raise RuntimeError(f"axis probe failed for {url}: {last}")


def _parse_iso(txt):
    txt = txt.strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(txt, fmt)
        except ValueError:
            continue
    raise ValueError(f"cannot parse ERDDAP timestamp '{txt}'")


def _csv_times(body):
    """Pull the timestamps out of a griddap .csv axis response.

    The body is ``time`` / ``UTC`` / one ISO stamp per line.
    """
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line in ("time", "UTC"):
            continue
        out.append(_parse_iso(line.split(",")[0]))
    if not out:
        raise ValueError("no timestamps in griddap axis response")
    return out


def probe_time_axis(ds_id, timeout=120, refresh=False):
    """Return ``(t_first, cadence, t_last)`` of the dataset's REAL time axis.

    The axis is read by INDEX (``time[0:1:1]`` and ``time[last]``), never by
    value, so the probe itself can never be off-axis.  Guessing the cadence
    from the catalogue blurb is not enough: the snap in :func:`snap_to_axis`
    has to reproduce the exact phase of the source, and only the source can
    supply it.
    """
    if not refresh and ds_id in _AXIS_CACHE:
        return _AXIS_CACHE[ds_id]
    head = _csv_times(_download_text(
        f"{ERDDAP_BASE}/{ds_id}.csv?time%5B0:1:1%5D", timeout=timeout))
    tail = _csv_times(_download_text(
        f"{ERDDAP_BASE}/{ds_id}.csv?time%5Blast%5D", timeout=timeout))
    if len(head) < 2:
        raise ValueError(f"{ds_id}: time axis has fewer than 2 levels")
    cadence = head[1] - head[0]
    if cadence.total_seconds() <= 0:
        raise ValueError(f"{ds_id}: non-increasing time axis")
    axis = (head[0], cadence, tail[-1])
    _AXIS_CACHE[ds_id] = axis
    return axis


def snap_to_axis(t_start, t_end, t_first, cadence, t_last):
    """Snap ``[t_start, t_end]`` OUTWARD onto the source axis.

    Outward, never inward: griddap answers an off-axis ``(value)`` with the
    NEAREST level, so a window that begins between two analyses comes back
    starting AFTER the caller's first hour and the SWAN record is short at the
    front with nothing in the response saying so.  Snapping down at the front
    and up at the back guarantees the returned levels bracket every target
    time, which is what :func:`interp_to_times` needs.
    """
    if t_end < t_start:
        t_start, t_end = t_end, t_start
    step = cadence.total_seconds()
    if t_start < t_first - datetime.timedelta(seconds=SNAP_TOL_S) or \
            t_end > t_last + datetime.timedelta(seconds=SNAP_TOL_S):
        raise ValueError(
            f"requested window {t_start}..{t_end} is not inside the source "
            f"record {t_first}..{t_last}")
    n0 = int(np.floor(((t_start - t_first).total_seconds() + SNAP_TOL_S) / step))
    n1 = int(np.ceil(((t_end - t_first).total_seconds() - SNAP_TOL_S) / step))
    n0 = max(n0, 0)
    n_last = int(round((t_last - t_first).total_seconds() / step))
    n1 = min(max(n1, n0), n_last)
    return (t_first + n0 * cadence, t_first + n1 * cadence)


def axis_levels(lo, hi, t_first, cadence):
    """Every source level in ``[lo, hi]`` - the exact set a subset must hold."""
    step = cadence.total_seconds()
    k0 = int(round((lo - t_first).total_seconds() / step))
    k1 = int(round((hi - t_first).total_seconds() / step))
    return [t_first + k * cadence for k in range(k0, k1 + 1)]


def _times_match(got, want, tol_s=TIME_TOL_S):
    if len(got) != len(want):
        return False
    return all(abs((a - b).total_seconds()) <= tol_s for a, b in zip(got, want))


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_gridded_wind(lon0, lon1, lat0, lat1, t_start, t_end, cache_dir,
                       dataset=None, pad_deg=0.5, chunk_days=30,
                       timeout=600):
    """Download a gridded 10 m wind field covering the SWAN domain.

    Parameters
    ----------
    lon0, lon1, lat0, lat1 : float
        Domain bounds in degrees (lon in -180..180).
    t_start, t_end : datetime
    cache_dir : str
        Chunks are cached here; an interrupted fetch resumes chunk-wise.  Each
        chunk carries a ``.json`` manifest and is reused only when the manifest
        records the identical URL/domain AND the file still holds exactly the
        source time levels that chunk covers.
    dataset : tuple or None
        One entry of :data:`WIND_DATASETS`; ``None`` tries them in order.
    pad_deg : float
        Halo added on every side so the domain corners are INTERIOR to the
        source grid and never need extrapolation.

    Returns
    -------
    dict with 'dataset_id', 'times' (list of datetime, ascending, unique),
    'lat', 'lon' (1-D ascending), 'u', 'v' (nt, nlat, nlon, NaN where the
    source is masked), 'n_chunks', 'urls', 'cadence_hours', 'window' (the
    on-axis [lo, hi] actually fetched, which brackets [t_start, t_end]),
    'n_cached' (chunks reused) and 'n_cache_rejected' (cached chunks discarded
    as stale).
    """
    os.makedirs(cache_dir, exist_ok=True)
    candidates = [dataset] if dataset else list(WIND_DATASETS)
    last_err = None
    for cand in candidates:
        ds_id, u_var, v_var = cand[0], cand[1], cand[2]
        nominal_h = cand[4] if len(cand) > 4 else None
        try:
            return _fetch_one(ds_id, u_var, v_var, lon0, lon1, lat0, lat1,
                              t_start, t_end, cache_dir, pad_deg, chunk_days,
                              timeout, nominal_h)
        except Exception as exc:                      # try the next dataset id
            last_err = exc
            print(f"[WARNING] gridded wind dataset '{ds_id}' unusable: {exc}")
    raise RuntimeError(
        f"no gridded wind dataset answered for {t_start}..{t_end}: {last_err}")


def _verify_chunk(path, u_var, v_var, want_times, la0, la1, lo0, lo1,
                  dom_lat, dom_lon):
    """Read a chunk and prove it IS the subset that was asked for.

    Checked: the exact source time levels the chunk covers are present and in
    order; the returned grid still spans the (unpadded) SWAN domain; and the
    returned edges sit within one grid spacing of the requested padded box.
    A file that fails any of these is stale or truncated - reusing it on the
    strength of its filename is how a resumed fetch silently returns a
    different domain or a short record.
    """
    times, lat, lon, u, v = read_wind_nc(path, u_var, v_var)
    if not _times_match(times, want_times):
        raise ValueError(
            f"time levels {len(times)} "
            f"({times[0] if times else '-'}..{times[-1] if times else '-'}) "
            f"!= the {len(want_times)} requested "
            f"({want_times[0]}..{want_times[-1]})")
    if lat.size < 2 or lon.size < 2:
        raise ValueError(f"degenerate grid {lat.size}x{lon.size}")
    dlat = abs(float(lat[1] - lat[0]))
    dlon = abs(float(lon[1] - lon[0]))
    lat_lo, lat_hi = float(min(lat)), float(max(lat))
    lon_lo, lon_hi = float(min(lon)), float(max(lon))
    if lat_lo > dom_lat[0] + 1e-6 or lat_hi < dom_lat[1] - 1e-6:
        raise ValueError(
            f"latitudes {lat_lo:.4f}..{lat_hi:.4f} do not cover the domain "
            f"{dom_lat[0]:.4f}..{dom_lat[1]:.4f}")
    if lon_lo > dom_lon[0] + 1e-6 or lon_hi < dom_lon[1] - 1e-6:
        raise ValueError(
            f"longitudes {lon_lo:.4f}..{lon_hi:.4f} do not cover the domain "
            f"{dom_lon[0]:.4f}..{dom_lon[1]:.4f}")
    # griddap snaps each requested edge to the nearest CELL, so the returned
    # box may sit up to half a spacing inside the request - but no further.
    if abs(lat_lo - la0) > 1.5 * dlat or abs(lat_hi - la1) > 1.5 * dlat or \
            abs(lon_lo - lo0) > 1.5 * dlon or abs(lon_hi - lo1) > 1.5 * dlon:
        raise ValueError(
            f"grid {lat_lo:.4f}..{lat_hi:.4f} x {lon_lo:.4f}..{lon_hi:.4f} is "
            f"not the requested box {la0:.4f}..{la1:.4f} x "
            f"{lo0:.4f}..{lo1:.4f}")
    return times, lat, lon, u, v


def _fetch_one(ds_id, u_var, v_var, lon0, lon1, lat0, lat1, t_start, t_end,
               cache_dir, pad_deg, chunk_days, timeout, nominal_hours=None):
    la0, la1 = min(lat0, lat1) - pad_deg, max(lat0, lat1) + pad_deg
    lo0, lo1 = min(lon0, lon1) - pad_deg, max(lon0, lon1) + pad_deg
    dom_lat = (min(lat0, lat1), max(lat0, lat1))
    dom_lon = (min(lon0, lon1), max(lon0, lon1))

    # Chunk boundaries must fall ON the source time axis, so the axis is probed
    # by index and the caller's window is snapped OUTWARD onto it.  griddap
    # answers an off-axis "(value)" with the NEAREST level instead of an error,
    # so an un-snapped 03:00Z start on a 6-hourly analysis returns a record that
    # begins at 06:00Z and the first requested hours are missing with nothing in
    # the response to say so.  Snapping also removes the "+1 second to avoid a
    # duplicate level" temptation, which would put the next request between two
    # analyses; chunks instead overlap by exactly one on-axis level and the
    # duplicate is dropped at merge time.
    t_first, cadence, t_last = probe_time_axis(ds_id, timeout=timeout)
    cad_h = cadence.total_seconds() / 3600.0
    if nominal_hours and abs(cad_h - float(nominal_hours)) > 1e-6:
        print(f"[WARNING] {ds_id}: catalogue says {nominal_hours} h but the "
              f"axis is {cad_h:g} h; using the probed axis")
    lo_t, hi_t = snap_to_axis(t_start, t_end, t_first, cadence, t_last)

    # Step by a WHOLE number of axis levels so every internal boundary is on-axis.
    per_chunk = max(1, int(round(chunk_days * 24.0 / cad_h)))
    step = per_chunk * cadence

    chunks, urls = [], []
    n_cached = n_rejected = 0
    t = lo_t
    idx = 0
    while True:
        t_hi = min(t + step, hi_t)
        want = axis_levels(t, t_hi, t_first, cadence)
        path = os.path.join(cache_dir, f"{ds_id}_{idx:03d}.nc")
        man_path = path + ".json"
        url = griddap_url(ds_id, (u_var, v_var), t, t_hi, la0, la1, lo0, lo1)
        urls.append(url)
        request = {"url": url, "dataset_id": ds_id,
                   "lat_request": [la0, la1], "lon_request": [lo0, lo1],
                   "t0": t.isoformat(), "t1": t_hi.isoformat(),
                   "n_levels": len(want)}

        got = None
        if os.path.isfile(path) and os.path.isfile(man_path):
            try:
                with open(man_path) as fh:
                    man = json.load(fh)
                if man.get("request") != request:
                    raise ValueError(
                        "manifest describes a different request "
                        f"({man.get('request', {}).get('url')})")
                got = _verify_chunk(path, u_var, v_var, want, la0, la1,
                                    lo0, lo1, dom_lat, dom_lon)
                n_cached += 1
            except Exception as exc:
                n_rejected += 1
                print(f"[WARNING] cached chunk {os.path.basename(path)} "
                      f"rejected ({exc}); refetching")
                got = None
                for stale in (path, man_path):
                    if os.path.exists(stale):
                        os.remove(stale)
        elif os.path.isfile(path):
            # v1 wrote no manifest, so an un-manifested file is unverifiable
            # provenance - treat it as stale rather than trust its name.
            n_rejected += 1
            print(f"[WARNING] cached chunk {os.path.basename(path)} has no "
                  "manifest; refetching")
            os.remove(path)

        if got is None:
            _download(url, path, timeout=timeout)
            got = _verify_chunk(path, u_var, v_var, want, la0, la1, lo0, lo1,
                                dom_lat, dom_lon)
            tmp_man = man_path + ".part"
            with open(tmp_man, "w") as fh:
                json.dump({"request": request,
                           "times": [x.isoformat() for x in got[0]]}, fh,
                          indent=1)
            os.replace(tmp_man, man_path)

        chunks.append(got)
        idx += 1
        if t_hi >= hi_t:
            break
        t = t_hi

    if not chunks:
        raise RuntimeError("empty time window")

    lat, lon = chunks[0][1], chunks[0][2]
    for c in chunks[1:]:
        if not (np.allclose(c[1], lat) and np.allclose(c[2], lon)):
            raise RuntimeError(
                "chunk grids differ - ERDDAP returned a different subset for "
                "one chunk; delete the cache and refetch")

    times, u_list, v_list = [], [], []
    seen = set()
    for tt, _, _, uu, vv in chunks:
        for k, ts in enumerate(tt):
            if ts in seen:
                continue
            seen.add(ts)
            times.append(ts)
            u_list.append(uu[k])
            v_list.append(vv[k])
    order = np.argsort(np.array([ts.timestamp() for ts in times]))
    times = [times[i] for i in order]
    u = np.stack([u_list[i] for i in order])
    v = np.stack([v_list[i] for i in order])

    # ascending lat/lon - griddap already returns ascending, but a descending
    # axis would silently mirror the field, so normalise instead of assuming.
    if lat[0] > lat[-1]:
        lat, u, v = lat[::-1], u[:, ::-1, :], v[:, ::-1, :]
    if lon[0] > lon[-1]:
        lon, u, v = lon[::-1], u[:, :, ::-1], v[:, :, ::-1]

    # The merged record must be the contiguous on-axis span that was snapped
    # to, with no level lost at a chunk seam.
    want_all = axis_levels(lo_t, hi_t, t_first, cadence)
    if not _times_match(times, want_all):
        raise RuntimeError(
            f"merged wind record has {len(times)} levels "
            f"({times[0]}..{times[-1]}) but the snapped window needs "
            f"{len(want_all)} ({want_all[0]}..{want_all[-1]})")
    if times[0] > t_start or times[-1] < t_end:
        raise RuntimeError(
            f"wind record {times[0]}..{times[-1]} does not bracket the "
            f"requested window {t_start}..{t_end}")

    return {"dataset_id": ds_id, "times": times, "lat": lat, "lon": lon,
            "u": u, "v": v, "n_chunks": len(chunks), "urls": urls,
            "cadence_hours": cadence.total_seconds() / 3600.0,
            "window": [lo_t, hi_t],
            "n_cached": n_cached, "n_cache_rejected": n_rejected}


# ---------------------------------------------------------------------------
# Gap filling / interpolation
# ---------------------------------------------------------------------------

def fill_masked_cells(u, v):
    """Nearest-neighbour fill land/masked cells, per time level.

    Returns (u, v, frac_filled).  Raises if a whole time level is masked -
    persistence across a fully blank analysis would fabricate forcing, and the
    caller must see that rather than get a plausible-looking field.
    """
    u = np.array(u, dtype=float)
    v = np.array(v, dtype=float)
    nt, ny, nx = u.shape
    yy, xx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    n_filled = 0
    for k in range(nt):
        bad = ~np.isfinite(u[k]) | ~np.isfinite(v[k])
        if not bad.any():
            continue
        if bad.all():
            raise ValueError(
                f"gridded wind time level {k} is entirely masked - the source "
                "has no analysis for this domain/time")
        good = ~bad
        gy, gx = yy[good], xx[good]
        by, bx = yy[bad], xx[bad]
        d2 = (by[:, None] - gy[None, :]) ** 2 + (bx[:, None] - gx[None, :]) ** 2
        near = np.argmin(d2, axis=1)
        u[k][bad] = u[k][good][near]
        v[k][bad] = v[k][good][near]
        n_filled += int(bad.sum())
    return u, v, n_filled / float(nt * ny * nx)


def interp_to_times(src_times, u, v, target_times):
    """Linearly interpolate the U and V COMPONENTS onto ``target_times``.

    Components, never speed/direction: interpolating a direction across the
    0/360 wrap rotates the vector through the wrong half of the compass.
    Target times outside the source record are an error, not a clamp - SWAN
    would otherwise be driven by a held-constant end value for the overhang.
    """
    ts = np.array([t.timestamp() for t in src_times], dtype=float)
    if np.any(np.diff(ts) <= 0):
        raise ValueError("source wind times are not strictly increasing")
    tt = np.array([t.timestamp() for t in target_times], dtype=float)
    if tt.min() < ts.min() - 1 or tt.max() > ts.max() + 1:
        raise ValueError(
            f"requested wind times {target_times[0]}..{target_times[-1]} are "
            f"not covered by the source record {src_times[0]}..{src_times[-1]}")
    nt, ny, nx = u.shape
    out_u = np.empty((len(tt), ny, nx), dtype=float)
    out_v = np.empty((len(tt), ny, nx), dtype=float)
    for j in range(ny):
        for i in range(nx):
            out_u[:, j, i] = np.interp(tt, ts, u[:, j, i])
            out_v[:, j, i] = np.interp(tt, ts, v[:, j, i])
    return out_u, out_v


def bilinear_to_points(lat, lon, field, plat, plon):
    """Bilinear-interpolate a [lat][lon] field onto scattered points.

    ``lat``/``lon`` must be ascending.  Points outside the source grid are
    rejected: an out-of-range corner silently clamped to the edge value is
    exactly the degeneracy this tool exists to remove.
    """
    plat = np.asarray(plat, dtype=float)
    plon = np.asarray(plon, dtype=float)
    if plat.min() < lat[0] - 1e-6 or plat.max() > lat[-1] + 1e-6:
        raise ValueError(
            f"target latitudes {plat.min():.4f}..{plat.max():.4f} fall outside "
            f"the source grid {lat[0]:.4f}..{lat[-1]:.4f}; increase pad_deg")
    if plon.min() < lon[0] - 1e-6 or plon.max() > lon[-1] + 1e-6:
        raise ValueError(
            f"target longitudes {plon.min():.4f}..{plon.max():.4f} fall outside "
            f"the source grid {lon[0]:.4f}..{lon[-1]:.4f}; increase pad_deg")

    iy = np.clip(np.searchsorted(lat, plat) - 1, 0, lat.size - 2)
    ix = np.clip(np.searchsorted(lon, plon) - 1, 0, lon.size - 2)
    wy = (plat - lat[iy]) / (lat[iy + 1] - lat[iy])
    wx = (plon - lon[ix]) / (lon[ix + 1] - lon[ix])
    wy = np.clip(wy, 0.0, 1.0)
    wx = np.clip(wx, 0.0, 1.0)
    f = field
    return ((1 - wy) * (1 - wx) * f[iy, ix]
            + (1 - wy) * wx * f[iy, ix + 1]
            + wy * (1 - wx) * f[iy + 1, ix]
            + wy * wx * f[iy + 1, ix + 1])


def regrid_to_swan_grid(lat, lon, u, v, node_lat, node_lon):
    """Bilinear-regrid every time level onto the SWAN input-grid NODES.

    ``node_lat``/``node_lon`` are 2-D arrays of shape ``(my+1, mx+1)`` with
    row 0 at the LOWEST y, matching SWAN ``idla=4``.
    """
    node_lat = np.asarray(node_lat, dtype=float)
    node_lon = np.asarray(node_lon, dtype=float)
    if node_lat.shape != node_lon.shape or node_lat.ndim != 2:
        raise ValueError("node_lat/node_lon must be 2-D arrays of equal shape")
    ny, nx = node_lat.shape
    flat_lat, flat_lon = node_lat.ravel(), node_lon.ravel()
    out_u = np.empty((u.shape[0], ny, nx), dtype=float)
    out_v = np.empty((v.shape[0], ny, nx), dtype=float)
    for k in range(u.shape[0]):
        out_u[k] = bilinear_to_points(lat, lon, u[k], flat_lat,
                                      flat_lon).reshape(ny, nx)
        out_v[k] = bilinear_to_points(lat, lon, v[k], flat_lat,
                                      flat_lon).reshape(ny, nx)
    return out_u, out_v


# ---------------------------------------------------------------------------
# Independence check
# ---------------------------------------------------------------------------

def assert_independent_of(station_ids, validation_station_id):
    """Raise when the wind source is the SCORED instrument.

    Feeding SWAN the validation buoy's own anemometer makes the HIGH-sensitivity
    driver of HSIGN an in-situ measurement at the scoring point, so the run is
    no longer an independent hindcast.  Callers building a station wind field
    must pass the scored station id here.
    """
    ids = [str(s) for s in station_ids]
    vid = str(validation_station_id)
    if vid in ids:
        raise ValueError(
            f"wind station list {ids} contains the VALIDATION station '{vid}': "
            "the scored buoy's own anemometer cannot force the domain whose "
            "HSIGN is being scored at that buoy. Use "
            "fetch_gridded_wind.fetch_gridded_wind() for an independent "
            "gridded analysis, or restrict the station list to other hulls.")
    return True


def validate_field(u, v, max_speed=60.0):
    """Range/finiteness check plus the spatial-degeneracy check."""
    res = {}
    spd = np.sqrt(u ** 2 + v ** 2)
    res["n_nan"] = int((~np.isfinite(spd)).sum())
    res["speed_range"] = (float(np.nanmin(spd)), float(np.nanmax(spd)))
    # Spatial spread per time level: a field that is constant in space is a
    # 0-D driver wearing a 2-D grid's clothes.
    per_t = np.nanmax(spd.reshape(spd.shape[0], -1), axis=1) - \
        np.nanmin(spd.reshape(spd.shape[0], -1), axis=1)
    res["mean_spatial_range_ms"] = float(np.nanmean(per_t))
    res["spatially_uniform"] = bool(res["mean_spatial_range_ms"] < 1e-6)
    if res["n_nan"]:
        res["status"] = f"FAIL: {res['n_nan']} non-finite wind samples"
    elif res["speed_range"][1] > max_speed:
        res["status"] = f"FAIL: max wind {res['speed_range'][1]:.1f} > {max_speed} m/s"
    elif res["spatially_uniform"]:
        res["status"] = ("FAIL: field is spatially uniform at every time level "
                         "- a gridded source must vary across the domain")
    else:
        res["status"] = "OK"
    return res


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lon0", type=float, required=True)
    p.add_argument("--lon1", type=float, required=True)
    p.add_argument("--lat0", type=float, required=True)
    p.add_argument("--lat1", type=float, required=True)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--cache", required=True)
    p.add_argument("--chunk-days", type=int, default=30)
    a = p.parse_args()
    got = fetch_gridded_wind(
        a.lon0, a.lon1, a.lat0, a.lat1,
        datetime.datetime.strptime(a.start, "%Y-%m-%d"),
        datetime.datetime.strptime(a.end, "%Y-%m-%d"),
        a.cache, chunk_days=a.chunk_days)
    uu, vv, frac = fill_masked_cells(got["u"], got["v"])
    print(f"{got['dataset_id']}: {len(got['times'])} levels "
          f"{got['times'][0]}..{got['times'][-1]} on a "
          f"{got['cadence_hours']:g} h axis, "
          f"grid {got['lat'].size}x{got['lon'].size}, filled {frac:.4%}, "
          f"chunks={got['n_chunks']} cached={got['n_cached']} "
          f"stale_rejected={got['n_cache_rejected']}")
    print(validate_field(uu, vv))
