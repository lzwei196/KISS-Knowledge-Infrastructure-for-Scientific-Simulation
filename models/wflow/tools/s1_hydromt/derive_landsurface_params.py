#!/usr/bin/env python3
"""
derive_landsurface_params.py — per-cell wflow_sbm land-surface parameters.

WHY THIS TOOL EXISTS (dt_w042)
------------------------------
`run_hydromt_build.py`'s manual branch used to write a SINGLE UNIFORM CONSTANT
for every land-surface staticmaps field: RootingDepth 750 mm, SoilThickness
2000 mm, InfiltCapSoil 100 mm/day, PathFrac 0.01, Cmax 1.0, CanopyGapFraction
0.1, Kext 0.6, Sl 0, Swood 0, WaterFrac 0, N 0.072. Only KsatVer / theta_s /
theta_r / c were genuine per-cell HWSD lookups. Uniform RootingDepth and
SoilThickness are exactly the two calibration-free controls Imhoff et al. (2020)
identifies as the most sensitive for discharge: with 2000 mm of plant-available
storage the basin never water-stresses, AET pins to ~PET, and the water that
should have become runoff is evaporated (Rio Pelotas: AET 1016 mm/yr = 0.97 x
PET vs the 758 mm/yr the observed balance implies, PBIAS -32%).

This module derives those fields per cell from DOCUMENTED-LEGEND sources only.

SOURCE PRECEDENCE
-----------------
  1. Land cover  -> GLC_FCS30-2015 (GLCFCS30), 30 m, legend documented in the
                    co-located GLCFCS30_2015Readme.docx -> 30 land-cover LC ids
                    plus code 250 "Filled value" (see GLCFCS30_README_LEGEND
                    below, transcribed verbatim, and the VINTAGE note).
                    Read as sub-grid
                    class AREA FRACTIONS (~371 x 371 30-m pixels per 0.1 deg
                    cell), NEVER as a dominant-class label: PathFrac and
                    WaterFrac are fractions by definition and a dominant-class
                    label would degenerate them to 0/1.
  2. LAI         -> GLASS LAI (AVHRR 1981-1999, MODIS-era 2000-2022), 0.1 deg,
                    float, four seasonal composites per year. No class legend is
                    involved, and the AVHRR archive is period-matched to the
                    1980s runs this KI does. Drives Cmax and CanopyGapFraction.
  3. Soil depth  -> HWSD_DATA.csv column REF_DEPTH (cm; 10 / 30 / 100),
                    SHARE-weighted across the SEQ rows of the cell's MU_GLOBAL,
                    converted to mm. NOTE ki_tools_common.soil_utils.lookup_hwsd
                    does NOT expose REF_DEPTH (it returns mu_id / sand / silt /
                    clay / oc / ph / bulk_density / sub_* / texture / hydraulics
                    only), so this module joins the CSV itself on mu_id.

PROHIBITED SOURCE — DO NOT USE
------------------------------
Do NOT read /mnt/disk1/Hydrocraft_server/data/landcover/
AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif for these parameters. Its legend is
undocumented: the `.tif.vat.dbf` carries only Value+Count and the `.tif.aux.xml`
only <PyramidResamplingType>. A control-point fingerprint contradicts the
UMD/Hansen 14-class scheme that is usually assumed for it — Finland
(26E, 62N, boreal needleleaf) and the Appalachians (-80, 37.5, deciduous
broadleaf) BOTH return 5; the Amazon (-60, -3) returns 7 while the Congo
(20, 0) returns 2; urban is 14 and class 13 is absent globally. Substituting a
guessed legend replaces one wrong map with another. (`tools/s6_sediment/
derive_usle_c.py` does carry an assumed AVHRR legend — that assumption is NOT
inherited here.)

VINTAGE — WHICH GLC_FCS30 LEGEND THIS IS
----------------------------------------
There are two incompatible GLC_FCS30 legends in circulation and only one of them
is on this server:
  * GLC_FCS30-2015 (the product in /mnt/datasets/vegetation/GLCFCS30, and the
    one this table binds to) splits only the DECIDUOUS BROADLEAVED (61/62),
    EVERGREEN NEEDLE-LEAVED (71/72) and DECIDUOUS NEEDLE-LEAVED (81/82) forests
    into open/closed, and keeps the UNSPLIT codes 50 "Evergreen broadleaved
    forest", 60 "Deciduous broadleaved forest", 70 "Evergreen needle-leaved
    forest", 80 "Deciduous needle-leaved forest" and 90 "Mixed leaf forest".
  * GLC_FCS30D / the 2020-era re-release additionally splits evergreen
    broadleaved into 51/52 and mixed leaf into 91/92.
The 51/52/91/92 codes therefore MUST NOT appear in this table, and encountering
one at runtime means the wrong vintage was staged; `_reject_wrong_vintage`
raises with that diagnosis rather than mapping it.

VERIFIED against the actual pixels, not just the readme — every GLC_FCS30 code
occurring inside the Rio Pelotas bbox (-51.05, -28.95, -49.30, -27.75;
28,931,141 pixels of GLCFCS30_W55S25.tif + GLCFCS30_W50S25.tif) is
  0 (0.031%, merge background -> LC_NODATA), 10, 11, 12, 20, 50 (43.459%), 60,
  61 (11.593%), 62, 90, 120, 130 (20.748%), 180, 190, 200, 210,
  250 (0.000%, "Filled value" -> LC_NODATA);
codes 51/52/91/92 do not occur at all. Unknown-code fraction is exactly 0.

FAILURE POLICY (dt_w040 — never substitute a placeholder)
---------------------------------------------------------
Every fallback is an error, not a silent default:
  * a source raster that does not overlap the grid                -> raise
  * a land-cover pixel value outside 0-255                        -> raise, in
    BOTH directions. Clipping folded negatives onto 0 (silently absorbed into
    LC_NODATA) while >255 clipped onto 255 and raised.
  * an ACTIVE cell only PARTIALLY covered by the mosaic           -> raise.
    rio_merge pads the part of the bbox no staged tile covers, so a cell
    straddling an unstaged tile still has pixels; computing its fractions over
    the covered sub-area redistributes the uncovered area pro rata over the
    classes inside it — the same substitution as a tolerated unknown code.
    A STAGING GAP AND IN-TILE NODATA ARE TWO DIFFERENT FAULTS AND ARE MEASURED
    SEPARATELY.  The previous revision pinned the pad to 0 — but 0 is itself a
    declared LC_NODATA code, so a padded pixel and a genuine in-tile nodata
    pixel were indistinguishable; and coverage compared only the CLASSIFIED
    pixel count against a full cell, so a cell lying wholly inside staged tiles
    but carrying >1% ocean / "Filled value" raised a message telling the
    operator to stage tiles that were already staged.  The pad is now
    LC_PAD_SENTINEL = 255, a value in NEITHER the readme legend NOR LC_NODATA,
    so the three populations (classified / in-tile nodata / pad) are disjoint
    and countable:
      FAULT 1 STAGING   an ACTIVE cell contains rio_merge pad.  Whether a pad
                        pixel is unstaged area or real data wearing the sentinel
                        is DECIDED, not guessed: a pad pixel inside the FOOTPRINT
                        of a staged tile cannot be unstaged area, and raises as a
                        sentinel COLLISION instead (grid-scoped and unconditional
                        — an ambiguous sentinel makes every pad and nodata count
                        on the mosaic untrustworthy).  Pad over INACTIVE cells is
                        benign — those cells are zeroed out of every field before
                        the staticmaps are written — so it is recorded and never
                        raised on.  The previous revision counted pad over the
                        whole grid and hard-failed a build whose bbox merely
                        overhung the coast, while an overhang into a region for
                        which the product ships no tile made `missing` non-empty,
                        bypassed the guard, and told the operator to stage a tile
                        that does not exist.
      FAULT 2 EDGE      an ACTIVE cell has NO pad yet fewer staged pixels than a
                        full cell holds.  The cause the previous revision named
                        here ("the model grid extends beyond the GLC_FCS30 tile
                        grid") is impossible in this branch — an overhang
                        produces pad, i.e. fault 1 — so the branch was
                        unreachable, and when it did print it named a cause that
                        could not have occurred.  What is actually left is
                        rasterization: px_per_cell is a FLOAT (resolution need
                        not be a whole multiple of the pixel size) and cell
                        membership is decided by rounding pixel CENTRES, so the
                        outermost cells can fall a fraction of a pixel row short.
                        The 1% tolerance exists for that and nothing else.
      FAULT 3 IN-TILE   classified, compared against the STAGED pixels OF THAT
                        NODATA    SAME CELL (never against a full cell, so it
                        cannot fire merely because a tile is missing).  Short ->
                        ocean / "Filled value" inside a staged tile; the message
                        says so and reports the nodata pixel count.
    All three raise — the pro-rata redistribution is identical either way — but
    each is now diagnosed as what it actually is, and each is measured over the
    ACTIVE mask only.  SCOPING IS DECLARED, NOT INCIDENTAL: every figure a fault
    message quotes is active-cell scoped and is taken from the FAILING cells
    themselves (`*_active`, `*_in_an_active_cell`); grid-wide figures are
    reported separately as `*_grid` / `*_in_any_grid_cell` and never appear in a
    message, so the pixel count printed can no longer come from a cell that is
    not in the failing set.  The coverage verdict is raised inside
    `_class_fractions`, next to the per-cell arrays and with the basin mask in
    hand — computing the statistics in one function and raising in another is
    what allowed the two scopes to be mixed.  For the same reason FAULT 1 names
    its tiles from the failing cells' OWN PAD PIXELS and selects its remedy on
    the unstaged tiles those pixels land in: resolving the name from the failing
    cell's CENTRE named the staged neighbour whenever a cell straddled a 5-deg
    boundary, and branching on the grid-wide `missing` list let a tile lying
    entirely over inactive cells — which cannot be the cause — pick the wording.
    Symmetrically, FAULT 2 claims only what its own branch establishes (no
    ACTIVE cell carries pad); it does NOT claim every enumerated tile is staged,
    because an unstaged tile over inactive cells is benign and does not raise.
    PROVENANCE IS A FIXED KEY SET, SEEDED AT `_class_fractions` ENTRY.  The six
    coverage keys — `lc_active_cells`,
    `lc_pad_pixels_inside_a_staged_footprint`, `lc_active_cells_unstaged`,
    `lc_active_cells_edge_short`, `lc_active_cells_nodata_dominated`,
    `lc_unstaged_tiles_under_failing_cells` — are written from
    `COVERAGE_PROVENANCE_SEED` as the first statement of that function, so a
    consumer reads 0 / [] rather than having to tell "the quantity was zero"
    apart from "the test did not run".  Every later assignment is an OVERWRITE,
    never the only write.  The previous revision seeded them in the MIDDLE of
    the function, which left the contract false on five paths: the
    sentinel-collision, unknown-code, out-of-0-255, empty-mosaic and bad-mask
    raises all fire before the seed ran, and FAULT 1 / FAULT 2 raise before
    `lc_active_cells_edge_short` / `lc_active_cells_nodata_dominated` reach
    their single assignment site inside their own fault block.
    SCOPE, NARROWED AND STATED RATHER THAN IMPLIED: the set is fixed FROM
    `_class_fractions` ENTRY ONWARD, i.e. for the coverage stage.  A failure
    before that stage is entered (bad grid, lc_source != glcfcs30) never had a
    coverage stage and none of these keys is claimed for it.
    SEED VALUE vs MEASURED VALUE: for the three `lc_active_cells_*` counters and
    `lc_unstaged_tiles_under_failing_cells` the seed 0 / [] is ALSO a legitimate
    success value, which is the point — no fault means no failing cells.  For
    `lc_active_cells` the seed 0 is NOT reachable on any success path, because
    an empty basin mask raises, so `lc_active_cells == 0` unambiguously means
    the stage raised before it counted the mask.
    THE CONTRACT IS OBSERVABLE: `prov` is a local of
    `derive_landsurface_params`, so on a raise it never binds in the caller.  A
    DeriveError from the coverage stage therefore carries the dict as
    `e.provenance` (class attribute `DeriveError.provenance = None`), and
    `main()` prints it under "provenance" on the failure path.  Seeding keys
    nothing can read would be decoration.  The unscoped
    grid-wide names of the previous revision (`lc_nodata_pixels`,
    `lc_pad_pixels`, `lc_pixels_per_cell_median`, `lc_cells_unstaged`,
    `lc_cells_nodata_dominated`, `lc_max_pad_pixels_in_a_cell`,
    `lc_max_nodata_pixels_in_a_cell`) were REPLACED, not aliased, by the scoped
    `*_grid` / `*_active` / `*_in_any_grid_cell` / `*_in_an_active_cell` names:
    an unscoped alias would keep alive exactly the ambiguity that let a
    grid-wide figure be quoted in a mask-scoped message.  Nothing subscripts the
    old names — run_hydromt_build.py only json.dumps() this dict into the
    staticmaps attribute `landsurface_provenance` and copies it wholesale into
    build_result.json.
  * a mapping unit with no usable SHARE-weighted T_SAND/T_CLAY/T_OC -> raise;
    no invented texture reaches saxton_rawls -> KsatVer -> InfiltCapSoil.
    USABILITY IS DECIDED PER COMPONENT ROW, NOT PER COLUMN.  A HWSD component
    row is a SOIL row only if T_SAND > 0 AND T_CLAY > 0 (both finite); a row
    recording 0/0 is a non-soil component (water body, glacier, rock outcrop)
    and is dropped from the SHARE weighting entirely, because letting it carry
    weight dilutes the texture toward zero — a substitution by another name.
    T_OC is required to be finite and >= 0 but NOT > 0: zero organic carbon is
    a physically meaningful HWSD record, whereas a zero sand or clay percentage
    is not.  This asymmetry is deliberate and declared.  All three columns are
    averaged over the SAME surviving rows, so sand, clay and OC can no longer be
    drawn from different subsets of the mapping unit.  (The revision this
    replaces tested each column independently with `np.isfinite(v) & (v >= 0)`,
    which let a 0/0 non-soil row contribute SHARE weight.)
  * a mapping unit whose SHARE-weighted sand+clay is outside (0, 100]  -> raise
    (the column is not a percentage, or the weighting collapsed)
  * a mapping unit whose Saxton-Rawls KsatVer is <= 0 or non-finite    -> raise
  * a CALLER-SUPPLIED KsatVer that is NaN, +/-inf, or finite and <= 0  -> raise,
    with the three categories counted DISJOINTLY and the minimum taken over the
    FINITE active cells only, labelled as such.  `(~isfinite).sum() +
    (ks <= 0).sum()` counted a -inf cell TWICE, so the reported number of bad
    cells could exceed the number that exist; and `np.nanmin` SKIPS NaN, so a
    failure caused purely by NaN cells printed the minimum of the HEALTHY cells
    ("min 480.0") and read as though nothing were wrong, while an all-NaN active
    set emitted a RuntimeWarning and printed "min nan".  A diagnostic that can
    conceal the fault it raises on is not a diagnostic.
  * ANY land-cover pixel whose code is neither in the documented legend nor in
    LC_NODATA                                                     -> raise.
    There is NO tolerated unknown-code fraction: an unmapped code is dropped
    from both the numerator and the `tot` denominator, so tolerating it would
    silently redistribute that area pro rata over the recognised classes, which
    is a substitution exactly like a placeholder.
  * a mapping unit with no HWSD row / no usable REF_DEPTH         -> raise
  * a cell with no valid LAI in any simulated year                -> raise
  * an output field that is CONSTANT across a multi-cell mask     -> raise
    (that constancy is the exact defect being fixed, so a uniform result means
    the lookup silently missed).

  Exactly TWO declared exceptions to the constancy rule, both of which raise
  unless their stated precondition holds:
    1. ZERO_CONSTANT_OK = ("PathFrac", "WaterFrac") — and ONLY these two. Both
       are literal sub-grid AREA FRACTIONS of a single class (impervious 190,
       water 210), so a constant of exactly 0.0 has the unambiguous reading
       "that class is absent from the basin". Swood is deliberately NOT in this
       set: it is a class-area-WEIGHTED parameter from GLCFCS30_PARAMS, so a
       constant-zero Swood does not mean "class absent" — it means the weighting
       collapsed, and it must fail like any other weighted field.
    2. SINGLE_MAPPING_UNIT_CONSTANT_OK = ("SoilThickness", "InfiltCapSoil") —
       the fields whose only determinant is a per-HWSD-mapping-unit attribute,
       so BOTH are legitimately uniform when the whole basin lies in ONE
       mapping unit: SoilThickness is REF_DEPTH (10 / 30 / 100 cm per unit) and
       InfiltCapSoil IS KsatVer (mm/day, NO floor) with KsatVer = Saxton-Rawls
       of that same unit's SHARE-weighted texture. The former max(KsatVer, 1)
       floor made this exception's "constant > 0" precondition INERT: a
       collapsed lookup surfaced as a legal constant 1.0 mm/day and was
       downgraded to a warning on a single-mapping-unit basin. A non-positive or
       non-finite KsatVer now raises where it is computed, so the constant that
       reaches this guard is always a real one. Listing only SoilThickness made
       this
       exception UNREACHABLE — a single-mapping-unit basin always has a constant
       InfiltCapSoil too, so the guard raised anyway. Tolerated only when
       len(prov["hwsd_mapping_units"]) == 1 AND the constant is > 0, and then
       downgraded to a warning; TWO OR MORE mapping units, or a constant 0.0,
       still raises because that can only be a missed join.
  Both exceptions are recorded in the provenance dict, never swallowed.
RootingDepth is clipped to <= SoilThickness per cell and the clip count is
reported.

KNOWN LIMITATIONS (recorded in the provenance dict, not hidden)
---------------------------------------------------------------
  * GLC_FCS30 is a 2015 snapshot used for 1980s runs. The canopy block, which
    carries the dominant AET signal, IS period-matched through GLASS LAI, so the
    2015 epoch only sets the slower-varying class-weighted fields.
  * LAI is reduced to a per-cell growing-season mean and written as a STATIC
    staticmaps field rather than as cyclic forcing, so no change to
    generate_wflow_toml.py is needed. FOLLOW-UP: emit cyclic monthly LAI and
    wire `[input.cyclic]`.
  * SoilThickness is HWSD REF_DEPTH — depth to the soil reference limit, NOT
    depth to bedrock. No Pelletier/SoilGrids BDTICM product exists on this
    server.
  * "A constant InfiltCapSoil is a collapsed lookup" is a rule about THIS
    module's definition of the field, not about wflow_sbm in general. The
    shipped developer example ships a uniform one — probed:
    developer_example/data/input/staticmaps-moselle.nc has InfiltCapSoil
    nunique == 1 (600 mm/day) over 50,063 cells, alongside RootingDepth
    nunique 342 and SoilThickness nunique 2661 — because HydroMT treats it as a
    fixed model parameter. Here it is DERIVED as the per-cell HWSD KsatVer, so
    constancy really does mean the per-cell join collapsed, except inside a
    single mapping unit (declared exception 2).
  * FOLLOW-UP: generate_wflow_toml.py currently wires InfiltCapPath but NOT
    InfiltCapSoil, and wires neither Kext nor Sl/Swood. The values written here
    are correct; two of them are simply not read by the TOML this KI generates.

USAGE
-----
    # standalone
    python derive_landsurface_params.py \
        --grid_nc  <staticmaps.nc | any nc with y/x coords> \
        --mask_var wflow_subcatch \
        --start_year 1980 --end_year 1990 \
        --out /tmp/landsurface.npz

    # or from an explicit bbox
    python derive_landsurface_params.py \
        --bbox -51.05 -28.95 -49.30 -27.75 --resolution 0.1 \
        --start_year 1980 --end_year 1990 --out /tmp/landsurface.npz

    # in-process (this is how run_hydromt_build.py uses it)
    from derive_landsurface_params import derive_landsurface_params
    fields, prov = derive_landsurface_params(lat_centers, lon_centers, mask,
                                             start_year, end_year,
                                             ksat_mm_day=ksat)

REFERENCES
----------
  * van Verseveld et al. 2024, gmd-17-3199-2024 — wflow_sbm description; the
    canopy formulation Cmax = 0.935 + 0.498 LAI - 0.00575 LAI^2 and
    CanopyGapFraction = exp(-Kext * LAI) (Von Hoyningen-Huene / Braden), the
    same relation hydroMT-wflow applies.
  * Imhoff et al. 2020 (imhoff2020_wflowsbm_ptf_rhine) — RootingDepth and
    KsatHorFrac are the most sensitive calibration-free discharge parameters.
  * Liu & Zhang, GLC_FCS30-2015 readme — the 29-class legend used below.
"""

