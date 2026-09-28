# KI input-flow pre-evaluation — Slice B

Date: 2026-09-27. Source baseline: `bdf2522e` plus the current working tree.

Scope: the 42 packages at indices `i % 3 == 1` in `sorted(Catalog(Path("models")).packages)`. Read-only examination of each package's input declarations, SKILL input/preparation/pipeline sections, and workflow references; deeper source inspection of four representative tools. This is not a scientific validation or an execution test. No models, providers, live database requests, or live app state were used.

The question is whether GeoForge can present an honest chain:

`requirement → selected source or value → actual files → preparation → consumer`

## Conclusion

The existing KIs already contain substantial knowledge for this chain. Much of it is in prose, stage documentation, CLI examples, or library APIs, rather than uniform machine bindings. That is useful knowledge an agent can interpret; missing structured bindings must not be reported as a scientific KI failure.

The current planner loses important parts of that knowledge before the UI sees it. A richer project input table should preserve KI-local requirements and their provenance, allow agent-proposed bindings grounded in those references, and distinguish a proposed/default recipe from an inspected file or an executed preparation step. Do not rewrite every KI into a new schema as a prerequisite.

## All examined packages and workflow patterns

The reference column points to the relevant SKILL section; `dag.yaml` and `docs/format_spec.yaml` input shapes were also inspected for each package. ESMF and PyMT have a format specification but no `dag.yaml` in this checkout. Rows describe documented workflows, not proof that the current machine can execute them.

