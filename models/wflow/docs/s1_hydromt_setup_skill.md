# s1 — HydroMT Model Setup Skill Document

## Purpose

Build the wflow spatial model: staticmaps.nc containing all grid parameters (DEM, soil, vegetation, river network). This is the foundation — all other stages depend on correct staticmaps. Skipping this stage means no spatial parameters exist and the model cannot run.

## Prerequisites

- Stage s0 complete (wflow_config.yaml exists)
- Basin shapefile (.shp) or coordinates for delineation
- For HydroMT mode: hydromt_wflow Python package installed
- For manual mode: HydroCraft's HWSD soil and AVHRR vegetation data available

## Inputs

| Name | Type | Source | Description |
|------|------|--------|-------------|
| wflow_config.yaml | file | s0 | Configuration with basin, period, resolution |
| shapefile | file | user or delineation | Basin boundary polygon |
| data_catalog.yml | file | build_data_catalog.py | HydroMT data catalog (HydroMT mode) |

## Procedure

### Option A: HydroMT Mode (recommended for first use)

1. Run `build_data_catalog.py` to create catalog pointing to HydroCraft datasets
2. Run `hydromt build wflow` via `run_hydromt_build.py --use_hydromt`
3. Verify staticmaps.nc contains expected variables
4. Check river network looks reasonable (5-20% of cells should be river)

### Option B: Manual Mode (when HydroMT is unavailable)

`hydromt_wflow` is NOT installed in this environment (`import hydromt_wflow` →
ModuleNotFoundError), so manual mode is in practice the ONLY path.

1. Run `run_hydromt_build.py --shapefile /path/to/basin.shp`
2. This derives staticmaps.nc per cell. The land-surface block (RootingDepth,
   SoilThickness, InfiltCapSoil, Cmax, CanopyGapFraction, Kext, Sl, Swood, N,
   PathFrac, WaterFrac) comes from `s1_hydromt/derive_landsurface_params.py`
   (GLC_FCS30-2015 sub-grid class fractions + GLASS LAI + HWSD REF_DEPTH);
   KsatVer / theta_s / theta_r / c come from the HWSD Saxton–Rawls lookup.
3. **There is NO uniform-constant mode, and a uniform land-surface map is a
   BUILD FAILURE, not a starting point.** With a uniform SoilThickness 2000 mm /
   RootingDepth 750 mm the basin never water-stresses, AET pins to ~PET, and the
   water that should have become runoff is evaporated — the discharge is
   systematically under-predicted while the timing still looks right, so the run
   *appears* merely uncalibrated (dt_w015 / dt_w042). Rio Pelotas: AET
   1016 mm/yr = 0.97 × PET against the 758 mm/yr the observed balance implies,
   PBIAS −32%. Imhoff et al. 2020 identifies RootingDepth as one of the two most
   sensitive calibration-free discharge parameters, so leaving it uniform makes
   the most important lever inert. If a source does not resolve, the build must
   FAIL — never substitute a placeholder (dt_w040).
4. River network is thresholded on upstream area (`--river_threshold_km2`), not
   all cells = river.

### Post-Build Checks