import argparse
import json
import math
import os
import sys

import numpy as np

# ── Default data locations ──────────────────────────────────────────────
GLCFCS30_DIR = "/mnt/datasets/vegetation/GLCFCS30"
GLASS_LAI_DIR = "/mnt/datasets/vegetation/GLASS_LAI_global"
HWSD_CSV = "/mnt/disk1/Hydrocraft_server/data/soil/HWSD_DATA.csv"
HWSD_RASTER = "/mnt/disk1/Hydrocraft_server/data/soil/HWSD_RASTER/hwsd.bil"

LAI_SEASONS = ("spring", "early-sum", "peak", "senescence")

# ── The documented legend, transcribed verbatim ─────────────────────────
# Source: /mnt/datasets/vegetation/GLCFCS30/GLCFCS30_2015Readme.docx, section
# "Classification system", columns (LC id, Classification System). Reproduced
# here so the parameter table below can be machine-checked against it instead of
# trusted. Do NOT edit this dict to make a mapping fit — it IS the legend.
GLCFCS30_README_LEGEND = {
    10:  "Rainfed cropland",
    11:  "Herbaceous cover",
    12:  "Tree or shrub cover (Orchard)",
    20:  "Irrigated cropland",
    50:  "Evergreen broadleaved forest",
    60:  "Deciduous broadleaved forest",
    61:  "Open deciduous broadleaved forest (0.15<fc<0.4)",
    62:  "Closed deciduous broadleaved forest (fc>0.4)",
    70:  "Evergreen needle-leaved forest",
    71:  "Open evergreen needle-leaved forest (0.15<fc<0.4)",
    72:  "Closed evergreen needle-leaved forest (fc>0.4)",
    80:  "Deciduous needle-leaved forest",
    81:  "Open deciduous needle-leaved forest (0.15<fc<0.4)",
    82:  "Closed deciduous needle-leaved forest (fc>0.4)",
    90:  "Mixed leaf forest (broadleaved and needle-leaved)",
    120: "Shrubland",
    121: "Evergreen shrubland",
    122: "Deciduous shrubland",
    130: "Grassland",
    140: "Lichens and mosses",
    150: "Sparse vegetation (fc<0.15)",
    152: "Sparse shrubland (fc<0.15)",
    153: "Sparse herbaceous (fc<0.15)",
    180: "Wetlands",
    190: "Impervious",
    200: "Bare areas",
    201: "Consolidated bare areas",
    202: "Unconsolidated bare areas",
    210: "Water body",
    220: "Permanent ice and snow",
    250: "Filled value",          # nodata, see LC_NODATA — not a land-cover type
}
# Codes that exist ONLY in the GLC_FCS30D / 2020-era legend. Their presence in a
# raster proves the staged tiles are a different vintage from the readme this
# table binds to (see the VINTAGE note in the module docstring).
GLCFCS30_OTHER_VINTAGE_CODES = {
    51: "Open evergreen broadleaved forest (GLC_FCS30D only)",
    52: "Closed evergreen broadleaved forest (GLC_FCS30D only)",
    91: "Open mixed leaf forest (GLC_FCS30D only)",
    92: "Closed mixed leaf forest (GLC_FCS30D only)",
}

