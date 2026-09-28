# KI planning pre-evaluation — slice C

Date: 2026-09-27. Scope: sorted `Catalog(repo/models).packages`, zero-based index `% 3 == 2` (42 of 127 packages).

## What was checked

Read-only qualitative inspection of each package's `SKILL.md` input/data-preparation, pipeline and tool instructions; DAG input declarations or the available format-spec fallback; and a relevant preparation-stage document. Selected tool implementations were inspected to ground four examples. No providers, downloads, project mutations, installations, model runs or scientific performance tests were performed. This is not a new scientific validation of any KI.

The question was whether an agent can reconstruct:

**requirement → selected source/value → input artifact(s) → preparation action → consumer**.

The codebase-design skill informed the recommendation to expose one planning interface backed by these existing declarations and instructions, rather than introduce a new independent source of scientific truth.

## Overall finding

The required knowledge is often present and intelligible to an agent, but distributed across several documents and tool interfaces. A missing normalized field is not evidence that the KI lacks the knowledge, nor that its scientific model is broken. In particular, preparation-stage documents frequently already have input/source/unit tables, output filenames, and the next consuming stage.

No single global rule such as "parameter = scalar", "forcing = database download", "one input = one file", or "source_kind=calibrated means no starting value exists" fits this slice. Templates, packaged crop libraries, model-internal defaults, generated upstream products, user observations, parameter arrays, and mixed input decks are all normal cases.

## Every package examined

The last column records the selected stage document in addition to the package SKILL and declarations. Statements describe planning interpretability, not a new claim about scientific correctness.