5. Open staticmaps.nc and verify:
   - wflow_subcatch has non-zero values
   - wflow_dem has realistic elevation range
   - KsatVer is in range 10-10000 mm/day
   - SoilThickness is in range 500-5000 mm
   - theta_s > theta_r everywhere
   - **every land-surface field VARIES across the mask.** `nunique == 1` over a
     multi-cell basin means the lookup silently missed. The only two declared
     exceptions: PathFrac / WaterFrac may be a constant 0.0 (that class is
     genuinely absent from the basin, and both are literal class area
     fractions), and SoilThickness *together with* InfiltCapSoil may be uniform
     when the whole basin lies in a SINGLE HWSD mapping unit — REF_DEPTH is a
     per-mapping-unit attribute taking only 10/30/100 cm, and InfiltCapSoil **is
     KsatVer, unfloored** (KsatVer = Saxton–Rawls of that same unit's
     SHARE-weighted texture), so the two are uniform together or not at all
     (check `hwsd_mapping_units` in the build provenance). A constant 0.0 is
     never tolerated for either. There is deliberately no `max(KsatVer, 1)`
     floor: it turned a collapsed lookup into a legal constant 1.0 mm/day that
     satisfied the "constant > 0" precondition and was waved through as a
     warning. A non-positive or non-finite KsatVer now FAILS the build, on the
     derived path and on the caller-supplied path alike. On the caller-supplied
     path the three bad categories (NaN / ±inf / finite-and-≤ 0) are counted
     **disjointly** — `(~isfinite).sum() + (ks <= 0).sum()` counted a −inf cell
     twice — and the minimum is reported over the **finite** active cells and
     labelled as such, because `np.nanmin` skips NaN and would otherwise print a
     healthy minimum for an all-NaN failure. Swood is NOT an
     exception: it is class-area-weighted, so a constant-zero Swood means the
     weighting collapsed.
   - **land-cover coverage — THREE different faults, measured separately and
     all scoped to the ACTIVE mask.** Each one leaves the class fractions
     computed over a sub-area (the rest redistributed pro rata) and each FAILS
     the build, but they have different remedies so they must not share a
     message. rio_merge pads uncovered area with `LC_PAD_SENTINEL = 255` — a
     code in neither the GLC_FCS30-2015 legend nor `LC_NODATA = (0, 250)` —
     which keeps the three pixel populations disjoint. Whether pad means
     "unstaged" or "a tile really uses 255" is **decided from the staged tiles'
     own footprints**, not inferred from which tile names are missing:
     0. *sentinel collision* (grid-scoped, unconditional) — a pad pixel lying
        INSIDE a staged tile's footprint cannot be unstaged area, so it is real
        data wearing the sentinel. Change `LC_PAD_SENTINEL`. This is the one
        check that is not mask-scoped, because an ambiguous sentinel invalidates
        every pad/nodata count on the mosaic, active cells included.
     1. *staging gap* — an ACTIVE cell contains pad. Both the tile names and
        the remedy come from **the failing cells' own pad pixels**, never from
        the cell centre and never from the grid-wide missing-tile list. A cell
        straddling a 5° boundary takes its pad from the NEIGHBOURING tile while
        its centre resolves to the tile it mostly sits in — which is staged — so
        the centre named a present tile as the cause; and an unstaged tile lying
        entirely over INACTIVE cells cannot be the cause, yet it used to select
        the "stage them" wording. The message says plainly that if GLC_FCS30
        ships no tile with the named name (the product has none over open ocean)
        then those active cells are not land and the **mask** is wrong — do not
        hunt for a tile that does not exist. Pad over INACTIVE cells is benign
        (they are zeroed before the staticmaps are written) and is recorded,
        never raised on: a bbox that merely overhangs the coast must not fail a
        build.
     2. *mosaic-edge shortfall* — an ACTIVE cell has NO pad yet fewer staged
        pixels than a full cell holds. "The grid extends beyond the tile grid"
        is impossible here (that produces pad, i.e. fault 1); the real cause is
        rasterization — `px_per_cell` is a FLOAT and membership is decided by
        rounding pixel centres — which is also what the 1% tolerance is for.
        The message claims **only** what this branch establishes, namely that no
        ACTIVE cell carries pad. It does *not* claim every enumerated tile is
        staged — reaching here does not prove that, because an unstaged tile
        over inactive cells is benign — so both tile lists are printed as facts
        and neither is offered as the cause.
     3. *in-tile nodata* — the cell IS fully staged, but `classified` is below
        99% of that cell's own STAGED pixels: ocean or "Filled value" inside the
        tile. Measured against the cell's staged count, never against a full
        cell, so it cannot fire just because a tile is missing — and the
        operator is never told to stage a tile that is already staged.

     **Scoping is part of the contract.** Every figure a fault message quotes is
     active-cell scoped and comes from the FAILING cells (`*_active`,
     `*_in_an_active_cell`); grid-wide figures are reported separately as
     `*_grid` / `*_in_any_grid_cell` and never appear in a message. The verdict
     is raised inside `_class_fractions`, which now takes the mask — computing
     the statistics in one place and raising in another is what allowed a
     grid-scoped pixel count to be printed next to a mask-scoped cell count.

     **Provenance is a fixed key set, seeded at `_class_fractions` entry.**
     The six coverage keys (`lc_active_cells`,
     `lc_pad_pixels_inside_a_staged_footprint`, `lc_active_cells_unstaged`,
     `lc_active_cells_edge_short`, `lc_active_cells_nodata_dominated`,
     `lc_unstaged_tiles_under_failing_cells`) are written from
     `COVERAGE_PROVENANCE_SEED` as the **first statement** of that function, so
     a consumer reads `0` / `[]` instead of having to tell "the quantity was
     zero" apart from "the test never ran". Every later assignment is an
     **overwrite**, never the only write — seeding in the middle of the function
     left the claim false on five paths (the sentinel-collision, unknown-code,
     out-of-0-255, empty-mosaic and bad-mask raises all fire earlier) and left
     `lc_active_cells_edge_short` / `lc_active_cells_nodata_dominated` with a
     single assignment site inside their own fault block, so a FAULT 1 raise
     dropped both and a FAULT 2 raise dropped the second.
     **The scope is narrowed and stated:** the set is fixed *from
     `_class_fractions` entry onward*, i.e. for the coverage stage. A failure
     before that stage is entered never had a coverage stage and claims none of
     these keys. For the three `lc_active_cells_*` counters and
     `lc_unstaged_tiles_under_failing_cells` the seed `0` / `[]` is also a
     legitimate success value (no fault ⇒ no failing cells); for
     `lc_active_cells` it is not reachable on any success path, because an empty
     mask raises, so `lc_active_cells == 0` means the stage raised before it
     counted the mask.
     **The contract is observable.** `prov` is a local of
     `derive_landsurface_params`, so on a raise it never binds in the caller —
     seeded keys nothing can read would be decoration. A `DeriveError` from the
     coverage stage carries the dict as `e.provenance` (class attribute
     `DeriveError.provenance = None`), and the CLI prints it under
     `"provenance"` on the failure path; `None` means the failure was outside
     the coverage stage. The `*_grid` / `*_active` figures are *not* part of the
     seeded set — they are measured once, after the mask checks, and are
     absent on the earlier raises. The unscoped names of the
     earlier revision (`lc_nodata_pixels`, `lc_pad_pixels`,
     `lc_pixels_per_cell_median`, `lc_cells_unstaged`,
     `lc_cells_nodata_dominated`, `lc_max_pad_pixels_in_a_cell`,
     `lc_max_nodata_pixels_in_a_cell`) were **replaced, not aliased** — an
     unscoped alias would preserve exactly the ambiguity that let a grid-wide
     figure be quoted in a mask-scoped message. Nothing subscripts them:
     `run_hydromt_build.py` only `json.dumps()` the dict into the staticmaps
     attribute `landsurface_provenance` and copies it wholesale into
     `build_result.json` under `"landsurface"`.
   - **HWSD texture is judged per component ROW, not per column**: a row counts
     as soil only if `T_SAND > 0` **and** `T_CLAY > 0`; a 0/0 row is a non-soil
     component (water, glacier, rock) and is dropped from the SHARE weighting
     instead of diluting the mean toward zero. `T_OC` only has to be finite and
     `>= 0` — zero organic carbon is a real HWSD record, a zero sand or clay
     percentage is not. All three columns are averaged over the same surviving
     rows.
   - land-cover legend: the tiles under `KISSPATH_DATA/vegetation/GLCFCS30` are
     **GLC_FCS30-2015**, whose forest codes are 50/60/70/80/90 with open–closed
     splits only at 61/62, 71/72, 81/82. Codes 51/52/91/92 belong to the
     GLC_FCS30D / 2020-era legend and must never be mapped through the 2015
     table; the deriver raises if it sees one.

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| staticmaps.nc | outputs/<run>/wflow_project/staticmaps.nc | ncdump -h shows expected variables |
| data_catalog.yml | outputs/<run>/data_catalog.yml | YAML loads, paths exist |