# ── GLC_FCS30 class -> wflow_sbm land-surface parameters ────────────────
# Keys are the LC ids of the GLC_FCS30-2015 classification system exactly as
# tabulated in GLCFCS30_2015Readme.docx ("Classification system", LC id column);
# _assert_legend_binding() below enforces that at import time.
# Parameter values follow the hydroMT-wflow LULC mapping convention
# (globcover/vito mapping tables: RootingDepth mm, Kext -, Sl mm/LAI, Swood mm,
# N s/m^(1/3) overland Manning).  PathFrac and WaterFrac are NOT taken from this
# table — they are the area fractions of the impervious and water classes.
GLCFCS30_PARAMS = {
    #   id: (name,                              RootingDepth, Kext,  Sl,    Swood, N)
    10:  ("Rainfed cropland",                          500.0, 0.60, 0.030, 0.01, 0.150),
    11:  ("Herbaceous cover",                          500.0, 0.60, 0.030, 0.01, 0.150),
    12:  ("Tree or shrub cover (orchard)",            1000.0, 0.70, 0.060, 0.20, 0.200),
    20:  ("Irrigated cropland",                        500.0, 0.60, 0.030, 0.01, 0.150),
    50:  ("Evergreen broadleaved forest",             1500.0, 0.80, 0.135, 0.50, 0.300),
    60:  ("Deciduous broadleaved forest",             1500.0, 0.80, 0.108, 0.50, 0.300),
    61:  ("Open deciduous broadleaved forest",        1200.0, 0.75, 0.090, 0.35, 0.250),
    62:  ("Closed deciduous broadleaved forest",      1500.0, 0.80, 0.108, 0.50, 0.300),
    70:  ("Evergreen needle-leaved forest",           1000.0, 0.60, 0.130, 0.50, 0.300),
    71:  ("Open evergreen needle-leaved forest",       900.0, 0.60, 0.110, 0.35, 0.250),
    72:  ("Closed evergreen needle-leaved forest",    1000.0, 0.60, 0.130, 0.50, 0.300),
    80:  ("Deciduous needle-leaved forest",           1000.0, 0.60, 0.110, 0.50, 0.300),
    81:  ("Open deciduous needle-leaved forest",       900.0, 0.60, 0.090, 0.35, 0.250),
    82:  ("Closed deciduous needle-leaved forest",    1000.0, 0.60, 0.110, 0.50, 0.300),
    90:  ("Mixed leaf forest",                        1200.0, 0.70, 0.120, 0.50, 0.300),
    120: ("Shrubland",                                 750.0, 0.60, 0.050, 0.10, 0.200),
    121: ("Evergreen shrubland",                       750.0, 0.60, 0.050, 0.10, 0.200),
    122: ("Deciduous shrubland",                       750.0, 0.60, 0.050, 0.10, 0.200),
    130: ("Grassland",                                 500.0, 0.60, 0.030, 0.00, 0.130),
    140: ("Lichens and mosses",                        100.0, 0.60, 0.020, 0.00, 0.100),
    150: ("Sparse vegetation",                         250.0, 0.60, 0.020, 0.00, 0.100),
    152: ("Sparse shrubland",                          300.0, 0.60, 0.020, 0.00, 0.100),
    153: ("Sparse herbaceous",                         250.0, 0.60, 0.020, 0.00, 0.100),
    180: ("Wetlands",                                  250.0, 0.60, 0.030, 0.00, 0.100),
    190: ("Impervious",                                100.0, 0.60, 0.000, 0.00, 0.050),
    200: ("Bare areas",                                100.0, 0.60, 0.000, 0.00, 0.050),
    201: ("Consolidated bare areas",                   100.0, 0.60, 0.000, 0.00, 0.045),
    202: ("Unconsolidated bare areas",                 100.0, 0.60, 0.000, 0.00, 0.055),
    210: ("Water body",                                  0.0, 0.60, 0.000, 0.00, 0.030),
    220: ("Permanent ice and snow",                      0.0, 0.60, 0.000, 0.00, 0.030),
}
IMPERVIOUS_CLASSES = (190,)
WATER_CLASSES = (210,)
# 0 and 250 ("Filled value") are IN-TILE nodata: they occur inside a staged tile
# and are excluded from the class denominator, never counted as a land-cover
# type. They are NOT the same thing as area no tile covers -- see below.
LC_NODATA = (0, 250)
# The value rio_merge writes over the part of the requested bbox that no staged
# tile covers. It MUST be a value the PRODUCT CANNOT PRODUCE — otherwise a
# staging gap and a real pixel become indistinguishable.
#
# Revision history of this constant, because both earlier choices were wrong in
# the same way and only the second failure showed why:
#   * 0    — a declared LC_NODATA code, so a staging gap and genuine in-tile
#            nodata collapsed into one undiagnosable shortfall.
#   * 255  — absent from GLCFCS30_README_LEGEND, and absent from the Rio Pelotas
#            tiles, so it LOOKED safe. It is not: the tiles are uint8 with NO
#            declared nodata (`nodatavals == (None,)`), and 255 occurs in them as
#            a raw fill. GLCFCS30_E5N50/E5N55 carry 9,277 such pixels over the
#            Saar window, which correctly tripped the sentinel-inside-a-staged-
#            footprint guard and hard-failed the build (2026-08-08). "Not in the
#            legend" is NOT the same property as "not in the file".
# The only sentinel that cannot collide is one OUTSIDE the product's dtype
# range, so the mosaic is read as int16 and padded with 300. LC_PAD_LUT_SIZE
# sizes the code->class lookup table to match.
# _assert_legend_binding() enforces the out-of-range property at import.
LC_PAD_SENTINEL = 300
LC_PAD_MERGE_DTYPE = "int16"
LC_PAD_LUT_SIZE = LC_PAD_SENTINEL + 1

FIELD_NAMES = ("RootingDepth", "Kext", "Sl", "Swood", "N", "PathFrac",
               "WaterFrac", "Cmax", "CanopyGapFraction", "SoilThickness",
               "InfiltCapSoil")
# DECLARED EXCEPTION 1 to the constancy rule (see FAILURE POLICY in the module
# docstring). ONLY these two, and ONLY at exactly 0.0. Both are literal sub-grid
# AREA FRACTIONS of a single class — PathFrac = frac(190 Impervious),
# WaterFrac = frac(210 Water body) — so an all-zero constant reads unambiguously
# as "that class is absent from this basin".
#
# Swood is deliberately EXCLUDED even though the earlier revision listed it: it
# is a class-area-WEIGHTED parameter drawn from GLCFCS30_PARAMS, not a class
# fraction, so a constant-zero Swood carries no "class absent" interpretation —
# it means the weighting collapsed, and it must fail like any other field.
ZERO_CONSTANT_OK = ("PathFrac", "WaterFrac")
# DECLARED EXCEPTION 2: the fields whose ONLY determinant is a per-HWSD-
# mapping-unit attribute, so a basin lying entirely within ONE mapping unit is
# genuinely uniform in them.
#   * SoilThickness = REF_DEPTH, which takes only 10 / 30 / 100 cm per unit.
#   * InfiltCapSoil = KsatVer (unfloored), and KsatVer is Saxton-Rawls of the
#     SHARE-weighted T_SAND / T_CLAY / T_OC of the SAME mapping unit -- on
#     either path (derived here when ksat_mm_day is None, or supplied by
#     run_hydromt_build.py's per-cell lookup_hwsd, which resolves the same
#     mapping unit for every cell inside it).  Listing only SoilThickness made
#     this exception UNREACHABLE: a single-mapping-unit basin always has a
#     constant InfiltCapSoil as well, so constant_fail raised regardless.
# Tolerated only when len(prov["hwsd_mapping_units"]) == 1 AND the constant is
# > 0; two or more units, or a constant 0.0, can only be a missed join and
# still raises.
SINGLE_MAPPING_UNIT_CONSTANT_OK = ("SoilThickness", "InfiltCapSoil")


class DeriveError(RuntimeError):
    """Raised instead of substituting a placeholder value.

    `provenance` carries the partially-filled provenance dict when the error
    comes from the coverage stage, which is what makes the fixed coverage key
    set observable: `prov` is a local of derive_landsurface_params, so on a
    raise it never binds in the caller and seeded keys nobody can read would be
    decoration.  It stays None for errors raised outside that stage, so a
    consumer can tell "no coverage stage ran" from "the coverage stage failed".
    """

    provenance = None


def _assert_legend_binding():
    """Fail at import if GLCFCS30_PARAMS drifts from the transcribed readme.

    The parameter table must cover every readme LC id except the ones declared
    nodata, and must not invent ids the readme does not define. This is what
    makes "the keys are the readme's LC ids" a checked claim rather than a
    comment.
    """
    legend = set(GLCFCS30_README_LEGEND) - set(LC_NODATA)
    table = set(GLCFCS30_PARAMS)
    if table != legend:
        raise DeriveError(
            "GLCFCS30_PARAMS does not match the transcribed "
            "GLCFCS30_2015Readme.docx legend: "
            f"missing from the table {sorted(legend - table)}, "
            f"absent from the readme {sorted(table - legend)}")
    stray = table & set(GLCFCS30_OTHER_VINTAGE_CODES)
    if stray:
        raise DeriveError(
            f"GLCFCS30_PARAMS contains GLC_FCS30D-only codes {sorted(stray)}; "
            "this module binds to the GLC_FCS30-2015 legend")
    # The pad sentinel only separates a staging gap from in-tile nodata while it
    # is claimed by NEITHER population.
    # It must be unreachable by the PRODUCT, not merely unlisted in the legend:
    # the tiles are uint8 with no declared nodata, so ANY value in 0-255 can
    # appear as raw fill (255 does, over the Saar). Require it outside that
    # range entirely, and representable in the merge dtype.
    if (LC_PAD_SENTINEL in GLCFCS30_README_LEGEND
            or LC_PAD_SENTINEL in LC_NODATA
            or 0 <= LC_PAD_SENTINEL <= 255
            or not (np.iinfo(LC_PAD_MERGE_DTYPE).min <= LC_PAD_SENTINEL
                    <= np.iinfo(LC_PAD_MERGE_DTYPE).max)):
        raise DeriveError(
            f"LC_PAD_SENTINEL={LC_PAD_SENTINEL} is claimed by the GLC_FCS30 "
            "legend or by LC_NODATA, or lies inside the tiles' uint8 0-255 "
            "range (where the product can emit it as raw fill), or is not "
            f"representable in LC_PAD_MERGE_DTYPE={LC_PAD_MERGE_DTYPE}; a "
            "staging gap could not be told apart from real land cover")


def _reject_wrong_vintage(codes_seen):
    """Raise if the raster carries GLC_FCS30D-only codes (wrong product)."""
    other = sorted(set(int(c) for c in codes_seen) &
                   set(GLCFCS30_OTHER_VINTAGE_CODES))
    if other:
        raise DeriveError(
            f"land-cover raster carries class code(s) {other} "
            f"({', '.join(GLCFCS30_OTHER_VINTAGE_CODES[c] for c in other)}), "
            "which exist only in the GLC_FCS30D / 2020-era legend. The staged "
            "tiles are not the GLC_FCS30-2015 product GLCFCS30_PARAMS binds to. "
            "Stage the 2015 tiles, or add a separate D-legend table — do NOT "
            "map D codes through the 2015 table.")


_assert_legend_binding()


# ══ GLC_FCS30 tiling ═══════════════════════════════════════════════════
def glcfcs30_tile_name(lat_top, lon_left):
    """GLC_FCS30 tiles are 5x5 deg, named by TOP-LEFT corner.

    Verified against the shipped tiles: GLCFCS30_W55S25.tif spans
    lat [-30.03, -24.90], lon [-55.00, -50.00]  -> "W55" = left edge,
    "S25" = top edge.  GLCFCS30_E100N35.tif spans lat [30.00, 35.13],
    lon [100.00, 105.00].
    """
    ns = "N" if lat_top >= 0 else "S"
    ew = "E" if lon_left >= 0 else "W"
    return f"GLCFCS30_{ew}{abs(int(round(lon_left)))}{ns}{abs(int(round(lat_top)))}.tif"


def glcfcs30_tiles_for_bbox(lc_dir, bbox):
    """Paths of the GLC_FCS30 tiles covering bbox=(minlon, minlat, maxlon, maxlat)."""
    minlon, minlat, maxlon, maxlat = bbox
    lon0 = int(math.floor(minlon / 5.0) * 5)
    lon1 = int(math.floor(maxlon / 5.0) * 5)
    top0 = int(math.ceil(minlat / 5.0) * 5)
    top1 = int(math.ceil(maxlat / 5.0) * 5)
    paths, missing = [], []
    for top in range(top0, top1 + 1, 5):
        for left in range(lon0, lon1 + 1, 5):
            p = os.path.join(lc_dir, glcfcs30_tile_name(top, left))
            (paths if os.path.exists(p) else missing).append(p)
    if not paths:
        raise DeriveError(
            f"no GLC_FCS30 tile under {lc_dir} covers bbox {bbox}; "
            f"expected at least one of {[os.path.basename(m) for m in missing]}")
    return sorted(set(paths)), missing


