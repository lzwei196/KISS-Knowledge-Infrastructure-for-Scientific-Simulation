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
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
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
| `tools/convert_forcing_data.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_data.py --help` |
| `tools/convert_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters.py --help` |
| `tools/parse_wsimod_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_wsimod_output.py --help` |
| `tools/run_wsimod.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_wsimod.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# WSIMOD Knowledge Infrastructure v1.0.0

- **Package**: `hydrocraft-wsimod`
- **Model**: WSIMOD (Water Systems Integrated Modelling framework)
- **Version**: 0.6+ (PyPI)
- **Domain**: Integrated water cycle modelling — water quantity and quality
- **Authors**: Barnaby Dobson, Imperial College London
- **References**: Dobson et al. 2023 (JOSS, doi:10.21105/joss.04996); Dobson et al. 2024 (GMD, doi:10.5194/gmd-17-4495-2024)
- **Stats**: 4 tools, 5 skill docs, 18 diagnostic triplets, ~11,500 lines Python source

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: Input from upstream hydrological models.
See `data_ki/GRanD/SKILL.md` for dam/reservoir database.
See `data_ki/HydroLAKES/SKILL.md` for lake morphometry.


## 1. Overview

WSIMOD is a Python framework for simulating water quantity and quality across the
terrestrial water cycle. It uses a **node-arc message-passing architecture** where
physical components (land surfaces, sewers, rivers, reservoirs, treatment works,
demand points) are represented as nodes connected by arcs that transport water.

Key capabilities:
- Integrated urban-rural catchment simulation
- 12 water quality pollutants tracked (N, P, BOD, COD, solids, DO, pH, temperature)
- Flexible node-arc graph: users wire any configuration of water system components
- Daily timestep with configurable orchestration sequence
- CLI and Python API execution modes
- YAML configuration with CSV timeseries inputs
- Mass-balance checking at every node and arc

WSIMOD combines processes from CityWat (urban water) and CatchWat (rural hydrology)
into a single message-passing framework. Each node responds to four message types:
`pull_check`, `pull_set`, `push_check`, `push_set` — enabling flexible routing of
water volumes with associated quality (VQIP dictionaries).

---

## 2. Installation

### From PyPI (recommended)
```bash
python -m venv venv && source venv/bin/activate
pip install wsimod
```

### From GitHub (development)
```bash
pip install git+https://github.com/ImperialCollegeLondon/wsi@main
```

### With demos (includes geopandas, matplotlib, shapely)
```bash
pip install wsimod[demos]
```

### Development mode
```bash
git clone https://github.com/ImperialCollegeLondon/wsi.git
cd wsi
pip install -e .[dev]
```

### Dependencies
| Package   | Purpose                          |
|-----------|----------------------------------|
| PyYAML    | YAML config parsing              |
| tqdm      | Progress bar during simulation   |
| dill      | Model serialization (pickle)     |
| pandas    | Data manipulation, CSV I/O       |
| pyarrow   | Parquet file support (optional)  |

### Test command
```bash
wsimod settings.yaml --inputs ./input_dir --outputs ./output_dir
```

---

## 3. Pipeline Stages

| Stage | Name                 | Tool                          | Depends On     |
|-------|----------------------|-------------------------------|----------------|
| s0    | Configuration        | —                             | —              |
| s1    | Domain Setup         | —                             | s0             |
| s2    | Data Preparation     | `convert_forcing_data.py`     | s0             |
| s3    | Forcing/Input        | `convert_forcing_data.py`     | s0, s2         |
| s4    | Parameters           | `convert_parameters.py`       | s0, s1         |
| s5    | Execution            | `run_wsimod.py`               | s2, s3, s4     |
| s6    | Output Parsing       | `parse_wsimod_output.py`      | s5             |

### Stage Details

**s0 — Configuration**: Define simulation period, pollutants to track, node types,
spatial extent. Choose between CLI (YAML settings) or Python API.

**s1 — Domain Setup**: Identify catchment boundaries, node graph topology. Define
which node types (Land, Sewer, River, Reservoir, Groundwater, Demand, WTW, etc.)
are needed and how they connect via arcs.

**s2 — Data Preparation**: Gather raw meteorological and hydrological timeseries.
Convert to WSIMOD's expected CSV format with columns: `site, date, variable, value`.

**s3 — Forcing/Input**: Convert precipitation (mm → m via MM_TO_M), temperature (°C),
evapotranspiration (mm/d), flow data. Build `data_input_dict` for each node.

**s4 — Parameters**: Set node-specific parameters: surface areas (m²), tank capacities
(ML or m³), residence times (days), pollutant loads (kg/timestep), decay rates.

**s5 — Execution**: Run the model via CLI or Python API. The orchestration loop
iterates over dates, calling node functions in sequence.

**s6 — Output Parsing**: Extract flows.csv, tanks.csv, surfaces.csv. Parse VQIP
records into analyzable DataFrames.

---

## 4. Unit Trap Table

These unit conversions are the most common source of silent errors in WSIMOD.

| Variable          | WSIMOD Expects         | Common Source        | Conversion Factor       | Trap ID |
|-------------------|------------------------|----------------------|-------------------------|---------|
| Precipitation     | m/timestep             | mm/day               | × MM_TO_M (1e-3)       | dt_001  |
| Volume            | ML (megalitres)        | m³                   | ÷ ML_TO_M3 (1000)      | dt_002  |
| Flow              | m³/s → ML/d            | m³/s                 | × M3_S_TO_ML_D (86.4)  | dt_003  |
| Area (surface)    | m²                     | km²                  | × KM2_TO_M2 (1e6)      | dt_004  |
| Pollutant (add.)  | kg/timestep            | mg/L                 | × MG_L_TO_KG_M3 × vol  | dt_005  |
| Pollutant (non-a) | mg/L or °C or pH       | varies               | direct                  | dt_006  |
| ET₀               | m/timestep             | mm/day               | × MM_TO_M (1e-3)       | dt_007  |
| RelHum/Pressure   | kPa                    | hPa                  | × HPA_TO_KPA (0.1)     | dt_008  |
| Radiation         | MJ/m²                 | cal/cm²              | ÷ MJ_M2_TO_CAL_CM2     | dt_009  |
| Decay rate        | per day                | per second           | ÷ PER_DAY_TO_PER_SEC   | dt_010  |
| Soil depth        | m                      | mm                   | × MM_TO_M (1e-3)       | dt_011  |
| Nutrient load     | kg/km²                 | g/m²                 | × G_M2_TO_KG_KM2 (1e3) | dt_012  |

### Critical Constants (from `wsimod.core.constants`)
```python
MM_TO_M = 1e-3              # precipitation, ET₀, soil depth
ML_TO_M3 = 1000             # volume conversion
M3_S_TO_ML_D = 86.4         # flow rate
KM2_TO_M2 = 1e6             # area
MG_L_TO_KG_M3 = 1e-3        # concentration → mass/volume
KG_M3_TO_MG_L = 1e3         # mass/volume → concentration
FLOAT_ACCURACY = 1e-11      # mass balance tolerance
DT_DAYS = 1                 # default timestep
DECAY_REFERENCE_TEMPERATURE = 20  # °C for decay rate adjustment
```

---

## 5. Node Types Reference

| Node Type          | Module        | Key Parameters                              |
|--------------------|---------------|---------------------------------------------|
| Node               | nodes.py      | name                                        |
| Waste              | waste.py      | name (absorbs all water)                    |
| Land               | land.py       | surfaces[], data_input_dict                 |
| ImperviousSurface  | land.py       | area (m²), pollutant_load                   |
| PerviousSurface    | land.py       | area (m²), depth (m), pollutant_load        |
| GrowingSurface     | land.py       | area, crop parameters, irrigation           |
| Sewer              | sewer.py      | capacity (m³/d), pipe_time (d)              |
| Groundwater        | storage.py    | area (m²), capacity (m³ or ML)              |
| River              | storage.py    | length, width, depth, velocity              |
| Reservoir          | storage.py    | capacity, area, initial_storage             |
| Catchment          | catchment.py  | data_input_dict (flow, pollutant data)      |
| Demand             | demand.py     | per_capita, population, pollutant_load      |
| Distribution       | distribution  | leakage rate                                |
| FWTW               | wtw.py        | treatment_throughput, process_parameters     |
| WWTW               | wtw.py        | treatment_throughput, stormwater_storage     |

---

## 6. VQIP (Volume-Quality Input Product) Structure

Every water transfer in WSIMOD is a VQIP dictionary:

```python
vqip = {
    'volume': 100.0,       # m³/timestep (or ML depending on config)
    'do': 8.5,             # mg/L — non-additive
    'temperature': 15.0,   # °C — non-additive
    'ph': 7.5,             # pH — non-additive
    'phosphate': 0.05,     # kg — additive (mass)
    'org-phosphorus': 0.01,# kg — additive
    'ammonia': 0.02,       # kg — additive
    'nitrate': 0.03,       # kg — additive
    'nitrite': 0.001,      # kg — additive
    'org-nitrogen': 0.01,  # kg — additive
    'bod': 5.0,            # kg — additive
    'cod': 10.0,           # kg — additive
    'solids': 1.0,         # kg — additive
}
```

**Additive pollutants** (9): Mass-based; scale linearly with volume. When mixing,
masses sum directly.

**Non-additive pollutants** (3): Concentration/intensive; when mixing, volume-weighted
average is taken (not summed).

---

## 7. Default Orchestration Sequence

The model calls node functions in this order each timestep:

| Order | Node Type    | Function               | Purpose                          |
|-------|-------------|------------------------|----------------------------------|
| 1     | FWTW        | treat_water            | Treat raw water for supply       |
| 2     | Demand      | create_demand          | Generate household/industrial demand |
| 3     | Land        | run                    | Surface/subsurface hydrology     |
| 4     | Groundwater | infiltrate             | Accept percolation from land     |
| 5     | Sewer       | make_discharge         | Route stormwater through pipes   |
| 6     | Foul        | make_discharge         | Route foul water                 |
| 7     | WWTW        | calculate_discharge    | Calculate treatment loads        |
| 8     | Groundwater | distribute             | Send baseflow to river           |
| 9     | River       | calculate_discharge    | Route river flow                 |
| 10    | Reservoir   | make_abstractions      | Abstract water for supply        |
| 11    | Land        | apply_irrigation       | Apply irrigation water           |
| 12    | WWTW        | make_discharge         | Discharge treated effluent       |
| 13    | Catchment   | route                  | Route catchment inflows          |

---

## 8. Tools Reference

| Tool                        | Stage | Script                          | Lines | Purpose                                   |
|-----------------------------|-------|---------------------------------|-------|-------------------------------------------|
| Forcing Converter           | s2-s3 | `convert_forcing_data.py`       | ~280  | CSV timeseries → WSIMOD data_input_dict   |
| Parameter Converter         | s4    | `convert_parameters.py`         | ~250  | Soil/land parameters → node config dicts  |
| Execution Wrapper           | s5    | `run_wsimod.py`                 | ~220  | Run WSIMOD via CLI or API with checks     |
| Output Parser               | s6    | `parse_wsimod_output.py`        | ~250  | Extract flows/tanks/surfaces to CSV       |

Total: ~1,000 lines validated Python

---

## 9. Skill Documents

| Stage | Document                           | Knowledge Type            |
|-------|------------------------------------|---------------------------|
| s0-s1 | `s0_configuration_skill.md`        | Procedural + evaluative   |
| s2-s3 | `s2_data_preparation_skill.md`     | Procedural + unit traps   |
| s4    | `s4_parameters_skill.md`           | Evaluative + domain       |
| s5    | `s5_execution_skill.md`            | Sequencing + procedural   |
| s6    | `s6_output_analysis_skill.md`      | Procedural + diagnostic   |

---

## 10. Critical Domain Knowledge

These non-obvious facts cause silent failures if violated:

**dt_001: Precipitation must be in meters, not millimeters.**
WSIMOD expects precipitation in m/timestep. Most weather datasets provide mm/day.
Omitting `× MM_TO_M` causes 1000× too much rainfall, flooding all nodes.
Detection: check `max(precipitation) < 0.5 m/d` for temperate climates.

**dt_002: Volume units are ML by default, but nodes may use m³.**
`MM_M2_TO_SIM_VOLUME` converts precipitation depth × area to simulation volume.
Default simulation volume is ML (megalitres). Some node parameters use m³.
Mixing units silently corrupts mass balance.

**dt_003: Additive vs non-additive pollutant mixing.**
Additive pollutants (phosphate, ammonia, etc.) are in kg — masses sum when mixing.
Non-additive pollutants (DO, temperature, pH) are concentrations — volume-weighted
average when mixing. Treating a non-additive as additive doubles concentrations.

**dt_004: data_input_dict keys are (variable, timestamp) tuples.**
The timestamp must be a pandas Timestamp or WSIMOD `to_datetime` object. Using
string dates as keys causes silent KeyError → zero forcing for all timesteps.

**dt_005: Node names in arcs must match exactly.**
Arc `in_port` and `out_port` reference node names. Typos cause KeyError at model
construction. Names are case-sensitive.

**dt_006: Sewer capacity is m³/d, not ML/d.**
Despite other nodes using ML, sewer capacity is in m³/d. Using ML values gives
1000× too much capacity, preventing any CSO (combined sewer overflow).

**dt_007: Pollutant decay uses reference temperature of 20°C.**
`k(T) = k_ref × (coeff ^ (T - 20))`. If temperature is in wrong units or missing,
decay rates are silently wrong. Always verify temperature is in °C.

**dt_008: Land surface area is in m².**
Some datasets provide area in km² or hectares. Using km² without converting to m²
gives 1e6× wrong runoff volume. Use `KM2_TO_M2 = 1e6`.

**dt_009: Mass balance tolerance is 1e-11.**
`FLOAT_ACCURACY = 1e-11`. Mass balance violations below this threshold are ignored.
If custom nodes accumulate floating-point errors, violations may be masked.

---

## 11. Validation: Built-in Test Cases

WSIMOD includes comprehensive tests in the `tests/` directory:

- **Quickstart demo**: Simple urban-rural catchment (Land → Sewer → Groundwater → River)
- **Oxford case study**: Multi-node Thames catchment with demand, WTW, reservoirs
- **Land demo**: Detailed land surface hydrology with multiple surface types

Test command:
```bash
cd source/repo && python -m pytest tests/ -v
```

---

## 12. Configuration Format

### YAML Settings File (custom mode)
```yaml
dates:
  - "2009-01-01"
  - "2009-01-02"
  # ... daily dates

