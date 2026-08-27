> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (7 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (22 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (12 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_mosart_grid.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_mosart_grid.py --help` |
| `tools/convert_grid_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_grid_parameters.py --help` |
| `tools/convert_runoff_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_runoff_forcing.py --help` |
| `tools/delineate_d8_from_merit.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/delineate_d8_from_merit.py --help` |
| `tools/frac_to_basin_shp.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/frac_to_basin_shp.py --help` |
| `tools/parse_mosart_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_mosart_output.py --help` |
| `tools/run_mosartwmpy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_mosartwmpy.py --help` |

*7 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# MOSART-WM (mosartwmpy) — Knowledge Infrastructure

**Package**: `hydrocraft-mosartwmpy-routing` v1.0.0
**Model**: mosartwmpy (Python translation of MOSART-WM)
**Repository**: https://github.com/IMMM-SFA/mosartwmpy
**Created by**: IMMM-SFA / PNNL (Travis Thurber et al.)
**Last updated**: 2026-03-26
**Stats**: 7 tools | 5 skill documents | 22 diagnostic triplets | ~2,500 lines of validated Python
**Validation status**: `validated`

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | MOSART-WM (Model for Scale Adaptive River Transport with Water Management) |
| Implementation | `mosartwmpy` |
| Version | `hydrocraft-mosartwmpy-routing` v1.0.0; scientific reference version MOSART-WM |
| Language | Python |
| License | BSD-3-Clause |
| Repository | https://github.com/IMMM-SFA/mosartwmpy |
| Primary domain | Hydrology / river routing and water management |
| Spatial mode | Distributed gridded river network |

## 2. What This Model Does

MOSART-WM routes externally supplied land-surface runoff through hillslope, tributary,
main-channel, reservoir, and water-supply components on a regular lat/lon river-network
grid. It is a routing and water-management model, not a rainfall-runoff generator: QOVER
and QDRAI runoff fields must come from an upstream land-surface model or equivalent
runoff product.

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from `dag.yaml` and
`diagnostics/triplets.yaml`; regenerate it after changing either, never hand-edit it).
This section explains intent and traps; `docs/format_spec.yaml` is the contract.

### 3.1 Runoff and Demand Forcing

| Variable | Unit model expects | Source dataset / producer | Source unit | Conversion |
|----------|-------------------|---------------------------|-------------|------------|
| `QOVER` surface runoff | mm/s | Upstream VIC/CLM/mHM/Livneh runoff, or BMI `surface_runoff_flux` | source-dependent | Use `tools/convert_runoff_forcing.py`; mm/day -> mm/s by division by 86400 |
| `QDRAI` subsurface runoff | mm/s | Upstream VIC/CLM/mHM/Livneh runoff, or BMI `subsurface_runoff_flux` | source-dependent | Use `tools/convert_runoff_forcing.py`; mm/day -> mm/s by division by 86400 |
| optional wetland runoff | mm/s | Optional gridded runoff component | source-dependent | Convert to mm/s before routing |
| `totalDemand` | m3/s | Water-demand NetCDF or ABM demand module | m3/s | Direct rate input; internally accumulated over substeps |

### 3.2 Static Inputs

| Input | Source | Tool that prepares it |
|-------|--------|----------------------|
| D8 river network triplet | MERIT-Hydro-derived Lohmann ArcASCII `direc` / `xmask` / `frac` files | `tools/delineate_d8_from_merit.py` |
| VIC domain bridge | Delineated `frac` grid | `tools/frac_to_basin_shp.py` |
| MOSART grid domain | Validated D8 network plus MOSART geometry defaults/fills | `tools/build_mosart_grid.py`, then `tools/convert_grid_parameters.py --validate-only` |
| Reservoir parameters | GRanD reservoir inputs and ISTARF coefficients | `create_grand_parameters` |
| Mean monthly reservoir flow/demand | Prepared Parquet schedules | External preparation, consumed by mosartwmpy |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| `config.yaml` | YAML | Simulation dates, timestep, output cadence, grid/runoff/demand/reservoir paths, water-management toggles |
| Restart file | NetCDF | Optional `{name}_restart_{year}_{month}_{day}.nc`; absent restart means zero-initialized state |

## 4. Build Instructions

Install the real package, then run `python preflight_check.py` in this KI directory before
debugging any model run. On Python 3.12, install `setuptools` with mosartwmpy because
mosartwmpy imports `pkg_resources`.

```bash
pip install mosartwmpy setuptools
# or
conda install -c conda-forge mosartwmpy
```

Canonical run environment on this server:
`KISSPATH_KI_ROOT/MOSART/venv/bin/python`.

## 5. Execution

Read each tool's `--help` before composing a command. The executable chain is:

```bash
python preflight_check.py
python tools/convert_runoff_forcing.py --help
python tools/build_mosart_grid.py --help
python tools/convert_grid_parameters.py --help
python tools/run_mosartwmpy.py --help
python tools/parse_mosart_output.py --help
```

The normal run order is runoff forcing -> grid preparation -> configuration ->
`run_mosartwmpy.py` -> `parse_mosart_output.py`. For a new real gauge, first produce
gridded runoff for the same cells and dates as the MOSART domain.

## 6. Output Description

**Sourced from `dag.yaml`; if this section and the dag ever disagree, the dag wins.**

**Headline output** (dag `validation_rank: 1`):

> `RIVER_DISCHARGE_OVER_LAND_LIQ` — Main-channel outflow / basin river discharge (BMI runoff_land, outgoing_water_volume_transport_along_river_channel); the gauge-comparable streamflow output. (`m3/s`)

Other dag outputs: `channel_outflow`, `STORAGE_LIQ`, `WRM_STORAGE`, `WRM_SUPPLY`,
`WRM_DEFICIT`.

| Output variable (dag `var`) | Rank | File | Unit | Description |
|-----------------------------|------|------|------|-------------|
| `RIVER_DISCHARGE_OVER_LAND_LIQ` | 1 | output NetCDF | m3/s | Main-channel outflow / basin river discharge (BMI runoff_land, outgoing_water_volume_transport_along_river_channel); the gauge-comparable streamflow output. |
| `channel_outflow` | 2 | output NetCDF | m3/s | Outflow from a single grid cell's main channel. |
| `STORAGE_LIQ` | 3 | output NetCDF | m3 | Total routing storage (channel + subnetwork + hillslope) on the grid; BMI surface_water_amount. |
| `WRM_STORAGE` | 4 | output NetCDF | m3 | Reservoir storage; BMI reservoir_water_amount. |
| `WRM_SUPPLY` | 5 | output NetCDF | m3/s | Water supply delivered to a grid cell from reservoir/channel extraction. |
| `WRM_DEFICIT` | 6 | output NetCDF | m3 | Cumulative unmet water-supply demand for a grid cell. |

## 7. Tool Inventory

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `tools/delineate_d8_from_merit.py` | Build a Lohmann-style D8 network triplet at the target gauge | MERIT-Hydro tiles and gauge location | ArcASCII `direc`, `xmask`, `frac` |
| `tools/frac_to_basin_shp.py` | Derive the VIC basin shapefile from the delineated `frac` grid | D8 `frac` grid | Basin shapefile for VIC |
| `tools/convert_runoff_forcing.py` | Convert existing runoff to mosartwmpy forcing | Gridded runoff NetCDF | `QOVER` / `QDRAI` NetCDF in mm/s |
| `tools/build_mosart_grid.py` | Build a MOSART domain grid from a validated D8 network | D8 network triplet | Full MOSART grid NetCDF |
| `tools/convert_grid_parameters.py` | Validate/fill an existing MOSART grid domain NetCDF | Grid domain NetCDF | Validated MOSART grid NetCDF |
| `tools/run_mosartwmpy.py` | Execute the real mosartwmpy model through BMI | `config.yaml` plus prepared inputs | Monthly output NetCDF files and restarts |
| `tools/parse_mosart_output.py` | Extract output time series for scoring or coupling | MOSART output NetCDF | CSV time series |

## 8. Unit Conversion Table (Unit Table)

**This table records the KI's known unit conversions; verify source NetCDF attributes before
running a new dataset.**

| Variable / quantity | Source unit (verified or required) | Model / internal unit | Factor or operation | Type |
|---------------------|-------------------------------------|------------------------|---------------------|------|
| `QOVER` / `QDRAI` from mm/day runoff | mm/day | mm/s | divide by 86400 | multiplicative |
| `QOVER` / `QDRAI` from m/s runoff | m/s | mm/s | multiply by 1000 | multiplicative |
| runoff loaded by mosartwmpy | mm/s | m3/s, then m/s | multiply by 0.001 x `frac` x `area`, then divide by `area` | multiplicative |
| runoff output finalization | m/s | m3/s | multiply by `area` | multiplicative |
| demand rate | m3/s | m3 per substep | multiply by subcycle delta-t | multiplicative |
| supply accumulator | m3 accumulated | m3/s output | divide by timestep | multiplicative |
| reservoir capacity `CAP_MCM` | million m3 | m3 | multiply by 1e6 | multiplicative |
| reservoir area `AREA_SKM` | km2 | m2 | multiply by 1e6 | multiplicative |
| reservoir evaporation | mm/s over km2 | m3 | multiply by 1e6 x delta-t x `AREA_SKM` | multiplicative |
| hillslope storage | m | m3 | multiply by `area` x `frac` | multiplicative |

## 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| Runoff forcing | Positive input flux in mm/s, split into `QOVER` and `QDRAI` | mm/day runoff rate or accumulated depth | Discharge can be 86400x wrong |
| River discharge | Absolute flow in m3/s at a grid cell / outlet | Depth per cell | Gauge comparison magnitude is invalid |
| `WRM_SUPPLY` | Delivered supply rate in m3/s after finalization | Accumulated m3 | Supply bias is scaled by timestep |
| Reservoir capacity | `CAP_MCM` in million m3 | m3 | Reservoir storage becomes 1e6x too large |
| Reservoir area | `AREA_SKM` in km2 | m2 | Evaporation becomes 1e6x too large |

## 9. Diagnostic Triplets (Top 5)

The full diagnostic corpus stays in `diagnostics/triplets.yaml`; check it before debugging.

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| T001 | Discharge is approximately 86400x higher than expected values | Runoff input units are mm/day but config assumes mm/s | Convert runoff to mm/s or use `convert_runoff_forcing.py --source-units mm/day` |
| T002 | Discharge is approximately 1000x higher than expected | Runoff units are m/s but mosartwmpy expects mm/s | Convert m/s to mm/s or use `convert_runoff_forcing.py --source-units m/s` |
| T003 | All output variables are zero or NaN | Grid mask excludes all cells, or runoff is zero at grid locations | Check active grid cells, runoff maxima, and exact lat/lon alignment |
| T021 | River discharge is exactly 0 at the gauge cell, but a neighbouring cell carries the full basin flow | The gauge cell was made the terminal `dnID == -1` outlet | Make interior gauges through-cells; use `build_mosart_grid.py` and score at `scoring_lat` / `scoring_lon` |
| T022 | No gridded runoff / QOVER-QDRAI file for a China basin; `convert_grid_parameters --source-type merit` produces nothing new | MOSART has no runoff-generation tool, and `convert_grid_parameters` only validates an existing grid | Run the VIC KI first, convert VIC flux to runoff forcing, and build the MOSART grid from the D8 triplet |

## 10. Coupling Interfaces

| Upstream model / producer | Variable exchanged | Unit | Temporal resolution |
|---------------------------|-------------------|------|---------------------|
| VIC / CLM / mHM / Livneh or equivalent LSM | `QOVER` surface runoff | mm/s | Model timestep or gridded time series |
| VIC / CLM / mHM / Livneh or equivalent LSM | `QDRAI` subsurface runoff | mm/s | Model timestep or gridded time series |
| Water-demand module or ABM | `totalDemand` / BMI `demand_flux` | m3/s | Monthly input, padded to nearest past time |

| Downstream consumer | Variable exchanged | Unit | Temporal resolution |
|---------------------|-------------------|------|---------------------|
| Gauge scoring / observed discharge comparison | `RIVER_DISCHARGE_OVER_LAND_LIQ` | m3/s | Output averaging window, commonly daily or monthly |
| Managed-water analysis | `WRM_SUPPLY`, `WRM_DEFICIT`, `WRM_STORAGE` | m3/s or m3 | Output averaging window |

## 11. Validated Results

**Sourced from `knowledge_infrastructure.yaml` and `docs/validation_convention.yaml`; do
not loosen, transfer, or invent thresholds. Null convention bands are written as
"no cited threshold".**

| Source field | Value |
|--------------|-------|
| Validation tier | `validated` |
| Manifest tier justification | measured: NSE=0.837, KGE=0.874, R=0.919, 2 scorecard(s) |
| Manifest metrics | best_nse=0.8367, best_kge=0.8741, best_r=0.9186 |
| Rank-1 judged output | `RIVER_DISCHARGE_OVER_LAND_LIQ` |

### Performance Metrics - judged against the field's bar, not intuition

| Dag variable | Metric | Direction | Convention band (cited) | Achieved value in sourced KI files |
|--------------|--------|-----------|--------------------------|-----------------------------------|
| `RIVER_DISCHARGE_OVER_LAND_LIQ` | nse | maximize | very_good >= 0.75 (`moriasi2007`, `swat_gomti2019`); good >= 0.65 (`moriasi2007`, `swat_gomti2019`); satisfactory >= 0.5 (`moriasi2007`, `swat_gomti2019`) | best_nse=0.8367 in `knowledge_infrastructure.yaml` |
| `RIVER_DISCHARGE_OVER_LAND_LIQ` | pbias | zero_centered | very_good <= 10 absolute percent bias (`moriasi2007`, `swat_gomti2019`); good <= 15 absolute percent bias (`moriasi2007`, `swat_gomti2019`); satisfactory <= 25 absolute percent bias (`moriasi2007`, `swat_gomti2019`) | not supplied by `knowledge_infrastructure.yaml` |
| `RIVER_DISCHARGE_OVER_LAND_LIQ` | nse | maximize | very_good >= 0.75 (`moriasi2007`, `swat_gomti2019`); good >= 0.65 (`moriasi2007`, `swat_gomti2019`); satisfactory >= 0.5 (`moriasi2007`, `swat_gomti2019`) | same convention appears for both point and spatial time-series shapes |
| `RIVER_DISCHARGE_OVER_LAND_LIQ` | pbias | zero_centered | very_good <= 10 absolute percent bias (`moriasi2007`, `swat_gomti2019`); good <= 15 absolute percent bias (`moriasi2007`, `swat_gomti2019`); satisfactory <= 25 absolute percent bias (`moriasi2007`, `swat_gomti2019`) | same convention appears for both point and spatial time-series shapes |
| `WRM_SUPPLY` | pbias | zero_centered | no cited threshold | not supplied by `knowledge_infrastructure.yaml` |

The rank-1 NSE value `best_nse=0.8367` exceeds the cited very_good band
(`moriasi2007`, `swat_gomti2019`) for
`RIVER_DISCHARGE_OVER_LAND_LIQ`. No achieved PBIAS value is stated in the manifest, so
do not infer one. For `WRM_SUPPLY`, the convention explicitly has no cited threshold, so
do not transfer the streamflow PBIAS bands (`moriasi2007`, `swat_gomti2019`).

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Runoff forcing | Upstream LSM runoff converted by `tools/convert_runoff_forcing.py` | Pipeline-supported | MOSART cannot synthesize runoff |
| Grid topology | D8 triplet converted by `tools/build_mosart_grid.py` | Pipeline-supported | Gauge cell must be a through-cell for interior gauges |
| Demand | Water-demand NetCDF or ABM | Optional / input-dependent | Active when water management is enabled |
| Reservoirs | GRanD parameters and schedules | Optional / input-dependent | Units must be MCM and km2 at input |
| Output parsing | `tools/parse_mosart_output.py` | Pipeline-supported | Score rank-1 discharge at the recorded scoring cell |

## 12. Parameter Selection by Region

MOSART-WM parameterization is dominated by gridded topology, channel geometry, slopes,
Manning roughness, reservoir geometry, and externally supplied runoff. No separate
region-specific parameter table is projected in this KI; start from documented MOSART
defaults and the prepared domain grid, then validate `RIVER_DISCHARGE_OVER_LAND_LIQ`
against the cited convention bars above.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: This model takes runoff from upstream hydrological models (VIC, mHM, etc.) as input.
See `data_ki/ObservedQ/SKILL.md` for observed discharge validation data.

### REAL-CASE APPLICABILITY — read before attempting a new gauge/period (verified 2026-06-21, MOSART @ HYDAT 05BB001)

MOSART-WM is a **routing model, not a rainfall-runoff model**. It cannot generate
discharge from meteorological forcing alone — it requires a **gridded runoff field
(QOVER/QDRAI, mm/s) from an upstream land-surface model** (VIC/CLM/Livneh) on the
SAME grid as the domain file, covering the SAME dates as the obs comparison period.
So the improve-mode case instruction "prepare THIS basin's forcing from CMFD/ERA5-Land"
is a CATEGORY ERROR for MOSART: its "forcing" is runoff, not meteorology. There is no
gridded-runoff product on the server (no ERA5-Land/GSWP3/runoff in the dataset index);
the only runoff source is to run the VIC KI over the basin first.

### CHINA BASIN REAL-CASE — SOLVED via VIC->MOSART (verified 2026-07-11, MOSART @ 唐乃亥/Tangnaihai, upper Yellow R)

The two blockers of the Bengbu/Bow runs are BOTH now closable:
1. **Missing grid-builder → FIXED.** New KI tool `tools/build_mosart_grid.py` converts a
   VALIDATED D8 flow-direction network (the ArcASCII `<STA>_direc.txt` + `<STA>_xmask.txt`
   channel length + `<STA>_frac.txt` that the VIC/Lohmann routing KI already builds &
   validates) into a full mosartwmpy domain grid (all 20 REQUIRED_VARIABLES). Because the
   topology is inherited from a routing network independently confirmed at the gauge
   (VIC+Lohmann NSE 0.63 at Tangnaihai), the main channel PROVABLY reaches the gauge — the
   exact property the Bengbu synthetic D8 lacked. For Tangnaihai it yields 251 cells,
   123,042 km² (+0.9% vs published 121,972), and a SINGLE outlet AT the gauge cell.
   `convert_grid_parameters.py --validate-only` → 0 errors, 0 warnings.
2. **Runoff exists once VIC is run.** All VIC Tangnaihai inputs (soil/veg/forcing/global
   param) persist in `outputs/tangnaihai/vic_temp/`; re-running `vic_classic.exe -g
   global_param_tangnaihai.txt` (~251 cells, minutes) regenerates per-cell flux, which the
   runner grids and feeds to `convert_runoff_forcing.py` (cols 16=OUT_RUNOFF, 17=OUT_BASEFLOW,
   mm/day, skiprows=3).

**GAUGE-CELL OUTFLOW TRAP (critical, cost the Bengbu run its number):** a cell with
`dnID == -1` is treated by mosartwmpy as the terminal OCEAN outlet, and its
`RIVER_DISCHARGE_OVER_LAND_LIQ` is **0** — the basin discharge then appears in the cell
one step UPSTREAM. An interior gauge (Tangnaihai is NOT a river mouth) must therefore be a
THROUGH-cell: `build_mosart_grid.py` redirects the primary outlet to a steepest-descent
inactive neighbour (new frac=0 sink) so the gauge cell's channel_outflow == basin
discharge, and records the cell to score in grid attrs `scoring_lat`/`scoring_lon`. Score
`parse_mosart_output.py --mode point` at THAT cell, not at the nominal lat/lon.

Full pipeline & scoring live in `models/MOSART/run_and_score.py` (resumable, detached):
VIC flux → grid runoff (convert_runoff_forcing) → build_mosart_grid → run_mosartwmpy
(2005-2016, 3h step, WM disabled — Longyangxia reservoir is DOWNSTREAM of Tangnaihai so the
gauge is quasi-natural) → parse+score. Spin-up 2005-06; cal 2007-11 / val 2012-16.

### BENGBU / HUAI follow-up (verified 2026-06-22, MOSART @ gauge 51080) — runoff EXISTS but topology still blocks

Unlike Bow@Banff, gridded VIC 5.1.0 runoff DOES exist for the Huai basin
(`KISSPATH_OUTPUTS/bengbu_1980_1990_cama/cama_input/bengbu_runoff_1d_{Y}.nc`,
0.25°, 16×24, combined `Runoff` mm/day, 1980-1990). The full real-binary chain runs:
`convert_runoff_forcing` (combined-runoff split + lat-orient fix, see below) →
`convert_grid_parameters` (validate) → `run_mosartwmpy` (1980-1990, ~30 min, 132 monthly
files) → `parse_mosart_output`. **But the result is still structurally invalid:**
- The only Bengbu grid available is the SYNTHETIC one from the dissection
  (`auto_dissect*/_work/MOSART/bengbu_mosart_grid.nc`); the KI has no real delineation tool.
  Its synthetic D8 over-accumulates to 242,644 km² (true basin 121,330) and routes the main
  channel to cell (33.375,117.625) — NOT the Bengbu gauge.
- Real-binary discharge at the true gauge cell (32.875,117.375) is **exactly 0** for the
  whole run (gauge is off the synthetic channel). The subdomain "32.94,117.35" extracts a
  DISCONNECTED sub-basin whose best outlet peaks ~28 m³/s.
- Best-available-outlet metrics vs obs 51080 (1980-1990, point_time_series):
  **NSE −0.39, r 0.46, KGE −0.38, PBIAS −91%** (sim mean 85 vs obs 942 m³/s, ~91% low).
- The dissection's reported "NSE 0.286 / r 0.828 / PBIAS +44" came from a HAND-CODED routing
  surrogate (`bengbu_validate_fast.py`, a custom Python accumulation loop), NOT mosartwmpy —
  it is NOT reproducible with the real binary. Treat that number as non-KDT-compliant.
- Conclusion: the missing-basin-delineation block applies to China basins too, even when
  upstream VIC runoff is present. To get a valid Bengbu discharge you need a CORRECT routing
  grid (MERIT-Hydro topology conditioned on the Huai network), which the KI cannot build.

`convert_runoff_forcing.py` upgrades made 2026-06-22 (now in canonical KI):
- `--total-var <name> --surface-fraction <f>`: split a single COMBINED total-runoff field
  (e.g. VIC-for-CaMa `Runoff`) into QOVER/QDRAI (default 60/40) when no separate
  surface/subsurface vars exist.
- Output is now sorted to ASCENDING lat/lon. mosartwmpy's `load_runoff` index-aligns runoff
  to the grid by flattening (NOT by coordinate), so runoff orientation MUST match the
  ascending-lat grid or all flow lands on the wrong cells.

What the KI tools do and do NOT do:
- `convert_runoff_forcing.py` only **reformats/unit-converts an EXISTING gridded runoff
  NetCDF**. It does NOT run an LSM or synthesize runoff. There is no runoff-generation tool.
- `convert_grid_parameters.py` only **validates/fills an EXISTING grid domain NetCDF**
  (despite the `--source-type merit` flag, it contains NO MERIT-Hydro topology-building
  logic — it just opens the input and checks fields). There is no basin-delineation /
  grid-building tool.

Consequence for a standalone gauge real-case (e.g. HYDAT 05BB001 Bow R. at Banff, 2006–2015):
- The bundled NLDAS 1/8° CONUS grid (`input/domains/mosart_conus_nldas_grid.nc`) DOES
  cover Bow at Banff (cell 51.1875,-115.5625; subdomain extraction works). The binary +
  full chain (run_mosartwmpy → parse_mosart_output) run end-to-end.
- BUT the only runoff that ships is `runoff_1981_05.nc` (May 1981 CONUS). NO gridded runoff
  exists on the server for North America 2006–2015 (all VIC outputs are China basins), and
  the KI provides no way to make it. **The requested 2006–2015 discharge comparison is
  therefore structurally uncomputable** without first running VIC/CLM for that basin+period.
- Best-achievable demo (May-1981 cold start, Bow subdomain): freshet onset timing is
  captured (r≈0.80 vs HYDAT daily) but magnitude is ~95% low (NSE≈−1.0) — dominated by
  cold-start channel filling + only-one-month forcing. Not a calibratable real-case.

To run a genuine new-basin real-case you must FIRST produce gridded runoff for the period
(run the VIC KI over the basin), then route it here. Treat MOSART as the second stage of a
VIC→MOSART pipeline, never standalone.

### DOMAIN-CONSISTENCY TRAP — the VIC domain and the MOSART domain must be the SAME cells

(Found 2026-07-19 at Wangjiaba; it silently invalidated the 2026-07-11 run.)

The MOSART domain comes from the delineated triplet; the VIC domain comes from a
SHAPEFILE fed to the VIC KI's `s1_grid/make_basin_grid_nc.py` via `VIC_BASIN_SHP`.
Nothing forced them to agree, so it was possible — and it happened — to route a
correct-looking network over a domain covering only **52% of the published basin
area** (Wangjiaba: 15,959 of 30,600 km²; the whole northern Hong/Ru headwater arm up
to ~34°N was outside the ArcASCII bbox). The run still completed, the network was
internally coherent, and it scored NSE 0.72 — the truncation showed up only as a
persistent low bias (PBIAS −24%). **A plausible NSE does not prove the domain is
complete.** Guard it with BOTH of:

1. `frac_to_basin_shp.py` — derive the VIC shapefile FROM the delineated frac, so
   the two stages cannot disagree by construction. (It insets each cell box by 2% of
   the cell size, because `make_basin_grid_nc.py` uses `USE_INTERSECTS=True` and the
   exact cell union would otherwise pull in a one-cell halo of edge-touching
   neighbours.)
2. `build_mosart_grid.py --expected-area-km2 <published> [--area-tol 0.10]` — hard
   gate: the frac-weighted `areaTotal` AT THE SCORING CELL must match the published
   basin area. Exits 1 and writes no NetCDF on failure. The reference standard is
   Tangnaihai's +0.9%; the truncated Wangjiaba domain trips it at −47.84%. The gate
   deliberately does NOT fall back to `areaTotal[active].max()` when no scoring cell
   was identified — it hard-fails, because that fallback could pass a network whose
   main channel never reaches the gauge.

Also honour `--min-bbox w,s,e,n` on `delineate_d8_from_merit.py` when you need the
emitted coarse domain to cover a known extent (expand-only; applied before
nrows/ncols). MERIT tiles are pixel-CENTRE-aligned to integer degrees (half-pixel
offset) — honour each tile's own transform rather than assuming corner alignment.

NOTE: the HYDAT obs at `KISSPATH_DATA/Hydat_sqlite3_20260116/Hydat.sqlite3` was ABSENT on
2026-06-21 (disk4 empty). Source of record was `KISSPATH_DATA/数据/National Water Data
Archive HYDAT.zip` → extract `Hydat.mdb`, read via `mdb-export <mdb> DLY_FLOWS` (no sqlite3
CLI installed; use `mdb-tools`).


## Overview

This knowledge infrastructure enables autonomous river routing and water management simulation using mosartwmpy. The 7 validated tools replace manual data preparation with a Python pipeline that integrates directly with HydroCraft's forcing, land surface, and reservoir infrastructure.

**What MOSART-WM does**: Grid-based river routing and water management model. Simulates:
- Hillslope overland flow (Manning's equation on hillslope surface)
- Subnetwork/tributary channel routing (Manning's equation in tributaries)
- Main channel routing (kinematic wave approximation)
- Reservoir regulation (storage-based release rules)
- ISTARF improved reservoir scheduling (statistical target release functions)
- Irrigation water supply/demand allocation (iterative dam-to-grid supply)
- Water balance tracking (storage, deficit, supply across all grid cells)
- Flood routing (excess storage returned to ocean)

**Key difference from other HydroCraft models**: MOSART-WM operates on a regular lat/lon grid (e.g., NLDAS 1/8°) with a full river network topology. It implements the Basic Model Interface (BMI) for coupling with CLM, VIC, or other land surface models. It routes runoff from hillslopes through tributaries and main channels to ocean outlets, with integrated reservoir operations.

**Three-tier routing**: Hillslope → Subnetwork (tributaries) → Main Channel. Each tier has its own Manning's coefficient, slope, width, and routing time step determined by CFL-like stability criteria.

---

## Installation

### From PyPI

```bash
pip install mosartwmpy setuptools     # setuptools is REQUIRED, see trap below
```

**PYTHON 3.12 TRAP (verified 2026-07-19, cost a full run's environment):**
`pip install mosartwmpy` ALONE leaves the package unimportable on Python 3.12.
`mosartwmpy/config/config.py` line 1 does `import pkg_resources`, which ships with
`setuptools` — and `setuptools` is no longer installed by default in a 3.12 venv
(PEP 632). The failure is `ModuleNotFoundError: No module named 'pkg_resources'`
raised from `import mosartwmpy`, i.e. it looks like a broken install rather than a
missing sibling package. Always `pip install setuptools` alongside. Pin
`setuptools<81` to silence the deprecation warning (81+ removes `pkg_resources`
entirely and will break mosartwmpy 0.6.2 outright).

Working canonical environment on this server:
`KISSPATH_KI_ROOT/MOSART/venv/bin/python`
(Python 3.12, mosartwmpy 0.6.2 + setuptools<81). NOTE `_work/MOSART/venv` — cited by
older run notes — is WIPE-PRONE and was already destroyed once; do not depend on it.
`/usr/bin/python3` has numpy/pandas/xarray/rasterio/geopandas/ki_tools_common and is
fine for every KI tool EXCEPT `run_mosartwmpy.py` (which needs the venv).

### From conda-forge

```bash
conda install -c conda-forge mosartwmpy
```

### From source

```bash
git clone https://github.com/IMMM-SFA/mosartwmpy.git
cd mosartwmpy
pip install -e .
```

### Python requirements

```
Python 3.9 - 3.12
bmipy>=2.0, numba>=0.53.1, numpy>=1.20.3,<2.0
xarray>=0.19.0, netCDF4>=1.5.7, pandas>=1.3.4
dask[complete]>=2021.10.0, pyarrow>=6.0.0
python-benedict>=0.24.3, click>=8.0.1
matplotlib>=3.4.3, rioxarray>=0.8.0, psutil>=5.8.0
regex>=2021.10.23, pathvalidate>=2.5.0, h5netcdf>=0.11.0
pyomo>=6.2, geopandas>=0.10.2
```

### Test data download

```bash
python -m mosartwmpy.download
# Select option 1 for "tutorial" (May 1981 CONUS subset)
# Select option 2 for "sample_input" (1980-1985 full dataset)
# Select option 3 for "validation" (1981-1982 reference results)
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0a | Delineation | `delineate_d8_from_merit.py` | MERIT-Hydro D8 → Lohmann ArcASCII direc/xmask/frac at the gauge |
| 0b | LSM domain bridge | `frac_to_basin_shp.py` | delineated frac → basin shapefile for the VIC KI's `VIC_BASIN_SHP` |
| 1 | Runoff forcing | `convert_runoff_forcing.py` | CLM/VIC/Livneh runoff to mosartwmpy NetCDF (mm/s) |
| 2 | Grid preparation | `build_mosart_grid.py` (+ `convert_grid_parameters.py --validate-only`) | triplet → full 20-variable domain grid, with the `--expected-area-km2` gate |
| 3 | Demand preparation | (manual or ABM) | Water demand NetCDF (m3/s totalDemand) |
| 4 | Reservoir setup | `create_grand_parameters` (CLI) | GRanD reservoir parameters + ISTARF coefficients |
| 5 | Configuration | config.yaml | Simulation name, dates, paths, WM toggle |
| 6 | Execution | `run_mosartwmpy.py` | BMI initialize → update_until → finalize |
| 7 | Output parsing | `parse_mosart_output.py` | Extract discharge, storage, supply to CSV |

### Stage Dependencies

```
Stages 1, 2, 3, 4 can run in parallel (independent data prep)
Stage 5 depends on 1-4 (paths must exist)
Stage 6 depends on 5
Stage 7 depends on 6
```

---

## Input Specification

### Grid Domain File (NetCDF)

| Variable | Field Name | Units | Description |
|----------|-----------|-------|-------------|
| Cell ID | `ID` | - | Unique integer identifier |
| Downstream ID | `dnID` | - | ID of downstream cell (-1 for outlet) |
| Flow direction | `fdir` | - | D8 flow direction code |
| Latitude | `lat` | degrees_north | Cell center latitude |
| Longitude | `lon` | degrees_east | Cell center longitude |
| Local drainage area | `area` | m² | Grid cell drainage area |
| Total upstream area (multi) | `areaTotal` | m² | Multi-flow-direction upstream area |
| Total upstream area (single) | `areaTotal2` | m² | Single-flow-direction upstream area |
| Drainage fraction | `frac` | 0-1 | Fraction of cell draining to outlet |
| Land fraction | `frac` | 0-1 | Land fraction of grid cell |
| Drainage density | `gxr` | m⁻¹ | Channel density per unit area |
| Hillslope slope | `hslp` | m/m | Mean topographic slope |
| Hillslope Manning's n | `nh` | s/m^(1/3) | Overland flow roughness |
| Subnetwork slope | `tslp` | m/m | Mean tributary slope |
| Subnetwork width | `twid` | m | Bankfull tributary width |
| Subnetwork Manning's n | `nt` | s/m^(1/3) | Tributary roughness |
| Channel length | `rlen` | m | Main channel length |
| Channel slope | `rslp` | m/m | Main channel slope |
| Channel width | `rwid` | m | Bankfull main channel width |
| Floodplain width | `rwid0` | m | Floodplain width linked to channel |
| Channel depth | `rdep` | m | Bankfull main channel depth |
| Channel Manning's n | `nr` | s/m^(1/3) | Main channel roughness |

### Runoff Forcing File (NetCDF)

| Variable | Field Name | Units | Description |
|----------|-----------|-------|-------------|
| Surface runoff | `QOVER` | mm/s | Surface runoff flux |
| Subsurface runoff | `QDRAI` | mm/s | Subsurface drainage flux |
| Wetland runoff | (optional) | mm/s | Glacier/wetland/lake runoff |
| Time | `time` | datetime | Time coordinate |
| Latitude | `lat` | degrees_north | Grid latitudes |
| Longitude | `lon` | degrees_east | Grid longitudes |

**CRITICAL UNIT TRAP**: Runoff is read as mm/s. Internally converted to m³/s via:
```
Q_m3s = 0.001 × land_fraction × area_m2 × Q_mm_s
```
Then to m/s for hillslope routing:
```
Q_m_s = Q_m3s / area_m2
```

### Demand File (NetCDF)

| Variable | Field Name | Units | Description |
|----------|-----------|-------|-------------|
| Total demand | `totalDemand` | m³/s | Grid cell water demand rate |
| Time | `time` | datetime | Monthly time coordinate |

### Reservoir Files

| File | Format | Key Fields |
|------|--------|------------|
| `reservoirs.nc` | NetCDF | GRAND_ID, GRID_CELL_INDEX, CAP_MCM (million m³), AREA_SKM (km²), DAM_HGT_M |
| `dependency_database.parquet` | Parquet | DEPENDENT_CELL_INDEX, GRAND_ID, RESERVOIR_CELL_INDEX |
| `mean_monthly_reservoir_flow.parquet` | Parquet | GRAND_ID, MONTH_INDEX, MEAN_FLOW (m³/s) |
| `mean_monthly_reservoir_demand.parquet` | Parquet | GRAND_ID, MONTH_INDEX, MEAN_DEMAND (m³/s) |

**CRITICAL UNIT TRAP**: Reservoir storage capacity in input is **million m³** (CAP_MCM). Surface area is **km²** (AREA_SKM). These are converted internally.

---

## Output Specification

### Default Output (NetCDF, monthly files, daily averages)

| Variable | Name in File | Units | Description |
|----------|-------------|-------|-------------|
| Surface runoff | `QSUR_LIQ` | m³/s | Hillslope surface runoff |
| Subsurface runoff | `QSUB_LIQ` | m³/s | Hillslope subsurface runoff |
| Total storage | `STORAGE_LIQ` | m³ | Total routing storage |
| River discharge | `RIVER_DISCHARGE_OVER_LAND_LIQ` | m³/s | Main channel outflow |
| Channel inflow | `channel_inflow` | m³/s | Upstream inflow to grid cell |
| Channel outflow | `channel_outflow` | m³/s | Outflow from grid cell |
| Reservoir storage | `WRM_STORAGE` | m³ | Water stored in reservoir |
| Water supply | `WRM_SUPPLY` | m³/s | Supply delivered to grid cell |
| Water demand | `WRM_DEMAND` | m³/s | Demand requested by grid cell |
| Unmet demand | `WRM_DEFICIT` | m³ | Cumulative unmet demand |

### BMI Output Variables (programmatic access)

| Standard Name | State Variable | Units |
|---------------|---------------|-------|
| `outgoing_water_volume_transport_along_river_channel` | `runoff_land` | m³/s |
| `incoming_water_volume_transport_along_river_channel` | `channel_inflow_upstream` | m³/s |
| `surface_water_amount` | `storage` | m³ |
| `reservoir_water_amount` | `reservoir_storage` | m³ |
| `supply_water_amount` | `grid_cell_supply` | m³ |
| `deficit_water_amount` | `grid_cell_deficit` | m³ |

### BMI Input Variables

| Standard Name | State Variable | Units |
|---------------|---------------|-------|
| `surface_runoff_flux` | `hillslope_surface_runoff` | mm/s |
| `subsurface_runoff_flux` | `hillslope_subsurface_runoff` | mm/s |
| `demand_flux` | `grid_cell_demand_rate` | m³/s |

---

## Unit Trap Table

| Quantity | External Unit | Internal Unit | Conversion | Where |
|----------|--------------|---------------|------------|-------|
| Runoff (input) | mm/s | m³/s → m/s | ×0.001×frac×area, then ÷area | `load_runoff()`, `_prepare()` |
| Runoff (output) | m/s | m³/s | ×area | `_finalize()` |
| Demand | m³/s | m³ (per substep) | ×Δt_subcycle | `_subcycle()` |
| Supply | m³ (accumulated) | m³/s | ÷timestep | `_finalize()` |
| Reservoir capacity | million m³ | m³ | ×1e6 (in grid loading) | `load_reservoirs()` |
| Reservoir area | km² | m² | ×1e6 (in grid loading) | `load_reservoirs()` |
| Reservoir evaporation | mm/s | m³ | ×1e6×Δt×area_km2 | `regulation()` |
| Channel storage | m³ | m³ | direct | internal |
| Hillslope storage | m | m³ | ×area×frac | `_finalize()` |
| Timestep | seconds | seconds | 10800 default (3 hours) | config |
| Subcycle Δt | seconds | seconds | timestep/subcycles | computed |
| Routing Δt | seconds | seconds | subcycle_Δt/routing_iterations | computed |

---

## Configuration Reference (config.yaml)

### Key Parameters

| Parameter | Default | Units | Description |
|-----------|---------|-------|-------------|
| `simulation.timestep` | 10800 | s | Main timestep (3 hours) |
| `simulation.subcycles` | 3 | - | Number of subcycles per timestep |
| `simulation.routing_iterations` | 5 | - | Routing iterations per subcycle |
| `simulation.output_resolution` | 86400 | s | Output averaging window (daily) |
| `simulation.output_file_frequency` | monthly | - | New file frequency |
| `water_management.enabled` | true | - | Toggle reservoir/demand system |
| `water_management.reservoirs.enable_istarf` | true | - | Toggle ISTARF release rules |
| `grid.subdomain` | null | - | List of lat,lon pairs to subset basins |
| `grid.unmask_output` | true | - | Include inactive cells in output |

### Internal Constants (Parameters class)

| Parameter | Value | Units | Purpose |
|-----------|-------|-------|---------|
| `tiny_value` | 1e-14 | - | Numerical floor |
| `radius_earth` | 6.37122e6 | m | Area computation |
| `hillslope_minimum` | 0.005 | m/m | Replace zero hillslope |
| `subnetwork_slope_minimum` | 0.0001 | m/m | Replace zero tributary slope |
| `channel_slope_minimum` | 0.0001 | m/m | Replace zero channel slope |
| `flood_threshold` | 1e36 | m³ | Flood excess threshold |
| `river_depth_minimum` | 1e-4 | m | Minimum river depth |
| `irrigation_extraction_parameter` | 0.1 | m | Minimum depth for extraction |
| `irrigation_extraction_maximum_fraction` | 0.5 | - | Max fraction extractable |
| `reservoir_flow_volume_ratio` | 0.9 | - | Flow volume available to supply |
| `kinematic_wave_parameter` | 1e6 | - | Kinematic wave condition |

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_runoff_forcing` | s1 | `tools/convert_runoff_forcing.py` | ~200 | VIC/CLM/generic runoff to mosartwmpy NetCDF |
| `build_mosart_grid` | s2 | `tools/build_mosart_grid.py` | ~290 | **Build** domain grid from a validated D8 network (direc/xmask/frac) — the missing grid-builder; sets interior gauge as through-cell + records scoring cell |
| `convert_grid_parameters` | s2 | `tools/convert_grid_parameters.py` | ~220 | **Validate/fill** an EXISTING grid domain NetCDF (NOT a builder; `--source-type merit` is a no-op — use `build_mosart_grid` to build) |
| `run_mosartwmpy` | s6 | `tools/run_mosartwmpy.py` | ~180 | Execute model via BMI with validation |
| `parse_mosart_output` | s7 | `tools/parse_mosart_output.py` | ~200 | Extract time series from output NetCDF to CSV |

---

## Routing Physics Summary

### Hillslope Routing
- Manning's equation: `v = (depth^(2/3)) × (slope^(1/2)) / n`
- Overland flow: `q = -depth × velocity × drainage_density`
- Storage update: `S(t+Δt) = S(t) + Δt × (runoff_surface + overland_flow)`
- Lateral inflow to subnetwork: `(subsurface_runoff - overland_flow) × frac × area`

### Subnetwork (Tributary) Routing
- Same Manning's equation with tributary geometry
- Adaptive sub-timesteps based on CFL condition (phi parameter)
- Discharge: `q = -velocity × cross_section_area`
- Feeds into main channel as lateral flow

### Main Channel Routing
- Kinematic wave approximation
- Condition: `drainage_area / (width × length) ≤ 1e6`
- If kinematic: `outflow = -velocity × cross_section_area`
- If not kinematic: `outflow = -(inflow + lateral_flow)`
- Channel cross-section: rectangular below bankfull, trapezoidal floodplain above

### Reservoir Regulation
- Storage balance: `S(t+Δt) = S(t) + inflow - outflow - evaporation`
- If excess: release all overflow, fill to capacity
- If insufficient: reduce release to match inflow
- ISTARF: statistical target release based on storage level and month

### Water Supply Allocation (Iterative)
1. Compute flow_volume at each dam (90% of channel outflow)
2. Aggregate demand from all dependent grid cells
3. Compute demand_fraction = available / total_demand
4. Three cases: full supply (fraction ≥ 1), prorated (sum ≥ 1), partial
5. Residual flow returned to channel

---

## Execution Quick Start

```python
from mosartwmpy import Model

model = Model()
model.initialize('config.yaml')

# Run full simulation
model.update_until(model.get_end_time())

# Or step one timestep at a time
model.update()

# Access output via BMI
discharge = model.get_value_ptr('outgoing_water_volume_transport_along_river_channel')
storage = model.get_value_ptr('surface_water_amount')
supply = model.get_value_ptr('supply_water_amount')

model.finalize()
```

---

## Validation

```bash
# Download validation data
python -m mosartwmpy.download  # Select option 3

# Run simulation covering 1981-1982
# Then validate with NMAE comparison
python -m mosartwmpy.validate
```

The validation tool computes Normalized Mean Absolute Error (NMAE) for:
- `STORAGE_LIQ` — total routing storage
- `RIVER_DISCHARGE_OVER_LAND_LIQ` — river discharge
- `WRM_STORAGE` — reservoir storage
- `WRM_SUPPLY` — water supply

NMAE should be 0% if code is unmodified from reference.

---

## Common Pitfalls

1. **Runoff unit confusion**: Input is mm/s, but routing works in m/s and m³/s internally
2. **Reservoir capacity units**: Input CAP_MCM is million m³, not m³
3. **Reservoir area units**: Input AREA_SKM is km², not m²
4. **Timestep stability**: If subcycles too few for large basins, CFL violation causes instability
5. **Multi-file paths**: Use `{Y}`, `{M}`, `{D}` placeholders for year/month/day in paths
6. **Numpy version**: Requires numpy<2.0 due to numba compatibility
7. **Grid orientation**: Lat/lon must match between grid, runoff, and demand files exactly
8. **Subdomain coordinates**: Each pair finds the basin containing that point
9. **Demand timing**: Demand is read monthly, padded to nearest past time
10. **Restart files**: Date parsed from filename pattern `YYYY_MM_DD`