# ══ (a) land cover -> sub-grid class fractions ═════════════════════════
# FIXED COVERAGE PROVENANCE KEY SET.  Written into `report` as the FIRST
# statement of _class_fractions, ahead of every raise in that function, so all
# six keys are present on EVERY path through the coverage stage: success, the
# three coverage faults, and equally the earlier sentinel-collision,
# unknown-code, out-of-0-255, empty-mosaic and bad-mask raises.  A consumer
# then reads a value instead of having to tell "the quantity was zero" apart
# from "the test did not run", and every assignment further down is an
# OVERWRITE rather than the only write.
#
# SCOPE (narrowed deliberately): the set is fixed FROM _class_fractions ENTRY
# ONWARD.  A failure before the coverage stage is entered never had a coverage
# stage, and nothing here is claimed for it.
#
# SEED VALUE vs MEASURED VALUE: for the three lc_active_cells_* counters and
# lc_unstaged_tiles_under_failing_cells the seed 0 / [] is ALSO a legitimate
# success value -- no fault means no failing cells -- so seed and measurement
# are indistinguishable BY DESIGN there.  For lc_active_cells the seed 0 is not
# reachable on any success path (an empty mask raises), so 0 unambiguously
# means the stage raised before it counted the mask.
COVERAGE_PROVENANCE_SEED = {
    "lc_active_cells": 0,
    "lc_pad_pixels_inside_a_staged_footprint": 0,
    "lc_active_cells_unstaged": 0,
    "lc_active_cells_edge_short": 0,
    "lc_active_cells_nodata_dominated": 0,
    "lc_unstaged_tiles_under_failing_cells": [],
}