data:
  land_timeseries:
    filename: "timeseries_data.csv"
    filters:
      - where: site
        is: oxford_land
    scaling:
      - where: variable
        is: precipitation
        variable: value
        factor: MM_TO_M
    index: [variable, date]
    output: value
    format: dict

nodes:
  - type_: Land
    name: my_land
    data_input_dict: "data:land_timeseries"
    surfaces:
      - type_: ImperviousSurface
        surface: urban
        area: 10
      - type_: PerviousSurface
        surface: rural
        area: 100
        depth: 0.5

  - type_: Sewer
    name: my_sewer
    capacity: 0.04

  - type_: Groundwater
    name: my_gw
    area: 100
    capacity: 100

arcs:
  - type_: Arc
    name: urban_drain
    in_port: my_land
    out_port: my_sewer

  - type_: Arc
    name: percolation
    in_port: my_land
    out_port: my_gw
```

### Saved Model Format
Models can be saved/loaded with `model.save()` / `model.load()`:
- `config.yml` — full model definition
- `*.csv.gz` — compressed timeseries data
- `*.parquet` — optional parquet data files

---

## 13. Diagnostic Triplets Summary

| ID     | Severity | Domain           | Summary                                    |
|--------|----------|------------------|--------------------------------------------|
| dt_001 | silent   | unit_conversion  | Precipitation mm vs m (1000× error)        |
| dt_002 | silent   | unit_conversion  | Volume ML vs m³ (1000× error)              |
| dt_003 | silent   | unit_conversion  | Additive/non-additive pollutant mixing     |
| dt_004 | fatal    | parameter_format | data_input_dict key type mismatch          |
| dt_005 | fatal    | parameter_format | Node name mismatch in arc definitions      |
| dt_006 | silent   | unit_conversion  | Sewer capacity m³ vs ML                    |
| dt_007 | silent   | unit_conversion  | Decay reference temperature assumption     |
| dt_008 | silent   | unit_conversion  | Land area m² vs km²                        |
| dt_009 | silent   | parameter_format | Mass balance tolerance masking errors       |
| dt_010 | degraded | parameter_format | Missing pollutant in VQIP initialization   |
| dt_011 | silent   | unit_conversion  | Soil depth mm vs m                         |
| dt_012 | silent   | unit_conversion  | Nutrient load g/m² vs kg/km²              |
| dt_013 | fatal    | runtime          | Empty data_input_dict → KeyError           |
| dt_014 | degraded | runtime          | Orchestration order changes results        |
| dt_015 | silent   | parameter_format | ET₀ in mm vs m                            |
| dt_016 | fatal    | dependency       | Missing PyYAML/dill/pandas                 |
| dt_017 | degraded | silent_error     | Float precision in VQIP operations         |
| dt_018 | silent   | unit_conversion  | Flow rate m³/s vs m³/d conversion          |

---

## Output Description

WSIMOD's `model.run()` returns four DataFrames: `flows`, `tanks`, `_, surfaces`. The `flows` DataFrame records water volumes (m^3 or ML) and VQIP pollutant masses/concentrations transferred along each arc per timestep. The `tanks` DataFrame logs storage levels at each node. The `surfaces` DataFrame tracks land surface states (soil moisture, runoff, percolation). These are returned as lists of dictionaries convertible to pandas DataFrames via `pd.DataFrame(flows)`. Use `parse_wsimod_output.py` to export results to CSV files (`flows.csv`, `tanks.csv`, `surfaces.csv`) with columns including `date, arc/node_name, volume, and pollutant values`, and to compute mass-balance checks across the network.

---

## 6. Output Description (dag.yaml-sourced)

This section restates the observable outputs from `dag.yaml`. If this section and
`dag.yaml` disagree, `dag.yaml` wins.

**Headline output** (the dag's `validation_rank: 1` variable; the variable this
model is judged by):

> `river flow / discharge` — Routed river discharge at a node, a subset of the
> flows record commonly compared to gauge data. (`m3/d or ML/d`)

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| river flow / discharge | 1 | m3/d or ML/d | Routed river discharge at a node, a subset of the flows record commonly compared to gauge data. |
| flows | not specified here | see dag.yaml | See `dag.yaml` for medium, observability, and rank details. |
| pollutant concentration / mass | not specified here | see dag.yaml | See `dag.yaml` for medium, observability, and rank details. |
| storage / tank levels | not specified here | see dag.yaml | See `dag.yaml` for medium, observability, and rank details. |
| land surface states (soil moisture, runoff, percolation) | not specified here | see dag.yaml | See `dag.yaml` for medium, observability, and rank details. |
| CSO spill / flood volume | not specified here | see dag.yaml | See `dag.yaml` for medium, observability, and rank details. |

The `flows` record is the main parsing source for routed discharge and water
quality transfers. The rank-1 output `river flow / discharge` is a subset of
that record and should be compared to gauge observations in `m3/d or ML/d`.

---

## 8. Unit Conversion Table

The exact I/O contract lives in `docs/format_spec.yaml`; this unit table
summarizes the unit traps used by the pipeline and diagnostic triplets. Verify
the source data attributes before converting a new dataset.

| Variable | Source unit | Model / parsed unit | Conversion | Diagnostic |
|----------|-------------|---------------------|------------|------------|
| Precipitation | mm/day | m/timestep | x `MM_TO_M` (`1e-3`) | dt_001 |
| Volume | m3 | ML | divide by `ML_TO_M3` (`1000`) | dt_002 |
| Flow | m3/s | ML/d | x `M3_S_TO_ML_D` (`86.4`) | dt_003, dt_018 |
| Area (surface) | km2 | m2 | x `KM2_TO_M2` (`1e6`) | dt_004, dt_008 |
| Pollutant additive load | mg/L with volume | kg/timestep | x `MG_L_TO_KG_M3` x volume | dt_005 |
| Pollutant non-additive value | varies | mg/L, degC, or pH | direct; mix by volume-weighted average | dt_006 |
| ET0 | mm/timestep | m/timestep | x `MM_TO_M` (`1e-3`) | dt_007, dt_015 |
| Relative humidity / pressure | hPa | kPa | x `HPA_TO_KPA` (`0.1`) | dt_008 |
| Radiation | cal/cm2 | MJ/m2 | divide by `MJ_M2_TO_CAL_CM2` | dt_009 |
| Decay rate | per second | per day | divide by `PER_DAY_TO_PER_SEC` | dt_010 |
| Soil depth | mm | m | x `MM_TO_M` (`1e-3`) | dt_011 |
| Nutrient load | g/m2 | kg/km2 | x `G_M2_TO_KG_KM2` (`1e3`) | dt_012 |
| River flow / discharge | flows record | m3/d or ML/d | keep in dag unit before scoring | dag rank-1 |

Output unit convention: `river flow / discharge` is scored in `m3/d or ML/d`.
Do not compare raw `m3/s` gauge data to parsed daily discharge until it has been
converted to the same unit basis.

---

## 11. Validated Results

This section states the model's validation target and field pass-bands from
`docs/validation_convention.yaml`. It does not claim a site-specific achieved
score unless a run report supplies one.

### Headline Validation Target

| Property | Value |
|----------|-------|
| Rank-1 dag variable | river flow / discharge |
| Unit | m3/d or ML/d |
| Description | Routed river discharge at a node, a subset of the flows record commonly compared to gauge data. |
| Validation data role | Gauge comparison for routed river discharge at a node |

### Performance Metrics -- judged against the field's bar, not intuition

| Dag variable | Metric | Direction | Very good | Good | Satisfactory |
|--------------|--------|-----------|-----------|------|--------------|
| flows | nse | maximize | >= 0.8 (moriasi2015, arnold2012) | >= 0.7 (moriasi2015, arnold2012) | >= 0.5 (moriasi2015, arnold2012) |
| flows | pbias | zero_centered | abs(PBIAS) <= 5.0 (moriasi2015) | abs(PBIAS) <= 10.0 (moriasi2015) | abs(PBIAS) <= 15.0 (moriasi2015) |
| river flow / discharge | nse | maximize | >= 0.8 (moriasi2015, moriasi2007) | >= 0.7 (moriasi2015, moriasi2007) | >= 0.5 (moriasi2015, moriasi2007) |
| river flow / discharge | pbias | zero_centered | abs(PBIAS) <= 5.0 (moriasi2015) | abs(PBIAS) <= 10.0 (moriasi2015) | abs(PBIAS) <= 15.0 (moriasi2015) |
| pollutant concentration / mass | nse | maximize | >= 0.65 (moriasi2015) | >= 0.5 (moriasi2015) | >= 0.35 (moriasi2015) |
| pollutant concentration / mass | pbias | zero_centered | abs(PBIAS) <= 15.0 (moriasi2015) | abs(PBIAS) <= 20.0 (moriasi2015) | abs(PBIAS) <= 30.0 (moriasi2015) |

For any metric or dag variable not listed in `docs/validation_convention.yaml`,
write the band as `no cited threshold`; do not substitute remembered hydrology
thresholds.

### Achieved Result Values

No calibration, validation, or full-period achieved metric values were supplied
in the sourced facts for this edit. Record achieved values only after running the
real WSIMOD package or CLI, then judge `river flow / discharge` against the
bands above.

---

## 14. Quick Start

```python
import pandas as pd
from wsimod.core import constants
from wsimod.orchestration.model import Model