| Package | Five-link planning interpretation / distinction | Stage document inspected |
|---|---|---|
| APEX | Template workspace plus weather/soil/site/control/management edits; `.SOL` mixes parameters and initial pools. | `docs/s3_build_soil.md` |
| Amanzi_ATS | Soil measurements or PTF values become material JSON/XML; mesh and process-kernel choices remain separate prerequisites. | `docs/s2_soil_parameterization.md` |
| BMI | A framework: selected wrapped model determines the real inputs; heat-template defaults are not universal BMI requirements. YAML config feeds `initialize`. | `docs/s1_configuration_setup.md` |
| CISM | Climate/PDD choice produces SMB and temperature fields; scalar/staggered grids and config selectors determine consumers. | `docs/s1_input_generation.md`, `docs/s2_forcing_preparation.md` |
| COAWST | Multiple domains and IC/BC/forcing files; parent-model outputs, tidal data and atmospheric reanalysis have different preparation routes. | `docs/s2_forcing_preparation.md` |
| CRHM | Selected module chain and HRUs determine parameters; derived JSON/overrides feed the `.prj` alongside `.obs`. | `docs/s4_parameter_config_skill.md` |
| Cell2Fire | Fire-model choice changes weather columns/fuel codes; co-registered rasters and lookup tables feed the instance folder. | `docs/01_landscape_preparation.md`, `docs/02_weather_preparation.md` |
| DHSVM | Soil map, class parameter table and JSON intermediate are distinct products; terrain/network setup is not supplied by weather retrieval. | `docs/s3_soil_parameters.md` |
| DSSAT | A `.SOL` can contain several pedons selected by FileX ID; cultivar and management are library/decision inputs, not generic forcing. | `docs/s3_soil_setup_skill.md` |
| Delft3D | Boundary source may be gauge, tide database, CaMa or parent-model output; FM versus FLOW selects different file families. | `docs/s4_boundary_conditions.md` |
| EF5 | SKILL/stage docs describe CREST/SAC scalar/grid parameters; quarantined DAG and surviving HYPE format metadata require explicit conflict handling. | `docs/s3_parameter_preparation.md` |
| EPANET | Demands and asset records produce sections of one `.inp`; chosen flow-unit system controls other units. Meteorology is not the core input. | `docs/02_demand_preparation.md` |
| Elmer_Ice | Climate/environment fields become named boundary files, then SIF keywords; geometry/mesh and physics choices govern applicability. | `docs/s3_forcing_preparation.md` |
| FloPy | User geology or optional measured K feeds per-layer arrays consumed by NPF/LPF/STO packages; selected packages decide needed inputs. | `docs/s2_aquifer_properties.md` |
| GEOtop | Soil properties plus user layer discretization become per-point soil CSV; forcing cadence/time convention is explicit in SKILL. | `docs/s2_soil_parameters.md` |
| GR4J___airGR | Four calibrated model parameters are distinct from catchment area and optional snow hypsometry; physical data need not be a parameter assignment. | `docs/s2_catchment_parameters.md` |
| GeoClaw | Earthquake geometry/slip is a source choice and preparation input producing dynamic topography, not an ordinary climate dataset. | `docs/s2_earthquake_source.md` |
| HYPE | Land cover plus soil generate SLC fractions and class definitions, then GeoData/par consumers; optional lakes require additional products. | `docs/s2_slc_classification.md` |
| HydroTrend | Monthly statistics and physical/hydraulic values assemble one ordered 47-line input deck; climate statistics differ from daily observations. | `docs/03_input_file_assembly.md` |
| LDNDC | Ecosystem choice maps to process modules in setup XML; climate, site, management and chemistry occupy separate linked files. | `docs/s3_setup_modules_skill.md` |
| LPJmL | Soil texture becomes grid-aligned class binary; land-use files and spinup/restart state are different acquisition/preparation classes. | `docs/s2_soil_parameters.md` |
| MARRMoT | Selected model structure determines parameter vector and bounds; soil-derived initial suggestions are starting points, not calibrated truth. | `docs/s2_parameter_estimation.md` |
| MONICA | Management records and packaged species/cultivar references form crop JSON; soil/site and climate remain separate inputs. | `docs/03_crop_rotation_setup.md` |
| OGGM | Built-in downloader, custom climate and GCM/SSP routes are explicit alternatives; glacier directories and baseline must exist first. | `docs/s3_climate_input_skill.md` |
| OpenHydroQual | Topology, geometry, reaction choices and prepared series assemble an `.ohq`; named blocks/links bind values to consumers. | `docs/s3_model_construction.md` |
| PHREEQC | Lab chemistry and reporting units become SOLUTION blocks; selected thermodynamic database and reaction type are independent choices. | `docs/s1_solution_definition.md` |
| PRMS | HRU attributes and soil/land data become dimensioned parameter file; module and unit-system selection shape conversion. | `docs/s2_parameter_preparation.md` |
| PyAEZ | Climate arrays, spatial rasters and crop/soil Excel tables feed different modules; their required shapes and units are already documented. | `docs/s0_data_preparation.md` |
| PySWMM | Soil data produces an infiltration section of a mixed `.inp`; method choice changes the parameter set, while network data stays user-specific. | `docs/s2_soil_infiltration.md` |
| RAPID | Upstream runoff plus reach areas/order/timestep becomes volume per reach per period, not another rainfall download. | `docs/s2_lateral_inflow.md` |
| RZWQM2 | Explicit soil-source priority and PTF steps produce mixed scenario files; management/cultivar and initial conditions have their own binding. | `docs/s4_soil_setup_skill.md` |
| SFINCS | Rainfall, upstream river output and optional coastal BC are separate conditional inputs; grid metadata is consumed during preparation. | `docs/s4_forcing_skill.md` |
| SUMMA | Decisions, table defaults, trial overrides, forcing and initial-state files are separate; HRU and GRU parameter representations matter. | `docs/s4_parameters_skill.md` |
| SWAT_Plus | Five weather-variable file families plus station indexes/mapping; source coverage must include warmup and preserve extrema. | `docs/s3_weather_preparation_skill.md` |
| SimPEG | User survey, uncertainty, map type and physical-property values generate a model-space vector and config; not a generic meteorological flow. | `docs/s2_model_parameters.md` |
| TOPMODEL | Parameters, initial conditions and a mode flag share one ordered params row; TWI and forcing are separate products. | `docs/s3_parameter_setup.md` |
| VELMA | Texture lookup, soil CSV or manual values are declared alternatives for a four-layer parameter JSON consumed by its run tool. | `docs/s2_soil_parameter_setup.md` |
| WOFOST | Built-in versus custom crop YAML is explicit; crop/variety selection and hierarchical inheritance precede assembly with weather and soil. | `docs/s1_crop_params_skill.md` |
| WSIMOD | Node-specific parameters come from GIS, utility, design or monitoring records; config dictionaries can be inputs without standalone files. | `docs/s4_parameters_skill.md` |
| mHM | Physiography plus climate preset yields global MPR coefficients, not per-cell calibrated maps; later calibration/transfer has distinct provenance. | `docs/s3_mpr_skill.md` |
| pyBadlands | Rainfall may be a scalar or map; sea level and tectonic events require different time/unit transformations and XML bindings. | `docs/s3_forcing_preparation.md` |
| tRIBS | Lookup tables differ from spatial maps and mesh; documented builders connect basin geometry to node classes and control-file references. | `docs/s2_soil_landuse.md` |