def _class_fractions(lat_centers, lon_centers, resolution, mask, lc_dir,
                     report):
    """Area fraction of every GLC_FCS30 class in each model cell.

    Returns frac[ny, nx, ncls] and the ordered class-code array.

    `mask` (1 = active) is taken HERE rather than leaving the coverage verdict
    to the caller.  Every coverage quantity is a per-cell array; computing those
    arrays in this function and raising on `mask == 1` in another is exactly
    what let a grid-scoped pixel figure be quoted next to a mask-scoped cell
    count.  Grid-scoped and active-cell-scoped figures are reported under
    different names and a fault message quotes only the active-scoped ones.

    `report` is mutated in place.  COVERAGE_PROVENANCE_SEED is written into it
    as the FIRST statement below, before any raise in this function, so the six
    coverage keys exist on every path out of here — including the raises that
    fire long before the coverage verdict is reached.  Later assignments
    overwrite the seed; none of them is the only write.
    """
    import rasterio
    from rasterio.merge import merge as rio_merge

    # FIRST statement that touches `report`, ahead of EVERY raise in this
    # function -- including the ones below that fire before the coverage verdict
    # is reached (empty mosaic, out-of-0-255 code, unknown code, pad-sentinel
    # collision, bad mask shape, empty mask).  Copied per key rather than
    # `report.update(COVERAGE_PROVENANCE_SEED)` so the mutable [] seed can never
    # be aliased into the module-level constant by a later append.
    for _k, _v in COVERAGE_PROVENANCE_SEED.items():
        report[_k] = list(_v) if isinstance(_v, list) else _v

    ny, nx = len(lat_centers), len(lon_centers)
    bbox = (float(lon_centers[0] - resolution / 2),
            float(min(lat_centers) - resolution / 2),
            float(lon_centers[-1] + resolution / 2),
            float(max(lat_centers) + resolution / 2))

    paths, missing = glcfcs30_tiles_for_bbox(lc_dir, bbox)
    srcs = [rasterio.open(p) for p in paths]
    # Footprint of every STAGED tile, kept so a pad pixel can be attributed to
    # its ACTUAL cause instead of inferred from `missing`: pad INSIDE a staged
    # footprint cannot be unstaged area (it is real data carrying the sentinel),
    # pad OUTSIDE every footprint is genuinely unstaged.  Inferring between the
    # two from `missing` alone is what produced the unreachable, mislabelled
    # branch this revision removes.
    tile_bounds = [(os.path.basename(s.name), tuple(float(b) for b in s.bounds))
                   for s in srcs]
    # Expand the MERGE window (not the model grid) by a couple of source pixels
    # on every side.
    #
    # rasterio.merge sizes the destination from `bounds / res` and copies each
    # source through an integer-rounded window, so when the requested bounds are
    # not an exact multiple of the source resolution the destination's LAST row
    # (and/or column) is never written and keeps the fill value — even though a
    # staged tile plainly covers it. Over the Saar this left exactly one 9,277-
    # pixel row at the bbox's bottom edge (lat 48.20022, one pixel of 0.0002695
    # deg), inside GLCFCS30_E5N50's footprint, and the pad guard below reported
    # it as "the sentinel is ambiguous" — the wrong diagnosis for a pure
    # rounding artifact, and one that no sentinel choice can fix.
    # Padding pushes that artifact row outside the model grid, where the
    # `inside` filter already discards it.
    _px, _py = srcs[0].res
    _pad = 2
    merge_bbox = (bbox[0] - _pad * _px, bbox[1] - _pad * _py,
                  bbox[2] + _pad * _px, bbox[3] + _pad * _py)
    try:
        # nodata=LC_PAD_SENTINEL PINS the value rio_merge writes over the part
        # of `bounds` that no staged tile covers.  The sentinel is OUTSIDE the
        # tiles' uint8 range (hence dtype=int16), so no source pixel can ever
        # carry it and a padded pixel stays distinguishable from real land cover
        # AND from an in-tile nodata pixel (0 / 250); all three coverage faults
        # below can be told apart.  rasterio.merge only uses this value to fill
        # the destination and to decide which destination pixels are still
        # unwritten; source pixels are masked by each tile's OWN declared
        # nodata, and the GLC_FCS30 tiles declare none (verified: rasterio
        # nodatavals == (None,)), so a genuine in-tile 0 is copied through and
        # is counted as in-tile nodata, not as pad.
        arr, tr = rio_merge(srcs, bounds=merge_bbox, nodata=LC_PAD_SENTINEL,
                            dtype=LC_PAD_MERGE_DTYPE)
    finally:
        for s in srcs:
            s.close()
    lc = arr[0]
    if lc.size == 0:
        raise DeriveError(f"GLC_FCS30 mosaic over {bbox} is empty — "
                          f"tiles {[os.path.basename(p) for p in paths]} do not "
                          f"overlap the model grid")

    # fine pixel centre -> coarse cell index (same convention as the MERIT
    # upscaling in run_hydromt_build.py: y descending, x ascending)
    nr, nc = lc.shape
    rr, cc = np.indices((nr, nc))
    plon = tr.c + (cc + 0.5) * tr.a
    plat = tr.f + (rr + 0.5) * tr.e
    cj = np.rint((lat_centers[0] - plat) / resolution).astype(np.int64)
    ci = np.rint((plon - lon_centers[0]) / resolution).astype(np.int64)
    inside = (cj >= 0) & (cj < ny) & (ci >= 0) & (ci < nx)

    codes = np.array(sorted(GLCFCS30_PARAMS.keys()), dtype=np.int64)
    ncls = len(codes)
    lut = np.full(LC_PAD_LUT_SIZE, -1, dtype=np.int64)  # class code -> tbl index
    lut[codes] = np.arange(ncls)
    for nd in LC_NODATA:
        lut[nd] = -2                                 # in-tile nodata (0 / 250)
    lut[LC_PAD_SENTINEL] = -3                        # rio_merge pad (unstaged)

    flat_lc = lc[inside].astype(np.int64)
    # No clipping.  np.clip folded every negative sentinel onto 0 -- silently
    # absorbed into LC_NODATA -- while anything above 255 clipped onto 255 and
    # DID raise: an asymmetric silent substitution.  Both directions are
    # out-of-legend and both must fail the same way.
    # LC_PAD_SENTINEL is deliberately outside 0-255 (that is what makes it
    # uncollidable), so it is exempt here and classified as pad by the lut.
    oor = ((flat_lc < 0) | (flat_lc > 255)) & (flat_lc != LC_PAD_SENTINEL)
    if oor.any():
        uo, uoc = np.unique(flat_lc[oor], return_counts=True)
        raise DeriveError(
            f"{int(oor.sum())} of {int(flat_lc.size)} land-cover pixels carry "
            f"values outside the 0-255 GLC_FCS30 code range "
            f"({dict(zip(uo.tolist(), uoc.tolist()))}). The raster is not a "
            "GLC_FCS30 class map, or it carries a signed nodata sentinel. "
            "Refusing to fold them onto 0 or 255 -- add the value to LC_NODATA "
            "if it is genuinely nodata.")
    idx = lut[flat_lc]

    unknown = flat_lc[idx == -1]
    n_unknown = int(unknown.size)
    n_nodata = int((idx == -2).sum())
    n_pad = int((idx == -3).sum())
    n_total = int(flat_lc.size)
    if n_unknown:
        u, ucnt = np.unique(unknown, return_counts=True)
        report["lc_unknown_classes"] = {int(a): int(b) for a, b in zip(u, ucnt)}
        # A code that is neither in the legend nor declared nodata is dropped
        # from `counts` AND from the `tot` denominator below, so its area would
        # be redistributed pro rata over the recognised classes. That is a
        # silent substitution, so there is NO tolerated fraction — not even one
        # pixel. Wrong vintage is diagnosed specifically before the generic
        # message, because it has a different remedy.
        _reject_wrong_vintage(u)
        raise DeriveError(
            f"{n_unknown} of {n_total} GLC_FCS30 pixels "
            f"({100*n_unknown/max(n_total,1):.4f}%) carry class codes absent "
            f"from the documented GLC_FCS30-2015 legend "
            f"({dict(zip(u.tolist(), ucnt.tolist()))}). Tolerating them would "
            "redistribute their area over the recognised classes. Refusing to "
            "guess — extend GLCFCS30_README_LEGEND + GLCFCS30_PARAMS from the "
            "readme, or add the code to LC_NODATA if it is genuinely nodata.")

    # The sentinel only works while no staged tile actually contains 255. That
    # is now DECIDED from the tiles' own footprints rather than inferred from
    # `missing`: a pad pixel lying inside a staged tile's footprint cannot be
    # unstaged area, so it is a real pixel wearing the sentinel.
    #
    # This one check is deliberately GRID-scoped and unconditional, and that is
    # not the scope confusion the coverage faults below were guilty of: it is
    # not a statement about the basin but about the sentinel itself, and once
    # the sentinel is ambiguous every pad and nodata count on the mosaic —
    # active cells included — is untrustworthy.
    #
    # The pad GEOMETRY below is computed UNCONDITIONALLY, on the no-pad path
    # too, for two reasons.  (i) `lc_pad_pixels_inside_a_staged_footprint`
    # belongs to a FIXED provenance key set: written only under `if n_pad:` it
    # was absent exactly when there was no pad, so a consumer could not tell
    # "the collision test found nothing" from "the collision test never ran".
    # (ii) FAULT 1 below attributes the failing cells' OWN pad pixels to the
    # tiles those pixels actually fall in, which needs their coordinates and
    # their cell membership, not a summary count.  With n_pad == 0 every array
    # here is empty, n_collide is 0, and no branch is entered.
    pad_full = np.zeros(lc.shape, dtype=bool)
    pad_full[inside] = (idx == -3)
    plon_pad = plon[pad_full]
    plat_pad = plat[pad_full]
    pcell_pad = cj[pad_full] * nx + ci[pad_full]   # flat cell index per pad px
    in_fp = np.zeros(plon_pad.size, dtype=bool)
    for _nm, (b_l, b_b, b_r, b_t) in tile_bounds:
        in_fp |= ((plon_pad >= b_l) & (plon_pad < b_r)
                  & (plat_pad >= b_b) & (plat_pad < b_t))
    n_collide = int(in_fp.sum())
    report["lc_pad_pixels_inside_a_staged_footprint"] = n_collide
    if n_collide:
        # LC_PAD_SENTINEL is outside the tiles' uint8 range, so no SOURCE pixel
        # can carry it: a sentinel pixel inside a staged footprint is a
        # destination pixel rasterio.merge never wrote. The merge window is
        # already padded by two source pixels so the known edge-rounding
        # artifact lands outside the model grid, which means anything reaching
        # here is a real, unexplained hole in the mosaic (a truncated or
        # corrupt tile, or a source grid that does not align with the
        # destination). Do NOT "fix" it by changing the sentinel — that was the
        # wrong diagnosis this guard used to print.
        raise DeriveError(
            f"{n_collide} of {int(plon_pad.size)} pad-sentinel pixels lie "
            f"INSIDE the footprint of a staged GLC_FCS30 tile "
            f"{tile_bounds}, i.e. rasterio.merge left destination pixels "
            f"unwritten where a staged tile does cover them. Code "
            f"{LC_PAD_SENTINEL} is outside the tiles' uint8 range so it cannot "
            "come from the data, and the merge window is already padded past "
            "the edge-rounding artifact: check the staged tiles for truncation "
            "or a grid misalignment. Refusing to count covered area as "
            "unstaged.")

    valid = idx >= 0
    cellflat = cj[inside] * nx + ci[inside]
    comb = cellflat[valid] * ncls + idx[valid]
    counts = np.bincount(comb, minlength=ny * nx * ncls).reshape(ny, nx, ncls)

    # Three DISJOINT per-cell populations. Unknown codes already raised above, so
    # classified + in-tile nodata + pad accounts for every fine pixel that falls
    # inside the cell, and the coverage faults can be attributed separately.
    tot = counts.sum(axis=2)                                   # classified
    nodata_cell = np.bincount(cellflat[idx == -2],
                              minlength=ny * nx).reshape(ny, nx)
    pad_cell = np.bincount(cellflat[idx == -3],
                           minlength=ny * nx).reshape(ny, nx)
    staged = tot + nodata_cell                                 # from a real tile

    # Fine pixels a FULLY covered model cell must receive, from the mosaic's own
    # transform.  This is a FLOAT: the model resolution need not be a whole
    # multiple of the pixel size, and cell membership is assigned by rounding
    # pixel CENTRES, so an otherwise perfect cell can land a pixel or two short.
    # The 1% tolerance below exists for exactly that, and nothing else.
    px_per_cell = (resolution / abs(tr.a)) * (resolution / abs(tr.e))

    act = (np.asarray(mask) == 1)
    if act.shape != (ny, nx):
        raise DeriveError(f"mask shape {act.shape} does not match the model "
                          f"grid ({ny}, {nx})")
    n_act = int(act.sum())
    if n_act == 0:
        raise DeriveError("the basin mask has no active cell (mask == 1), so "
                          "no coverage statement can be made about it")

    # ── provenance ────────────────────────────────────────────────────────
    # GRID-scoped and ACTIVE-CELL-scoped figures carry DIFFERENT names. Every
    # figure a fault message quotes below is active-scoped and is taken from the
    # FAILING cells, so the pixel count printed can never come from a cell that
    # is not in the failing set.
    report["lc_source_pixels"] = n_total
    report["lc_unknown_pixels"] = n_unknown
    report["lc_tiles"] = [os.path.basename(p) for p in paths]
    report["lc_tiles_absent"] = [os.path.basename(m) for m in missing]
    report["lc_pixels_per_cell_expected"] = int(round(px_per_cell))
    report["lc_nodata_pixels_grid"] = n_nodata
    report["lc_pad_pixels_grid"] = n_pad
    report["lc_max_pad_pixels_in_any_grid_cell"] = int(pad_cell.max())
    report["lc_max_nodata_pixels_in_any_grid_cell"] = int(nodata_cell.max())
    report["lc_nodata_pixels_active"] = int(nodata_cell[act].sum())
    report["lc_pad_pixels_active"] = int(pad_cell[act].sum())
    report["lc_max_pad_pixels_in_an_active_cell"] = int(pad_cell[act].max())
    report["lc_max_nodata_pixels_in_an_active_cell"] = int(nodata_cell[act].max())
    report["lc_pixels_per_cell_median_active"] = int(np.median(staged[act]))
    # Pad over INACTIVE cells is benign: those cells are zeroed out of every
    # field before the staticmaps are written, so a bbox that overhangs the tile
    # grid or the coast costs nothing as long as no ACTIVE cell loses a pixel.
    # Recorded, never raised on -- the previous grid-scoped guard failed a build
    # for exactly this, and when the overhang lay over a region for which the
    # product ships no tile it instead told the operator to stage a tile that
    # does not exist.
    report["lc_pad_pixels_in_inactive_cells"] = int(pad_cell[~act].sum())
    # The ACTIVE-cell count the coverage verdict below is taken over, recorded
    # by the function that raises that verdict.  derive() logs THIS key instead
    # of its own `n_active`, so the number printed beside the coverage figures
    # is provably the number the verdict used rather than a second count of the
    # same mask that could drift from it.
    #
    # OVERWRITE of the COVERAGE_PROVENANCE_SEED value, not the only write.  The
    # previous revision seeded the key set HERE, which is downstream of the
    # sentinel-collision / unknown-code / out-of-range / empty-mosaic / bad-mask
    # raises, and it seeded only two of the six keys, leaving
    # lc_active_cells_edge_short and lc_active_cells_nodata_dominated with a
    # single assignment site each inside their own fault block -- so a FAULT 1
    # raise dropped both and a FAULT 2 raise dropped the second.  The seed now
    # runs at function entry and lc_unstaged_tiles_under_failing_cells is no
    # longer seeded here at all; FAULT 1 overwrites it when it has a value.
    report["lc_active_cells"] = n_act
    # NAMING CHANGE, declared here because it is a contract change and not an
    # incidental rename.  The unscoped grid-wide keys lc_nodata_pixels,
    # lc_pad_pixels, lc_pixels_per_cell_median, lc_cells_unstaged,
    # lc_cells_nodata_dominated, lc_max_pad_pixels_in_a_cell and
    # lc_max_nodata_pixels_in_a_cell were REPLACED (not aliased) by the
    # explicitly scoped *_grid / *_active / *_in_any_grid_cell /
    # *_in_an_active_cell names above, because an unscoped name is precisely
    # what let a grid-wide pixel figure be printed beside a mask-scoped cell
    # count.  Keeping an unscoped alias would keep that hazard alive.  No
    # consumer subscripts the old names: this dict is returned to
    # run_hydromt_build.py, which only json.dumps() it into the staticmaps
    # attribute `landsurface_provenance` and copies it wholesale into
    # build_result.json under "landsurface" -- verified by grep over the KI,
    # whose only hits for the old names are this module's own superseded patch
    # scripts under _fix6_/_fix7_.

    # ── FAULT 1: STAGING GAP -- an ACTIVE cell contains pad ────────────────
    # Pad inside a staged footprint already raised above as a sentinel
    # collision, so pad reaching here is genuinely unstaged area. The cell's
    # class fractions would be computed over the covered sub-area, i.e. the
    # uncovered area redistributed pro rata over whichever classes lie in the
    # covered part -- the same silent substitution as a tolerated unknown code.
    unstaged = act & (pad_cell > 0)
    n_unstaged = int(unstaged.sum())
    report["lc_active_cells_unstaged"] = n_unstaged
    if n_unstaged:
        # Both the tile NAMES and the choice of remedy come from the FAILING
        # CELLS' OWN PAD PIXELS.  Two distinct defects are closed here.
        #   * The names used to be resolved from the failing cell's CENTRE.  A
        #     model cell straddling a 5-deg tile boundary takes its pad from the
        #     NEIGHBOURING tile, while its centre resolves to the tile it mostly
        #     sits in -- which is staged.  The message then named a present tile
        #     as the cause.  Pixel coordinates cannot make that mistake: a pad
        #     pixel is in exactly one 5-deg tile, the one it is missing from.
        #   * The remedy used to branch on `absent` being non-empty, i.e. on
        #     whether ANY tile is unstaged anywhere in the bbox.  An unstaged
        #     tile lying entirely over INACTIVE cells is benign and cannot be
        #     the cause, yet it selected the "stage them" wording. The branch is
        #     now taken on `absent_here` -- the unstaged tiles that the failing
        #     cells' pad pixels actually land in.
        unstaged_flat = np.nonzero(unstaged.ravel())[0]
        sel = np.isin(pcell_pad, unstaged_flat)
        lat_top = np.ceil(plat_pad[sel] / 5.0).astype(np.int64) * 5
        lon_left = np.floor(plon_pad[sel] / 5.0).astype(np.int64) * 5
        want = sorted({glcfcs30_tile_name(int(t), int(l)) for t, l in
                       np.unique(np.stack([lat_top, lon_left], axis=1), axis=0)})
        absent_all = [os.path.basename(m) for m in missing]
        absent_here = [t for t in want if t in absent_all]
        report["lc_unstaged_tiles_under_failing_cells"] = absent_here
        raise DeriveError(
            f"{n_unstaged} of {n_act} ACTIVE cell(s) contain rio_merge pad: up "
            f"to {int(pad_cell[unstaged].max())} of "
            f"~{int(round(px_per_cell))} pixels in one active cell, "
            f"{int(pad_cell[unstaged].sum())} pad pixels over the failing "
            f"cells. Those pad pixels themselves lie in 5-deg tile(s) {want}. "
            + (f"Of those, {absent_here} are NOT staged under {lc_dir}. Stage "
               "them. If GLC_FCS30 ships no tile with that name -- the product "
               "has no tile over open ocean -- then those active cells are not "
               "land and the basin mask is wrong; do not go looking for a tile "
               "that does not exist as a product. "
               if absent_here else
               "Every one of those tiles IS staged, yet these pixels fall "
               f"outside every staged footprint {tile_bounds}. That is an "
               "inconsistency between glcfcs30_tiles_for_bbox's 5-deg name "
               "enumeration and the tiles' actual bounds -- a bug to fix here, "
               "not an operator action. ")
            + "Refusing to compute class fractions over a covered sub-area.")

    # ── FAULT 2: MOSAIC-EDGE SHORTFALL -- active, no pad, still short ──────
    # The cause the previous revision named in this situation ("the model grid
    # extends beyond the GLC_FCS30 tile grid") is impossible here: an overhang
    # produces pad, which is fault 1. What is left is rasterization against the
    # FLOAT px_per_cell, plus rio_merge clipping the mosaic to `bounds`.
    edge_short = act & (pad_cell == 0) & (staged < 0.99 * px_per_cell)
    n_edge = int(edge_short.sum())
    report["lc_active_cells_edge_short"] = n_edge
    if n_edge:
        raise DeriveError(
            f"{n_edge} of {n_act} ACTIVE cell(s) receive fewer pixels from a "
            f"STAGED tile than a full cell holds and contain NO pad: "
            f"{int(staged[edge_short].min())} of ~{int(round(px_per_cell))} "
            f"pixels in the worst active cell. NO ACTIVE CELL CARRIES PAD, so "
            "this is NOT a staging gap and NOT an overhang past the tile grid "
            "-- an overhang produces pad, which is FAULT 1. That single fact is "
            "the whole of what reaching this branch establishes; in particular "
            "it does NOT establish that every enumerated tile is staged, "
            "because an unstaged tile lying entirely over INACTIVE cells is "
            f"benign and does not raise. Tiles staged: {report['lc_tiles']}; "
            f"enumerated but NOT staged: {report['lc_tiles_absent']} (a "
            "non-empty second list is consistent with this branch and is not "
            "the cause). What is left is that the mosaic pixel grid "
            f"({abs(tr.a):.9g} x "
            f"{abs(tr.e):.9g} deg) does not tile the {resolution} deg model "
            "cell a whole number of times, or the mosaic bounds clip the "
            "outermost half-pixel. The 1% tolerance already absorbs ordinary "
            "rounding, so a shortfall this large would redistribute the missing "
            "area pro rata over the classes present in the rest of the cell. "
            "Re-cut the model grid onto the mosaic's own pixel grid, or stage a "
            "product whose pixel size divides the model resolution.")

    # ── FAULT 3: IN-TILE NODATA -- fully staged, but ocean / "Filled value" ─
    # Measured against the STAGED pixels OF THAT SAME CELL, never against a full
    # cell, so it cannot fire merely because a tile is missing and the operator
    # is never told to stage a tile that is already staged.
    nodata_dom = act & (tot < 0.99 * np.maximum(staged, 1))
    n_nodata_dom = int(nodata_dom.sum())
    report["lc_active_cells_nodata_dominated"] = n_nodata_dom
    if n_nodata_dom:
        raise DeriveError(
            f"{n_nodata_dom} of {n_act} ACTIVE cell(s) ARE fully covered by "
            f"staged GLC_FCS30 tiles ({report['lc_tiles']}), but more than 1% "
            f"of their pixels carry a declared in-tile nodata code {LC_NODATA} "
            "(0 / 250 \"Filled value\"): up to "
            f"{int(nodata_cell[nodata_dom].max())} of "
            f"~{int(round(px_per_cell))} pixels in one active cell, "
            f"{int(nodata_cell[nodata_dom].sum())} over the failing cells. This "
            "is NOT a staging gap. Class fractions would be computed over the "
            "classified sub-area only, redistributing the nodata area pro rata "
            "over the classes inside it. Either the basin mask includes cells "
            "that are mostly water / outside the land mask, or the land-cover "
            "product does not cover them.")

    frac = np.zeros((ny, nx, ncls))
    ok = tot > 0
    frac[ok] = counts[ok] / tot[ok][:, None]
    return frac, codes


