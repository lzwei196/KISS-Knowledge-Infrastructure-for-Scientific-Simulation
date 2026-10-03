"""run_city_swmm — whole-city SWMM build+run via swmmanywhere, scored on
mass-balance continuity self-consistency.

Closes the gap noted in SKILL.md: the s1-s7 pipeline is a manual GIS workflow
with no automated from-OSM city builder. swmmanywhere 0.2.2 downloads OSM
streets + Overture buildings + NASADEM elevation for a bbox, synthesises a
drainage network, writes a SWMM .inp; we then run it with pyswmm and read the
surface-runoff and flow-routing continuity errors from the authoritative SWMM
.rpt report.

Parameterised by city/bbox so the Real-case (Nanjing) and verifier (Hefei,
Wuhan, ...) runs reuse the exact same code path.

Design notes (root causes fixed in this tool, with evidence):

* CONTINUITY READ — pyswmm's ``sim.runoff_error`` / ``sim.flow_routing_error``
  are only finalised inside the SWMM engine on ``swmm_end()``, which pyswmm
  calls from the ``Simulation`` context-manager ``__exit__``. Reading them
  INSIDE the ``with`` block (after the step loop, before exit) returns the
  uninitialised value 0.0 — which silently masked a broken mass balance in an
  earlier version of this tool (headline "0.0000%" while the .rpt said 1.656%).
  We therefore treat the .rpt file (written on close) as authoritative and read
  continuity from it AFTER the context exits.

* RUNOFF-CONTINUITY NaN — SWMM 5.2.4 leaves snowpack imelt uninitialized on
  zero-area surfaces. swmmanywhere's unused ``empty`` snow template triggers
  this heap-dependent failure; a controlled allocator regression reproduces
  NaN storage with the real engine. Remove only that exact template when no
  temperature forcing, initial snow, or hotstart is present. Real snow setups
  are preserved. Missing/non-finite balances always invalidate the result.

* BUILDINGS — the Overture-buildings download (anonymous pyarrow S3 through the
  HTTP proxy) is slow but works. We attempt the REAL download and fall back to
  a VALID empty geoparquet ONLY if it genuinely fails or leaves a corrupt
  footer-less file, so real building footprints are used whenever available.

* EXTERNAL RAIN — swmmanywhere wires every subcatchment to one rain gage that
  reads its bundled 5-minute design storm (year 2000, one day). To run the
  city model on real rain, pass ``rain_dat`` (a .dat written by
  tools/s3_rainfall_forcing/build_rain_timeseries_from_source.py or
  create_rain_timeseries.py) with ``rain_interval`` and ``rain_format``. The
  tool then writes a copy of the model, ``<name>_extrain.inp``, in which the
  gage reads that series ([RAINGAGES] TIMESERIES + [TIMESERIES] rows) and the
  simulation dates cover the chosen days. INTERVAL and FORMAT must be the ones
  the rain tool printed: a 3-hourly series read with the design storm's 0:05
  INTERVAL would keep 1/36 of the rain, with no error. After the run the rain
  depth SWMM reports is compared with the depth in the .dat for the same days
  (``rain_applied_ok``), so a rain series that did not get in cannot pass.

Command line (the same function, for a run by path):
  python run_city_swmm.py --city Nanjing --bbox 118.74,32.00,118.86,32.10 \
      --workdir <dir> --rain_dat rain.dat --rain_interval 3:00 \
      --rain_format intensity --wettest_days 5 --json_out result.json
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from pathlib import Path

import pyswmm

from swmmanywhere.swmmanywhere import swmmanywhere


def _patch_s3_timeouts(connect_timeout: float = 30.0, request_timeout: float = 120.0):
    """Inject longer pyarrow S3 timeouts.

    swmmanywhere downloads Overture buildings via
    ``fs.S3FileSystem(anonymous=True, region=...)`` using pyarrow's default
    connect/request timeouts (~1-3 s). Through the local HTTP proxy the AWS C++
    client needs much longer to resolve + scan the bucket. Bumping the timeouts
    makes the same anonymous request succeed. This patches the symbol
    swmmanywhere actually calls without altering its logic.
    """
    from swmmanywhere import prepare_data

    _orig = prepare_data.fs.S3FileSystem

    def _patched(*args, **kwargs):
        kwargs.setdefault("connect_timeout", connect_timeout)
        kwargs.setdefault("request_timeout", request_timeout)
        return _orig(*args, **kwargs)

    prepare_data.fs.S3FileSystem = _patched


def _patch_resilient_buildings():
    """Make the Overture buildings download tolerant of empty/failed scans
    WITHOUT discarding real footprints.

    ``download_buildings_bbox`` opens a ParquetWriter and only writes batches
    with rows; if the S3 scan yields zero buildings or errors mid-scan it can
    leave a 4-byte ``PAR1``-only file with no footer, and geopandas then raises
    ArrowInvalid when the subcatchment graph function reads it, killing the
    whole build. We wrap the ORIGINAL downloader: try the real download first
    (so genuine Overture footprints are used and impervious area is correct);
    only if it raises, or leaves a missing / corrupt / footer-less parquet, do
    we write a VALID empty geoparquet (single ``geometry`` column, EPSG:4326,
    0 rows) so derive_rc falls back to street-cover impervious area — a
    hydraulically valid network for a mass-balance check.
    """
    import geopandas as gpd
    from swmmanywhere import prepare_data

    _orig = prepare_data.download_buildings_bbox

    def _write_empty(file_address):
        gdf = gpd.GeoDataFrame(
            {"geometry": gpd.GeoSeries([], dtype=object)},
            geometry="geometry",
            crs="EPSG:4326",
        )
        gdf.to_parquet(file_address)

    def _valid_parquet(file_address) -> bool:
        p = Path(file_address)
        # A valid parquet is far larger than the 4-byte "PAR1" stub and must be
        # readable by geopandas (i.e. has a footer).
        if not p.exists() or p.stat().st_size < 64:
            return False
        try:
            gpd.read_parquet(p)
            return True
        except Exception:
            return False

    def _patched(file_address, bbox):
        try:
            _orig(file_address, bbox)
        except Exception:
            # Genuine download failure -> degrade gracefully to street-only.
            _write_empty(Path(file_address))
            return
        if not _valid_parquet(file_address):
            # Download "succeeded" but left an empty/corrupt footer-less file.
            _write_empty(Path(file_address))

    prepare_data.download_buildings_bbox = _patched


def _patch_osmnx_timeout(timeout: int = 600):
    """Give osmnx/Overpass a generous timeout for large urban bboxes."""
    try:
        import osmnx as ox

        if hasattr(ox, "settings"):
            for attr in ("requests_timeout", "timeout"):
                if hasattr(ox.settings, attr):
                    setattr(ox.settings, attr, timeout)
    except Exception:
        pass


def _patch_robust_outfalls():
    """Guard swmmanywhere's derive_topology against stale outfall ids.

    In swmmanywhere 0.2.2, topology_graphfcns.derive_topology builds the
    ``outfalls`` list BEFORE calling graph_utilities.filter_streets(G).
    filter_streets removes a node that is simultaneously an outfall source and
    an endpoint of a non-street edge, leaving ``outfalls`` stale; it is then
    passed to shortest_path_utils.dijkstra_pq(G, outfalls), which seeds its
    heap from every outfall and calls G.in_edges(node) ->
    NetworkXError("Node <id> is not in the graph") for any deleted outfall
    (e.g. "Node 1388 is not in the graph"). We wrap dijkstra_pq to drop
    outfalls absent from G before routing; surviving outfalls still drain the
    graph, matching filter_streets' intent.
    """
    from swmmanywhere import shortest_path_utils as spu

    _orig = spu.dijkstra_pq

    def _patched(G, outfalls, *args, **kwargs):
        valid = [o for o in outfalls if o in G]
        return _orig(G, valid, *args, **kwargs)

    spu.dijkstra_pq = _patched


def _floor_subcatchment_slopes(inp: Path, min_slope_pct: float = 0.01) -> dict:
    """Floor [SUBCATCHMENTS] %Slope to a small positive value, in place.

    Fixes the 0/0 -> NaN overland-flow alpha for DEM-flat subcatchments (see
    module docstring). Only RAISES values strictly below ``min_slope_pct``;
    every non-flat subcatchment is left byte-identical. Returns counts so the
    caller can report exactly what was touched.

    [SUBCATCHMENTS] columns:
      Name RainGage Outlet Area %Imperv Width %Slope CurbLen SnowPack
    %Slope is column index 6 (0-based).
    """
    lines = inp.read_text().splitlines(keepends=True)
    out = []
    section = None
    n_total = 0
    n_floored = 0
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].upper()
            out.append(line)
            continue
        if section == "SUBCATCHMENTS" and s and not s.startswith(";"):
            parts = line.split()
            if len(parts) >= 7:
                n_total += 1
                try:
                    slope = float(parts[6])
                except ValueError:
                    out.append(line)
                    continue
                if not math.isfinite(slope) or slope < min_slope_pct:
                    parts[6] = repr(min_slope_pct)
                    n_floored += 1
                    # Rebuild with single-space delimiters (SWMM is
                    # whitespace-delimited; alignment is cosmetic).
                    newline = " ".join(parts)
                    if line.endswith("\n"):
                        newline += "\n"
                    out.append(newline)
                    continue
            out.append(line)
            continue
        out.append(line)
    inp.write_text("".join(out))
    return {"n_subcatchments": n_total, "n_slopes_floored": n_floored,
            "min_slope_pct": min_slope_pct}


def _floor_subarea_manning(inp: Path, min_manning_n: float = 0.01) -> dict:
    """Floor [SUBAREAS] N-Imperv and N-Perv to a small positive value, in place.

    swmmanywhere's swmm_conversion.yml writes Manning's n = 0. This floor
    selects a positive overland roughness for the generated network. It is a
    model assumption, not the NaN fix: EPA 5.2.4 explicitly handles n=0 as
    instantaneous runoff. The empty-snowpack guard addresses the observed NaN.

    [SUBAREAS] columns:
      Subcatchment N-Imperv N-Perv S-Imperv S-Perv PctZero RouteTo PctRouted
    N-Imperv is column index 1, N-Perv index 2 (0-based).
    """
    lines = inp.read_text().splitlines(keepends=True)
    out = []
    section = None
    n_total = 0
    n_floored = 0
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].upper()
            out.append(line)
            continue
        if section == "SUBAREAS" and s and not s.startswith(";"):
            parts = line.split()
            if len(parts) >= 3:
                n_total += 1
                changed = False
                for idx in (1, 2):  # N-Imperv, N-Perv
                    try:
                        n = float(parts[idx])
                    except ValueError:
                        continue
                    if not math.isfinite(n) or n < min_manning_n:
                        parts[idx] = repr(min_manning_n)
                        changed = True
                if changed:
                    n_floored += 1
                    newline = " ".join(parts)
                    if line.endswith("\n"):
                        newline += "\n"
                    out.append(newline)
                    continue
            out.append(line)
            continue
        out.append(line)
    inp.write_text("".join(out))
    return {"n_subareas": n_total, "n_manning_floored": n_floored,
            "min_manning_n": min_manning_n}


def _clamp_subcatchment_imperv(inp: Path, lo: float = 0.0, hi: float = 100.0) -> dict:
    """Clamp [SUBCATCHMENTS] %Imperv into [lo, hi], in place.

    swmmanywhere's derive_rc can overshoot 100 by a rounding ULP. Keep the
    generated input inside the documented percentage range. EPA 5.2.4 also
    clamps the upper bound internally; this is input hygiene, not the cause of
    the observed NaN. In-range values are unchanged.

    [SUBCATCHMENTS] columns:
      Name RainGage Outlet Area %Imperv Width %Slope CurbLen SnowPack
    %Imperv is column index 4 (0-based).
    """
    lines = inp.read_text().splitlines(keepends=True)
    out = []
    section = None
    n_total = 0
    n_clamped = 0
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].upper()
            out.append(line)
            continue
        if section == "SUBCATCHMENTS" and s and not s.startswith(";"):
            parts = line.split()
            if len(parts) >= 7:
                n_total += 1
                try:
                    imperv = float(parts[4])
                except ValueError:
                    out.append(line)
                    continue
                if not math.isfinite(imperv):
                    clamped = lo
                else:
                    clamped = min(hi, max(lo, imperv))
                if clamped != imperv:
                    parts[4] = repr(clamped)
                    n_clamped += 1
                    newline = " ".join(parts)
                    if line.endswith("\n"):
                        newline += "\n"
                    out.append(newline)
                    continue
            out.append(line)
            continue
        out.append(line)
    inp.write_text("".join(out))
    return {"n_subcatchments": n_total, "n_imperv_clamped": n_clamped,
            "imperv_lo": lo, "imperv_hi": hi}


def _remove_inactive_template_snowpack(inp: Path) -> dict:
    """Remove swmmanywhere's exact unused snow template in rain-only models.

    SWMM 5.2.4 mallocs TSnowpack without initializing imelt. snow_plowSnow
    resets imelt only for positive-area surfaces, while snow_getSnowMelt reads
    it for every surface. The template's zero-area PLOWABLE surface can thus
    contribute 0 * NaN and poison impervious runoff, depending on heap contents.
    Do not modify real snow setups, temperature forcing, or hotstart projects.
    """
    lines = inp.read_text().splitlines(keepends=True)
    section = None
    records = {}
    for i, line in enumerate(lines):
        body = line.split(";", 1)[0].strip()
        if body.startswith("["):
            section = body.upper()
        elif body:
            records.setdefault(section, []).append((i, body.split()))
    result = {"n_snowpack_references_removed": 0, "reason": "not the inactive rain-only template"}
    if records.get("[TEMPERATURE]") or records.get("[ADJUSTMENTS]") or any(
            "HOTSTART" in [x.upper() for x in parts] for _, parts in records.get("[FILES]", [])):
        return result
    expected = {key: [0.001, 0.001, 32.0, 0.10, 0.0, 0.0, 0.0]
                for key in ("PLOWABLE", "IMPERVIOUS", "PERVIOUS")}
    expected["REMOVAL"] = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    template = [(i, parts) for i, parts in records.get("[SNOWPACKS]", []) if parts[0] == "empty"]
    try:
        actual = {parts[1].upper(): list(map(float, parts[2:])) for _, parts in template}
    except (ValueError, IndexError):
        return result
    if len(template) != 4 or actual != expected:
        return result
    if any(len(parts) > 8 and parts[8] == "empty" and len(parts) != 9
           for _, parts in records.get("[SUBCATCHMENTS]", [])):
        return result
    for i, parts in records.get("[SUBCATCHMENTS]", []):
        if len(parts) == 9 and parts[8] == "empty":
            comment = lines[i].partition(";")[2].rstrip("\n")
            lines[i] = " ".join(parts[:8]) + (" ;" + comment if comment else "") + "\n"
            result["n_snowpack_references_removed"] += 1
    if result["n_snowpack_references_removed"]:
        for i, _ in template:
            lines[i] = ""
        inp.write_text("".join(lines))
        result["reason"] = "removed empty snowpack with no temperature forcing or initial snow"
    return result


def _rpt_continuity(rpt: Path) -> dict:
    """Parse continuity error % from the authoritative SWMM .rpt.

    Returns floats (possibly NaN if SWMM itself wrote 'nan') or None if the
    block is absent. This is the source of truth — NOT pyswmm's in-loop scalar.
    """
    out = {"runoff_pct": None, "flow_routing_pct": None}
    if not rpt.exists():
        return out
    text = rpt.read_text(errors="ignore")

    def _grab(header):
        block = re.search(header + r"[^\n]*\n(.*?)(?:\n[ \t]*\n|\Z)", text, re.S | re.I)
        if not block:
            return None
        m = re.search(
            r"^[ \t]*Continuity Error \(%\)[ \t]*\.*[ \t]*([+-]?(?:nan|inf(?:inity)?|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?))",
            block.group(1),
            re.M | re.I,
        )
        if not m:
            return None
        tok = m.group(1)
        return float("nan") if tok.lower() == "nan" else float(tok)

    out["runoff_pct"] = _grab(r"Runoff Quantity Continuity")
    out["flow_routing_pct"] = _grab(r"Flow Routing Continuity")
    return out


def _count_inp_sections(inp: Path) -> dict:
    """Count nodes (junctions+outfalls+storage), conduits, subcatchments."""
    counts = {"JUNCTIONS": 0, "OUTFALLS": 0, "STORAGE": 0, "CONDUITS": 0,
              "SUBCATCHMENTS": 0}
    section = None
    for line in inp.read_text(errors="ignore").splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].upper()
            continue
        if not s or s.startswith(";"):
            continue
        if section in counts:
            counts[section] += 1
    n_nodes = counts["JUNCTIONS"] + counts["OUTFALLS"] + counts["STORAGE"]
    return {
        "n_nodes": n_nodes,
        "n_conduits": counts["CONDUITS"],
        "n_subcatchments": counts["SUBCATCHMENTS"],
    }


def _building_rows(workdir: Path) -> int | None:
    """How many building footprints ended up in the download (0 = street-only)."""
    try:
        import geopandas as gpd

        hits = list(Path(workdir).rglob("building.geoparquet"))
        if not hits:
            return None
        return int(len(gpd.read_parquet(hits[0])))
    except Exception:
        return None


def _interval_hours(interval: str) -> float:
    """'3:00' / '0:05' / '1:00:00' -> hours. Raises ValueError on bad text."""
    parts = str(interval).strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"rain_interval '{interval}' is not H:MM")
    nums = [int(x) for x in parts]
    hours = nums[0] + nums[1] / 60.0 + (nums[2] / 3600.0 if len(nums) == 3 else 0.0)
    if hours <= 0:
        raise ValueError(f"rain_interval '{interval}' must be longer than zero")
    return hours


# the header line of a KI rain .dat that names its series
_RAIN_NAME_TAG = ";;SWMM Rainfall Timeseries:"


def _read_rain_dat(rain_dat: Path):
    """Read a KI rain .dat (name, MM/DD/YYYY, HH:MM:SS, value per row).

    Returns (series_name, [(datetime, value), ...]) sorted by time. One series
    per file; a bad row, a non-finite or a negative value stops the read.

    A file with no rows is an all-dry period when it has a ';;COVERAGE' line
    (zero rows are left out by the writer): it gives (series_name, []), the
    name read from its ';;SWMM Rainfall Timeseries: <name>' line. With no
    ';;COVERAGE' line an empty file proves nothing and is refused.
    """
    rain_dat = Path(rain_dat)
    if not rain_dat.is_file():
        raise FileNotFoundError(f"rain_dat not found: {rain_dat}")
    names = set()
    records = []
    header_name = None
    for n, line in enumerate(rain_dat.read_text().splitlines(), 1):
        s = line.strip()
        if s.startswith(_RAIN_NAME_TAG):
            header_name = s[len(_RAIN_NAME_TAG):].strip()
        if not s or s.startswith(";"):
            continue
        parts = s.split()
        if len(parts) != 4:
            raise ValueError(f"{rain_dat} line {n}: need 'name date time value', "
                             f"got '{s}'")
        try:
            dt = datetime.strptime(parts[1] + " " + parts[2], "%m/%d/%Y %H:%M:%S")
            value = float(parts[3])
        except ValueError as e:
            raise ValueError(f"{rain_dat} line {n}: {e}")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{rain_dat} line {n}: rain value {parts[3]} is not usable")
        names.add(parts[0])
        records.append((dt, value))
    if not records:
        if _read_rain_coverage(rain_dat) is None:
            raise ValueError(f"{rain_dat} holds no rain rows and no ;;COVERAGE "
                             f"line; it cannot tell a dry period from no data")
        if not header_name or len(header_name.split()) != 1:
            raise ValueError(f"{rain_dat} holds no rain rows (all dry) and no "
                             f"'{_RAIN_NAME_TAG} <name>' line to name the series")
        return header_name, []
    if len(names) != 1:
        raise ValueError(f"{rain_dat} holds {len(names)} series {sorted(names)}; "
                         f"one rain gage takes one series")
    records.sort(key=lambda r: r[0])
    return names.pop(), records


def _read_rain_coverage(rain_dat: Path):
    """The (start, end) of the ';;COVERAGE <start> <end>' line of a KI rain
    .dat (end not included), or None when the file has no such line."""
    found = None
    for n, line in enumerate(Path(rain_dat).read_text().splitlines(), 1):
        s = line.strip()
        if not s.startswith(";;COVERAGE"):
            continue
        parts = s.split()
        try:
            if len(parts) != 3:
                raise ValueError("need ';;COVERAGE <start> <end>'")
            a = datetime.strptime(parts[1], "%Y-%m-%dT%H:%M:%S")
            b = datetime.strptime(parts[2], "%Y-%m-%dT%H:%M:%S")
        except ValueError as e:
            raise ValueError(f"{rain_dat} line {n}: {e}")
        if b <= a:
            raise ValueError(f"{rain_dat} line {n}: coverage end is not after its start")
        if found is not None:
            raise ValueError(f"{rain_dat} holds more than one ;;COVERAGE line")
        found = (a, b)
    return found


def _rain_depth_mm(records, interval_h: float, rain_format: str,
                   start: datetime, end: datetime) -> float:
    """Rain depth (mm) of the rows with start <= time < end."""
    per_value = interval_h if rain_format.upper() == "INTENSITY" else 1.0
    return sum(v for dt, v in records if start <= dt < end) * per_value


def _wettest_window(records, interval_h: float, rain_format: str, days: int):
    """The `days` whole days in a row with the most rain. Returns (start, end)
    as datetimes at 00:00, end = the midnight after the last day."""
    first = records[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
    last = records[-1][0].replace(hour=0, minute=0, second=0, microsecond=0)
    n_days = (last - first).days + 1
    if days < 1:
        raise ValueError("wettest_days must be 1 or more")
    if days > n_days:
        raise ValueError(f"wettest_days={days} but the rain rows span only "
                         f"{n_days} day(s)")
    best = None
    for i in range(n_days - days + 1):
        a = first + timedelta(days=i)
        b = a + timedelta(days=days)
        depth = _rain_depth_mm(records, interval_h, rain_format, a, b)
        if best is None or depth > best[0]:
            best = (depth, a, b)
    return best[1], best[2]


def _apply_external_rain(inp: Path, out_inp: Path, series_name: str, records,
                         rain_interval: str, rain_format: str,
                         start: datetime, end: datetime,
                         report_step: str | None = None,
                         coverage=None) -> dict:
    """Write `out_inp` = `inp` with the rain gage(s) reading `series_name`.

    - [RAINGAGES]: each gage keeps its name, becomes
      ``<gage> <FORMAT> <INTERVAL> 1.0 TIMESERIES <series_name>``
    - [TIMESERIES]: the rows of the series inside start..end (a section of the
      same series name already there is replaced)
    - [OPTIONS]: START/REPORT_START/END date and time = start..end;
      REPORT_STEP = `report_step` (default: the rain interval, so a run of
      several days does not write a table row every 15 minutes for every
      subcatchment, node and link)

    `coverage` = (start, end) of the period the rain data covers. A window
    that is not fully inside it is refused: the part outside would run as
    zero rain. A window with no rain row is a dry window when `coverage` is
    given (the series then gets one 0.0 row at `start`, so SWMM has a series
    to read); without `coverage` it is refused.
    """
    fmt = rain_format.upper()
    if fmt not in ("INTENSITY", "VOLUME"):
        raise ValueError("rain_format must be intensity or volume")
    interval_h = _interval_hours(rain_interval)
    if end <= start:
        raise ValueError("the simulation end is not after its start")
    if coverage is not None and (start < coverage[0] or end > coverage[1]):
        raise ValueError(
            f"the simulation window {start} .. {end} is not fully inside the "
            f"rain data, which covers {coverage[0]} .. {coverage[1]}; the "
            f"uncovered time would run as zero rain")
    rows = [(dt, v) for dt, v in records if start <= dt < end]
    if not rows and coverage is None:
        raise ValueError(f"the rain series has no row between {start} and {end}")
    # all dry inside the covered period: one true zero keeps the series defined
    ts_rows = rows or [(start, 0.0)]
    if report_step is None:
        total_s = int(round(interval_h * 3600))
        report_step = f"{total_s // 3600:02d}:{(total_s % 3600) // 60:02d}:00"

    options = {
        "START_DATE": start.strftime("%m/%d/%Y"),
        "START_TIME": start.strftime("%H:%M:%S"),
        "REPORT_START_DATE": start.strftime("%m/%d/%Y"),
        "REPORT_START_TIME": start.strftime("%H:%M:%S"),
        "END_DATE": end.strftime("%m/%d/%Y"),
        "END_TIME": end.strftime("%H:%M:%S"),
        "REPORT_STEP": report_step,
    }
    ts_block = ["[TIMESERIES]\n", ";;Name           Date       Time       Value\n"]
    ts_block += [f"{series_name} {dt:%m/%d/%Y} {dt:%H:%M:%S} {v:.4f}\n" for dt, v in ts_rows]
    ts_block.append("\n")

    out = []
    section = None
    gages = []
    seen_options = set()
    for line in Path(inp).read_text().splitlines(keepends=True):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].upper()
            if section == "TIMESERIES":
                continue            # dropped; written again at the end
            out.append(line)
            continue
        if section == "TIMESERIES":
            # keep other series, drop an older copy of this one
            if s and not s.startswith(";") and s.split()[0] != series_name:
                ts_block.insert(-1, line if line.endswith("\n") else line + "\n")
            continue
        if section == "RAINGAGES" and s and not s.startswith(";"):
            gage = s.split()[0]
            gages.append(gage)
            out.append(f"{gage} {fmt} {rain_interval} 1.0 TIMESERIES {series_name}\n")
            continue
        if section == "OPTIONS" and s and not s.startswith(";"):
            key = s.split()[0].upper()
            if key in options:
                out.append(f"{key:<20} {options[key]}\n")
                seen_options.add(key)
                continue
        out.append(line)
    if not gages:
        raise ValueError(f"{inp} has no rain gage in [RAINGAGES]")
    missing = set(options) - seen_options
    if missing:
        raise ValueError(f"{inp} [OPTIONS] lacks {sorted(missing)}")
    if out and not out[-1].endswith("\n"):
        out.append("\n")
    out.append("\n")
    out.extend(ts_block)
    Path(out_inp).write_text("".join(out))
    return {
        "inp": str(out_inp),
        "rain_gages": gages,
        "series_name": series_name,
        "raingage_format": fmt,
        "raingage_interval": rain_interval,
        "sim_start": start.strftime("%Y-%m-%d %H:%M:%S"),
        "sim_end": end.strftime("%Y-%m-%d %H:%M:%S"),
        "report_step": report_step,
        "n_rain_rows": len(rows),
        "rain_supplied_mm": round(_rain_depth_mm(rows, interval_h, fmt, start, end), 3),
        "max_rain_value": max((v for _, v in rows), default=0.0),
    }


def _rpt_runoff_depths(rpt: Path) -> dict:
    """Depth column (mm) of the Runoff Quantity Continuity block of the .rpt."""
    out = {}
    if not Path(rpt).exists():
        return out
    text = Path(rpt).read_text(errors="ignore")
    m = re.search(r"Runoff Quantity Continuity(.*?)Continuity Error", text, re.S | re.I)
    if not m:
        return out
    for key, label in (("total_precip_mm", "Total Precipitation"),
                       ("evaporation_mm", "Evaporation Loss"),
                       ("infiltration_mm", "Infiltration Loss"),
                       ("surface_runoff_mm", "Surface Runoff"),
                       ("final_storage_mm", "Final Storage")):
        mm = re.search(label + r"\s*\.+\s+(\S+)\s+(\S+)", m.group(1))
        if mm:
            try:
                out[key] = float(mm.group(2))
            except ValueError:
                out[key] = float("nan")
    return out


def run_city_swmm(city: str, bbox, workdir, duration: int = 86400,
                  min_slope_pct: float = 0.01,
                  min_manning_n: float = 0.01,
                  rain_dat=None, rain_interval: str | None = None,
                  rain_format: str | None = None,
                  sim_start: str | None = None, sim_end: str | None = None,
                  wettest_days: int | None = None,
                  report_step: str | None = None,
                  existing_inp=None) -> dict:
    """Build a synthetic SWMM network for `bbox` and run it.

    Args:
        city: project/city name (used for swmmanywhere project dir).
        bbox: (min_lon, min_lat, max_lon, max_lat).
        workdir: base directory for swmmanywhere downloads + model.
        duration: simulation duration in seconds (informational; swmmanywhere's
            bundled design-storm event sets the actual run window).
        min_slope_pct: floor for subcatchment %Slope in generated networks.
        rain_dat: a rain .dat from tools/s3_rainfall_forcing (one series). When
            given, the rain gage reads it instead of the bundled design storm;
            rain_interval and rain_format are then required.
        rain_interval: the [RAINGAGES] INTERVAL of that series, 'H:MM'
            ('3:00' for cmfd / mswx, '1:00' for nasa_power).
        rain_format: 'intensity' (mm/hr) or 'volume' (mm per interval).
        sim_start, sim_end: first and last day to simulate, 'YYYY-MM-DD', both
            included. Default: the whole period the rain data covers. The
            window must lie fully inside that period (the ';;COVERAGE' line of
            the .dat, or the days its rows span when it has none); a window
            that reaches outside it is refused, not run as zero rain.
        wettest_days: instead of sim_start/sim_end, simulate the N days in a
            row with the most rain in the series.
        report_step: REPORT_STEP for the external-rain run (default: the rain
            interval).
        existing_inp: a model this tool built before (the swmmanywhere .inp);
            skips the build, so a relaunch does not download and derive the
            network again.

    Returns dict with continuity_error (max abs %), component errors, network
    sizes, building count, bbox and inp path.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # External rain: read and check it BEFORE the slow build.
    rain = None
    if rain_dat is not None:
        if not rain_interval or not rain_format:
            raise ValueError("rain_dat needs rain_interval and rain_format (the "
                             "INTERVAL and FORMAT the rain tool printed)")
        if wettest_days and (sim_start or sim_end):
            raise ValueError("give wettest_days or sim_start/sim_end, not both")
        interval_h = _interval_hours(rain_interval)
        series_name, records = _read_rain_dat(Path(rain_dat))
        gaps = [(b[0] - a[0]).total_seconds() / 3600.0
                for a, b in zip(records, records[1:])]
        if gaps and min(gaps) < interval_h - 1e-9:
            raise ValueError(
                f"rain rows are {min(gaps):g} h apart but rain_interval is "
                f"{rain_interval}; the INTERVAL must be the data step")
        # The period the rain data covers. A KI rain .dat leaves zero rows
        # out, so its ';;COVERAGE' line is the proof; a file without that line
        # only proves the whole days its rows span.
        coverage = _read_rain_coverage(Path(rain_dat))
        if coverage is None:
            day0 = records[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
            day1 = records[-1][0].replace(hour=0, minute=0, second=0, microsecond=0)
            cov_start, cov_end = day0, day1 + timedelta(days=1)
            cov_from = "the days its rows span (no ;;COVERAGE line)"
        else:
            cov_start, cov_end = coverage
            cov_from = "its ;;COVERAGE line"
            if records and (records[0][0] < cov_start
                            or records[-1][0] >= cov_end):
                raise ValueError(
                    f"{rain_dat} has rows from {records[0][0]} to {records[-1][0]}, "
                    f"outside its ;;COVERAGE {cov_start} .. {cov_end}")
        if wettest_days and not records:
            raise ValueError(
                f"{rain_dat} is all dry over {cov_start} .. {cov_end}; "
                f"wettest_days has no wet day to pick, give sim_start/sim_end")
        if wettest_days:
            start_dt, end_dt = _wettest_window(records, interval_h, rain_format,
                                               int(wettest_days))
        else:
            start_dt = datetime.strptime(sim_start, "%Y-%m-%d") if sim_start \
                else cov_start
            end_dt = datetime.strptime(sim_end, "%Y-%m-%d") + timedelta(days=1) \
                if sim_end else cov_end
        if end_dt <= start_dt:
            raise ValueError("the simulation end is not after its start")
        if start_dt < cov_start or end_dt > cov_end:
            raise ValueError(
                f"the simulation window {start_dt} .. {end_dt} is not fully inside "
                f"the rain data, which covers {cov_start} .. {cov_end} (from "
                f"{cov_from}); the uncovered time would run as zero rain. Build "
                f"the rain .dat for the whole window or shorten the window.")
        rain = (series_name, records, start_dt, end_dt, cov_start, cov_end)
    elif any(x is not None for x in (rain_interval, rain_format, sim_start,
                                     sim_end, wettest_days)):
        raise ValueError("rain_interval / rain_format / sim_start / sim_end / "
                         "wettest_days only apply together with rain_dat")

    if existing_inp is not None and Path(existing_inp).is_file():
        inp_path = Path(existing_inp)
    else:
        _patch_s3_timeouts()
        _patch_resilient_buildings()
        _patch_osmnx_timeout()
        _patch_robust_outfalls()

        config = {
            "base_dir": workdir,        # must be a Path, not str
            "project": city.lower(),
            "bbox": list(bbox),
            # Build only: we floor subcatchment slopes in the written .inp
            # BEFORE running, then run with pyswmm ourselves.
            "run_model": False,
        }

        inp_path, _ = swmmanywhere(config)
        inp_path = Path(inp_path)
    built_inp = inp_path

    slope_fix = _floor_subcatchment_slopes(inp_path, min_slope_pct=min_slope_pct)
    manning_fix = _floor_subarea_manning(inp_path, min_manning_n=min_manning_n)
    imperv_fix = _clamp_subcatchment_imperv(inp_path)
    snowpack_fix = _remove_inactive_template_snowpack(inp_path)

    rain_info = None
    if rain is not None:
        series_name, records, start_dt, end_dt, cov_start, cov_end = rain
        ext_inp = inp_path.with_name(inp_path.stem + "_extrain.inp")
        rain_info = _apply_external_rain(inp_path, ext_inp, series_name, records,
                                         rain_interval, rain_format, start_dt,
                                         end_dt, report_step=report_step,
                                         coverage=(cov_start, cov_end))
        rain_info["rain_dat"] = str(rain_dat)
        rain_info["rain_coverage_start"] = cov_start.strftime("%Y-%m-%d %H:%M:%S")
        rain_info["rain_coverage_end"] = cov_end.strftime("%Y-%m-%d %H:%M:%S")
        inp_path = ext_inp

    # Run the prepared model with the real EPA SWMM engine via pyswmm.
    with pyswmm.Simulation(str(inp_path)) as sim:
        for _ in sim:
            pass
    # NOTE: continuity errors are finalised on context __exit__ (swmm_end);
    # read them from the authoritative .rpt now that it is written/closed.

    rpt = inp_path.with_suffix(".rpt")
    rpt_cont = _rpt_continuity(rpt)
    runoff_err = rpt_cont["runoff_pct"]
    routing_err = rpt_cont["flow_routing_pct"]

    finite = [abs(e) for e in (runoff_err, routing_err)
              if e is not None and math.isfinite(e)]
    has_nan = any(e is not None and not math.isfinite(e)
                  for e in (runoff_err, routing_err))
    continuity_valid = len(finite) == 2 and not has_nan
    ce = max(finite) if continuity_valid else None
    # JSON has no NaN/Infinity literals. Preserve the failure flag, and use null
    # for invalid components so web/API clients can read the diagnostic result.
    rpt_cont = {key: value if value is None or math.isfinite(value) else None
                for key, value in rpt_cont.items()}
    runoff_err = rpt_cont["runoff_pct"]
    routing_err = rpt_cont["flow_routing_pct"]

    counts = _count_inp_sections(inp_path)

    depths = _rpt_runoff_depths(rpt)
    depths = {key: value if value is None or math.isfinite(value) else None
              for key, value in depths.items()}
    if rain_info is not None:
        # Did the rain get in? SWMM's own rain depth against the .dat's.
        got = depths.get("total_precip_mm")
        want = rain_info["rain_supplied_mm"]
        rain_info["rpt_total_precip_mm"] = got
        # A dry window (want == 0) is fine when SWMM also saw no rain.
        rain_info["rain_applied_ok"] = bool(
            got is not None and math.isfinite(got)
            and (abs(got - want) <= 0.01 * want if want > 0
                 else abs(got) < 0.001))

    return {
        "city": city,
        "bbox": list(bbox),
        "inp": str(inp_path),
        "built_inp": str(built_inp),
        "rpt": str(rpt),
        "external_rain": rain_info,
        "rpt_runoff_depths_mm": depths,
        "continuity_error": ce,
        "continuity_valid": continuity_valid,
        "continuity_has_nan": has_nan,
        "runoff_continuity_error_pct": runoff_err,
        "flow_routing_continuity_error_pct": routing_err,
        "rpt_continuity": rpt_cont,
        "slope_fix": slope_fix,
        "manning_fix": manning_fix,
        "imperv_fix": imperv_fix,
        "snowpack_fix": snowpack_fix,
        "n_building_footprints": _building_rows(workdir),
        **counts,
    }


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Build a city SWMM model from a bbox (swmmanywhere), run it, "
                    "report the continuity errors")
    parser.add_argument("--city", required=True, help="City / project name")
    parser.add_argument("--bbox", required=True,
                        help="min_lon,min_lat,max_lon,max_lat")
    parser.add_argument("--workdir", required=True,
                        help="Folder for the downloads and the model")
    parser.add_argument("--rain_dat", default=None,
                        help="Rain .dat from tools/s3_rainfall_forcing; replaces the "
                             "bundled design storm")
    parser.add_argument("--rain_interval", default=None,
                        help="[RAINGAGES] INTERVAL of the rain .dat, H:MM (3:00 cmfd / "
                             "mswx, 1:00 nasa_power)")
    parser.add_argument("--rain_format", default=None, choices=["intensity", "volume"],
                        help="What the rain .dat holds: mm/hr or mm per interval")
    parser.add_argument("--sim_start", default=None, help="First day, YYYY-MM-DD")
    parser.add_argument("--sim_end", default=None, help="Last day (included), YYYY-MM-DD")
    parser.add_argument("--wettest_days", type=int, default=None,
                        help="Simulate the N wettest days in a row of the rain series")
    parser.add_argument("--report_step", default=None,
                        help="REPORT_STEP for an external-rain run, HH:MM:SS "
                             "(default: the rain interval)")
    parser.add_argument("--existing_inp", default=None,
                        help="A model built before by this tool; skips the build")
    parser.add_argument("--json_out", default=None, help="Write the result dict here")
    args = parser.parse_args()

    bbox = tuple(float(x) for x in args.bbox.split(","))
    if len(bbox) != 4:
        parser.error("--bbox needs four numbers")
    result = run_city_swmm(
        args.city, bbox, args.workdir,
        rain_dat=args.rain_dat, rain_interval=args.rain_interval,
        rain_format=args.rain_format, sim_start=args.sim_start,
        sim_end=args.sim_end, wettest_days=args.wettest_days,
        report_step=args.report_step, existing_inp=args.existing_inp)
    text = json.dumps(result, indent=2, default=str, allow_nan=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(text)
    print(text)
    if not result["continuity_valid"]:
        raise SystemExit("SWMM continuity balance is missing or non-finite; see the report")


if __name__ == "__main__":
    main()
