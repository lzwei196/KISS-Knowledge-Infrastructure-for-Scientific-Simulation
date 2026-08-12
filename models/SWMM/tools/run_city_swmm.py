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

* RUNOFF-CONTINUITY NaN — swmmanywhere's defs/swmm_conversion.yml writes
  ``[SUBAREAS]`` with Manning's n = 0 for both impervious and pervious surfaces
  (``iwcolumns: [subcatchment, /0, /0, /0, /0, /0, /OUTLET, /0]``). SWMM's
  overland nonlinear-reservoir routing coefficient is alpha = 1.49 * W *
  sqrt(S) / (A * n). With n = 0, alpha is +inf for every subcatchment with a
  positive slope (they drain instantly — fine), BUT for the handful of
  subcatchments whose DEM-derived slope is exactly 0 the expression becomes
  0 / 0 = NaN, producing a NaN ponded depth -> NaN "Final Storage" -> NaN
  Surface-Runoff continuity error for the whole model. (For the Nanjing bbox,
  55 of 23974 subcatchments had slope 0.) A perfectly flat subcatchment is a
  DEM artefact, so we floor the subcatchment %Slope to a small positive value
  before running. This makes alpha finite for those cells (identical instant-
  drain behaviour to the other 23919), eliminating the 0/0 without altering the
  hydraulics of any non-flat subcatchment.

* BUILDINGS — the Overture-buildings download (anonymous pyarrow S3 through the
  HTTP proxy) is slow but works. We attempt the REAL download and fall back to
  a VALID empty geoparquet ONLY if it genuinely fails or leaves a corrupt
  footer-less file, so real building footprints are used whenever available.
"""

from __future__ import annotations

import math
import re
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

    swmmanywhere's swmm_conversion.yml writes Manning's n = 0 for every subarea.
    The overland nonlinear-reservoir coefficient is alpha = 1.49 * W * sqrt(S)
    / (A * n); with n = 0 it is x/0 = +inf for every (slope-floored) cell, which
    SWMM propagates to a NaN ponded depth and hence a NaN Runoff-Quantity
    continuity error for the whole model. Flooring %Slope alone removes the 0/0
    but leaves x/0 = inf -> still NaN; the n term is the governing zero. We floor
    both N columns so alpha is finite and the surface mass balance closes.

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

    swmmanywhere's derive_rc computes the impervious fraction as a float ratio
    that can overshoot 100 by a rounding ULP (observed 100.00000000000003 on 6
    of 23974 Nanjing subcatchments). %Imperv > 100 makes the PERVIOUS subarea
    area = Area*(100-%Imperv)/100 negative; SWMM's overland nonlinear reservoir
    then raises a negative ponded depth to the 5/3 power -> NaN ponded depth ->
    NaN "Final Storage" -> NaN Runoff-Quantity continuity for the whole model.
    Flooring n and %Slope does NOT touch this; %Imperv is the governing input.
    Only RAISES values < lo or LOWERS values > hi; in-range cells are untouched.

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
        m = re.search(
            header + r".*?Continuity Error \(%\)\s*\.*\s*([-\d.]+|nan)",
            text,
            re.S | re.I,
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


def run_city_swmm(city: str, bbox, workdir, duration: int = 86400,
                  min_slope_pct: float = 0.01,
                  min_manning_n: float = 0.01) -> dict:
    """Build a synthetic SWMM network for `bbox` and run it.

    Args:
        city: project/city name (used for swmmanywhere project dir).
        bbox: (min_lon, min_lat, max_lon, max_lat).
        workdir: base directory for swmmanywhere downloads + model.
        duration: simulation duration in seconds (informational; swmmanywhere's
            bundled design-storm event sets the actual run window).
        min_slope_pct: floor for subcatchment %Slope (NaN-continuity fix).

    Returns dict with continuity_error (max abs %), component errors, network
    sizes, building count, bbox and inp path.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    _patch_s3_timeouts()
    _patch_resilient_buildings()
    _patch_osmnx_timeout()
    _patch_robust_outfalls()

    config = {
        "base_dir": workdir,        # must be a Path, not str
        "project": city.lower(),
        "bbox": list(bbox),
        # Build only: we floor subcatchment slopes in the written .inp BEFORE
        # running, then run with pyswmm ourselves (avoids the 0/0 NaN and a
        # wasteful double run).
        "run_model": False,
    }

    inp_path, _ = swmmanywhere(config)
    inp_path = Path(inp_path)

    slope_fix = _floor_subcatchment_slopes(inp_path, min_slope_pct=min_slope_pct)
    manning_fix = _floor_subarea_manning(inp_path, min_manning_n=min_manning_n)
    imperv_fix = _clamp_subcatchment_imperv(inp_path)

    # Run the (slope-fixed) model with the real EPA SWMM engine via pyswmm.
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
    ce = max(finite) if finite else float("nan")

    counts = _count_inp_sections(inp_path)

    return {
        "city": city,
        "bbox": list(bbox),
        "inp": str(inp_path),
        "continuity_error": ce,
        "continuity_has_nan": has_nan,
        "runoff_continuity_error_pct": runoff_err,
        "flow_routing_continuity_error_pct": routing_err,
        "rpt_continuity": rpt_cont,
        "slope_fix": slope_fix,
        "manning_fix": manning_fix,
        "imperv_fix": imperv_fix,
        "n_building_footprints": _building_rows(workdir),
        **counts,
    }