# ══ (b) LAI -> canopy storage ══════════════════════════════════════════
def _lai_files(lai_dir, year):
    """Seasonal LAI composites for `year`, preferring the AVHRR archive."""
    out = []
    for season in LAI_SEASONS:
        for stem in (f"GLASS_AVHRR_LAI_{season}_{year}_01deg.tif",
                     f"GLASS_LAI_{season}_{year}_01deg.tif"):
            p = os.path.join(lai_dir, stem)
            if os.path.exists(p):
                out.append(p)
                break
    return out


def _growing_season_lai(lat_centers, lon_centers, start_year, end_year,
                        lai_dir, report):
    """Per-cell growing-season mean LAI over the simulated years.

    GLASS LAI carries nodata = 0.0, so a composite with LAI == 0 is 'no valid
    retrieval / not growing'; the mean is taken over the composites that DO
    carry a retrieval, i.e. a growing-season rather than annual mean.
    """
    import rasterio
    from rasterio.windows import from_bounds as win_from_bounds

    ny, nx = len(lat_centers), len(lon_centers)
    ssum = np.zeros((ny, nx))
    scnt = np.zeros((ny, nx), dtype=np.int64)

    years_used, years_missing, files_used = [], [], 0
    pad = 0.2
    bbox = (float(lon_centers.min() - pad), float(lat_centers.min() - pad),
            float(lon_centers.max() + pad), float(lat_centers.max() + pad))

    for year in range(int(start_year), int(end_year) + 1):
        files = _lai_files(lai_dir, year)
        if not files:
            years_missing.append(year)
            continue
        years_used.append(year)
        for p in files:
            with rasterio.open(p) as src:
                win = win_from_bounds(*bbox, transform=src.transform)
                win = win.round_offsets().round_lengths()
                a = src.read(1, window=win, boundless=True, fill_value=0.0)
                wtr = src.window_transform(win)
            if a.size == 0:
                raise DeriveError(f"{os.path.basename(p)} does not overlap the "
                                  f"model grid bbox {bbox}")
            rows = np.rint((lat_centers - wtr.f) / wtr.e - 0.5).astype(int)
            cols = np.rint((lon_centers - wtr.c) / wtr.a - 0.5).astype(int)
            if (rows < 0).any() or (rows >= a.shape[0]).any() or \
               (cols < 0).any() or (cols >= a.shape[1]).any():
                raise DeriveError(
                    f"{os.path.basename(p)} window does not cover every model "
                    f"cell centre (rows {rows.min()}..{rows.max()} of "
                    f"{a.shape[0]}, cols {cols.min()}..{cols.max()} of "
                    f"{a.shape[1]})")
            sub = a[np.ix_(rows, cols)].astype(float)
            good = np.isfinite(sub) & (sub > 0.0)
            ssum[good] += sub[good]
            scnt[good] += 1
            files_used += 1

    if not years_used:
        raise DeriveError(
            f"no GLASS LAI composite found under {lai_dir} for "
            f"{start_year}-{end_year}")

    report["lai_years_used"] = years_used
    report["lai_years_missing"] = years_missing
    report["lai_files_read"] = files_used
    report["lai_period_matched"] = not years_missing
    return ssum, scnt


# ══ (c) HWSD REF_DEPTH -> SoilThickness ════════════════════════════════
def _hwsd_soil_thickness(lat_centers, lon_centers, mask, hwsd_raster, hwsd_csv,
                         report, need_ksat=False, resolution=None):
    """SHARE-weighted REF_DEPTH (cm -> mm) per active cell.

    When `need_ksat` is set, the same single CSV read also yields a
    SHARE-weighted Saxton-Rawls KsatVer (mm/day) per cell, so the caller does not
    have to call ki_tools_common.soil_utils.lookup_hwsd once per cell — that
    re-reads the 7.5 MB HWSD table on every call.

    NON-SOIL MAPPING UNITS (why this samples the whole cell, not its centre)
    -----------------------------------------------------------------------
    HWSD reserves mapping units for surfaces that HAVE no soil profile: 7001 UR
    (urban), 7003 WR (water bodies), and the other `ISSOIL = 0` units (glacier,
    rock outcrop, salt flat, dunes, no-data). Every soil attribute in those rows
    is NaN BY DEFINITION — REF_DEPTH included.

    This function used to read ONE HWSD pixel per cell, at the cell centre, so a
    single cell centred on a city or a lake made the whole build fail with
    "mapping unit(s) [7001, 7003] carry no usable REF_DEPTH row ... fix the soil
    join". There is nothing to fix in the join: the Saar basin simply contains
    Saarbrücken and open water (2026-08-08). Any basin with a city or a
    reservoir in it hit this.

    So the cell is sampled over its FULL footprint and REF_DEPTH / texture are
    weighted by the PIXEL AREA of each SOIL mapping unit inside it, with the
    declared non-soil units excluded from the weighting. That is reading HWSD as
    documented (a non-soil unit contributes no soil depth), not substituting a
    value: the number reported for a cell is still measured HWSD data, taken
    from the part of that cell which actually has soil. A cell with NO soil
    pixels at all still raises, and a unit that claims to be soil (ISSOIL = 1)
    but carries unusable data still raises — those are real defects.
    """
    import pandas as pd
    import rasterio

    ny, nx = len(lat_centers), len(lon_centers)
    if resolution is None:
        resolution = (abs(float(lat_centers[0] - lat_centers[1]))
                      if ny > 1 else abs(float(lon_centers[1] - lon_centers[0])))
    half = float(resolution) / 2.0
    # mu_counts[j][i] = {MU_GLOBAL: pixel count inside the cell}
    mu_counts = {}
    mu = np.zeros((ny, nx), dtype=np.int64)   # dominant unit, provenance only
    with rasterio.open(hwsd_raster) as src:
        for j in range(ny):
            for i in range(nx):
                if mask[j, i] == 0:
                    continue
                lat = float(lat_centers[j])
                lon = float(lon_centers[i])
                r, c = src.index(lon, lat)
                if not (0 <= r < src.height and 0 <= c < src.width):
                    raise DeriveError(
                        f"HWSD raster {hwsd_raster} does not cover cell "
                        f"({lat:.4f}, {lon:.4f})")
                win = rasterio.windows.from_bounds(
                    lon - half, lat - half, lon + half, lat + half,
                    transform=src.transform).round_offsets().round_lengths()
                block = src.read(1, window=win, boundless=False)
                if block.size == 0:
                    block = src.read(
                        1, window=rasterio.windows.Window(c, r, 1, 1))
                vals, cnts = np.unique(block, return_counts=True)
                d = {int(v): int(n) for v, n in zip(vals, cnts) if int(v) > 0}
                mu_counts[(j, i)] = d
                mu[j, i] = max(d, key=d.get) if d else 0

    ids = sorted({m for d in mu_counts.values() for m in d})
    if not ids:
        raise DeriveError("every active cell maps to HWSD MU_GLOBAL 0 (no soil "
                          "mapping unit) — the grid is off the HWSD raster")

    cols = ["MU_GLOBAL", "SEQ", "SHARE", "REF_DEPTH", "ISSOIL"]
    if need_ksat:
        cols += ["T_SAND", "T_CLAY", "T_OC"]
    df = pd.read_csv(hwsd_csv, low_memory=False, usecols=cols)
    # HWSD's declared non-soil units: every component row carries ISSOIL = 0.
    # They are EXCLUDED from the per-cell weighting rather than failing it.
    nonsoil_mu = set()
    for mu_id in ids:
        s = df.loc[df["MU_GLOBAL"] == mu_id, "ISSOIL"].to_numpy(dtype=float)
        if s.size and np.all(np.nan_to_num(s, nan=0.0) == 0.0):
            nonsoil_mu.add(int(mu_id))
    depth_by_mu, ksat_by_mu, bad, bad_texture, bad_ksat = {}, {}, [], [], []
    for mu_id in ids:
        if mu_id in nonsoil_mu:
            continue
        rows = df[df["MU_GLOBAL"] == mu_id]
        rows = rows[np.isfinite(rows["REF_DEPTH"]) & (rows["REF_DEPTH"] > 0)]
        if len(rows) == 0:
            bad.append(mu_id)
            continue
        w = rows["SHARE"].to_numpy(dtype=float)
        w = np.where(np.isfinite(w) & (w > 0), w, 0.0)
        if w.sum() <= 0:
            w = np.ones(len(rows))
        depth_cm = float((rows["REF_DEPTH"].to_numpy(dtype=float) * w).sum() / w.sum())
        depth_by_mu[mu_id] = depth_cm * 10.0          # cm -> mm
        if need_ksat:
            from ki_tools_common.soil_utils import saxton_rawls

            # NO invented texture.  The previous revision defaulted a mapping
            # unit with no usable texture row to T_SAND=40 / T_CLAY=20 /
            # T_OC=1.5, and that guess propagated through saxton_rawls into
            # KsatVer and InfiltCapSoil -- a silent placeholder (dt_w040),
            # while the REF_DEPTH branch above correctly raised for the very
            # same condition.  Both conditions now fail the same way.
            # Usability is decided PER COMPONENT ROW, not per column. The
            # previous revision tested each column on its own with
            # `np.isfinite(v) & (v >= 0.0)`, so a non-soil component recorded as
            # T_SAND=0 / T_CLAY=0 (water body, glacier, rock outcrop) still
            # carried SHARE weight and diluted the texture toward zero, and the
            # three columns could even be averaged over different row subsets.
            # A SOIL row needs T_SAND > 0 AND T_CLAY > 0; T_OC only has to be
            # finite and >= 0, because zero organic carbon is a physically
            # meaningful HWSD record while a zero sand or clay percentage is
            # not. That asymmetry is deliberate and is stated in the FAILURE
            # POLICY.
            t_sand = rows["T_SAND"].to_numpy(dtype=float)
            t_clay = rows["T_CLAY"].to_numpy(dtype=float)
            t_oc = rows["T_OC"].to_numpy(dtype=float)
            soil_row = (np.isfinite(t_sand) & (t_sand > 0.0)
                        & np.isfinite(t_clay) & (t_clay > 0.0)
                        & np.isfinite(t_oc) & (t_oc >= 0.0))
            ws = np.where(soil_row, w, 0.0)
            if not soil_row.any() or ws.sum() <= 0:
                bad_texture.append(
                    (mu_id, {"soil_rows": int(soil_row.sum()),
                             "rows": int(len(rows)),
                             "share_of_soil_rows": float(ws.sum())}))
                continue
            sand = float((t_sand * ws).sum() / ws.sum())
            clay = float((t_clay * ws).sum() / ws.sum())
            oc = float((t_oc * ws).sum() / ws.sum())
            if not 0.0 < sand + clay <= 100.0:
                bad_texture.append(
                    (mu_id, {"T_SAND": sand, "T_CLAY": clay, "T_OC": oc,
                             "note": "sand+clay outside (0, 100] %"}))
                continue
            h = saxton_rawls(sand, clay, oc)
            # NO max(1.0, ...) floor. The floor made a collapsed lookup surface
            # as a legal constant 1.0 mm/day, which then passed the "constant
            # > 0" precondition on declared exception 2 and was downgraded to a
            # warning. A non-positive or non-finite KsatVer is a failed
            # computation and must fail as one.
            ksat_mu = float(h["ksat_cm_hr"]) * 10.0 * 24.0
            if not np.isfinite(ksat_mu) or ksat_mu <= 0.0:
                bad_ksat.append((mu_id, {"T_SAND": sand, "T_CLAY": clay,
                                         "T_OC": oc, "ksat_mm_day": ksat_mu}))
                continue
            ksat_by_mu[mu_id] = ksat_mu

    if bad:
        raise DeriveError(
            f"HWSD mapping unit(s) {bad} carry no usable REF_DEPTH row in "
            f"{hwsd_csv}. Refusing to fall back to the 2000 mm placeholder "
            f"(dt_w040) — fix the soil join instead.")
    if bad_texture:
        raise DeriveError(
            f"HWSD mapping unit(s) {[m for m, _ in bad_texture]} carry no "
            f"usable SHARE-weighted SOIL row (T_SAND > 0 and T_CLAY > 0, T_OC "
            f"finite) in {hwsd_csv} ({dict(bad_texture)}), so KsatVer -> "
            "InfiltCapSoil cannot be derived from real texture. Refusing to "
            "substitute an invented texture (dt_w040) — fix the soil join, or "
            "hand the deriver a real per-cell ksat_mm_day.")
    if bad_ksat:
        raise DeriveError(
            f"HWSD mapping unit(s) {[m for m, _ in bad_ksat]} yield a "
            f"non-positive or non-finite Saxton-Rawls KsatVer ({dict(bad_ksat)}) "
            "from real texture, so InfiltCapSoil would be a collapsed lookup. "
            "The former max(KsatVer, 1) floor hid exactly this as a legal "
            "constant 1.0 mm/day — refusing to floor it (dt_w040).")

    st = np.zeros((ny, nx))
    ks = np.zeros((ny, nx))
    soilless = []
    n_cells_with_nonsoil = 0
    nonsoil_pix = 0
    total_pix = 0
    for (j, i), counts in mu_counts.items():
        # Pixel-area weighting over the SOIL units present in this cell.
        w = {m: n for m, n in counts.items() if m in depth_by_mu}
        total_pix += sum(counts.values())
        drop = sum(n for m, n in counts.items() if m not in depth_by_mu)
        if drop:
            n_cells_with_nonsoil += 1
            nonsoil_pix += drop
        if not w:
            soilless.append(
                {"lat": round(float(lat_centers[j]), 4),
                 "lon": round(float(lon_centers[i]), 4),
                 "mu_pixels": {int(k): int(v) for k, v in counts.items()}})
            continue
        tot = float(sum(w.values()))
        st[j, i] = sum(depth_by_mu[m] * n for m, n in w.items()) / tot
        if need_ksat:
            ks[j, i] = sum(ksat_by_mu[m] * n for m, n in w.items()) / tot
    if soilless:
        raise DeriveError(
            f"{len(soilless)} active cell(s) contain NO HWSD soil pixel at all "
            f"— every pixel is MU_GLOBAL 0 or a declared non-soil unit "
            f"{sorted(nonsoil_mu)} (urban / water / glacier / rock, ISSOIL = 0): "
            f"{soilless[:5]}. There is no measured soil depth to weight, and "
            "inventing one is the dt_w040 placeholder failure. Drop the cell "
            "from the domain or hand the deriver a real per-cell value.")

    report["hwsd_mapping_units"] = ids
    report["hwsd_nonsoil_mapping_units_excluded"] = sorted(nonsoil_mu)
    report["hwsd_cells_with_nonsoil_pixels"] = n_cells_with_nonsoil
    report["hwsd_nonsoil_pixel_fraction"] = (
        round(nonsoil_pix / total_pix, 5) if total_pix else 0.0)
    report["hwsd_ref_depth_mm_by_mu"] = {int(k): round(v, 1)
                                         for k, v in depth_by_mu.items()}
    return (st, ks) if need_ksat else st