## Four concrete source-to-consumer examples

### 1. CRHM — derived values plus selected process chain

`models/CRHM/SKILL.md:173` explicitly describes HWSD/DEM/literature → `derived_params.json` → `create_prj_file.py --derived_params` → `.prj`. The table at line195 connects particular module parameters to sources and references. `docs/s4_parameter_config_skill.md:18` names HRU JSON, module-chain JSON, observation path and dates as inputs. `tools/s4_parameter_config/create_prj_file.py:464` accepts these and loads the optional derived JSON at line473.

The relationship exists now. A planning row should surface its effective source and the source document/tool locator; it should not demand that every coefficient become an independent uploaded file or database lookup.

### 2. SUMMA — defaults, overrides and array representation

`models/SUMMA/docs/s4_parameters_skill.md:9` explains table defaults and trial-parameter overrides, with physics-decision applicability at line14. `tools/s4_parameters/set_trial_parameters.py:336` is the manual adapter: a scalar expands to all HRUs, while a list is written as an HRU array (lines351–357); `generate_from_hwsd` at line193 is another route. The implementation also contains GRU-dimension basin-parameter handling at line280 and explicit canopy-default caveats at line119.

An agent can resolve the chain, but an unqualified "uses defaults" label is too shallow. The UI must show which default table/branch applies, whether a supplied override wins, and whether values are scalar, per-HRU or per-GRU.

### 3. RAPID — a prepared coupling artifact

`models/RAPID/docs/s2_lateral_inflow.md:12` links runoff, catchment area, `riv_bas_id.csv` and `ZS_TauR` to `Vlat.nc(time,rivid)` in cubic metres. `tools/convert_lsm_to_vlat.py:3` repeats this interface and explains why volume is not discharge. `SKILL.md:195` places this preparation before namelist assembly and RAPID execution.

For an existing upstream model run the source can be its output. Database discovery is one possible alternative, not an obligatory step for this row. The approved temporal interval and reach alignment are part of the binding, not merely a filename.

### 4. PHREEQC — user observations and model-specific choices

`models/PHREEQC/docs/s1_solution_definition.md:9` identifies lab/field chemistry, pH, temperature and concentration units; its output at line20 is `.pqi` SOLUTION blocks plus a conversion summary. `SKILL.md:140` then connects solution definition, thermodynamic-database selection and reaction setup to assembled input and execution. `tools/convert_solution_input.py:123` consumes CSV rows; lines184–189 emit solution metadata and units.

A useful nuance is visible by reading both docs and implementation: the document calls pH and temperature required, while `META_FIELDS` at tool line46 declares fallback values (pH7, temperature25). This is a planning clarification point, not proof of a failed model: a missing measurement and a tool fallback must be distinguished and not presented as measured data. The applicable policy should be explicit in the plan.

## Parser limitations versus content/discoverability issues

### Desktop representation limitations

