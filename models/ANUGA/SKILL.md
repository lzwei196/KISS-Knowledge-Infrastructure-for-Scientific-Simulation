<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (5 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (25 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (13 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_inflow_hydrograph.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_inflow_hydrograph.py --help` |
| `tools/convert_forcing_to_anuga.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_anuga.py --help` |
| `tools/load_hydat_series.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/load_hydat_series.py --help` |
| `tools/parse_anuga_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_anuga_output.py --help` |
| `tools/run_anuga.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_anuga.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# ANUGA Skill

> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong (model crashes, wrong output,
> unexpected values), follow this order. Do NOT skip steps or write debug scripts:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — Check the model's own documentation (PDF manual, README,
>    official examples) for expected input formats, variable names, and units
> 3. **Find working examples** — Look in `outputs/` for previous successful runs of
>    this model, or check if the model ships with test/example data
> 4. **Fix the tool** — Now that you know what "correct" looks like, make targeted fixes
>
> Resist the urge to write diagnostic/debug Python scripts. The answers are almost
> always in the official docs and working examples, not in reverse-engineering the binary.

---

> **Version**: ANUGA 3.3.2 (`anuga-py`)
> **Domain**: hydrology / 2D shallow-water inundation
> **Last updated**: 2026-08-18
> **Validation status**: tested; real-world body campaign pending

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | ANUGA |
| Version | 3.3.2 |
| Language | Python with compiled C core flux kernels |
| License | Apache-2.0 |
| Repository | https://github.com/anuga-community/anuga_core |
| Citation | Geoscience Australia / ANU MSI community-maintained ANUGA |
| Primary domain | Hydrology: riverine flooding, dam-break, storm surge, tsunami runup |
| Spatial mode | 2-D unstructured triangular mesh |
| Scientific reference version | ANUGA 2D nonlinear shallow-water (Saint-Venant) finite-volume solver, DE0 discontinuous-elevation flow algorithm |

## 2. What This Model Does

ANUGA solves the 2D depth-averaged shallow-water equations over an unstructured triangular mesh. It predicts water-surface stage, depth, horizontal momentum, discharge through cross-sections, and flood inundation extent for event-scale hydrodynamic simulations.

Scope includes rainfall and riverine inflow forcing, wetting/drying, Manning friction, open or reflective boundaries, and hydraulic-structure operators. Scope excludes fully 3D turbulence, vertical convection, breaking waves, and forecasting as the model role.

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from dag + triplets; regenerate it after changing either source, never hand-edit it). This section states intent and common traps; the spec file is the contract.

### 3.1 Forcing

| Variable | Unit model expects | Source dataset / source kind | Model input format | Tool |
|----------|--------------------|------------------------------|--------------------|------|
| rainfall | m/s | CMFD / MSWX / NASA POWER forcing | volumetric rate per unit area applied via `Rate_operator` each step | `tools/convert_forcing_to_anuga.py` |
| inflow discharge | m^3/s | observed or prepared discharge hydrograph | prescribed total discharge via `Inlet_operator`, optional velocity direction | `tools/build_inflow_hydrograph.py` |

### 3.2 Static Inputs and Parameters

| Input | Unit | Source kind | Model input format |
|-------|------|-------------|--------------------|
| DEM / bed elevation | m | dataset lookup | terrain fitted to mesh as the `elevation` quantity |
| Manning's n (friction) | s/m^(1/3) | calibrated | `domain.set_quantity('friction', n)` field; default 0.03 |
| maximum_triangle_area | m^2 | user provided | mesh-generation constraint with optional interior-region refinement |
| g (gravitational acceleration) | m/s^2 | default | config.py hardcoded default 9.8 |
| minimum_storable_height | m | default | cells shallower than 1e-3 m stored as dry in SWW |
| minimum_allowed_height (H0) | m | default | DE0/DE3 use 1e-12; DE1/DE2 use 1e-5; config global default 1e-5 |
| CFL (Courant number) | - | default | config default 1.0; DE0 effective 0.9 |

### 3.3 Initial and Boundary Conditions

| Input | Unit | Model input format |
|-------|------|--------------------|
| initial stage | m | `set_quantity('stage', ...)`; dry bed requires `stage=elevation` everywhere |
| initial xmomentum | m^2/s | `set_quantity('xmomentum', ...)`; default 0.0 |
| initial ymomentum | m^2/s | `set_quantity('ymomentum', ...)`; default 0.0 |
| flow_algorithm | - | `set_flow_algorithm()`; DE0 default, DE1 higher order, `1_5` legacy |
| Reflective_boundary | - | solid wall; use on upslope/lateral edges |
| Transmissive boundary | - | weakly reflective open/free-outflow boundary at outlet/downstream |
| Dirichlet_boundary | m | fixed constant stage / momenta at the edge |
| Time_boundary | - | conserved quantities prescribed as a function of simulation time |
| File_boundary / Field_boundary | - | stage/momentum time series read from SWW, space/time interpolated |
| boundary_tags | - | dictionary mapping tag names to 0-based polygon edge indices |
| finaltime | s | evolve endpoint; yieldstep controls SWW save cadence |

## 4. Build Instructions

ANUGA is already installed at `KISSPATH_HOME/.local/lib/python3.12/site-packages/anuga`. Before any run, execute the KI preflight from this directory:

```bash
python preflight_check.py
```

Known build/runtime issue: if `import anuga` fails with a missing `.so` or undefined symbol, use diagnostic `dt_anuga_016` and reinstall ANUGA for the current Python interpreter before running the KI.

## 5. Execution

Always run the real ANUGA package through the KI tools. Start with preflight, then use the stage docs and commands in the legacy workflow sections below for rainfall, riverine inflow, simulation, and SWW parsing.

```bash
python preflight_check.py
python tools/run_anuga.py --help
python tools/parse_anuga_output.py --help
```

Expected runtime is mesh-size and event-length dependent; `maximum_triangle_area`, `finaltime`, and the adaptive CFL timestep dominate cost.

## 6. Output Description

**Source: `dag.yaml`.** The dag is the model identity for observable outputs; if this section ever disagrees with `dag.yaml`, the dag wins.

**Headline output** (dag `validation_rank: 1`; the variable this model is judged by):

> `inundation_extent` — Surface-water flooded area, derived by thresholding water depth over the mesh at peak inundation. (`km^2 (or boolean wet/dry field)`)

| Output variable (dag `var`) | Validation rank | Emitted in / file | Unit | Dag description |
|-----------------------------|-----------------|-------------------|------|-----------------|
| `inundation_extent` | 1 | derived from SWW depth field | km^2 (or boolean wet/dry field) | Surface-water flooded area, derived by thresholding water depth over the mesh at peak inundation. |
| `discharge` | 2 | derived via `get_flow_through_cross_section()` | m^3/s | Surface-water flow through a cross-section: integral of water momentum (uh, vh) normal to a polyline. |
| `stage` | 3 | SWW (NetCDF) dynamic variable | m | Water surface elevation (bed elevation + water depth); primary conserved quantity stored over the mesh. |
| `stage (analytical-benchmark centerline)` | 4 | derived from SWW along the channel centerline | m | 1D centerline stage profile at final time, compared against exact shallow-water solutions (dam-break, parabolic basin, runup). |
| `depth` | 5 | derived from SWW (stage - elevation) | m | Water depth = stage - elevation (clipped at 0); flood thickness above the bed. |
| `xmomentum` | 6 | SWW (NetCDF) dynamic variable | m^2/s | Depth-integrated surface-water momentum in x (uh); conserved quantity. |
| `ymomentum` | 7 | SWW (NetCDF) dynamic variable | m^2/s | Depth-integrated surface-water momentum in y (vh); conserved quantity. |

Other dag outputs are `stage`, `depth`, `xmomentum`, `ymomentum`, `discharge`, and `stage (analytical-benchmark centerline)`.

## 7. Tool Inventory

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `tools/convert_forcing_to_anuga.py` | Convert CMFD/MSWX/NASA POWER forcing to ANUGA rainfall | source dataset, lat/lon, years | rainfall time-series CSV in m/s |
| `tools/load_hydat_series.py` | Extract HYDAT flow or level series and datum metadata | station, variable, date range | tidy `date,value,symbol` CSV and metadata JSON |
| `tools/build_inflow_hydrograph.py` | Convert gauge discharge to an `Inlet_operator` hydrograph | gauge discharge CSV | `time_seconds,discharge_m3s` CSV |
| `tools/run_anuga.py` | Build domain, apply forcing/inflow, run ANUGA | DEM, forcing/inflow, mesh and boundary options | SWW output and run summary |
| `tools/parse_anuga_output.py` | Extract outputs from SWW | SWW file, gauge or cross-section options | stage/depth/discharge/inundation CSV or summary |

Use the detailed stage docs in `docs/s1_convert_rainfall_forcing.md` through `docs/s5_parse_anuga_outputs.md` before composing commands.

## 8. Unit Conversion Table

| Variable | Source unit (verified) | Model unit | Factor / operation | Type |
|----------|------------------------|------------|--------------------|------|
| CMFD precipitation | kg/m^2/s | m/s | divide by 1000 after conversion to water depth units | multiplicative |
| MSWX precipitation | mm/3hr | m/s | divide by 1000 * 10800 | multiplicative |
| NASA POWER precipitation | mm/hr | m/s | divide by 1000 * 3600 | multiplicative |
| HYDAT flow | m^3/s | m^3/s | x1 | identity |
| HYDAT level / stage | m | m | x1 only after vertical datum compatibility is confirmed | identity with datum check |
| DEM / bed elevation | m | m | x1 only when datum matches boundary and gauge elevations | identity with datum check |

## 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| rainfall rate | positive m/s adds water through `Rate_operator`; negative rates remove water and scale momentum | mm/hr or mm/timestep passed as a rate | 1000x to 3600x overflooding, or near-zero rainfall after double division |
| stage | water surface elevation above the model datum | water depth | apparent 150-300 m "depth" where terrain elevation is included |
| depth | `stage - elevation`, clipped at 0 | raw SWW `stage` | invalid flood-depth and inundation calculations |
| xmomentum / ymomentum | depth-integrated momentum in m^2/s | velocity in m/s | wrong discharge and velocity interpretation |
| discharge | m^3/s through an oriented cross-section; sign depends on polyline endpoint order | unsigned flow magnitude | zero or wrong-signed Q when the section is misplaced or oriented incorrectly |

## 9. Diagnostic Triplets (Top 5)

Read `diagnostics/triplets.yaml` on any error. These five real IDs cover the most common KI-level failures; do not duplicate the full corpus here.

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| `dt_anuga_001` | Entire domain floods unrealistically | rainfall supplied to `Rate_operator` in mm/hr or kg/m^2/s instead of m/s | convert rainfall to m/s or regenerate with `convert_forcing_to_anuga.py` |
| `dt_anuga_003` | stage offset by 20-40 m | DEM and water levels use different vertical datums | put DEM, boundary levels, and gauge levels on the same vertical datum |
| `dt_anuga_007` | benchmark skill varies or fails | flow algorithm missing or wrong | explicitly use `DE0` unless a benchmark requires `DE1` |
| `dt_anuga_023` | non-China DEM load fails or clamps to wrong terrain | old hardcoded China DEM path or missing global DEM fallback | pass `--dem_path` or rely on the MERIT DEM resolver and inspect `run_summary.json` |
| `dt_anuga_024` | extracted gauge stage is flat and depth is always zero | nearest mesh vertex is a dry bank/bridge point | use `--snap_to_channel_m` and treat low wetness warnings as a hard stop |

## 10. Coupling Interfaces

| Upstream model / data source | Variable exchanged | Unit | Temporal resolution |
|------------------------------|--------------------|------|---------------------|
| CMFD / MSWX / NASA POWER | rainfall | m/s after conversion | source-dependent; converted to ANUGA time series |
| observed discharge gauges | inflow discharge | m^3/s | event hydrograph timestep |
| DEM datasets | bed elevation | m | static |

| Downstream model / consumer | Variable exchanged | Unit | Temporal resolution |
|-----------------------------|--------------------|------|---------------------|
| GIS / flood-mask evaluation | inundation_extent | km^2 or boolean wet/dry field | peak spatial snapshot |
| gauge validation workflow | stage, depth, discharge | m, m, m^3/s | SWW yieldstep / extracted time series |
| analytical benchmark scorer | stage (analytical-benchmark centerline) | m | fixed final-time profile |

## 11. Validated Results

### Test Basin: analytical dam-break benchmark

| Property | Value |
|----------|-------|
| Location | synthetic flat channel |
| Area | no cited basin area |
| Period | finaltime=50 s |
| Resolution | 1000 m x 5 m flat channel; h1=10 m left, h0=1 m right |

### Performance Metrics -- judged against the field's bar, not intuition

**Source for bars: `docs/validation_convention.yaml`.** Every stated threshold below is cited exactly as the convention cites it. Null convention bands are written as `no cited threshold`.

> Bar for `inundation_extent` (`csi`, direction maximize): satisfactory >= 0.46 (`hoch2019`, `neal2016`); good = no cited threshold; very good >= 0.74 (`hoch2019`, `neal2016`). Achieved: body campaign pending.

| Dag variable | Metric | Direction | Bar (convention, cited) | Achieved in this KI |
|--------------|--------|-----------|--------------------------|---------------------|
| `inundation_extent` | csi | maximize | satisfactory >= 0.46 (`hoch2019`, `neal2016`); good = no cited threshold; very good >= 0.74 (`hoch2019`, `neal2016`) | body campaign pending |
| `stage` | nse | maximize | satisfactory >= 0.50 (`moriasi2007`, `roth2016`); good >= 0.65 (`moriasi2007`, `roth2016`); very good >= 0.75 (`moriasi2007`, `roth2016`) | no field-stage body result recorded here |
| `stage` | pbias | zero_centered | satisfactory = no cited threshold; good = no cited threshold; very good = no cited threshold | no field-stage body result recorded here |
| `depth` | nse | maximize | satisfactory >= 0.50 (`moriasi2007`, `roth2016`); good >= 0.65 (`moriasi2007`, `roth2016`); very good >= 0.75 (`moriasi2007`, `roth2016`) | no field-depth body result recorded here |
| `stage (analytical-benchmark centerline)` | nse | maximize | no cited threshold in convention for analytical centerline stage | best_nse=0.9999775984887547 |
| `stage (analytical-benchmark centerline)` | kge | maximize | no cited threshold in convention for analytical centerline stage | best_kge=0.9982459570150168 |
| `stage (analytical-benchmark centerline)` | r | maximize | no cited threshold in convention for analytical centerline stage | best_r=0.9999955436562552 |

Manifest validation tier: tested. Manifest tier justification: `measured: NSE=1.000, KGE=0.998, R=1.000`. This is an analytical centerline-stage benchmark result, not a completed body-campaign validation of rank-1 `inundation_extent`.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | KI tools | available | rainfall and inflow tools are present |
| DEM | KI resolver | available | `--dem_path`, China 90 m DEM when in footprint, or MERIT DEM tiles |
| Initial conditions | `run_anuga.py` | available | dry-bed default is `stage=elevation` |
| Boundary conditions | `run_anuga.py` | available | outlet side and boundary type must match the event |
| Observed body validation | flood masks / gauges | pending | body campaign pending for rank-1 `inundation_extent` |

## 12. Parameter Selection by Region

These are physically informed starting points, not proof of calibration.

| Region / use | Key parameters | Rationale |
|--------------|----------------|-----------|
| Analytical benchmarks | Manning's n = 0.0; maximum_triangle_area = 1-10 m^2 | frictionless exact-solution comparisons require high mesh accuracy |
| Smooth channels | Manning's n = 0.02-0.03 | diagnostic `dt_anuga_010` starting range |
| Natural streams | Manning's n = 0.03-0.05 | diagnostic `dt_anuga_010` starting range |
| Vegetated floodplains | Manning's n = 0.05-0.10 | diagnostic `dt_anuga_010` starting range |
| Dense forest floodplains | Manning's n = 0.10-0.15 | diagnostic `dt_anuga_010` starting range |
| Real-world domains up to 10 km | maximum_triangle_area = 100-1000 m^2 | diagnostic `dt_anuga_011` starting range |

---

**Type:** 2D depth-averaged shallow-water hydrodynamics (finite-volume, unstructured triangular mesh)
**Primary use:** tsunami inundation, dam-break, flood modeling
**Authoritative source:** https://github.com/anuga-community/anuga_core
**Installed at:** KISSPATH_HOME/.local/lib/python3.12/site-packages/anuga

## KI Tools

All tools are in `tools/` and use `ki_tools_common.load_forcing` for CMFD/MSWX/NASA POWER data.

| Tool | Purpose |
|------|---------|
| `tools/convert_forcing_to_anuga.py` | Convert CMFD/MSWX/NASA POWER forcing → rainfall time series CSV (m/s) |
| `tools/load_hydat_series.py` | Extract a daily HYDAT flow **or** level series (+ vertical-datum metadata) → tidy `date,value,symbol` CSV |
| `tools/build_inflow_hydrograph.py` | Gauge discharge (China TAB archive **or** tidy CSV) → `time_seconds,discharge_m3s` for `Inlet_operator` |
| `tools/run_anuga.py` | Set up domain from DEM, apply rainfall and/or riverine inflow, run simulation → SWW output |
| `tools/parse_anuga_output.py` | Extract discharge (via cross-section), stage at a gauge, and inundation extent from SWW output |

## Stage Docs

- `docs/s1_convert_rainfall_forcing.md` — CMFD/MSWX/NASA POWER rainfall to ANUGA `Rate_operator` CSV
- `docs/s2_load_hydat_series.md` — HYDAT flow/level extraction with datum metadata
- `docs/s3_build_inflow_hydrograph.md` — gauge discharge to `Inlet_operator` hydrograph CSV
- `docs/s4_run_anuga_simulation.md` — DEM setup, boundaries, rainfall/inflow, and SWW generation
- `docs/s5_parse_anuga_outputs.md` — discharge, stage/depth, and inundation-extent extraction

### Two forcing modes — pick the one the event actually has

* **Rain-on-grid** (`run_anuga.py --forcing_csv`, `Rate_operator`): rainfall
  falls on the whole mesh. Correct for a small headwater box; it CANNOT
  reproduce a flood routed in from upstream.
* **Riverine inflow** (`run_anuga.py --inflow_csv --inlet_latlon`,
  `Inlet_operator`): a prescribed discharge hydrograph enters at a point on the
  channel. This is the dag's first-class `inflow discharge` forcing and the
  right mode for any reach whose water comes from upstream. The two can be
  combined.

### Coordinate frames — the #1 source of silent wrong answers

ANUGA uses **two** frames and they differ by `extent_m/2`:

| Frame | Range | Used by |
|-------|-------|---------|
| mesh-relative | `0 .. extent_m` | `set_quantity()` callables (elevation fitting) |
| absolute (polygon) | `-extent_m/2 .. +extent_m/2` | `anuga.Region` (inlet), SWW `x + xllcorner` (gauge) |

Never hand-convert. Use `--inlet_latlon LAT LON` (run_anuga.py) and
`--gauge_latlon LAT,LON` with `--center_lat/--center_lon`
(parse_anuga_output.py); both route through `run_anuga.latlon_to_domain_xy`.
`run_anuga.py` also carries a post-fit **elevation range guard** that raises if
the fitted terrain escapes the source DEM range — that guard is what catches a
frame/extrapolation bug instead of silently fabricating ±1000 m terrain.

### DEM selection

`run_anuga.py` resolves terrain in this order: `--dem_path` → the China 90 m
DEM (only when the whole domain bbox fits inside it) → the overlapping
**MERIT DEM 90 m** global tiles (`KISSPATH_DATA/MERIT_DEM/nNNwWWW_dem.tif`,
mosaicked automatically across a seam). MERIT is EGM96 orthometric; the China
DEM is SRTM. There is **no synthetic-terrain fallback** unless you pass
`--allow_synthetic_dem` (smoke tests only).

### Real-world simulation workflow

```bash
# 1. Convert forcing to ANUGA rainfall format
python tools/convert_forcing_to_anuga.py \
    --source cmfd --lat 32.9 --lon 117.4 \
    --start_year 2005 --end_year 2005 \
    --output_dir ./forcing/

# 2. Run ANUGA simulation with DEM and rainfall
python tools/run_anuga.py \
    --lat 32.9 --lon 117.4 --extent_m 5000 \
    --forcing_csv ./forcing/rainfall_timeseries.csv \
    --output_dir ./output/ --finaltime 86400

# 3. Extract discharge at outlet cross-section
python tools/parse_anuga_output.py \
    --sww_file ./output/anuga_sim.sww \
    --cross_section "-2500,0,2500,0" \
    --output_csv ./output/discharge.csv
```

### Riverine workflow — stage at a gauge (worked example, HYDAT)

Validated 2026-08-09 on the Fraser River: inlet driven by observed discharge at
HYDAT `08MF005` (Fraser R. at Hope), stage scored at HYDAT `08MF035` (Fraser R.
near Agassiz) 31 km downstream. Drive from an **upstream** station and score at
a **different, downstream** station — driving and scoring the same gauge only
reproduces its rating curve.

```bash
# 1. Observations: upstream discharge (driver) + downstream level (target)
python tools/load_hydat_series.py --station 08MF005 --variable flow \
    --start 2020-04-01 --end 2020-06-30 --output_csv ./obs/hope_flow.csv
python tools/load_hydat_series.py --station 08MF035 --variable level \
    --start 2020-04-01 --end 2020-06-30 --output_csv ./obs/agassiz_level.csv

# 2. Inlet hydrograph (t=0 at --start, shared origin with the rainfall CSV)
python tools/build_inflow_hydrograph.py --gauge_csv ./obs/hope_flow.csv \
    --start 2020-04-01 --end 2020-06-30 --output_csv ./forcing/inflow.csv

# 3. Run: Inlet_operator on the channel, Transmissive outlet facing downstream
python tools/run_anuga.py --lat 49.230 --lon -121.740 --extent_m 20000 \
    --max_area 30000 --manning_n 0.035 --outlet_side left \
    --inflow_csv ./forcing/inflow.csv \
    --inlet_latlon 49.2745 -121.651 --inlet_radius_m 1200 \
    --finaltime 7862400 --yieldstep 21600 --output_dir ./output/

# 4. Stage at the gauge, snapped to the channel low point
python tools/parse_anuga_output.py --sww_file ./output/anuga_sim.sww \
    --gauge_latlon "49.20369,-121.77583" \
    --center_lat 49.230 --center_lon -121.740 \
    --snap_to_channel_m 400 --output_csv ./output/stage.csv
```

**Vertical datum — check BEFORE scoring stage.** ANUGA carries no datum
awareness, so an absolute stage comparison is only meaningful when the gauge
datum is geodetic. `load_hydat_series.py` writes `<csv>.meta.json` with
`datum_name`, `datum_id` and every published `STN_DATUM_CONVERSION` offset.
Many HYDAT stations use `ASSUMED DATUM` (id 10) whose zero is arbitrary — e.g.
`08MF005` levels need `+27.926 m` to reach the GSC geodetic datum. Score
against a station whose own datum is geodetic (`08MF035` = id 35), or apply the
published conversion; never compare a raw arbitrary-datum level to DEM
elevations.

**`--snap_to_channel_m` is not cosmetic.** A published gauge lat/lon is a bank
or bridge position. On a 30–90 m DEM the nearest mesh vertex is routinely a
bank cell that never wets, so the extracted "stage" is a CONSTANT equal to the
bank elevation. `parse_anuga_output.py` warns when the extraction vertex is wet
in <50 % of stored timesteps — treat that warning as a hard stop, not noise.

**Known limitation of a 90 m DEM for absolute stage.** MERIT/SRTM record the
*water surface* at acquisition, not the bed, and resolve neither the channel
bathymetry nor engineered dikes. On a large diked river the model therefore
conveys the flood across the whole floodplain and the absolute stage is biased
low. Prefer `r` / timing for a KI-validity verdict on such a reach and read
`nse`/`pbias` as a terrain-data statement, not a solver statement.

### Key variables

| Variable | Source | Unit |
|----------|--------|------|
| stage | direct ANUGA output (SWW) | m |
| depth | stage − elevation | m |
| discharge | `anuga.get_flow_through_cross_section()` on SWW | m³/s |

### Unit conversions (forcing)

- CMFD precip: kg/m²/s → mm/timestep (×timestep_s) → m/s (÷1000 ÷ timestep_s)
- ANUGA `Rate_operator` expects rainfall in **m/s**

## Parameters

| Parameter | Description | Typical Range | Unit |
|-----------|-------------|---------------|------|
| `maximum_triangle_area` | Maximum mesh element area; controls spatial resolution | 100–10000 | m² |
| `Manning's n` | Surface roughness coefficient for friction model | 0.01–0.15 | s/m^(1/3) |
| `finaltime` | Simulation end time | 50–86400 | s |
| `flow_algorithm` | Shallow water solver variant (`DE0`, `DE1`, `1_5Dkp`) | — | — |
| `minimum_storable_height` | Minimum depth below which cell is considered dry | 0.001–0.01 | m |
| `minimum_allowed_height` | Absolute minimum water depth for numerical stability | 1e-5–1e-3 | m |

Calibration is typically limited to Manning's n and mesh resolution. ANUGA is a physics-based solver; most parameters are physical constants, not tuneable coefficients.

## Output Description

ANUGA writes simulation results to **SWW files** (NetCDF-like format):

| Output Variable | Description | Unit | File |
|----------------|-------------|------|------|
| `stage` | Water surface elevation | m | SWW |
| `xmomentum` | Depth-averaged x-momentum | m²/s | SWW |
| `ymomentum` | Depth-averaged y-momentum | m²/s | SWW |
| `elevation` | Bed elevation (static) | m | SWW |
| `depth` | Water depth (stage − elevation) | m | derived |
| `discharge` | Flow through cross-section | m³/s | derived via `get_flow_through_cross_section()` |

Use `parse_anuga_output.py` to extract stage/discharge time series to CSV. SWW files can also be visualized with `anuga_viewer` or converted to raster grids for GIS analysis.

## Validation strategy

ANUGA is a physics solver, not a forecasting model. The correct validation is against
**analytical / closed-form solutions**, not gauge NSE/KGE. Treat `comparison_type='analytical'`
as the default mode for ANUGA tests.

Standard benchmarks shipped under `validation_tests/analytical_exact/` in the source repo:

| Test | Analytical reference | Use |
|------|----------------------|-----|
| `dam_break_wet` | Stoker / Ritter (Riemann) | quick wet-bed dam-break benchmark (default) |
| `dam_break_dry` | Ritter | dry-bed benchmark |
| `carrier_greenspan_transient` | Carrier & Greenspan 1958 | canonical linear-slope runup |
| `parabolic_basin` | Thacker 1981 | oscillating parabolic basin |
| `runup_on_beach` | steady-state flat lake | smoke test |

## Default test

`dam_break_wet`: 1D Stoker dam-break on a 1000 m x 5 m flat channel, h1=10 m (left),
h0=1 m (right), no friction, finaltime=50 s. Compare modeled stage along the centerline
at t=50 s against `anuga.validation_tests.analytical_exact.dam_break_wet.analytical_dam_break_wet.vec_dam_break`.

## Execution

```
python -c "import anuga" # sanity
# runner: diagnostics/run_dam_break_wet.py — loads numerical + analytical, writes NSE/R/KGE
```

Metric reporting: NSE, Pearson R, KGE computed on 1D centerline stage profile
(numerical_stage at t_final vs analytical h at the same x).

## Notes on previous failure

The earlier run used `examples/simple_examples/runup.py` (synthetic 10x10 rectangular beach)
with `comparison_type='none'`, yielding null metrics. The fix is to switch to an
analytical-solution benchmark and compare pointwise.