# ══ public API ═════════════════════════════════════════════════════════
def derive_landsurface_params(lat_centers, lon_centers, mask,
                              start_year, end_year,
                              resolution=None,
                              ksat_mm_day=None,
                              lc_source="glcfcs30",
                              lc_dir=GLCFCS30_DIR,
                              lai_dir=GLASS_LAI_DIR,
                              hwsd_csv=HWSD_CSV,
                              hwsd_raster=HWSD_RASTER,
                              verbose=True):
    """Derive per-cell wflow_sbm land-surface staticmaps fields.

    Args:
        lat_centers: 1-D cell-centre latitudes, DESCENDING (staticmaps convention)
        lon_centers: 1-D cell-centre longitudes, ASCENDING
        mask:        (ny, nx) int array, 1 inside the delineated domain
        start_year, end_year: simulation period (drives the LAI composites read)
        resolution:  grid spacing in degrees (inferred from the coords if None)
        ksat_mm_day: (ny, nx) per-cell HWSD KsatVer in mm/day; InfiltCapSoil is
                     taken from it instead of the old 100 mm/day constant. When
                     None it is looked up here via ki_tools_common.soil_utils.

    Returns:
        (fields, provenance) — fields is {name: (ny, nx) float array}, zero
        outside the mask; provenance records the source of every field, the
        clip/fallback counts and per-field min/median/max/nunique.

    Raises:
        DeriveError on any condition that would otherwise be papered over with a
        placeholder (see the module docstring's FAILURE POLICY).
    """
    lat_centers = np.asarray(lat_centers, dtype=float)
    lon_centers = np.asarray(lon_centers, dtype=float)
    mask = np.asarray(mask)
    ny, nx = len(lat_centers), len(lon_centers)
    if mask.shape != (ny, nx):
        raise DeriveError(f"mask shape {mask.shape} != grid ({ny}, {nx})")
    n_active = int((mask == 1).sum())
    if n_active == 0:
        raise DeriveError("mask has no active cell")
    if resolution is None:
        if nx < 2 and ny < 2:
            raise DeriveError("cannot infer resolution from a 1x1 grid — "
                              "pass resolution=")
        resolution = float(abs(lon_centers[1] - lon_centers[0])) if nx > 1 \
            else float(abs(lat_centers[1] - lat_centers[0]))
    if lc_source != "glcfcs30":
        raise DeriveError(
            f"lc_source={lc_source!r} is not implemented. GLC_FCS30 is the only "
            "documented-legend, sub-grid-resolution source on this server. "
            "ESA_CCI_LC_global is stored at 0.1 deg = the model grid, so it can "
            "only give a dominant class (PathFrac/WaterFrac would degenerate to "
            "0/1) and it starts in 1992.")

    prov = {"lc_source": ("GLC_FCS30-2015 (30 m; 30 land-cover LC ids + code "
                          "250 'Filled value', per GLCFCS30_2015Readme.docx)"),
            "lai_source": "GLASS LAI seasonal composites (0.1 deg)",
            "soil_thickness_source": "HWSD_DATA.csv REF_DEPTH, SHARE-weighted",
            "prohibited_source_not_used":
                "AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif (legend undocumented)",
            "lc_epoch_mismatch":
                f"GLC_FCS30 is a 2015 snapshot applied to {start_year}-{end_year}; "
                "the canopy block is period-matched via GLASS LAI",
            "resolution_deg": resolution,
            "active_cells": n_active}

    def _log(msg):
        if verbose:
            print(f"  [landsurface] {msg}", file=sys.stderr)

    # (a) land cover fractions ------------------------------------------------
    # The coverage verdict is raised INSIDE _class_fractions, next to the
    # per-cell arrays it is computed from and with the basin mask in hand.
    # Splitting the two -- statistics there, raise here -- is what let a
    # grid-scoped pixel figure be quoted alongside a mask-scoped cell count.
    #
    # `prov` is a LOCAL, so on a raise it never binds in the caller -- the fixed
    # coverage key set seeded inside _class_fractions would be unreadable on
    # precisely the fault paths it exists for.  Attaching it to the exception is
    # what makes the contract observable; the scope is deliberately the coverage
    # stage only, which is the scope the key set itself is declared for.
    try:
        frac, codes = _class_fractions(
            lat_centers, lon_centers, resolution, mask, lc_dir, prov)
    except DeriveError as exc:
        exc.provenance = prov
        raise
    # `prov['lc_active_cells']`, not the local `n_active` bound above: the two
    # are the same count of the same mask, but reading it back from the report
    # the coverage verdict wrote makes the logged figure provably the figure the
    # verdict was taken over, and keeps the log honest if the two ever diverge.
    _log(f"GLC_FCS30 {prov['lc_tiles']}: "
         f"{prov['lc_source_pixels']:,} pixels, "
         f"~{prov['lc_pixels_per_cell_median_active']:,}/cell over "
         f"{prov['lc_active_cells']} active cell(s)")

    rd = np.zeros((ny, nx)); kext = np.zeros((ny, nx))
    sl = np.zeros((ny, nx)); swood = np.zeros((ny, nx)); nman = np.zeros((ny, nx))
    for k, code in enumerate(codes):
        _, p_rd, p_kext, p_sl, p_sw, p_n = GLCFCS30_PARAMS[int(code)]
        f = frac[:, :, k]
        rd += f * p_rd
        kext += f * p_kext
        sl += f * p_sl
        swood += f * p_sw
        nman += f * p_n

    pathfrac = np.zeros((ny, nx))
    for c in IMPERVIOUS_CLASSES:
        pathfrac += frac[:, :, int(np.where(codes == c)[0][0])]
    waterfrac = np.zeros((ny, nx))
    for c in WATER_CLASSES:
        waterfrac += frac[:, :, int(np.where(codes == c)[0][0])]

    # Dominant class per cell, purely for the provenance report.
    dom = codes[np.argmax(frac, axis=2)]
    dom_active = dom[mask == 1]
    u, ucnt = np.unique(dom_active, return_counts=True)
    prov["lc_dominant_class_cells"] = {
        f"{int(a)} {GLCFCS30_PARAMS[int(a)][0]}": int(b) for a, b in zip(u, ucnt)}
    prov["lc_basin_fractions"] = {
        f"{int(c)} {GLCFCS30_PARAMS[int(c)][0]}":
            round(float(frac[:, :, k][mask == 1].mean()), 4)
        for k, c in enumerate(codes)
        if float(frac[:, :, k][mask == 1].mean()) >= 0.001}
    _log("dominant classes: " + ", ".join(
        f"{k}={v}" for k, v in sorted(prov["lc_dominant_class_cells"].items())))

    # (b) LAI -> Cmax / CanopyGapFraction -------------------------------------
    ssum, scnt = _growing_season_lai(lat_centers, lon_centers, start_year,
                                     end_year, lai_dir, prov)
    no_lai = int(((mask == 1) & (scnt == 0)).sum())
    if no_lai:
        raise DeriveError(f"{no_lai} active cell(s) have no valid GLASS LAI "
                          f"retrieval in {start_year}-{end_year}")
    lai = np.zeros((ny, nx))
    ok = scnt > 0
    lai[ok] = ssum[ok] / scnt[ok]

    cmax = 0.935 + 0.498 * lai - 0.00575 * lai ** 2
    n_cmax_clip = int(((mask == 1) & (cmax < 0.1)).sum())
    cmax = np.maximum(cmax, 0.1)
    cgf = np.exp(-np.maximum(kext, 1e-6) * lai)
    n_cgf_clip = int(((mask == 1) & ((cgf < 0.01) | (cgf > 0.95))).sum())
    cgf = np.clip(cgf, 0.01, 0.95)
    prov["lai_mean_growing_season"] = {
        "min": round(float(lai[mask == 1].min()), 3),
        "median": round(float(np.median(lai[mask == 1])), 3),
        "max": round(float(lai[mask == 1].max()), 3)}
    prov["cmax_clipped_cells"] = n_cmax_clip
    prov["canopygapfraction_clipped_cells"] = n_cgf_clip
    prov["canopy_formulation"] = ("Cmax = 0.935 + 0.498*LAI - 0.00575*LAI^2; "
                                  "CanopyGapFraction = exp(-Kext*LAI) "
                                  "(van Verseveld 2024)")
    _log(f"GLASS LAI {prov['lai_years_used'][0]}-{prov['lai_years_used'][-1]} "
         f"({prov['lai_files_read']} composites): mean LAI "
         f"{prov['lai_mean_growing_season']['min']}-"
         f"{prov['lai_mean_growing_season']['max']}")

    # (c) HWSD REF_DEPTH -> SoilThickness, KsatVer -> InfiltCapSoil ------------
    need_ksat = ksat_mm_day is None
    res_hwsd = _hwsd_soil_thickness(lat_centers, lon_centers, mask, hwsd_raster,
                                    hwsd_csv, prov, need_ksat=need_ksat,
                                    resolution=resolution)
    if need_ksat:
        st, ksat_mm_day = res_hwsd
        prov["ksat_source"] = ("HWSD SHARE-weighted Saxton-Rawls, computed "
                               "inside the deriver")
    else:
        st = res_hwsd
        ksat_mm_day = np.asarray(ksat_mm_day, dtype=float)
        if ksat_mm_day.shape != (ny, nx):
            raise DeriveError(f"ksat_mm_day shape {ksat_mm_day.shape} != "
                              f"grid ({ny}, {nx})")
        prov["ksat_source"] = "caller-supplied per-cell HWSD KsatVer"
    # InfiltCapSoil IS KsatVer, with no floor. np.maximum(ksat, 1.0) turned a
    # collapsed lookup into a legal constant 1.0 mm/day, which then satisfied the
    # "constant > 0" precondition on SINGLE_MAPPING_UNIT_CONSTANT_OK and was
    # downgraded to a warning. The derived path now raises where KsatVer is
    # computed; the caller-supplied path is checked here, so neither can deliver
    # a non-positive KsatVer that the constancy guard would wave through.
    ks_active = np.asarray(ksat_mm_day, dtype=float)[mask == 1]
    # THREE DISJOINT categories. The previous count was
    # `(~isfinite).sum() + (ks <= 0).sum()`, which counted a -inf cell twice and
    # could therefore report more bad cells than the mask contains. NaN is
    # excluded from `ks_nonpos` by the isfinite guard (NaN <= 0 is False
    # anyway), and +/-inf is its own category, so the three sum to the total.
    ks_nan = np.isnan(ks_active)
    ks_inf = np.isinf(ks_active)
    ks_nonpos = np.isfinite(ks_active) & (ks_active <= 0.0)
    ks_bad = ks_nan | ks_inf | ks_nonpos
    if ks_bad.any():
        # The minimum is taken over the FINITE cells only and is LABELLED as
        # such. np.nanmin skips NaN, so a failure caused purely by NaN cells
        # printed the minimum of the HEALTHY cells and read as though nothing
        # were wrong; an all-NaN active set emitted a RuntimeWarning and printed
        # "min nan".
        ks_finite = ks_active[np.isfinite(ks_active)]
        ks_min = (f"{float(ks_finite.min()):.6g}" if ks_finite.size
                  else "no active cell carries a finite KsatVer")
        raise DeriveError(
            f"{int(ks_bad.sum())} of {n_active} active cell(s) carry an "
            f"unusable KsatVer: {int(ks_nan.sum())} NaN, "
            f"{int(ks_inf.sum())} +/-inf, {int(ks_nonpos.sum())} finite and "
            f"<= 0 (disjoint categories). Minimum over the FINITE active "
            f"cells: {ks_min}. InfiltCapSoil would be a collapsed lookup. "
            "Refusing to floor it at 1 mm/day (dt_w040) — fix the HWSD join "
            "upstream.")
    infilt = np.where(mask == 1, ksat_mm_day, 0.0)

    # RootingDepth <= SoilThickness -------------------------------------------
    clip_sel = (mask == 1) & (rd > st)
    n_rd_clip = int(clip_sel.sum())
    rd = np.where(clip_sel, st, rd)
    prov["rootingdepth_clipped_to_soilthickness_cells"] = n_rd_clip
    prov["rootingdepth_clip_pct"] = round(100.0 * n_rd_clip / n_active, 1)
    _log(f"HWSD REF_DEPTH SoilThickness {st[mask==1].min():.0f}-"
         f"{st[mask==1].max():.0f} mm; RootingDepth clipped in "
         f"{n_rd_clip}/{n_active} cells")

    fields = {
        "RootingDepth": rd,
        "Kext": kext,
        "Sl": sl,
        "Swood": swood,
        "N": nman,
        "PathFrac": pathfrac,
        "WaterFrac": waterfrac,
        "Cmax": cmax,
        "CanopyGapFraction": cgf,
        "SoilThickness": st,
        "InfiltCapSoil": infilt,
    }
    fields = {k: np.where(mask == 1, v, 0.0).astype(float)
              for k, v in fields.items()}

    # ── guards: a constant field means the lookup silently missed ──────────
    n_mapping_units = len(prov.get("hwsd_mapping_units", []))
    stats, constant_fail = {}, []
    constant_warn, single_mu_warn = [], []
    for name in FIELD_NAMES:
        v = fields[name][mask == 1]
        nuniq = int(np.unique(np.round(v, 9)).size)
        stats[name] = {"min": float(np.min(v)), "median": float(np.median(v)),
                       "max": float(np.max(v)), "nunique": nuniq}
        if n_active > 1 and nuniq == 1:
            # Declared exception 1 — a class-fraction field constant at 0.0.
            if name in ZERO_CONSTANT_OK and float(v[0]) == 0.0:
                constant_warn.append(name)
            # Declared exception 2 — SoilThickness (REF_DEPTH) and
            # InfiltCapSoil (= KsatVer, unfloored; KsatVer = Saxton-Rawls of the same
            # unit's SHARE-weighted texture) are BOTH per HWSD mapping unit, so
            # a basin inside a SINGLE mapping unit is legitimately uniform in
            # both — and uniform in both or neither, which is why listing only
            # SoilThickness made this branch unreachable. Two or more units plus
            # a constant means the join missed, and still fails; so does a
            # constant 0.0, which is a collapsed lookup, not a uniform soil.
            elif (name in SINGLE_MAPPING_UNIT_CONSTANT_OK
                  and n_mapping_units == 1 and float(v[0]) > 0.0):
                single_mu_warn.append(f"{name}={float(v[0])!r}")
            else:
                constant_fail.append(f"{name}={float(v[0])!r}")
    prov["field_stats"] = stats
    prov["constant_zero_fraction_fields"] = constant_warn
    prov["constant_single_mapping_unit_fields"] = single_mu_warn
    if constant_warn:
        _log("WARNING: class genuinely absent from the basin, field is a "
             "constant 0.0: " + ", ".join(constant_warn))
    if single_mu_warn:
        _log(f"WARNING: the whole {n_active}-cell mask lies in ONE HWSD mapping "
             f"unit ({prov.get('hwsd_mapping_units')}), so REF_DEPTH is "
             f"genuinely uniform: " + ", ".join(single_mu_warn))
    if constant_fail:
        raise DeriveError(
            "these derived fields are CONSTANT over a "
            f"{n_active}-cell mask: {', '.join(constant_fail)}. A uniform "
            "land-surface field is the exact defect dt_w042 describes — the "
            "lookup missed. Refusing to write placeholder maps.")

    return fields, prov