# 1. Load timeseries data
data = pd.read_csv("timeseries_data.csv")
data.loc[data.variable == "precipitation", "value"] *= constants.MM_TO_M
data.date = pd.to_datetime(data.date)
dates = data.date.drop_duplicates()

# 2. Build data_input_dict
land_inputs = data.set_index(["variable", "date"]).value.to_dict()

# 3. Define nodes
nodes = [
    {"type_": "Land", "name": "my_land",
     "data_input_dict": land_inputs,
     "surfaces": [
         {"type_": "PerviousSurface", "surface": "rural",
          "area": 100, "depth": 0.5}
     ]},
    {"type_": "Groundwater", "name": "my_gw",
     "area": 100, "capacity": 100},
    {"type_": "Node", "name": "my_river"},
    {"type_": "Waste", "name": "outlet"},
]

# 4. Define arcs
arcs = [
    {"type_": "Arc", "in_port": "my_land", "out_port": "my_gw",
     "name": "percolation"},
    {"type_": "Arc", "in_port": "my_land", "out_port": "my_river",
     "name": "runoff"},
    {"type_": "Arc", "in_port": "my_gw", "out_port": "my_river",
     "name": "baseflow"},
    {"type_": "Arc", "in_port": "my_river", "out_port": "outlet",
     "name": "outflow"},
]

