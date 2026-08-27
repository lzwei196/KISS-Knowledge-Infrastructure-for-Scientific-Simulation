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
| to run the pipeline stages | `tools/` (11 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (8 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (29 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (15 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/s1_installation/verify_dlbreach.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_installation/verify_dlbreach.py --help` |
| `tools/s2_dam_properties/create_dam_geometry.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_dam_properties/create_dam_geometry.py --help` |
| `tools/s3_reservoir_curve/create_reservoir_curve.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_reservoir_curve/create_reservoir_curve.py --help` |
| `tools/s4_inflow/convert_cama_to_inflow.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_inflow/convert_cama_to_inflow.py --help` |
| `tools/s5_breach_config/assemble_input_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_breach_config/assemble_input_file.py --help` |
| `tools/s5_breach_config/set_breach_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_breach_config/set_breach_parameters.py --help` |
| `tools/s6_execution/run_dlbreach.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_execution/run_dlbreach.py --help` |
| `tools/s7_output/extract_breach_results.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_output/extract_breach_results.py --help` |
| `tools/s7_output/inject_breach_to_cama.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_output/inject_breach_to_cama.py --help` |
| `tools/s8_visualization/plot_breach_evolution.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_visualization/plot_breach_evolution.py --help` |
| `tools/s8_visualization/plot_breach_hydrograph.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_visualization/plot_breach_hydrograph.py --help` |

*11 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

## Data Preparation

### Input data

**Input Source**: DLBreach takes inflow hydrographs from upstream models (VIC+CaMa-Flood).
- `convert_cama_to_inflow.py` — Converts CaMa-Flood discharge output to DLBreach inflow format
- `create_dam_geometry.py` — Creates dam geometry from GRanD database or user parameters
- `create_reservoir_curve.py` — Creates elevation-area-volume curves

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for upstream forcing documentation.

---

# DLBreach Knowledge Infrastructure -- Agent Entry Point

**Package**: `dlbreach-knowledge-infrastructure` v1.0.0
**Model**: DLBreach (Version 2016.4, Clarkson University)
**Domain**: Dam safety, levee breach, flood risk, emergency management
**Role in HydroCraft**: Fills the dam/levee breach modeling gap -- couples with CaMa-Flood for inflow (upstream) and downstream flood routing

---

## What This Enables

An AI agent can autonomously:
1. Build a DLBreach dam breach simulation from dam properties and reservoir data
2. Extract CaMa-Flood discharge at a dam cell as the inflow hydrograph
3. Run breach simulation for overtopping or piping failure modes
4. Parse the 13-column output to extract breach hydrograph and geometry evolution
5. Inject breach outflow back into CaMa-Flood for downstream flood routing
6. Visualize breach hydrograph and geometry evolution

## Quick Reference

| Component | What | Where |
|-----------|------|-------|
| **Binary** | `DLBreach_Barrier.exe` (Fortran, runs via **wine** on Linux) | `model/dlbreach/bin/DLBreach_Barrier.exe` |
| **Execution** | `echo "casename" \| wine DLBreach_Barrier.exe` | Reads casename from stdin |
| **Input** | Single card-based ASCII file | `casename.txt` (same dir as binary) |
| **Output** | Single ASCII file, 13 columns | `casename.out` (same dir as binary) |
| **Unit system** | SI (meters, seconds, m3/s, Pa) | All inputs and outputs |
| **Test cases** | 15 official cases from Wu 2016 | `model/dlbreach/test_cases/` |
| **Documentation** | Wu 2016 Technical Report | `docs/reference/DLBreach_Technical_Report_2016.pdf` |

**IMPORTANT**: The `run_dlbreach.py` tool handles wine execution automatically. Do NOT use `dlbreach.py` (Python reimplementation) — it has simplified erosion physics that produce ~10x lower peak discharge than the Fortran original. Validated: Banqiao official test case gives 71,783 m³/s (Fortran) vs literature 78,000 m³/s.

**Downstream card required**: The Fortran binary requires `Downstream_Channel_Flow_Out` card (width, slope, Manning's n). Without it, output file is empty.

## Pipeline Overview (8 Stages)

```
S1 Installation ──> S2 Dam Geometry ──> S3 Reservoir Curve ──> S4 Inflow
                                              │                    │
                                              v                    v
                                         S5 Breach Config ──> S6 Execute
                                                                   │
                                                                   v
                                                          S7 Output & Coupling
                                                                   │
                                                                  v
                                                          S8 Visualization
```

## Stage How-To Documents

- [S1 Installation](docs/s1_installation.md) - verify the DLBreach binary or Wine execution path.
- [S2 Dam Geometry](docs/s2_dam_geometry.md) - generate embankment geometry cards.
- [S3 Reservoir Curve](docs/s3_reservoir_curve.md) - generate the `Upstream_Reservoir` storage card.
- [S4 Inflow](docs/s4_inflow.md) - convert CaMa-Flood or manual inflow into `Upstream_Reservoir_Inflow`.
- [S5 Breach Config](docs/s5_breach_config.md) - generate breach cards and assemble `casename.txt`.
- [S6 Execution](docs/s6_execution.md) - run the actual DLBreach Fortran binary.
- [S7 Output And Coupling](docs/s7_output.md) - parse 13-column output and inject breach flow to CaMa-Flood.
- [S8 Visualization](docs/s8_visualization.md) - plot hydrograph and breach-geometry diagnostics.

## Tools (11 Total)

| Stage | Tool | Script | Purpose |
|-------|------|--------|---------|
| S1 | `verify_dlbreach` | `tools/s1_installation/verify_dlbreach.py` | Check binary, run test |
| S2 | `create_dam_geometry` | `tools/s2_dam_properties/create_dam_geometry.py` | Generate embankment cards |
| S3 | `create_reservoir_curve` | `tools/s3_reservoir_curve/create_reservoir_curve.py` | Generate V-z / As-z curve |
| S4 | `convert_cama_to_inflow` | `tools/s4_inflow/convert_cama_to_inflow.py` | CaMa outflw -> DLBreach inflow |
| S5 | `set_breach_parameters` | `tools/s5_breach_config/set_breach_parameters.py` | Breach mode, soil, Manning |
| S5 | `assemble_input_file` | `tools/s5_breach_config/assemble_input_file.py` | Combine all cards into input |
| S6 | `run_dlbreach` | `tools/s6_execution/run_dlbreach.py` | Execute binary, capture output |
| S7 | `extract_breach_results` | `tools/s7_output/extract_breach_results.py` | Parse 13-col output -> CSV/JSON |
| S7 | `inject_breach_to_cama` | `tools/s7_output/inject_breach_to_cama.py` | Add breach Q to CaMa runoff NC |
| S8 | `plot_breach_hydrograph` | `tools/s8_visualization/plot_breach_hydrograph.py` | Discharge vs time plot |
| S8 | `plot_breach_evolution` | `tools/s8_visualization/plot_breach_evolution.py` | Breach geometry evolution plot |

## Key Input Format Rules

1. **Single input file**: All parameters in `casename.txt`, card-based keywords
2. **Card format**: `Keyword    value(s)    ! optional comment`
3. **Multiline cards**: Tabulated data (reservoir curve, inflow, waves) must have NO comments or blank lines between the keyword and data lines
4. **SI units everywhere**: meters, seconds, m3/s, Pa, kg/m3
5. **Slopes**: V/H ratio (vertical/horizontal), NOT H/V
6. **Embankment height**: Crest-to-base, NOT geo-reference elevation
7. **Embankment length**: Base length = maximum breach bottom width
8. **Water levels**: Above embankment base, positive values
9. **Time in inflow/WSL cards**: HOURS (not seconds)
10. **Time_Step and Simulation_Period**: SECONDS

## Recommended Parameter Values (Wu 2016, Chapter 5)

All values from the DLBreach Technical Report (Wu 2016). **Use these as defaults when no site-specific data is available.** Parameters marked ★ are the most sensitive.

### Sediment Parameters

| Parameter | Non-cohesive | Cohesive | Card Name | Notes |
|-----------|-------------|----------|-----------|-------|
| Diameter d50 | Site-specific (m) | **0.00003 m** (0.03mm) | `Sediment_Diameter` | Cohesive: representative floc diameter |
| Specific gravity | 2.65 | 2.65 | `Sediment_Specific_Gravity` | Standard |
| Porosity | 0.30-0.45 | 0.35-0.45 | `Sediment_Porosity` | |
| Cohesion | 0 (or apparent) | Site-specific (Pa) | `Sediment_Cohesion` | For slope stability, not erosion |
| Internal friction | tan(30-40°) | tan(20-30°) | `Sediment_Internal_Friction` | tanφ, not degrees |
| ★ **kd (erosion coeff)** | N/A | **2.5-30.0 cm³/N-s** | `Cohesive_Soil_Erosion_kd` | **Most important parameter for cohesive dams.** Use 10 as default. Sensitivity analysis recommended. |
| ★ **τc (critical shear)** | N/A | **0.15 Pa** | `Cohesive_Soil_Erosion_Tauc` | Used in all 35 cohesive test cases |
| λ (adaptation) | **6.0** (field), 3.0 (lab) | N/A | `Noncohesive_Sed_Adaptation_Lamda` | Non-equilibrium transport |

### Headcut Parameters (overtopping_mode=2, cohesive only)

| Parameter | Recommended | Card Name | Notes |
|-----------|-------------|-----------|-------|
| ★ Headcut Ct | **0.0025-0.0049** m^(-1/6)s^(-2/3) | `Headcut_Ct` | Default formula 2 (Eq. 4.31) |
| Headcut mode | 2 (default) | `Headcut_Formula` | 1=erodibility index, 2=Ct formula, 3=C2 formula |

### Manning's Roughness

| Condition | Value | Notes |
|-----------|-------|-------|
| Cohesive sediment | **0.016** | Wu 2016 Ch.5 recommendation |
| Non-cohesive (field) | n = 12 × d50^(1/6) | An=12 for field, 16 for lab (Eq. 3.6) |
| Non-cohesive (lab) | n = 16 × d50^(1/6) | |

### Pilot Breach (Initial Breach)

| Parameter | Overtopping | Piping | Notes |
|-----------|-------------|--------|-------|
| Depth | **0.2-0.4 m** | N/A | From crest down |
| Width | **1.0-5.0 m** | **0.2 m** | Bottom width |
| Pipe depth | N/A | Measured from top | Below crest |

### Time Step

| Application | Recommended | Notes |
|-------------|-------------|-------|
| Laboratory | 0.1-1.0 s | Smaller for stability |
| Field | 1.0-5.0 s | Test multiple values for stability |

### Reservoir Curve

For method 3 (power law V=αz^m): exponent **m=2** suggested (range 1-3).

## Output Format (13 Columns)

| Col | Variable | Unit | Description |
|-----|----------|------|-------------|
| 1 | time | hours | Elapsed time |
| 2 | breach_flow | m3/s | Breach discharge |
| 3 | spillway_gate_flow | m3/s | Spillway/gate discharge |
| 4 | upstream_wsl | m | Upstream water level (above base) |
| 5 | downstream_wsl | m | Downstream water level (above base) |
| 6 | breach_bottom_elev | m | Breach bottom elevation (above base) |
| 7 | breach_bottom_width | m | Breach bottom width |
| 8 | breach_top_width | m | Breach top width |
| 9 | breach_flow_area | m2 | Flow area at breach |
| 10 | breach_side_slope | V/H | Side slope |
| 11 | cumulative_volume | m3 | Total volume through breach+spillway |
| 12 | sediment_upstream | m3/s | Upstream sediment discharge |
| 13 | sediment_downstream | m3/s | Downstream sediment discharge |

## Output Description (DAG-Sourced)

**Source of truth**: `dag.yaml`. The DAG is the model identity for observable outputs,
validation ranking, and output binding. If this section and `dag.yaml` ever disagree,
`dag.yaml` wins.

**Headline output** (DAG `validation_rank: 1`, the variable this model is judged by):

> `breach_discharge` -- Breach water outflow hydrograph (discharge through the breach over time); the primary validation target. (`m3/s`)

Other DAG outputs:

| Output variable (DAG `var`) | Rank | Emitted in | Unit | Description |
|-----------------------------|------|------------|------|-------------|
| `breach_discharge` | 1 | `casename.out` column 2 | m3/s | Breach water outflow hydrograph (discharge through the breach over time); the primary validation target. |
| `time_to_peak_discharge` | 2 | derived from `casename.out` column 1 at peak of column 2 | hours | Breach water-discharge characteristic time — elapsed time from breach initiation to peak water discharge through the breach. |
| `reservoir_water_level` | 3 | `casename.out` column 4 | m above base | Upstream reservoir water-surface level over time; drawn down as the reservoir drains through the breach. |
| `breach_bottom_width` | 4 | `casename.out` column 7 | m | Earthen embankment soil-breach bottom width; grows as erosion progresses, capped at embankment length. |
| `breach_top_width` | 5 | `casename.out` column 8 | m | Earthen embankment soil-breach top width derived from bottom width and side slope. |
| `breach_bottom_elevation` | 6 | `casename.out` column 6 | m above base | Earthen embankment breach-bed elevation; decreases from crest toward base as the breach erodes downward. |
| `cumulative_breach_volume` | 7 | `casename.out` column 11 | m3 | Cumulative water volume released through the breach plus spillway. |

## Unit Table

This table documents the units an agent must preserve when preparing inputs,
parsing DLBreach output, computing metrics, and coupling to CaMa-Flood. Exact
I/O shapes live in `docs/format_spec.yaml`; output identity and validation
ranking live in `dag.yaml`.

| Variable / quantity | Source unit | Model/output unit | Conversion / rule | Notes |
|---------------------|-------------|-------------------|-------------------|-------|
| CaMa-Flood `outflw` inflow | m3/s | m3/s | x1 | Extract at the dam grid cell and write to `Upstream_Reservoir_Inflow`. |
| DLBreach inflow-card time | days or source timestep from upstream data | hours | convert to hours | Time in inflow and WSL cards is HOURS. |
| `Time_Step` | seconds | seconds | x1 | `Time_Step` and `Simulation_Period` are SECONDS. |
| `Simulation_Period` | seconds | seconds | x1 | `Time_Step` and `Simulation_Period` are SECONDS. |
| Embankment dimensions | meters | meters | x1 | Height, length, water levels, breach depths, and widths use meters. |
| Water levels | meters above embankment base | meters above embankment base | x1 | Water levels are above embankment base, positive values. |
| Slopes | V/H | V/H | x1 | Slopes are vertical/horizontal, not horizontal/vertical. |
| Sediment cohesion / critical shear | Pa | Pa | x1 | Soil strength and `Cohesive_Soil_Erosion_Tauc` use Pa. |
| `breach_discharge` | DLBreach column 2 `breach_flow` | m3/s | x1 | DAG rank-1 output and primary validation target. |
| `breach_bottom_width` | DLBreach column 7 | m | x1 | DAG output and validation-convention variable. |
| `breach_top_width` | DLBreach column 8 | m | x1 | DAG output. |
| `breach_bottom_elevation` | DLBreach column 6 | m above base | x1 | DAG output. |
| `reservoir_water_level` | DLBreach column 4 `upstream_wsl` | m above base | x1 | DAG output. |
| `cumulative_breach_volume` | DLBreach column 11 `cumulative_volume` | m3 | x1 | DAG output. |
| `time_to_peak_discharge` | DLBreach column 1 time axis | hours | derive from peak `breach_discharge` timestep | DAG output. |
| Spillway/gate discharge | DLBreach column 3 | m3/s | x1 | Use with breach discharge when computing total downstream injection. |
| CaMa-Flood injection | hourly breach outflow | daily mean breach discharge | hourly to daily mean | Inject as additional runoff at the downstream cell. |

## Validated Results

### Validation Target

DLBreach is judged first on the DAG rank-1 variable:

> `breach_discharge` -- Breach water outflow hydrograph (discharge through the breach over time); the primary validation target. (`m3/s`)

### Performance Metrics -- Field Convention Bars

**Source of truth**: `docs/validation_convention.yaml`. The convention defines the
metric, direction, pass bands, and citation keys. Null bands are written as
`no cited threshold`; do not substitute remembered hydrology thresholds.

| DAG variable | Metric | Direction | Very good band | Good band | Satisfactory band |
|--------------|--------|-----------|----------------|-----------|-------------------|
| `breach_discharge` | `peak_pbias` | zero_centered | no cited threshold (`wu2013`, `zhong2016`) | no cited threshold (`wu2013`, `zhong2016`) | 25.0 (`wu2013`, `zhong2016`) |
| `breach_discharge` | `pbias` | zero_centered | no cited threshold (`wu2013`, `zhong2016`) | no cited threshold (`wu2013`, `zhong2016`) | 25.0 (`wu2013`, `zhong2016`) |
| `breach_bottom_width` | `final_width_pbias` | zero_centered | no cited threshold (`wu2013`, `zhong2016`) | no cited threshold (`wu2013`, `zhong2016`) | 25.0 (`wu2013`, `zhong2016`) |

For zero-centered PBIAS metrics, the target is zero bias. A run-level value must
be compared against the cited convention bands above; this document does not
invent achieved calibration or validation scores when they are not present in
the KI facts.

## HydroCraft Coupling

### CaMa-Flood -> DLBreach (Inflow)
- Extract `outflw` (m3/s) at the dam grid cell from CaMa-Flood output
- Daily CaMa output -> hourly DLBreach inflow via shape-preserving interpolation
- Use `convert_cama_to_inflow` tool

### DLBreach -> CaMa-Flood (Breach Outflow)
- Extract breach_flow (col 2) + spillway_gate_flow (col 3) from DLBreach output
- Convert hourly -> daily mean breach discharge
- Inject as additional runoff into CaMa-Flood runoff NetCDF at the downstream cell
- Use `inject_breach_to_cama` tool
- Re-run CaMa-Flood to propagate the breach flood wave

### Typical HydroCraft Dam Breach Workflow
```
VIC (runoff) -> CaMa-Flood (river routing) -> outflw at dam cell
                                                     |
                                            DLBreach (breach sim)
                                                     |
                                     breach Q -> inject into CaMa runoff
                                                     |
                                          CaMa-Flood (re-run for flood routing)
                                                     |
                                          downstream flood map (optional downscaling)
```

## Parameter Guidance

### Breach Mode Selection
| Dam Type | Breach_Mode | Overtopping_Mode |
|----------|-------------|------------------|
| Non-cohesive homogeneous | 1 | 1 (surface erosion) |
| Cohesive homogeneous | 1 | 2 (headcut erosion) |
| Composite with clay core | 1 | 3 |
| Internal erosion (any) | 2 | N/A |

### Recommended Defaults (from 50+ test cases)
| Parameter | Non-cohesive | Cohesive | Unit |
|-----------|-------------|----------|------|
| Sediment_Diameter | 0.001 | 0.00003 | m |
| Sediment_Specific_Gravity | 2.65 | 2.65 | - |
| Sediment_Porosity | 0.35 | 0.35 | - |
| Breach_Manning_n | 0.025 | 0.016 | - |
| Noncohesive_Sed_Adaptation_Lamda | 6.0 (field) | N/A | - |
| Cohesive_Soil_Erosion_kd | N/A | 2.5-30.0 | cm3/N-s |
| Cohesive_Soil_Erosion_Tauc | N/A | 0.15 | Pa |
| Initial_Overtopping_Breach | 0.2, 1.0 | 0.2, 1.0 | m |
| Initial_Piping_Breach | 5.0, 0.1 | 5.0, 0.1 | m |
| Time_Step (field) | 1-5 | 1-5 | sec |
| Time_Step (lab) | 0.1-1 | 0.1-1 | sec |

### Sensitivity Analysis Priority
1. **kd** (cohesive erosion coefficient) -- most important for cohesive dams
2. **Sediment_Diameter** -- controls erosion rate for non-cohesive dams
3. **Breach_Manning_n** -- affects flow velocity and erosion rate
4. **Initial breach dimensions** -- affects timing but not peak flow significantly

## Diagnostics

When DLBreach fails or produces unexpected results, consult `diagnostics/triplets.yaml` for symptom-diagnosis-remedy triplets covering 21 common failure modes.

## Reading Basin Context

Before running, check if upstream CaMa-Flood has written findings:
```bash
python KISSPATH_INTERNAL_NOT_SHIPPED/tools/write_findings.py \
  --read --context_file outputs/{run_name}/basin_context.yaml
```

## Writing Findings

After DLBreach completes, write findings:
```bash
python KISSPATH_INTERNAL_NOT_SHIPPED/tools/write_findings.py \
  --context_file outputs/{run_name}/basin_context.yaml \
  --model "DLBreach" --stage s_dlbreach --status completed \
  --artifact "breach_hydrograph:outputs/{run}/dlbreach/breach_results.csv:Breach outflow hydrograph" \
  --summary "peak_breach_q_m3s=5000" --summary "failure_time_hr=2.5" \
  --insight "dam_breach:high:Peak breach discharge 5000 m3/s at 2.5 hours, breach width 80m" \
  --insight "coupling:medium:Breach volume 50M m3 injected into CaMa-Flood downstream cell"
```