# ══ CLI ════════════════════════════════════════════════════════════════
def _grid_from_args(args):
    if args.grid_nc:
        import xarray as xr
        # This venv's netCDF4/HDF5 build raises `NetCDF: HDF error` on files it
        # did not write; h5netcdf opens the same file fine. Try both rather than
        # letting the default engine decide.
        ds, last = None, None
        for eng in (None, "h5netcdf", "scipy"):
            try:
                ds = xr.open_dataset(args.grid_nc) if eng is None else \
                    xr.open_dataset(args.grid_nc, engine=eng)
                break
            except Exception as e:      # noqa: BLE001 — engine probe
                last = e
        if ds is None:
            raise DeriveError(f"cannot open {args.grid_nc}: {last}")
        ycoord = "y" if "y" in ds.coords else "lat"
        xcoord = "x" if "x" in ds.coords else "lon"
        lat = ds[ycoord].values.astype(float)
        lon = ds[xcoord].values.astype(float)
        if args.mask_var and args.mask_var in ds:
            m = ds[args.mask_var].values
            mask = np.where(np.isfinite(m) & (np.nan_to_num(m) != 0), 1, 0)
            mask = mask.astype(np.int32)
        else:
            mask = np.ones((len(lat), len(lon)), dtype=np.int32)
        ds.close()
        res = args.resolution or float(abs(lon[1] - lon[0]))
        return lat, lon, mask, res
    if args.bbox:
        res = args.resolution
        if not res:
            raise DeriveError("--resolution is required with --bbox")
        minlon, minlat, maxlon, maxlat = args.bbox
        lon = np.arange(np.floor(minlon / res) * res,
                        np.ceil(maxlon / res) * res + res / 2, res) + res / 2
        lat = (np.arange(np.floor(minlat / res) * res,
                         np.ceil(maxlat / res) * res + res / 2, res) + res / 2)[::-1]
        return lat, lon, np.ones((len(lat), len(lon)), dtype=np.int32), res
    raise DeriveError("provide --grid_nc or --bbox")


def main():
    ap = argparse.ArgumentParser(
        description="Derive per-cell wflow_sbm land-surface staticmaps fields "
                    "from GLC_FCS30 + GLASS LAI + HWSD")
    ap.add_argument("--grid_nc", type=str, default="",
                    help="NetCDF whose y/x coords define the model grid")
    ap.add_argument("--mask_var", type=str, default="wflow_subcatch",
                    help="Variable in --grid_nc marking active cells")
    ap.add_argument("--bbox", type=float, nargs=4, default=None,
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"),
                    help="Alternative to --grid_nc (needs --resolution)")
    ap.add_argument("--resolution", type=float, default=0.0,
                    help="Grid spacing (deg)")
    ap.add_argument("--start_year", type=int, required=True)
    ap.add_argument("--end_year", type=int, required=True)
    ap.add_argument("--lc_source", type=str, default="glcfcs30",
                    choices=["glcfcs30"])
    ap.add_argument("--lc_dir", type=str, default=GLCFCS30_DIR)
    ap.add_argument("--lai_dir", type=str, default=GLASS_LAI_DIR)
    ap.add_argument("--hwsd_csv", type=str, default=HWSD_CSV)
    ap.add_argument("--hwsd_raster", type=str, default=HWSD_RASTER)
    ap.add_argument("--out", type=str, default="",
                    help="Output .npz (arrays + provenance JSON) or .nc")
    args = ap.parse_args()

    try:
        lat, lon, mask, res = _grid_from_args(args)
        fields, prov = derive_landsurface_params(
            lat, lon, mask, args.start_year, args.end_year, resolution=res,
            lc_source=args.lc_source, lc_dir=args.lc_dir, lai_dir=args.lai_dir,
            hwsd_csv=args.hwsd_csv, hwsd_raster=args.hwsd_raster)
    except DeriveError as e:
        # The seeded coverage key set is only worth having if something can read
        # it on a fault path.  derive_landsurface_params attaches the provenance
        # dict it was filling to any DeriveError from the coverage stage, so the
        # six keys are printed with the values they held when the fault fired.
        # None here means the failure was outside the coverage stage.
        print(json.dumps({"status": "failed", "error": str(e),
                          "provenance": getattr(e, "provenance", None)},
                         indent=2, default=float))
        sys.exit(2)

    if args.out:
        if args.out.endswith(".nc"):
            import xarray as xr
            ds = xr.Dataset({k: (["y", "x"], v) for k, v in fields.items()},
                            coords={"y": lat, "x": lon})
            ds.attrs["provenance"] = json.dumps(prov)
            ds.to_netcdf(args.out)
        else:
            np.savez(args.out, provenance=json.dumps(prov), y=lat, x=lon,
                     mask=mask, **fields)

    print(json.dumps({"status": "success", "out": args.out or None,
                      "provenance": prov}, indent=2, default=float))


if __name__ == "__main__":
    main()