| KI | Input/preparation pattern that the table must represent | SKILL reference |
|---|---|---|
| ANUGA | Rain-on-grid **or** upstream hydrograph; DEM, mesh and datum; weather → rainfall CSV or gauge series → inflow CSV → solver | `models/ANUGA/SKILL.md:92`, `:311` |
| Alpine3D | Station SMET weather, layered SNO profiles, DEM/land-cover grids and `io.ini`; optional MeteoIO generators and SnowDrift wind fields | `models/Alpine3D/SKILL.md:378`, `:570` |
| BIOME_BGC | Weather → fixed-column `.met`; site `.ini`, EPC library, CO2/N deposition choices; spin-up state | `models/BIOME_BGC/SKILL.md:134`, `:186` |
| CE_QUAL_W2 | Bathymetry and branch topology; meteorology, inflow/outflow, initial profiles and WQ choices → fixed-width control deck | `models/CE_QUAL_W2/SKILL.md:178` |
| CLM5___CTSM | Compset/resolution selection; surface, soil, domain/mapping and DATM streams → CIME namelists; site-tower alternative | `models/CLM5___CTSM/SKILL.md:84`, `:198` |
| CREST | DEM → DDM/FAM; precipitation/PET grids; soil → parameter grids; routing-method-specific configuration and gauges | `models/CREST/SKILL.md:151` |
| CaMa_Flood | Upstream runoff conversion → source-grid mapping and regional river maps → generated run script → MAIN_cmf | `models/CaMa_Flood/SKILL.md:88`, `:173` |
| DART | Observations **or explicitly selected OSSE synthetic path**; model-specific ensemble restart states → observation sequence → assimilation | `models/DART/SKILL.md:176` |
| DNDC | Climate text, soil profile, crop/management calendar → `.dnd` assembly → batch execution | `models/DNDC/SKILL.md:208` |
| DayCent | Weather/site/soil/libraries plus management schedules; equilibrium → base history → treatment with predecessor state archives | `models/DayCent/SKILL.md:134`, `:411` |
| DualSPHysics | Geometry and physical choices → XML; wave/current inputs; GenCase → initial particles → CPU/GPU solver | `models/DualSPHysics/SKILL.md:101`, `:212` |
| ELMFIRE | Landscape and weather raster sets → namelist and ignition choice; deterministic/ensemble paths | `models/ELMFIRE/SKILL.md:142` |
| ESMF | Source/destination grids, remapping method, masks/corners/areas; generated weight file or coupled component states; framework rather than a single fixed physical-model input list | `models/ESMF/SKILL.md:144`, `:299` |
| FSM2 | Sub-daily meteorology with DRIV1D-specific columns; compile-time physics and namelist parameters; hourly loader rather than generic daily forcing | `models/FSM2/SKILL.md:70`, `:217` |
| GEOPHIRES | Site/reservoir/economics values → parameter text file; model-dependent external simulator/temperature file; no weather forcing required by the input schema | `models/GEOPHIRES/SKILL.md:142`, `:163` |
| GLM | Morphometry, met/inflow/outflow CSVs, initial profiles and optional AED2 chemistry → namelist → lake model; optional downstream coupling | `models/GLM/SKILL.md:132`, `:340` |
| GemPy | Static contact points and orientations, geological structure/fault relations, grid choices → Python model; no time-series forcing or initial state | `models/GemPy/SKILL.md:194`, `:259` |
| HEC_RAS | Existing project or authored geometry; flow profiles, roughness and boundary choices → real steady solver; unsteady path has separate platform/orchestration requirements | `models/HEC_RAS/SKILL.md:181`, `:194` |
| HydroCNHS | Per-subbasin climate, GWLF/ABCD parameters and routing topology → YAML; optional human-agent Python rules | `models/HydroCNHS/SKILL.md:135` |
| KINEROS2 | This package's documented lumped daily workflow: weather + Green-Ampt parameter JSON → configured/calibrated execution | `models/KINEROS2/SKILL.md:168`, `:303` |
| LPJ_GUESS | This package's disclosed analytic implementation: FLUXNET/reanalysis → standardized forcing CSV; PFT/site values → JSON | `models/LPJ_GUESS/SKILL.md:80`, `:267` |
| Lohmann_Routing | Upstream VIC output must become seven-column daily files; DEM/basin/outlet → D8, fraction, distance, station and unit-hydrograph files | `models/Lohmann_Routing/SKILL.md:81`, `:160` |
| MOM6 | Supergrid, bathymetry, atmospheric fluxes, initial state and optional regional OBCs → multiple INPUT files plus MOM namelists | `models/MOM6/SKILL.md:152` |
| Noah_MP | Domain/setup NetCDF, soil/vegetation tables, LDASIN forcing, initial state, physics options; tower column and routed basin are different workflows | `models/Noah_MP/SKILL.md:81`, `:291` |
| OpenGeoSys | Mesh/geometry, material properties, time-dependent BCs and process selection → XML `.prj` plus referenced files | `models/OpenGeoSys/SKILL.md:144` |
| PFLOTRAN | Grid, region/material assignment, chemistry, BCs and ICs → hierarchical `.in` deck; optional coupling | `models/PFLOTRAN/SKILL.md:162`, `:196` |
| PISM | Geometry bootstrap, climate/ocean inputs, model selections → configuration and long spin-up → transient run; explicit synthetic benchmarks are separate | `models/PISM/SKILL.md:150`, `:183` |
| PorePy | Geometry/fractures, SI material constants, BC/IC functions, discretization and solver choices → Python dictionaries and composed model classes | `models/PorePy/SKILL.md:135`, `:205` |
| PyMT | Select installed BMI plugin → discover parameters and input/output variables → `model.setup()` config → initialize/run/couple; requirements depend on the selected plugin | `models/PyMT/SKILL.md:190` |
| QUINCY | This package's disclosed analytic implementation: forcing CSV + PFT/physiology JSON → model execution | `models/QUINCY/SKILL.md:116` |
| ROMS | Grid, compile-time CPP physics, atmosphere, ICs, OBCs, tides → multiple NetCDFs plus `roms.in`; some stages require external tools | `models/ROMS/SKILL.md:158` |
| Ribasim | Node/link network plus basin profiles, time/static tables, pumps/control/demand rules → GeoPackage + TOML | `models/Ribasim/SKILL.md:94`, `:481` |
| SNOWPACK | SMET weather + layered `.sno` profile + `.ini` options → spin-up then production | `models/SNOWPACK/SKILL.md:178` |
| SWAP | Weather `.met`, layered hydraulic properties, crop rotation and irrigation → `.swp` assembled from a validated base, with referenced `.crp` files | `models/SWAP/SKILL.md:151`, `:223` |
| SimFire | Operational landscape **or procedural demonstration**; wind source, derived fuel moisture and ignition → YAML/API; observed perimeter must match grid | `models/SimFire/SKILL.md:147` |
| TELEMAC_MASCARET | Mesh `.slf` plus boundary `.cli`, met/tidal forcing, bathymetry, selected module → steering `.cas` | `models/TELEMAC_MASCARET/SKILL.md:207` |
| TopoFlow | DEM/D8, weather, soil and channel grids; component/provider selection → multiple `.cfg` files → EMELI | `models/TopoFlow/SKILL.md:146`, `:198` |
| WASP | This package's disclosed analytic lake-WQ workflow: observations → cleaned T/DO/Chl-a inputs; morphometry and kinetics → parameters | `models/WASP/SKILL.md:88`, `:189` |
| WRF_Hydro | Basin/DEM/land-cover/soil sources → geogrid, initial state, routing and groundwater files; weather → LDASIN; namelists bind all artifacts | `models/WRF_Hydro/SKILL.md:223`, `:1157` |
| icepack | Glacier outline → mesh; thickness/bed/velocity → FEM fields; Python solver parameters; diagnostic, prognostic and inverse workflows | `models/icepack/SKILL.md:164` |
| openAMUNDSEN | Project grid/DEM and station metadata/weather in parallel → YAML configuration → model initialization/execution | `models/openAMUNDSEN/SKILL.md:158`, `:310` |
| pySTEPS | Ordered radar frame collection + metadata → precipitation arrays → motion → nowcast; method, cadence and transform choices; not daily reanalysis forcing | `models/pySTEPS/SKILL.md:114`, `:197` |