- `kiss/kiss_cli/preparation.py:172` uses group/keyword heuristics for lanes. A choice, scalar, observation, or parameter array can share a broad DAG group. The source content can be clear while its projected lane/action is wrong.
- `preparation.py:224` does not retain applicability; `:249` drops top-level `model_input_format` while preserving it only within variants. Single-variant UI hides that variant (`web/app.html:1546`). This loses existing knowledge; it is not a missing KI contract.
- Source-kind tags describe origin or derivation, not the full effective-value selection. "Calibrated" does not establish whether to upload a file, choose a prior value, derive a baseline, or reuse calibrated values.
- Stage docs and tools contain valid information absent from typed DAG fields. An agent-resolved planning record can cite that evidence; a desktop parser should not invent missing joins or conflate absence with failure.
- BMI is a positive counterexample to a mandatory-DAG rule: no `dag.yaml` is present, but `docs/format_spec.yaml` contains nested parameter defaults/ranges, grid/time and compliance information. Its selected model, not a universal meteorological schema, supplies scientific meaning.

### Existing content or discoverability debt (not scientific revalidation)

- **EF5 known quarantine with a surviving stale fallback:** `dag.yaml.WRONG-MODEL-HYPE.README.md` already explains why its HYPE DAG was quarantined. However `docs/format_spec.yaml:4` still labels itself EF5 while declaring `implementation.id: hype-5-35-0` and HYPE `Pobs.txt`/`GeoClass.txt` inputs. Its actual EF5 SKILL/stage docs describe CREST/SAC grids and `control.txt`. Do not accept the stale fallback as authoritative simply because YAML parses. This is a contract conflict; no run was tested here.
- **Tool naming can be resolvable rather than genuinely missing:** Cell2Fire SKILL line201 names `convert_landscape_to_c2f`, absent from the executable file list. But `docs/01_landscape_preparation.md:59` directs terrain preparation through `convert_fuel_params.py --elevation`, and the actual `compute_slope_aspect` implementation exists at tool line196. A name mismatch should lead to protocol/tool inspection, not an invented tool call or "model cannot work" conclusion. This inspection does not prove all landscape preparation is automated.
- **Generic data-preparation boilerplate can overlead:** EPANET and SimPEG contain shared meteorological-loader guidance, while their actual input/pipeline sections describe demand/network and geophysical-survey workflows. The selected process and model-specific stage contract should determine relevance.
- **Stale data-KI references coexist with newer routes:** several SKILL files still refer to `data_ki/...`; GEOtop lines75–79 and SWAT_Plus lines129–131 explicitly explain their removal and point to shared utilities. Preserve current tool discovery and source locators instead of blindly following old example paths.
- **Historical examples are not a universal plan:** defaults, source priority, climate presets and site-specific learned guidance must be contextualized to the requested project. They are valuable evidence, not automatic authorization to apply the same location, periods or scientific choices everywhere.

## Planning acceptance suggestions

1. Build an agent-readable draft with the five links and evidence locators from the current KI; preserve unknown/conflicting links instead of inventing them.
2. Include one case from each normal shape: user CSV/observations, scalar/library choice, per-cell parameter array, mixed deck, upstream generated artifact, and framework-selected model.
3. Test replacement binding: selecting a user file means subsequent preparation receives that exact file/member/variable, with generated or built-in fallback remaining visible rather than silently winning.
4. Exercise conditional inputs and precedence: SUMMA decisions/table versus trial override, Cell2Fire fire-model weather schema, and optional river/coastal forcing.
5. Check consumer evidence, not merely file existence: relevant model path, variable/profile ID, unit/shape and consuming step are preserved. A present file is not automatically scientifically valid.
6. Test conflict handling with EF5's already quarantined metadata and positive format-spec-only handling with BMI. Neither should trigger blanket scientific judgments about the whole library.

The output of this pre-evaluation is an integration plan and representative fixtures. It is not a request to rerun or rebuild all models, nor to require every KI to be rewritten before improving desktop planning.
