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
| to run the pipeline stages | `tools/` (12 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (8 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (15 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (14 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/s1_installation/verify_pywr_installation.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_installation/verify_pywr_installation.py --help` |
| `tools/s2_dam_inventory/find_dams_in_basin.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_dam_inventory/find_dams_in_basin.py --help` |
| `tools/s3_reservoir_properties/build_reservoir_properties.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_reservoir_properties/build_reservoir_properties.py --help` |
| `tools/s4_inflow/convert_obs_to_inflow.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_inflow/convert_obs_to_inflow.py --help` |
| `tools/s4_inflow/convert_vic_to_inflow.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_inflow/convert_vic_to_inflow.py --help` |
| `tools/s5_operating_rules/create_operating_rules.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_operating_rules/create_operating_rules.py --help` |
| `tools/s6_demands/create_demand_nodes.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_demands/create_demand_nodes.py --help` |
| `tools/s7_assembly/assemble_pywr_model.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_assembly/assemble_pywr_model.py --help` |
| `tools/s8_execution/check_overtopping.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_execution/check_overtopping.py --help` |
| `tools/s8_execution/inject_releases_to_cama.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_execution/inject_releases_to_cama.py --help` |
| `tools/s8_execution/plot_reservoir_operations.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_execution/plot_reservoir_operations.py --help` |
| `tools/s8_execution/run_pywr.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_execution/run_pywr.py --help` |

*12 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

## Forcing Data

Pywr requires time-varying forcing input files that drive the water allocation model:

| Forcing Variable | Source | Format | Units |
|-----------------|--------|--------|-------|
| Reservoir inflow | VIC runoff+baseflow or observed discharge | CSV timeseries | m3/s |
| Irrigation demand | DSSAT crop water stress or prescribed schedule | JSON parameter | m3/s |
| Municipal/industrial demand | Prescribed or population-scaled | JSON parameter | m3/s |
| Precipitation (optional) | For direct-rainfall reservoirs | CSV timeseries | mm/day |

All forcing input files must cover the simulation period with daily timestep. Missing days cause Pywr to raise `DataFrameKeysError`.

## Configuration

Pywr models are configured through a single JSON model file assembled by `assemble_pywr_model.py`. Key configuration settings:

| Setting | Location | Default | Notes |
|---------|----------|---------|-------|
| Simulation period | `metadata.minimum_version` + `timestepper` | — | `start`, `end`, `timestep` (days) |
| Solver | `solver.name` | `glpk` | Only GLPK supported in this KI |
| Node costs | Each node's `cost` parameter | varies | More negative = higher priority |
| Control curve | `parameters` section | — | Monthly target storage levels (fraction) |
| Demand profiles | `parameters` section | — | `monthlyprofile` or `dataframe` type |

The JSON config file is the only configuration needed — no `.ini`, `.cfg`, or namelist files.

## Data Preparation

### Input data

**Input Source**: Pywr takes inflow time series from upstream models (VIC) or observations.
- `convert_vic_to_inflow.py` — Converts VIC/CaMa-Flood discharge to Pywr inflow DataFrame
- `convert_obs_to_inflow.py` — Converts observed discharge to Pywr inflow format
- `find_dams_in_basin.py` — Finds dams from GRanD database within basin
- `build_reservoir_properties.py` — Builds reservoir properties (capacity, area, elevation) from GRanD/HydroLAKES

**Data Validation Reference**: See `data_ki/GRanD/SKILL.md` for dam/reservoir database documentation.
See `data_ki/HydroLAKES/SKILL.md` for lake morphometry documentation.

---

# Pywr Knowledge Infrastructure — Agent Entry Point

**Package**: `pywr-knowledge-infrastructure` v1.0.0
**Model**: Pywr 1.30.0 (Python Water Resources Framework)
**Domain**: Reservoir operations, water resources management, flood control, water supply
**Role in HydroCraft**: Fills the reservoir operations gap — couples with VIC (inflow), CaMa-Flood (regulated routing), DSSAT (irrigation demand), DLBreach (dam-break trigger)

---

## What This Enables

An AI agent can autonomously:
1. Find dams within any basin using the GRanD global database (7,320 dams)
2. Build reservoir physical properties from GRanD data (capacity, area-volume, dead storage)
3. Convert VIC model output to reservoir inflow timeseries
4. Generate operating rules (flood control, irrigation, hydropower) with regional flood seasons
5. Assemble and run a complete Pywr water allocation model
6. Inject regulated releases back into CaMa-Flood for downstream routing
7. Detect overtopping events and trigger DLBreach dam-break analysis

## Quick Reference

| Component | What | Where |
|-----------|------|-------|
| **Python package** | `pywr` 1.30.0 | `KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3` |
| **Solver** | GLPK (GNU Linear Programming Kit) | System library |
| **Dam database** | GRanD_allocated.csv (7,320 dams) | `model/cmf_v420_pkg/map/data/GRanD_allocated.csv` |
| **Input format** | JSON model file + CSV timeseries | Generated by assemble_pywr_model.py |
| **VIC results** | Daily flux files | `outputs/{run}/vic_result/` |
| **CaMa results** | Daily discharge NetCDF | `model/cmf_v420_pkg/out/{run}/` |

## Pipeline Overview (8 Stages)

```
S1 Verify Pywr ──> S2 Find Dams ──> S3 Reservoir Properties
                                          │
                                          v
                        S4 VIC->Inflow ──> S5 Operating Rules
                             │                    │
                             v                    │
                        S6 Demands ──────────>  S7 Assemble Model
                                                   │
                                                   v
                                              S8 Run + Plot + CaMa Inject
```

## Output Description

This section restates `dag.yaml`; if this section and `dag.yaml` disagree, `dag.yaml` wins.

**Headline output**: `release_discharge` is the dag's `validation_rank: 1` variable and is the variable this model is judged by.

> `release_discharge` — Total regulated release plus spill leaving a storage node toward downstream. (`m3/s`)

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| `release_discharge` | 1 | `m3/s` | Total regulated release plus spill leaving a storage node toward downstream. |
| `storage_volume` | dag output | see `dag.yaml` | Other dag output listed in the extracted KI facts. |
| `spill_discharge` | dag output | see `dag.yaml` | Other dag output listed in the extracted KI facts. |
| `demand_deficit` | dag output | see `dag.yaml` | Other dag output listed in the extracted KI facts. |
| `supply_reliability` | dag output | see `dag.yaml` | Other dag output listed in the extracted KI facts. |

## Unit Table / Unit Conversion Table

This unit table is sourced from `dag.yaml` for model outputs and from the existing HydroCraft coupling rules in this skill for pipeline conversions.

| Variable or exchange | Source unit | Target/model unit | Conversion |
|----------------------|-------------|-------------------|------------|
| `release_discharge` | Pywr output | `m3/s` | No conversion for the dag headline output. |
| VIC -> Pywr inflow | `mm/day` runoff+baseflow | `m3/s` inflow | `* cell_area_m2 / (1000 * 86400)` |
| Pywr -> CaMa regulated release | `m3/s` release | `mm/day` runoff | `* 86400 / cell_area_m2 * 1000` |
| DSSAT -> Pywr irrigation demand | `mm` irrigation need | `m3/s` demand | `* area_m2 / (1000 * 86400 * efficiency)` |
| GRanD capacity -> Pywr storage | `MCM` | `m3` | `* 1e6` |

## Validated Results

This section restates `docs/validation_convention.yaml`; if this section and `docs/validation_convention.yaml` disagree, `docs/validation_convention.yaml` wins. The field's convention bars below are thresholds for judging outputs, not achieved run metrics.

**Headline validation variable**: `release_discharge`.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band | Citation keys |
|--------------|--------|-----------|-------------------|-----------|----------------|---------------|
| `storage_volume` | `nse` | maximize | `0.5` (`moriasi2007`, `gonzalez2021`) | `0.65` (`moriasi2007`, `gonzalez2021`) | `0.75` (`moriasi2007`, `gonzalez2021`) | `moriasi2007`, `gonzalez2021` |
| `release_discharge` | `nse` | maximize | `0.5` (`moriasi2007`, `shrestha2018`, `hamilton2024`) | `0.65` (`moriasi2007`, `shrestha2018`, `hamilton2024`) | `0.75` (`moriasi2007`, `shrestha2018`, `hamilton2024`) | `moriasi2007`, `shrestha2018`, `hamilton2024` |
| `release_discharge` | `pbias` | zero_centered | `25` (`moriasi2007`, `shrestha2018`) | `15` (`moriasi2007`, `shrestha2018`) | `10` (`moriasi2007`, `shrestha2018`) | `moriasi2007`, `shrestha2018` |
| `spill_discharge` | `nse` | maximize | `0.5` (`moriasi2007`, `shrestha2018`) | `0.65` (`moriasi2007`, `shrestha2018`) | `0.75` (`moriasi2007`, `shrestha2018`) | `moriasi2007`, `shrestha2018` |
| `spill_discharge` | `pbias` | zero_centered | `25` (`moriasi2007`, `shrestha2018`) | `15` (`moriasi2007`, `shrestha2018`) | `10` (`moriasi2007`, `shrestha2018`) | `moriasi2007`, `shrestha2018` |

`demand_deficit` and `supply_reliability` are dag outputs, but no convention bar was provided for them in the extracted KI facts above.

## Tools Reference

| Stage | Tool ID | Script | Purpose |
|-------|---------|--------|---------|
| S1 | `verify_pywr_installation` | `tools/s1_installation/verify_pywr_installation.py` | Check Pywr + GLPK + dependencies |
| S2 | `find_dams_in_basin` | `tools/s2_dam_inventory/find_dams_in_basin.py` | Search GRanD for dams in basin |
| S3 | `build_reservoir_properties` | `tools/s3_reservoir_properties/build_reservoir_properties.py` | Compute volumes, area-volume curve |
| S4 | `convert_vic_to_inflow` | `tools/s4_inflow/convert_vic_to_inflow.py` | VIC runoff+baseflow to m3/s inflow |
| S5 | `create_operating_rules` | `tools/s5_operating_rules/create_operating_rules.py` | Monthly control curves, release rules |
| S6 | `create_demand_nodes` | `tools/s6_demands/create_demand_nodes.py` | Environmental, irrigation, municipal demands |
| S7 | `assemble_pywr_model` | `tools/s7_assembly/assemble_pywr_model.py` | Generate complete Pywr JSON |
| S8 | `run_pywr` | `tools/s8_execution/run_pywr.py` | Run model, extract results |
| S8 | `plot_reservoir_operations` | `tools/s8_execution/plot_reservoir_operations.py` | Multi-panel visualization |
| S8 | `inject_releases_to_cama` | `tools/s8_execution/inject_releases_to_cama.py` | Regulated flow -> CaMa runoff |
| S8 | `check_overtopping` | `tools/s8_execution/check_overtopping.py` | DLBreach trigger evaluation |

## Stage Skill Documents

- [S1 Installation](docs/s1_installation.md)
- [S2 Dam Inventory](docs/s2_dam_inventory.md)
- [S3 Reservoir Properties](docs/s3_reservoir_properties.md)
- [S4 Inflow](docs/s4_inflow.md)
- [S5 Operating Rules](docs/s5_operating_rules.md)
- [S6 Demands](docs/s6_demands.md)
- [S7 Assembly](docs/s7_assembly.md)
- [S8 Execution](docs/s8_execution.md)

## GRanD Dam Database

The Global Reservoir and Dam (GRanD) database is at:
```
model/cmf_v420_pkg/map/data/GRanD_allocated.csv
```

| Stat | Count |
|------|-------|
| Total dams | 7,320 |
| China | 1,571 |
| Huaihe basin | ~68 |
| Has height data | ~90% |
| Has capacity data | 100% |

Key columns: `ID, lat_alloc, lon_alloc, DamName, RiverName, CAP_MCM, DAM_HGT_M, YEAR, ELEV_MASL, area_alloc`

## HydroCraft Coupling Summary

| Coupling | Direction | Unit Conversion | Tool |
|----------|-----------|-----------------|------|
| VIC -> Pywr | runoff+baseflow (mm/day) -> inflow (m3/s) | `* cell_area_m2 / (1000 * 86400)` | `convert_vic_to_inflow` |
| Pywr -> CaMa | release (m3/s) -> runoff (mm/day) | `* 86400 / cell_area_m2 * 1000` | `inject_releases_to_cama` |
| DSSAT -> Pywr | irrigation need (mm) -> demand (m3/s) | `* area_m2 / (1000 * 86400 * efficiency)` | `create_demand_nodes` |
| Pywr -> DLBreach | overtopping (m3) -> breach trigger | excess volume + inflow hydrograph | `check_overtopping` |

## Critical Domain Knowledge

1. **Pywr uses GLPK linear programming.** Every timestep is an independent LP problem that optimally allocates water. The solver minimizes total cost across the network. Negative costs attract water (storage fills); positive costs repel water (storage empties).

2. **Node types are lowercase.** `storage`, `input`, `output`, `link`, `catchment`. Using `Storage` or `Input` causes a parse error.

3. **Parameter types are lowercase.** `constant`, `monthlyprofile`, `dataframe`, `controlcurve`. Using `MonthlyProfile` causes a parse error.

4. **MCM to m3: multiply by 1e6.** GRanD CAP_MCM is in million cubic meters. Pywr volumes are in m3. Forgetting `* 1e6` makes the reservoir 1 million times too small.

5. **VIC mm/day to m3/s requires two conversions.** Divide by 1000 (mm to m) AND divide by 86400 (day to seconds). Missing either produces inflow off by orders of magnitude.

6. **Dataframe CSV paths are resolved relative to model JSON location.** Use absolute paths in the `url` field to avoid FileNotFoundError.

7. **Control curves are essential for realistic operation.** Without a ControlCurveParameter, the LP solver either fills to max or empties to min with no intermediate regulation. The control curve provides monthly target levels.

8. **Environmental flow has highest priority (most negative cost).** In Pywr's cost-based allocation, more negative cost = higher priority. Environmental flow: -1000, municipal: -900, irrigation: -800, industrial: -700, spill: +1000.

9. **Spill path is mandatory.** Every storage node must have a spill/overflow path to avoid InfeasibleError when inflow exceeds demand + storage capacity.

10. **CaMa injection replaces, not adds.** `inject_releases_to_cama.py` replaces the VIC runoff at the dam cell with Pywr release. It does NOT add to existing runoff. This is correct because the release already includes the upstream catchment water.

## Python Environment

Pywr is installed in a separate environment from HydroCraft's main venv:

```bash
# Pywr-capable Python:
KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3

# HydroCraft main venv (does NOT have Pywr):
KISSPATH_PYTHON_ENV/bin/python
```

For tools that need both Pywr AND HydroCraft dependencies (geopandas, xarray, etc.), use the Pywr environment which has all dependencies.

## Error Handling

When errors occur, look up symptoms in `diagnostics/triplets.yaml` (15 triplets). Key triplets:

- **dt_pywr_001**: GLPK not found — install libglpk-dev
- **dt_pywr_005**: Inflow all zeros — wrong VIC flux file format or upstream cells
- **dt_pywr_009**: InfeasibleError — demands exceed supply, add spill path or reduce demands
- **dt_pywr_011**: CaMa injection negative runoff — cell area unit error
- **dt_pywr_014**: MCM to m3 mismatch — forgot `* 1e6` in capacity conversion
- **dt_pywr_015**: VIC mm/day to m3/s conversion — forgot `/1000` or `/86400`

## Quick Start Example

```bash
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
TOOLS="models/Pywr/knowledge_infrastructure/tools"
GRAND="model/cmf_v420_pkg/map/data/GRanD_allocated.csv"

# 1. Verify installation
$PYWR_PYTHON $TOOLS/s1_installation/verify_pywr_installation.py

# 2. Find dams in basin
$PYWR_PYTHON $TOOLS/s2_dam_inventory/find_dams_in_basin.py \
  --shp data/shp/bengbu_shp/bengbu_clip.shp \
  --grand $GRAND --output /tmp/dams.json

# 3. Build reservoir properties (pick first dam)
$PYWR_PYTHON $TOOLS/s3_reservoir_properties/build_reservoir_properties.py \
  --dam_json /tmp/dams.json --dam_index 0 --output /tmp/reservoir.json

# 4. Convert VIC to inflow
$PYWR_PYTHON $TOOLS/s4_inflow/convert_vic_to_inflow.py \
  --vic_dir outputs/bengbu_1980-1990_025deg/vic_result \
  --grid_nc outputs/bengbu_1980-1990_025deg/vic_temp/grid/grid_bengbu_1980-1990_025deg_025deg.nc \
  --dam_lat 31.43 --dam_lon 115.92 --method all \
  --start_year 1980 --end_year 1990 --output /tmp/inflow.csv

# 5. Create operating rules
$PYWR_PYTHON $TOOLS/s5_operating_rules/create_operating_rules.py \
  --reservoir_json /tmp/reservoir.json --purpose flood_control \
  --region china_east --output /tmp/rules.json

# 6. Create demand nodes
$PYWR_PYTHON $TOOLS/s6_demands/create_demand_nodes.py \
  --type environmental --mean_annual_flow_m3s 150.0 \
  --output /tmp/demands.json

# 7. Assemble model
$PYWR_PYTHON $TOOLS/s7_assembly/assemble_pywr_model.py \
  --reservoir_json /tmp/reservoir.json --inflow_csv /tmp/inflow.csv \
  --rules_json /tmp/rules.json --demands_json /tmp/demands.json \
  --start_date 1980-01-01 --end_date 1990-12-31 \
  --output /tmp/model.json

# 8. Run model
$PYWR_PYTHON $TOOLS/s8_execution/run_pywr.py \
  --model /tmp/model.json --output_dir /tmp/pywr_results/

# 9. Plot results
$PYWR_PYTHON $TOOLS/s8_execution/plot_reservoir_operations.py \
  --storage_csv /tmp/pywr_results/storage_timeseries.csv \
  --release_csv /tmp/pywr_results/release_timeseries.csv \
  --inflow_csv /tmp/inflow.csv --rules_json /tmp/rules.json \
  --output /tmp/pywr_results/operations_plot.png \
  --title "Huaihe Basin Reservoir"
```

---

*This knowledge infrastructure was built using the Knowledge Dissection Toolkit v1.0 (Jianyun Zhang Research Group, Hohai University).*
