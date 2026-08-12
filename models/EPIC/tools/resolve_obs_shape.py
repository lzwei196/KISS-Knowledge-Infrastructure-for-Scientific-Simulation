#!/usr/bin/env python3
"""Resolve the dag-correct obs_shape + comparison contract for an EPIC output var.

WHY THIS EXISTS
---------------
EPIC 1102 is a 0-D point field model, but most yield observations reachable on
this server are AREA-AVERAGE, census-anchored products (GDHY 0.5deg, SPAM,
FAOSTAT, statistical yearbooks) rather than true point records.  dag.yaml lists
BOTH ``point_time_series`` and ``regional_aggregate_time_series`` under
``outputs[YLDG].observability.comparable_obs_shapes`` but carries NO rule for
choosing between them.  A GDHY 0.5deg cell was therefore bound as
``point_time_series``, which promoted raw inter-annual r / NSE / KGE to the
headline -- metrics the dag's own ``regional_aggregate_time_series`` caveat says
are structurally unreachable for a fixed-management weather-driven point model.
See triplet EPIC_025.

WHAT IS DAG-DRIVEN AND WHAT IS NOT (read before trusting the output)
--------------------------------------------------------------------
Read verbatim out of dag.yaml, so editing the dag changes the answer:
  * the set of admissible obs_shapes            (comparable_obs_shapes)
  * comparison_mode, metric_families, determining_metric, caveats  (per shape)
  * detrending_options                          (per var)
  * WHICH metric is the verdict -- it is exactly ``determining_metric`` and
    nothing else.  This tool never promotes a second metric to verdict status.
  * the non-verdict rationale -- quoted verbatim from the chosen shape's caveats.

NOT in the dag, and therefore declared here as an explicit registry:
  * dag.yaml names metric FAMILIES ("trend_match"), not metric KEYS ("r_detr").
    ``METRIC_FAMILY_SOURCE`` below is the KI-local binding from each dag family
    to (the ki_tools_common scorer that computes it, the subset of THAT
    scorer's emitted keys the family covers); ``METRIC_FAMILY_METRICS`` is
    derived from it.  It is data, not logic, and it is CHECKED:
    ``verify_metric_registry()`` asserts every declared key is really emitted
    by its scorer -- statically on every ``resolve()`` (reported as
    ``metric_registry_check``) and against the LIVE scorers under
    ``--self-check``.  A dag family with no registry row is reported in
    ``unmapped_metric_families`` -- for the chosen shape AND for the var's
    other shapes -- rather than silently dropped, so an edited dag fails
    loudly instead of quietly returning a short list.
  * the area-average detection heuristics (granularity / dataset / geometry).
  * which vars carry a moisture basis (``MOISTURE_BASIS_VARS``).

USAGE
-----
    python tools/resolve_obs_shape.py --var YLDG --granularity grid \\
        --geometry "0.5deg grid cell" --dataset-id gdhy_v1_2_v1_3 --n-steps 20
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DAG = os.path.join(os.path.dirname(_HERE), "dag.yaml")

AREA_GRANULARITIES = {
    "grid", "gridcell", "grid_cell", "region", "regional", "area",
    "national", "country", "province", "prefecture", "county",
    "admin", "admin1", "admin2", "district", "basin",
}
AREA_DATASET_HINTS = (
    "gdhy", "iizumi", "spam", "faostat", "fao_", "yearbook", "census",
    "agmip", "gaez", "eurostat", "usda_nass_county",
)
AREA_GEOMETRY_RE = re.compile(
    r"(\d+(\.\d+)?\s*(deg|degree|arcmin|arcsec|km))|cell|polygon|shapefile|county|province",
    re.I,
)

# ---------------------------------------------------------------------------
# dag metric FAMILY -> the metric keys ki_tools_common ACTUALLY emits.
#
# EMITTED_METRIC_KEYS is the literal return-key set of each ki_tools_common
# scorer, copied from its return dict (paths are
# models/ki_tools_common/ki_tools_common/metrics.py):
#   all_metrics      -> NSE, KGE, PBIAS, RMSE, r                    (return at :290-296)
#   trend_metrics    -> r_detr, r_firstdiff, slope_ratio,
#                       slope_obs, slope_sim, PBIAS                 (return at :511-516)
#   spatial_metrics  -> all_metrics keys + csi, csi_threshold,
#                       csi_by_threshold, n_pairs                   (return at :637-648)
# Note PBIAS is emitted by trend_metrics too -- that is why "trend_match"
# carries it.  Omitting it (as this registry previously did) made the family
# binding UNFAITHFUL to the scorer.
#
# METRIC_FAMILY_SOURCE binds each dag metric_family to ONE scorer plus the
# subset of THAT scorer's emitted keys the family covers.  The family split for
# spatial_metrics is the one its own docstring declares: spatial_pattern_match
# = the pattern metrics (csi + csi_threshold + r/NSE/RMSE over cell pairs),
# magnitude_accuracy = PBIAS.
#
# verify_metric_registry() checks every declared key is a member of its
# scorer's emitted set, and (live=True, also exposed as `--self-check`)
# re-derives those sets by CALLING the scorers, so this registry cannot drift
# away from ki_tools_common silently.
# Add a row here when dag.yaml gains a new family; do NOT special-case in code.
EMITTED_METRIC_KEYS = {
    "ki_tools_common.metrics.all_metrics":
        ["KGE", "NSE", "PBIAS", "RMSE", "r"],
    "ki_tools_common.metrics.trend_metrics":
        ["PBIAS", "r_detr", "r_firstdiff", "slope_obs", "slope_ratio", "slope_sim"],
    "ki_tools_common.metrics.spatial_metrics":
        ["KGE", "NSE", "PBIAS", "RMSE", "csi", "csi_by_threshold",
         "csi_threshold", "n_pairs", "r"],
}

METRIC_FAMILY_SOURCE = {
    "magnitude_accuracy":     ("ki_tools_common.metrics.all_metrics",
                               ["PBIAS", "RMSE"]),
    "temporal_pattern_match": ("ki_tools_common.metrics.all_metrics",
                               ["r", "NSE", "KGE"]),
    "trend_match":            ("ki_tools_common.metrics.trend_metrics",
                               ["r_detr", "r_firstdiff", "slope_ratio",
                                "slope_obs", "slope_sim", "PBIAS"]),
    "spatial_pattern_match":  ("ki_tools_common.metrics.spatial_metrics",
                               ["csi", "csi_threshold", "r", "NSE", "RMSE"]),
}

# The family -> metric-keys view used by the resolver.  DERIVED, never edited
# by hand, so it cannot disagree with METRIC_FAMILY_SOURCE.
METRIC_FAMILY_METRICS = {fam: list(keys)
                         for fam, (_src, keys) in METRIC_FAMILY_SOURCE.items()}


def _live_emitted_keys():
    """Emitted key sets re-derived by CALLING ki_tools_common.metrics.

    The probe is run with KDT_SERIES_DUMP_DIR pointed at a throwaway temp dir
    (and KDT_RUN_CONTEXT cleared) so all_metrics'/spatial_metrics' best-effort
    evidence capture can never write a synthetic series into a real run's
    series dir.  Raises on import failure; the caller decides what that means.
    """
    import tempfile
    from ki_tools_common import metrics as _m

    o = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = [1.1, 1.9, 3.2, 3.8, 5.3]
    saved = {k: os.environ.get(k) for k in ("KDT_SERIES_DUMP_DIR", "KDT_RUN_CONTEXT")}
    try:
        with tempfile.TemporaryDirectory(prefix="resolve_obs_shape_selfcheck_") as td:
            os.environ["KDT_SERIES_DUMP_DIR"] = td
            os.environ.pop("KDT_RUN_CONTEXT", None)
            return {
                "ki_tools_common.metrics.all_metrics": sorted(_m.all_metrics(o, s)),
                "ki_tools_common.metrics.trend_metrics": sorted(_m.trend_metrics(o, s)),
                "ki_tools_common.metrics.spatial_metrics": sorted(_m.spatial_metrics(o, s)),
            }
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def verify_metric_registry(live=True):
    """(ok, report) -- is every declared family key really emitted by its scorer?

    live=True additionally compares EMITTED_METRIC_KEYS against the key sets
    the scorers actually return right now, so a renamed/dropped metric key in
    ki_tools_common surfaces here instead of silently shrinking a family.
    """
    emitted = {k: sorted(v) for k, v in EMITTED_METRIC_KEYS.items()}
    problems = []
    live_ok = False
    if live:
        try:
            live_keys = _live_emitted_keys()
            live_ok = True
        except Exception as exc:                      # ki_tools_common not importable
            live_keys = {}
            problems.append("live probe unavailable (%s: %s)"
                            % (type(exc).__name__, exc))
        for src, keys in live_keys.items():
            declared = sorted(EMITTED_METRIC_KEYS.get(src) or [])
            if declared != keys:
                problems.append(
                    "EMITTED_METRIC_KEYS[%s] declares %s but the scorer emits %s"
                    % (src, declared, keys))
            emitted[src] = keys                       # trust the live set
    for fam, (src, keys) in METRIC_FAMILY_SOURCE.items():
        if src not in emitted:
            problems.append("family %r names unknown scorer %s" % (fam, src))
            continue
        missing = [k for k in keys if k not in emitted[src]]
        if missing:
            problems.append("family %r maps to %s, which %s does not emit"
                            % (fam, missing, src))
    return (not problems), {
        "live_probe_ran": live_ok,
        "emitted_metric_keys": emitted,
        "metric_family_source": {f: {"scorer": s, "metrics": k}
                                 for f, (s, k) in METRIC_FAMILY_SOURCE.items()},
        "problems": problems,
    }

# Vars whose value is a mass of harvested material, so a dry/market moisture
# basis exists and must be declared on BOTH sides before scoring.
MOISTURE_BASIS_VARS = {"YLDG", "YLDF", "BIOM"}

# ---------------------------------------------------------------------------
# OBS moisture-basis registry  (closes the open item of triplet EPIC_025)
# ---------------------------------------------------------------------------
# EPIC_025 required the OBS moisture basis to be ESTABLISHED from the obs
# product's own documentation and CITED, and until it is, the tool must say
# UNKNOWN rather than assume. That left every run free to pick, and at
# Changchun the undeclared choice moved the dag's DETERMINING metric from
# PBIAS +26.8% to +50.1%.
#
# This table is the ESTABLISHED record, one row per obs product, each with the
# documentary chain that establishes it. It is DATA, not a guess: a product
# with no row still resolves to "undetermined", a CROP with no cited constant in
# a row that does exist ALSO resolves to "undetermined", and the tool never
# infers a basis from the product's name nor borrows one crop's constant for
# another.
#
# Establishing chain for the census-anchored products
# ---------------------------------------------------
# GDHY / SPAM / FAOSTAT are all anchored to FAO-reported country yield
# statistics, so they inherit FAO's reporting basis:
#   * GDHY: "The grid-cell yield data were estimated using the satellite-derived
#     crop-specific vegetation index and FAO-reported country yield statistics"
#     (Iizumi & Sakai 2020, Sci Data 7:97, doi:10.1038/s41597-020-0433-7). The
#     GDHY NetCDF carries NO attributes at all (verified 2026-07-29: the .nc4
#     files have empty global attrs and an unlabelled var 'var'), so the basis
#     cannot be read off the file and MUST come from this chain.
#   * FAO crop-production definitions: "Production data for cereals are reported
#     in terms of clean, dry weight of grains with 12-14 percent moisture in the
#     form usually marketed" and "Area and production data on cereals relate to
#     crops harvested for dry grain only. Rice, however, is reported in terms of
#     paddy."
# => CEREALS in these products are MARKET (commercial) moisture, NOT oven-dry
#    matter. EPIC .ACY YLDG is dry matter, so the two sides are NOT comparable
#    as-is.
#
# HOW FAR THE CHAIN REACHES (the scope limit that makes this data, not a guess)
# ----------------------------------------------------------------------------
# The two documents above establish exactly two things: (a) FAO reports CEREALS
# at a 12-14% market-moisture BAND, and (b) China GB 1353 fixes MAIZE grain
# trade moisture at <=14.0% -- a crop-specific POINT convention.  They say
# NOTHING about oilseeds, roots, tubers, fibre or any other crop group.
#
# That difference between a BAND and a POINT is the whole reason this table is
# split in two.  A conversion needs ONE number, and the only crop for which the
# chain cites one is maize (GB 1353's <=14.0%, which also happens to sit at the
# top of FAO's band).  For the other cereals the chain reaches the crop but
# stops at the band: picking its midpoint (0.135) would be a value this KI
# INVENTED, not one any cited source states -- i.e. exactly the uncited
# constant triplet EPIC_025 was opened against, just with a citation-shaped
# comment attached.  So band-only crops resolve to UNDETERMINED (no conversion,
# `established=False`) and carry the band as an explicit RANGE-ONLY
# SENSITIVITY; they become convertible only when a crop-specific point
# convention is established from documentation and cited, the way GB 1353 does
# for maize.  Crops the chain does not reach at all -- soybean included -- stay
# undetermined with no band either.  There is deliberately NO product-level
# default `w`: a default is exactly how an uncited constant gets chosen
# silently.
#
# `w` is the water fraction of the obs product's mass. Convert EITHER side --
# the resulting PBIAS is identical:
#     sim_market = sim_dry / (1 - w)      or      obs_dry = obs_market * (1 - w)

# Crops for which the chain cites a crop-specific POINT convention, each with
# the citation that establishes THAT crop.  ONLY these license a conversion.
# A crop absent from this table has no cited w for these products; see
# FAO_MARKET_W_BAND_ONLY (band cited, no point value) and
# FAO_MARKET_W_UNDETERMINED (chain does not reach the crop at all).
FAO_MARKET_W_BY_CROP = {
    "maize": 0.14,
}
FAO_MARKET_W_PROVENANCE = {
    "maize": "China GB 1353 (maize) national grain standard: trade moisture "
             "<=14.0%, a crop-specific POINT convention, which is also the top "
             "of FAO's 12-14% cereal band.",
}
# Crops the chain reaches only as a BAND: FAO's cereal statement covers them,
# but no cited source fixes a point value, so they are NOT convertible.  Each
# row carries the band to report as a range-only sensitivity and the reason the
# tool refuses a point conversion.
FAO_MARKET_W_BAND_ONLY = {
    "wheat": {
        "w_range": [0.12, 0.14],
        "band_source": "FAO crop-production definitions: cereals reported as "
                       "'clean, dry weight of grains with 12-14 percent "
                       "moisture in the form usually marketed'.",
        "reason": "the cited chain gives a 12-14% moisture BAND for cereals as "
                  "a group; it states no wheat-specific point value, and no "
                  "wheat grain standard is cited here. A midpoint (0.135) "
                  "would be this KI's invention, not the source's number, so "
                  "no conversion is applied. Report the band as a RANGE-ONLY "
                  "sensitivity, and add a row to FAO_MARKET_W_BY_CROP only "
                  "once a wheat-specific point convention (a national/trade "
                  "grain standard, as GB 1353 is for maize) is established "
                  "from documentation and cited.",
    },
    "rice": {
        "w_range": [0.12, 0.14],
        "band_source": "FAO crop-production definitions: cereals reported as "
                       "'clean, dry weight of grains with 12-14 percent "
                       "moisture in the form usually marketed'; rice is "
                       "reported as PADDY.",
        "reason": "the cited chain gives a 12-14% moisture BAND for cereals as "
                  "a group; it states no rice-specific point value, so a "
                  "midpoint (0.135) would be this KI's invention rather than "
                  "the source's number and no conversion is applied. Report "
                  "the band as a RANGE-ONLY sensitivity. Note the "
                  "paddy-vs-milled convention is a SEPARATE issue from "
                  "moisture and must be handled too -- establishing a rice "
                  "point w does not by itself make the pairing comparable.",
    },
}
# Crops explicitly NOT established by the chain above, with the reason -- so the
# tool can say WHY it is refusing rather than just returning a blank.
FAO_MARKET_W_UNDETERMINED = {
    "soybean": "The FAO '12-14 percent moisture' statement is about CEREALS and "
               "China GB 1353 is the MAIZE grain standard; neither establishes a "
               "market-moisture basis for soybean, which is an oilseed. (The "
               "w=0.13 previously carried here is the US soybean grain-trade "
               "convention -- a US trade rule, not the FAO reporting basis these "
               "products inherit.) Establish soybean's basis from the product's "
               "own documentation, cite it, and only then add a row here.",
}

OBS_MOISTURE_BASIS = {
    "gdhy_v1_2_v1_3": {
        "basis": "market",
        "established": True,
        "inherited_from": "faostat_country_yield_statistics",
        "w_by_crop": dict(FAO_MARKET_W_BY_CROP),
        "w_provenance": dict(FAO_MARKET_W_PROVENANCE),
        "w_band_only": {c: dict(v) for c, v in FAO_MARKET_W_BAND_ONLY.items()},
        "w_undetermined": dict(FAO_MARKET_W_UNDETERMINED),
        "w_range": [0.12, 0.14],
        "citations": [
            "Iizumi & Sakai (2020) 'The global dataset of historical yields for "
            "major crops 1981-2016', Sci Data 7:97, doi:10.1038/s41597-020-0433-7 "
            "-- GDHY grid yields are estimated from a satellite crop-specific "
            "vegetation index calibrated to FAO-reported COUNTRY YIELD STATISTICS, "
            "so GDHY inherits FAOSTAT's reporting basis.",
            "FAO crop-production definitions/standards -- 'Production data for "
            "cereals are reported in terms of clean, dry weight of grains with "
            "12-14 percent moisture in the form usually marketed'; 'Area and "
            "production data on cereals relate to crops harvested for dry grain "
            "only. Rice, however, is reported in terms of paddy.'",
            "China GB 1353 (maize) national grain standard: trade moisture "
            "<=14.0% -- the value used for maize in China, and the top of FAO's "
            "12-14% cereal band.",
        ],
        "confidence": "inherited (FAO basis via the documented calibration), not "
                      "a moisture statement printed in the GDHY files themselves; "
                      "the .nc4 files carry no attributes",
        "note": "Report PBIAS on BOTH bases regardless (EPIC_025). The w=0.155 US "
                "market-moisture constant used before this registry existed is a "
                "US grain-trade convention, NOT FAO's -- it is kept only as a "
                "sensitivity, not as the headline.",
    },
    "faostat_global_production_crops_livestock": {
        "basis": "market",
        "established": True,
        "inherited_from": "self",
        "w_by_crop": dict(FAO_MARKET_W_BY_CROP),
        "w_provenance": dict(FAO_MARKET_W_PROVENANCE),
        "w_band_only": {c: dict(v) for c, v in FAO_MARKET_W_BAND_ONLY.items()},
        "w_undetermined": dict(FAO_MARKET_W_UNDETERMINED),
        "w_range": [0.12, 0.14],
        "citations": [
            "FAO crop-production definitions/standards -- cereals reported as "
            "'clean, dry weight of grains with 12-14 percent moisture in the form "
            "usually marketed'; rice reported as paddy.",
        ],
        "confidence": "direct (this IS the FAO product)",
        "note": "Rice is PADDY (rough rice), not milled -- do not compare EPIC "
                "RICE YLDG to it without also handling the paddy convention.",
    },
    "spam2020": {
        "basis": "market",
        "established": True,
        "inherited_from": "faostat_country_yield_statistics",
        "w_by_crop": dict(FAO_MARKET_W_BY_CROP),
        "w_provenance": dict(FAO_MARKET_W_PROVENANCE),
        "w_band_only": {c: dict(v) for c, v in FAO_MARKET_W_BAND_ONLY.items()},
        "w_undetermined": dict(FAO_MARKET_W_UNDETERMINED),
        "w_range": [0.12, 0.14],
        "citations": [
            "SPAM allocates FAOSTAT/sub-national census production and area to a "
            "5-arcmin grid, so its yields carry the FAO market-moisture basis.",
        ],
        "confidence": "inherited (FAO basis via the allocation procedure)",
        "note": "Single-year snapshot product -- usually binds to point_snapshot.",
    },
}
# Alias -> registry key (same product under another id in the dataset index).
OBS_MOISTURE_ALIASES = {
    "gdhy": "gdhy_v1_2_v1_3",
    "faostat": "faostat_global_production_crops_livestock",
    "faostat_china": "faostat_global_production_crops_livestock",
    "spam": "spam2020",
    "spam_2020_crop_yield": "spam2020",
    # ki_tools_common.crop_obs.get_observed_yield labels its SPAM reads by the
    # file flavour it hit; both are the same SPAM2020 product, same chain.
    "spam2020_geotiff": "spam2020",
    "spam2020_csv": "spam2020",
    "globalcropyield5min": None,   # basis not established -> stays undetermined
    # NOT aliased on purpose: crop_obs' 'FAOSTAT_fallback' is a small hand-typed
    # table of approximate national averages, not the FAO product, so it gets no
    # row and resolves to undetermined.
}

CROP_ALIASES = {"corn": "maize", "soy": "soybean", "soybeans": "soybean",
                "paddy": "rice", "paddy_rice": "rice",
                "winter_wheat": "wheat", "spring_wheat": "wheat"}


def lookup_obs_moisture_basis(dataset_id, crop=None):
    """Return the ESTABLISHED obs moisture basis for (`dataset_id`, `crop`), or
    an explicit 'undetermined' record.

    Never guesses (triplet EPIC_025).  There are FOUR distinct outcomes and the
    caller must be able to tell them apart, so the record reports the product
    basis and the crop-specific constant SEPARATELY:

      * unknown product          -> product_basis_established=False,
                                    established=False, w=None
      * known product, but the crop is missing or the cited chain does not
        reach it at all (e.g. soybean, or `crop=None`)
                                 -> product_basis_established=True,
                                    established=False, w=None,
                                    undetermined_reason=<why>
      * known product, crop reached by the chain only as a BAND (no cited point
        convention -- e.g. wheat/rice under FAO's 12-14% cereal statement)
                                 -> product_basis_established=True,
                                    established=False, w=None,
                                    w_range_sensitivity=[lo, hi],
                                    w_range_source=<the band citation>,
                                    sensitivity_only=True
      * known product AND a cited crop-specific POINT w for THAT crop
                                 -> established=True, w=<cited value>,
                                    w_source=<the citation for that crop>

    ``established`` therefore means "this (product, crop) PAIR has a cited
    POINT moisture basis" -- it is the flag a caller may gate a conversion on.
    A band alone never sets it: a range cannot be applied as a conversion, only
    reported as a sensitivity.  There is no product-level default w, and no
    midpoint is ever synthesised from a band -- a product's basis being market
    does not by itself license a conversion constant for an arbitrary crop.
    """
    key = (dataset_id or "").strip().lower()
    key = OBS_MOISTURE_ALIASES.get(key, key)
    rec = OBS_MOISTURE_BASIS.get(key) if key else None
    crop_key = (crop or "").strip().lower()
    crop_key = CROP_ALIASES.get(crop_key, crop_key)
    if rec is None:
        return {
            "dataset_id": dataset_id,
            "crop": crop_key or None,
            "basis": "undetermined",
            "product_basis": "undetermined",
            "product_basis_established": False,
            "established": False,
            "w": None,
            "w_source": None,
            "w_range_sensitivity": None,
            "w_range_source": None,
            "sensitivity_only": False,
            "citations": [],
            "undetermined_reason": (
                "no registry row for obs product %r, so not even the product's "
                "own reporting basis is established here" % (dataset_id,)
            ),
            "rule": (
                "No registry row for this obs product. Establish the moisture "
                "basis from that product's OWN documentation, cite it in the run "
                "notes, and add a row to OBS_MOISTURE_BASIS in this file so the "
                "next run cannot silently re-decide it."
            ),
        }
    out = dict(rec)
    out["dataset_id"] = key
    out["crop"] = crop_key or None
    # The product's own reporting basis (established by this row's citations)
    # is reported separately from the per-crop constant.
    out["product_basis"] = rec["basis"]
    out["product_basis_established"] = bool(rec.get("established"))
    out["crops_with_established_w"] = sorted(rec.get("w_by_crop") or {})
    band_rows = rec.get("w_band_only") or {}
    out["crops_with_band_only_w"] = sorted(band_rows)
    w = (rec.get("w_by_crop") or {}).get(crop_key) if crop_key else None
    band = band_rows.get(crop_key) if crop_key else None
    if w is None:
        if not crop_key:
            reason = (
                "no crop was given, and %r has no product-level default w. The "
                "cited chain establishes a market-moisture constant per CROP "
                "(%s), not for the product as a whole -- pass --crop."
                % (key, ", ".join(out["crops_with_established_w"]) or "none")
            )
        elif band:
            reason = band.get("reason") or (
                "crop %r is reached by the cited chain only as the band %s, "
                "which fixes no point value." % (crop_key, band.get("w_range"))
            )
        else:
            reason = (rec.get("w_undetermined") or {}).get(crop_key) or (
                "crop %r has no cited crop-specific moisture basis in this "
                "registry row; the crops with a cited point w are %s and the "
                "band-only crops are %s."
                % (crop_key,
                   ", ".join(out["crops_with_established_w"]) or "none",
                   ", ".join(out["crops_with_band_only_w"]) or "none")
            )
        out["established"] = False
        out["w"] = None
        out["w_source"] = None
        out["undetermined_reason"] = reason
        if band:
            # The chain reaches this crop, but only as a RANGE.  Hand the range
            # back explicitly so the caller can report a range-only
            # sensitivity -- never as a conversion, and never collapsed to a
            # midpoint, which no cited source states.
            lo, hi = band.get("w_range") or [None, None]
            out["sensitivity_only"] = True
            out["w_range_sensitivity"] = list(band.get("w_range") or [])
            out["w_range_source"] = band.get("band_source")
            out["rule"] = (
                "Do NOT apply a moisture conversion: the cited chain gives a "
                "BAND (w in [%s, %s]) for this crop, not a point value, and a "
                "midpoint is not a cited constant. %s Score the raw "
                "(dry-vs-as-published) pairing as the headline, and report the "
                "band as a RANGE-ONLY sensitivity -- e.g. sim_dry / (1 - %s) "
                "to sim_dry / (1 - %s) -- clearly labelled as a sensitivity, "
                "never as the verdict. Add a row to FAO_MARKET_W_BY_CROP only "
                "once a crop-specific POINT convention is established from "
                "documentation and cited."
                % (lo, hi, reason, lo, hi)
            )
        else:
            out["sensitivity_only"] = False
            out["w_range_sensitivity"] = None
            out["w_range_source"] = None
            out["rule"] = (
                "Do NOT apply a moisture conversion. The product basis is %r, "
                "but that alone does not fix a constant for this crop: %s "
                "Establish the crop's basis from the product's own "
                "documentation, cite it, and add it to FAO_MARKET_W_BY_CROP / "
                "the row's w_by_crop in this file."
                % (rec.get("basis"), reason)
            )
    else:
        out["established"] = True
        out["w"] = w
        out["w_source"] = (rec.get("w_provenance") or {}).get(crop_key)
        # A cited POINT w is the headline; the product's band stays alongside it
        # as the sensitivity (SKILL.md: "w_range = 0.12-0.14 is the
        # sensitivity"), so the field means the same thing in every outcome.
        out["sensitivity_only"] = False
        out["w_range_sensitivity"] = list(rec.get("w_range") or []) or None
        out["w_range_source"] = None
        out["undetermined_reason"] = None
    return out


def load_dag(path):
    import yaml
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def var_aliases(name):
    """All output-var aliases declared in one dag ``var:`` string.

    dag.yaml groups related outputs in a single row, e.g.
    ``"MUSS/MUST/USLE (water erosion sediment yield)"`` or
    ``"QNO3 / SNO3 (nitrate loss / soil nitrate)"``.  The parenthetical
    description is dropped FIRST (it can itself contain a '/'), then the
    remainder is split on '/'.
    """
    base = re.sub(r"\(.*?\)", " ", str(name or ""))
    return [a.strip() for a in base.split("/") if a.strip()]


def _var_block(dag, var):
    want = str(var).strip().upper()
    for row in dag.get("outputs") or []:
        if want in {a.upper() for a in var_aliases(row.get("var", ""))}:
            return row
    return None


def is_area_average(granularity=None, geometry=None, dataset_id=None, network=None):
    """True when the obs represents an area average rather than a point."""
    reasons = []
    g = (granularity or "").strip().lower()
    if g in AREA_GRANULARITIES:
        reasons.append("granularity=%s" % g)
    ident = " ".join(x for x in (dataset_id, network) if x).lower()
    for hint in AREA_DATASET_HINTS:
        if hint in ident:
            reasons.append("dataset_id/network matches area-average product '%s'" % hint)
            break
    if geometry and AREA_GEOMETRY_RE.search(geometry):
        reasons.append("geometry=%r describes a cell/polygon" % geometry)
    return (len(reasons) > 0), reasons


def _metrics_for(families, unmapped=None):
    """Expand dag metric families into emitted metric keys, order-preserving."""
    out = []
    for fam in families or []:
        keys = METRIC_FAMILY_METRICS.get(fam)
        if keys is None:
            if unmapped is not None and fam not in unmapped:
                unmapped.append(fam)
            continue
        for k in keys:
            if k not in out:
                out.append(k)
    return out


def resolve(var, granularity=None, geometry=None, dataset_id=None,
            network=None, n_steps=None, dag_path=DEFAULT_DAG, crop=None):
    dag = load_dag(dag_path)
    blk = _var_block(dag, var)
    if blk is None:
        raise SystemExit("resolve_obs_shape: var %r not in %s outputs" % (var, dag_path))
    obs = blk.get("observability") or {}
    shape_list = obs.get("comparable_obs_shapes") or []
    shapes = {s["obs_shape"]: s for s in shape_list}
    if not shapes:
        raise SystemExit("resolve_obs_shape: %s has no comparable_obs_shapes" % var)

    area, reasons = is_area_average(granularity, geometry, dataset_id, network)
    multi = (n_steps is None) or (int(n_steps) >= 2)

    if area and multi:
        prefer = ["regional_aggregate_time_series", "point_time_series"]
    elif area:
        prefer = ["spatial_snapshot", "point_snapshot", "point_time_series"]
    elif multi:
        prefer = ["point_time_series", "regional_aggregate_time_series"]
    else:
        prefer = ["point_snapshot", "point_time_series"]

    chosen = next((s for s in prefer if s in shapes), None)
    fallback = chosen is None
    if fallback:
        chosen = list(shapes)[0]
    spec = shapes[chosen]

    mode = spec.get("comparison_mode")
    determining = spec.get("determining_metric")
    caveats = spec.get("caveats") or []
    families = spec.get("metric_families") or []

    detr_opts = obs.get("detrending_options") or ["none"]
    aggregate = (mode == "aggregate_trend_comparison")
    detrending = "linear_residual" if (aggregate and "linear_residual" in detr_opts) else "none"

    # --- metric ROLES, all derived from the dag ------------------------------
    # VERDICT is exactly the dag's determining_metric -- never more than that.
    # docs/validation_convention.yaml (yield / regional_aggregate_time_series)
    # declares headline_metrics = [pbias] only; trend metrics are evidence.
    # Static registry check (no scorer import, no side effects). `--self-check`
    # runs the same check with live=True, which calls the scorers.
    registry_ok, registry_report = verify_metric_registry(live=False)
    if not registry_ok:
        registry_report["note"] = (
            "METRIC_FAMILY_SOURCE disagrees with the declared scorer key sets -- "
            "the expanded metric lists below are NOT trustworthy; fix the registry.")

    unmapped = []
    in_shape = _metrics_for(families, unmapped)
    verdict = [determining] if determining else []
    _v = {str(m).lower() for m in verdict}
    diagnostic = [m for m in in_shape if m.lower() not in _v]

    # NON-VERDICT = metrics belonging to families this var declares for its
    # OTHER obs_shapes but NOT for the chosen one.  For YLDG under an
    # area-average obs that resolves to temporal_pattern_match -> r/NSE/KGE,
    # which is exactly what the chosen shape's own dag caveat forbids.
    other_families = []
    for s in shape_list:
        if s.get("obs_shape") == chosen:
            continue
        for fam in s.get("metric_families") or []:
            if fam not in families and fam not in other_families:
                other_families.append(fam)
    # `unmapped` is threaded through BOTH expansions: a dag family with no
    # registry row is reported in unmapped_metric_families whether it came from
    # the chosen shape or from one of the var's other shapes -- never dropped.
    non_verdict = [m for m in _metrics_for(other_families, unmapped)
                   if m not in in_shape and m.lower() not in _v]

    out = {
        "var": var,
        "matched_dag_var": blk.get("var"),
        "obs_shape": chosen,
        "comparison_mode": mode,
        "metric_families": families,
        "determining_metric": determining,
        "caveats": caveats,
        "required_detrending": detrending,
        "detrending_options": detr_opts,
        # --- metric roles ---
        "verdict_metrics": verdict,
        "diagnostic_metrics": diagnostic,
        "diagnostic_metrics_note": (
            "pattern / supporting evidence for the chosen obs_shape -- REPORT these, "
            "but the verdict is %r alone (dag determining_metric)." % (determining,)
        ),
        "non_verdict_metrics": non_verdict,
        "non_verdict_reason": (
            "these metrics belong to metric_families %s which dag.yaml declares for "
            "OTHER obs_shapes of %r but NOT for %r; the chosen shape's dag caveats "
            "are: %s" % (other_families, blk.get("var"), chosen, caveats)
        ) if non_verdict else None,
        "metric_family_map": {f: METRIC_FAMILY_METRICS.get(f)
                              for f in list(families) + list(other_families)},
        "metric_family_scorer": {
            f: (METRIC_FAMILY_SOURCE[f][0] if f in METRIC_FAMILY_SOURCE else None)
            for f in list(families) + list(other_families)},
        "unmapped_metric_families": unmapped,
        "metric_registry_check": registry_report,
        "area_average": area,
        "area_evidence": reasons,
        "dag_fallback_used": fallback,
        "dag_path": dag_path,
    }
    if str(var).strip().upper() in MOISTURE_BASIS_VARS:
        obs_basis = lookup_obs_moisture_basis(dataset_id, crop=crop)
        mb = {
            "sim_native": "EPIC .ACY YLDG/YLDF/BIOM are DRY MATTER t/ha",
            "obs_native": obs_basis,
            "rule": (
                "Declare the basis of BOTH sides before scoring and report the "
                "determining metric on BOTH bases. Convert only when the obs is "
                "ESTABLISHED to be market-basis FOR THIS CROP, i.e. the registry "
                "carries a CITED crop-specific w -- a product-level basis alone is "
                "not enough, and there is no default w. Then: "
                "sim_market = sim_dry / (1 - w), or equivalently "
                "obs_dry = obs_market * (1 - w) -- the two give an IDENTICAL "
                "PBIAS. Never leave the choice implicit: at Changchun the "
                "undeclared choice moved PBIAS from +26.8% (dry) to +50.1% (market)."
            ),
            "must_report_both": True,
        }
        if obs_basis.get("established") and obs_basis.get("basis") == "market" \
                and obs_basis.get("w") is not None:
            w = obs_basis["w"]
            mb["conversion"] = {
                "applies": True,
                "w": w,
                "crop": obs_basis.get("crop"),
                "sim_dry_to_market": "yield_dry / (1 - %.3f)" % w,
                "obs_market_to_dry": "yield_obs * (1 - %.3f)" % w,
                "w_range_sensitivity": obs_basis.get("w_range"),
                "w_source": obs_basis.get("w_source"),
                "source": obs_basis.get("citations"),
            }
        else:
            why = (obs_basis.get("undetermined_reason")
                   or "the product has no registry row").strip()
            if not why.endswith("."):
                why += "."
            conv = {
                "applies": False,
                "reason": "no ESTABLISHED, cited crop-specific POINT moisture "
                          "basis for this (obs product, crop) pair -- %s Score "
                          "on the raw (dry-vs-as-published) pairing, say so "
                          "explicitly, and do NOT apply a moisture factor."
                          % (why,),
                "product_basis": obs_basis.get("product_basis"),
                "product_basis_established": obs_basis.get(
                    "product_basis_established"),
                "crops_with_established_w": obs_basis.get(
                    "crops_with_established_w"),
                "crops_with_band_only_w": obs_basis.get(
                    "crops_with_band_only_w"),
            }
            if obs_basis.get("sensitivity_only") and \
                    obs_basis.get("w_range_sensitivity"):
                # The cited chain reaches this crop only as a BAND.  Report the
                # band as a RANGE-ONLY sensitivity; do not collapse it to a
                # midpoint, which is not a value any cited source states.
                lo, hi = obs_basis["w_range_sensitivity"][:2]
                conv["range_only_sensitivity"] = {
                    "w_range": [lo, hi],
                    "w_range_source": obs_basis.get("w_range_source"),
                    "sim_dry_to_market_range": [
                        "yield_dry / (1 - %.3f)" % lo,
                        "yield_dry / (1 - %.3f)" % hi,
                    ],
                    "obs_market_to_dry_range": [
                        "yield_obs * (1 - %.3f)" % lo,
                        "yield_obs * (1 - %.3f)" % hi,
                    ],
                    "report_as": "a labelled RANGE-ONLY sensitivity spanning "
                                 "the cited band -- never a point conversion, "
                                 "and never the headline/verdict, which stays "
                                 "the raw dry-vs-as-published pairing",
                }
            mb["conversion"] = conv
        out["moisture_basis"] = mb
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Resolve dag obs_shape / comparison contract")
    ap.add_argument("--self-check", dest="self_check", action="store_true",
                    help="verify METRIC_FAMILY_SOURCE against the LIVE "
                         "ki_tools_common scorers and exit")
    ap.add_argument("--var", required=False)
    ap.add_argument("--granularity", default=None)
    ap.add_argument("--geometry", default=None)
    ap.add_argument("--dataset-id", dest="dataset_id", default=None)
    ap.add_argument("--network", default=None)
    ap.add_argument("--n-steps", dest="n_steps", type=int, default=None)
    ap.add_argument("--dag", dest="dag_path", default=DEFAULT_DAG)
    ap.add_argument("--assert-shape", dest="assert_shape", default=None)
    ap.add_argument("--crop", default=None,
                    help="crop name; selects the CITED crop-specific POINT "
                         "market moisture w from the obs moisture-basis "
                         "registry. There is no default. Only maize has a cited "
                         "point convention (GB 1353); wheat/rice are reached by "
                         "the FAO chain only as the 12-14%% band, so they report "
                         "conversion.applies=false plus a range-only "
                         "sensitivity, and a crop the chain does not reach at "
                         "all (e.g. soybean), or omitting --crop, reports "
                         "undetermined with conversion.applies=false")
    a = ap.parse_args(argv)
    if a.self_check:
        ok, report = verify_metric_registry(live=True)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if ok else 1
    if not a.var:
        ap.error("--var is required (or use --self-check)")
    res = resolve(a.var, a.granularity, a.geometry, a.dataset_id,
                  a.network, a.n_steps, a.dag_path, crop=a.crop)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    if a.assert_shape and res["obs_shape"] != a.assert_shape:
        sys.stderr.write("ASSERT FAILED: obs_shape=%s expected=%s\n"
                         % (res["obs_shape"], a.assert_shape))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