# 5. Create and run model
model = Model()
model.dates = dates
model.add_nodes(nodes)
model.add_arcs(arcs)
flows, tanks, _, surfaces = model.run()

# 6. Parse output
flows_df = pd.DataFrame(flows)
print(flows_df.head())
```

---

## 15. Coupling Points

| Interface         | External Model | Data Exchange                        |
|-------------------|----------------|--------------------------------------|
| Inflow            | VIC/CaMa-Flood | River discharge → Catchment node     |
| Met forcing       | CMFD/MSWX/ERA5 | Precip, temp, ET₀ → Land node        |
| Water quality     | SWAT+/AED2     | Pollutant loads → Catchment node     |
| Demand            | Census/utility  | Per-capita demand → Demand node      |
| Land use          | MODIS/Corine   | Surface type fractions → Land node   |
| Reservoir ops     | Dam databases   | Storage/release rules → Reservoir    |

---

## 16. File Structure

```
ki/
├── SKILL.md                              # This file
├── knowledge_infrastructure.yaml          # Schema-compliant YAML
├── tools/
│   ├── convert_forcing_data.py           # Forcing/input converter
│   ├── convert_parameters.py             # Soil/parameter converter
│   ├── run_wsimod.py                     # Execution wrapper
│   └── parse_wsimod_output.py            # Output parser
├── docs/
│   ├── s0_configuration_skill.md         # Configuration guide
│   ├── s2_data_preparation_skill.md      # Data preparation guide
│   ├── s4_parameters_skill.md            # Parameter setup guide
│   ├── s5_execution_skill.md             # Execution guide
│   └── s6_output_analysis_skill.md       # Output analysis guide
└── diagnostics/
    └── triplets.yaml                     # 18 diagnostic triplets
```