## Concrete gaps in the current planner

### 1. KI-local/user-owned requirements are not equivalent to canonical database variables

`ki_tools_common/ki_tools_common/flow/ki_inputs.py:539` reads DAG input groups and retains a limited subset of their fields. `flow/plan.py:549` sends entries without a canonical ID into `ki_internal`, before considering user ownership. Those entries are not ordinary inventory requirements and are explicitly described as “never questions” at `plan.py:528`.

A pure, read-only call to `model_inputs(vocabulary_root, name, ki_root=repo / "models" / name)`, with `vocabulary_root=repo / "ki_tools_common/ki_tools_common/flow/data"`, verified the following. This is the desktop bundled registry: 492 aliases loaded, with VIC control inputs resolving to the expected temperature/precipitation/pressure/radiation IDs. An initial call using the repository as the vocabulary root was discarded because it loaded zero aliases.

- GemPy `surface_points` and `orientations`: `canonical_id=None`; their source kind is `user geological observation data`.
- icepack `glacier_outline`, mesh resolution, boundary IDs and model type: `canonical_id=None`, despite `source_kind=user_provided`.
- PorePy geometry, fracture network, boundary schedules and initial fields: `canonical_id=None`, despite `source_kind=user_provided`.
- GEOPHIRES reservoir depth, geothermal gradient, economic parameters and design choices: `canonical_id=None`, with `user_specified` or `user_choice` source kinds. Not every field is unresolved: its `Surface Temperature` resolves to `water_temperature`, another reason to preserve the local meaning rather than treat a vocabulary match alone as scientific suitability.

Their scientific meaning is already documented. Preserve their KI-local identity and explicit user/default/derived distinction even when there is no database vocabulary match. An agent can propose or interpret values without the platform pretending the input does not exist.