## Validation Checks

1. staticmaps.nc exists and is >1 MB
2. Grid dimensions match expected resolution
3. Active cells (wflow_subcatch > 0) > 0
4. No NaN values in soil parameters within basin mask
5. River network has proper connectivity (dt_w013)

## Common Pitfalls

- **dt_w013**: If wflow_river is all zeros, routing produces zero flow
- **dt_w014**: Boundary cells with invalid flow direction cause BoundsError
- **dt_w024**: HydroMT-wflow version must match Wflow.jl version
- **dt_w042**: A uniform land-surface field (`nunique == 1` over a multi-cell
  mask) is a BUILD FAILURE, not a caveat to disclose — see Option B item 3. The
  only declared exceptions are PathFrac/WaterFrac constant at exactly 0.0, and
  SoilThickness + InfiltCapSoil uniform (and > 0) inside a single HWSD mapping
  unit — those two are per-mapping-unit attributes and are uniform together or
  not at all. That "> 0" only means something because InfiltCapSoil carries no
  `max(..., 1)` floor: with the floor, a collapsed KsatVer lookup surfaced as a
  legal constant 1.0 mm/day and passed the exception.
- **Coverage provenance (fixed key set)** — no triplet id is cited here on
  purpose: `diagnostics/triplets.yaml` currently ends at `dt_w041` and a doc that
  names an id the file does not define is the same dangling reference `dt_w042`
  already is. The rule is proposed as a tier-3 addition, not asserted here.
  The coverage key set is seeded at
  `_class_fractions` entry, before every raise in it, and each fault block only
  *overwrites*. A key assigned solely inside its own fault block is absent
  whenever an EARLIER fault raises, which silently turns a declared "always
  present" contract into a `KeyError` on exactly the paths it was written for.
  The rule: if a key is declared always-present, seed it at function entry, and
  narrow the declared scope to the function that seeds it. And if the dict is a
  local of the caller, attach it to the exception — otherwise nothing can read
  it on the fault path and the seeding is decoration.
- **dt_w040 (land cover)**: a sentinel collision, a staging gap, a mosaic-edge
  shortfall and in-tile nodata are FOUR separate faults with separate messages
  — see the coverage item under Post-Build Checks. The mosaic pad sentinel (255)
  must stay outside both the legend and `LC_NODATA`, or they collapse into one
  undiagnosable shortfall. Three rules that are easy to get wrong: pad is
  attributed by TILE FOOTPRINT, never inferred from the missing-tile list (the
  inferred branch was unreachable and named a cause that could not have
  occurred); the failing cells' TILE NAMES and the choice of remedy come from
  those cells' own PAD PIXELS, not from the cell centre (a cell straddling a 5°
  boundary would otherwise name its staged neighbour) and not from whether any
  tile is missing anywhere in the bbox (a tile over inactive cells cannot be the
  cause); and a coverage fault is measured over the ACTIVE mask only, so a bbox
  overhanging the coast or the tile grid over inactive cells is recorded, not
  failed.