### 2. Framework discovery must be a legitimate planning step

ESMF and PyMT return `dag.yaml unreadable ... FileNotFoundError` from `model_inputs`, and `derive_plan_for_model` returns an empty/error plan at `plan.py:536`. Yet their format specs and SKILLs document meaningful inputs and workflows.

- ESMF `docs/format_spec.yaml:10` includes grid formats, coordinates, areas, time, and nested `parameters.critical`.
- PyMT `docs/format_spec.yaml:16` explicitly says inputs depend on the wrapped BMI model; `SKILL.md:200` describes discovery before configuration.

Do not invent a static weather checklist for these packages. Let discovery/inspection produce scoped requirements. An unavailable plugin is an environment/setup question, not proof that the framework KI is scientifically invalid.

### 3. A recipe/default is not an actual value or prepared artifact

`plan.py:554` changes a non-user-resolved requirement into `ki_default` with text saying the KI prepares it per SKILL. `to_artifacts` then emits `status=resolved`, `agent_resolvable=true`, empty `local_paths` (`plan.py:718–742`). The source comment correctly distinguishes source-known from file-ready; the new table should preserve and make that distinction visible.

Keep at least these evidence states separate: proposed recipe, selected source/value, located source file, prepared artifact, validated consumer binding. A default proposal should include the concrete value or referenced table/profile plus provenance when known, and remain editable by the user.

### 4. Shared source does not mean shared prepared input

`plan.py:720` merges inventory items by canonical ID and only adds `required_by`. It does not retain a per-consumer unit, shape, temporal resolution or preparation binding.

Examples in this slice:

- ANUGA rain input is m/s in `time_seconds,rainfall_m_per_s` CSV; its stage doc connects that file to `run_anuga.py --forcing_csv` (`models/ANUGA/docs/s1_convert_rainfall_forcing.md:5`).
- BIOME_BGC uses precipitation cm/day, VPD Pa and **daylight-average** radiation (`SKILL.md:140`).
- FSM2 requires sub-daily inputs and distinguishes DRIV1D column/humidity conventions (`SKILL.md:70`, `:217`).
- pySTEPS requires a sequence of radar fields and metadata at minutes cadence; `docs/s1_data_import.md:7` connects an archive to NPZ + metadata consumed by later stages.

A source can be reused; consumer preparation bindings still need separate records. Do not merge away the distinction between a raw dataset, converted forcing and upstream model output.

### 5. Mode and implementation scope change the required inputs

DART real assimilation vs OSSE, ANUGA rainfall vs riverine inflow, GLM AED2 on/off, PISM benchmark vs physical domain, HEC-RAS steady vs unsteady and SimFire operational vs procedural are explicit branches. Choosing all rows from all modes gives irrelevant questions and downloads.

Some packages explicitly disclose analytic/reimplemented workflow scope (LPJ_GUESS, QUINCY, WASP; KINEROS2 documents its lumped daily path). Record the actual selected implementation/consumer. Do not silently imply a more complete or different engine because a familiar model name appears in the catalogue. This review does not assess the scientific adequacy of those implementations.

### 6. Prose is valuable, but generic boilerplate is not a binding

GEOPHIRES and GemPy have generic `load_daily_forcing` prose under Data Preparation (`SKILL.md:75` and `:77`), while their actual DAG/spec correctly say no meteorological forcing for the static/site workflow. The planner/agent must reconcile the specific selected mode and actual tool interface, not treat every generic preparation paragraph as an instruction to download weather.

`flow/declared.py:78` finds a preparation tool through the first file-extension match in tool source; `:96` uses name/token/category matching. These are discovery hints, not proof that a tool consumes/prepares that particular requirement. Multiple `.nc`, `.csv` or `.json` artifacts are routine in this slice.

The desktop already has a useful richer reader in `kiss/kiss_cli/preparation.py:132`: it merges DAG and format-spec declarations and preserves nested details. Reuse or align that knowledge extraction with the shared flow rather than creating a third divergent reader. It still is not a runtime binding registry.

## Four representative tool inspections

1. **ESMF — `models/ESMF/tools/generate_regrid_weights.py:89`.** Inputs are concrete source and destination grid paths plus a remapping method; output is a weight-file path. Method selection changes grid requirements. The tool can use the executable or ESMPy (`:186`). This is a complete useful five-link example with no obligatory GeoForge DB acquisition. Source inspection only; this audit did not certify its scientific validation checks.

2. **PyMT — `models/PyMT/tools/configure_model.py:60`.** Enumerates plugin parameters/defaults; `configure_and_setup` checks override names against the selected plugin, uses `model.setup(path=..., **overrides)`, verifies the generated config path, and returns config path, input/output names and parameter metadata (`:79–138`). This existing tool provides the right kind of dynamic evidence for a project table. Parameter names cannot be inferred from a fixed generic PyMT checklist.

3. **PorePy — `models/PorePy/tools/run_porepy.py:80`.** Builds a Python model script from JSON configuration, material constants, meshing/time/solver values and selected model class. General user-defined geometry/BC/IC composition is documented in SKILL; it is not all represented by this wrapper's limited config keys. The wrapper also writes `/tmp/porepy_run.py` (`:239`), illustrating why project cwd alone does not guarantee every artifact is project-owned. Record the actual supported consumer/config target; do not claim every library capability is wired by the generic wrapper.

4. **WRF-Hydro — `models/WRF_Hydro/tools/run_wrfhydro_full_pipeline.py:7`.** Gives a concrete many-source/many-artifact chain. Source paths are explicit CLI overrides (`:237`); `output_dir/DOMAIN` and `output_dir/FORCING` contain named generated artifacts (`:291`). `build_geo_em` consumes DEM, land cover, soil raster/MDB and basin shape (`:382`). Defaults also assume a specific installed/server layout (`:62`), and soil parameter table paths are inserted separately (`:444`). The planner should show the effective paths/values used, including installation assets, rather than only a general data folder.

Related inspected stage reference: `models/CaMa_Flood/docs/s2_configure_basin.md:7` explicitly requires global maps, GPCC climatology and the upstream runoff/source grid, and writes basin maps plus the generated run script beneath the CaMa installation. Installation assets, project-generated maps and shared immutable sources are different ownership roles.

## Implications for the proposed unified input table

- Use a stable **KI-local requirement ID** even without a canonical vocabulary match. Canonical IDs are optional search/coupling aids.
- Allow source/value variants: user file/collection, user scalar/choice, referenced model default/library, derived artifact, upstream model output, database record, external service and runtime-discovered framework input.
- Retain a consumer-specific binding: stage/tool or API, config key/CLI argument/file slot, expected unit/shape, selected mode and the evidence reference used to propose it.
- Permit one source to feed several prepared artifacts, and several sources to produce one deck/profile/network. A five-link row need not mean exactly five physical files.
- Distinguish proposed names from real paths and validated content. Actual-file entries should come from inspection or preparation results, not from the mere presence of a recipe.
- Preserve user overrides and local-only/no-DB workflows. Database search is optional source discovery, not mandatory scientific planning.
- Scope readiness to the next permitted stage. A required runtime-discovery step can be ready even while its later scientific inputs are still unknown.
- Keep the existing prose available to the agent with citations and let it propose bindings. Check accepted concrete paths, tool/config targets and preparation evidence deterministically where possible; unknown applicability should remain a question, not silently become an invented default.

## Limits

This was a breadth-first source pre-evaluation, not a line-by-line audit of every SKILL document or every tool. Detailed tool inspection was limited to the four tools above; selected stage references were read for ANUGA, CaMa-Flood and pySTEPS. File existence, installation readiness, scientific correctness of datasets, live provider behavior and successful model runs were not tested. The pure extractor replay tested only current planning representation.
