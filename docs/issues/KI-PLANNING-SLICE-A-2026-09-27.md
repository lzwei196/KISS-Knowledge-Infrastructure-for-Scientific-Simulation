# KI project-input planning audit — slice A

Date: 2026-09-27. Scope: repository KIs at indices `0, 3, 6, ...` in
`sorted(Catalog(Path('models')).packages)`: **43 packages**.

This is a read-only **planning/content audit**, not scientific revalidation, an
installation test, or a model run. For every package below I inspected relevant
SKILL workflow/data-preparation sections, DAG and format-spec input declaration
shapes, and referenced preparation tools. I read four representative tool routines
in detail. No provider, live project, network request, or model execution was used.

The proposed five-link flow is interpreted here as: project requirement → selected
source/value → acquired/raw artifact → prepared model artifact/configuration →
consuming step. These are associations to establish, not five mandatory files.

## Result

All 43 packages have meaningful DAG/format-spec declarations that the current
Desktop preparation reader can enumerate. They also carry agent-readable workflow
instructions. **Missing a uniform machine-readable mapping does not mean a KI is
unusable.** The main gap is that Desktop currently flattens rich information into a
requirements checklist; that checklist is not an authoritative project binding.

The count below is the output of the actual current `_model_inputs(ki)` function,
not a count of files, missing datasets, required downloads, or validated inputs.

## Every examined KI

| KI | Parsed entries | Existing preparation / consumer pattern |
|---|---:|---|
| ADCIRC | 10 | Mesh/bathymetry `fort.14`, attributes `fort.13`, tides/met forcing and `fort.15` control; coupled fixed-name file bundle. |
| APSIM | 32 | NetCDF/CSV weather → `.met`; soil → JSON; those plus crop/management → `.apsimx` case. |
| AquaCrop | 33 | Weather/ET0 → prepared dataframe; soil/crop/management objects → simulation configuration. |
| CAESAR_Lisflood | 23 | DEM ASCII grid, rainfall-zone/time files, grain parameters → case/run directory. |
| CLASSIC | 36 | Per-variable NetCDF forcing + initialization/restart NetCDF + joboptions namelist. |
| COSIPY | 36 | Weather → forcing NetCDF; terrain → static NetCDF; constants/config TOML; point runs can bypass static builder. |
| CWatM | 24 | Meteorology/static/soil preparation → NetCDF/maps and settings; basin-specific static builder. |
| Climate_Projection | 26 | Historical/future CMIP6 + basin grid + existing VIC baseline forcing → deltas → scenario forcing. |
| DLBreach | 32 | Dam/site geometry + reservoir curves + observed or CaMa-derived inflow → breach input cards. |
| Daisy | 24 | Weather → `.dwf`; soil/management → `.dai`; main `.dai` and libraries → run. |
| DuMux | 16 | Mesh and physical fields → DGF/Eclipse/INI case; some model choices live in C++ Problem/SpatialParams code. |
| ELM | 24 | Domain/surface data, DATM forcing streams, restart and namelist settings → CIME case. |
| EPIC | 20 | Weather/site/soil/operations and fixed-width tables → copied/edited model deck; instructions explicitly prefer copy-first. |
| FATES | 32 | Plant/soil parameters, surface data and forcing → host-model CIME/CTSM case; not a standalone weather-file consumer. |
| ForeFire | 18 | DEM/fuel/wind → landscape NetCDF; fuel table and ignition script → fire case. |
| GIFMod | 28 | Soil/network definition plus weather CSV → `.GIFMod` network/case. |
| GSFLOW | 35 | PRMS forcing/parameter/control bundle + MODFLOW packages and coupled exchange configuration. |
| HEC_HMS | 23 | Meteorological/PET forcing plus subbasin/method parameters → basin simulation wrapper. |
| HexWatershed | 18 | DEM + mesh/flowline/basin JSON → watershed routing structure; no atmospheric forcing declaration. |
| ISSM | 23 | Mesh, per-vertex/per-element fields, SMB/thermal/boundary data → model objects; not one flat forcing table. |
| LISFLOOD | 37 | Meteorology/evaporation → NetCDF/PCRaster; static maps and warm state → XML-configured case. |
| Landlab | 20 | Grid/elevation fields + rain scalar/array + components/initial/boundary conditions → landscape workflow. |
| MODFLOW6 | 23 | Recharge and groundwater boundary data + grid/material/solver choices → FloPy-generated per-package model deck. |
| MOSART | 20 | Upstream runoff, river-domain/network data, optional demand/reservoir configuration → routing case. |
| OpenFOAM | 14 | Mesh and physical/solver/boundary fields → `0/`, `constant/`, `system/` case directory. |
| PCR_GLOBWB_2 | 24 | Clone/LDD/static maps, exact-variable meteorology NetCDF and states → INI-configured case. |
| PIHM | 20 | DEM/mesh, weather, soil/geology/land cover, river and attributes → multi-file model deck. |
| ParFlow | 24 | Domain/grid + physical properties/slopes + meteorology → PFB/CLM inputs and YAML/TCL case. |
| PyDeltaRCM | 36 | Scenario parameters/defaults, seed and optional checkpoint → YAML configuration; no forcing dataset is intrinsically required. |
| Pywr | 15 | Inflow/demand time series, reservoir/network/control-curve choices → JSON network and DataFrameParameter inputs. |
| RHESSys | 38 | Station weather bundles + world/header/flow/defaults/TEC → watershed case. |
| Raven | 26 | `.rvt` forcing + `.rvh/.rvp/.rvi/.rvc` basin/parameter/control/state bundle; stage basin/forcing before initialization. |
| SHAW | 37 | Weather and site/profile/state preparation → `.wea/.sit/.inp/.moi/.tem` file bundle. |
| SWAN | 15 | Bathymetry, wind/current/water-level and optional boundary spectra → command-file case; requirements depend on scenario. |
| SWMM | 32 | Rain and GIS drainage/subcatchment/LID information → aggregate `.inp` deck. |
| SuperflexPy | 19 | Observed meteorological arrays + topology, prefixed parameter and state dictionaries → JSON/in-memory model inputs. |
| TRIGRS | 24 | DEM/slope/flow topology, property zones, step rainfall periods → `tr_in.txt` and raster bundle. |
| VIC | 48 | Grid/soil/vegetation/snowbands and per-cell weather → global parameter file and run; soil/grid preparation precedes forcing conversion. |
| WRF | 12 | 3-D atmospheric boundary inputs + geodata → WPS/met_em → real.exe input/boundary files → WRF run. |
| dfnWorks | 29 | Fracture geometry/distributions and hydraulic/transport parameters → DFNGen/PFLOTRAN deck; no atmospheric forcing declaration. |
| mizuRoute | 12 | Upstream runoff + topology/remapping → routing NetCDF + generated control file. |
| pyGIMLi | 17 | ERT/SRT/IP/EM measurements, sensors, mesh and inversion settings → geophysical inversion workflow. |
| wflow | 29 | HydroMT basin/static preparation + forcing NetCDF + state/configuration → TOML-based model case; SBM/GWF/sediment variants. |

## Four actual tool routines: existing links are real, not merely filenames

### APSIM: raw weather → prepared `.met` → case consumer reference

1. `models/APSIM/tools/convert_met.py:311` branches between shared forcing
   loaders, NetCDF and CSV sources. Lines 339–381 construct an APSIM weather
   header and columns with explicit units; lines 468–470 write the prepared
   artifact at the caller's `--output`.
2. `models/APSIM/tools/build_apsimx.py:304` loads soil JSON and assembles the
   case. Lines 320–329 resolve `--met-file` to an absolute path, explicitly
   explaining why APSIM's `%root%` does **not** mean the case directory. Lines
   411–414 place that actual path in the Weather object's `FileName`.

Thus one weather requirement can be satisfied by several source formats, but the
consumer requires a prepared `.met` reference embedded in a separate case file.
Relocating raw files alone does not repair the embedded absolute path. This audit
does not validate weather values, soil suitability, or successful APSIM execution.

### mizuRoute: upstream model output → routing field → control-file binding

3. `models/mizuRoute/tools/s3_runoff/convert_vic_runoff.py:233` scans the caller's
   VIC result directory against the grid. Lines 248–251 and 279–282 convert
   runoff depth per model interval to mm/s. Lines 300–330 write `RUNOFF` in the
   caller's NetCDF output, including units and source/conversion metadata.
4. `models/mizuRoute/tools/s4_control/generate_control_file.py:110` checks the
   supplied network/runoff/remap files. Lines 129–139 derive absolute directories
   and basenames; lines 160–180 embed those in the control file. The template at
   lines 44–54 and 73–76 links input directory + filename + variable/time-step
   conventions for the routing consumer.

Here the source is an upstream simulation, **not a database weather download**.
A correct project binding must preserve the producer, conversion, resulting
artifact and consumer configuration. Reading these routines does not establish
that a particular coupled simulation has run or passed validation.

## Concrete Desktop representation gaps

1. **Path hints are discarded.** `_normalise` in
   `kiss/kiss_cli/preparation.py:207` retains a limited metadata set. The actual
   current parser drops `path`, `path_china` and `path_global` from
   `Climate_Projection/docs/format_spec.yaml:90–106`. A parser-only replay showed
   `VIC baseline forcing` retains its description but not
   `outputs/{basin}/vic_temp/forcing/forcing_1d/`; historical CMIP6 loses both
   source hints. These are hints/placeholders, not automatically trusted actual
   project paths, but they should remain available to the agent as evidence.
2. **DAG groups are not semantic input kinds.** `_lane_for` at
   `preparation.py:172` puts every boundary/initial-condition declaration in
   `starting_state`. MODFLOW6's temporal discretization, solver, Newton switch
   and output controls are declared under boundary conditions, while other KIs
   put meshes/physical boundaries there. A new table cannot use group alone to
   decide file upload versus model parameter versus run setting.
3. **The action label is a heuristic, not readiness evidence.**
   `_action_for` at `preparation.py:188` infers broad actions from `source_kind`;
   the default message can say an agent can prepare something without an actual
   source, selected default, preparer, artifact or consuming-step binding.
4. **A uniform download path would misclassify valid workflows.** HexWatershed,
   PyDeltaRCM and dfnWorks have no atmospheric forcing; mizuRoute/MOSART primarily
   consume upstream runoff; MODFLOW6 explicitly needs recharge rather than raw
   weather; pyGIMLi consumes geophysical measurements. WRF requires 3-D atmospheric
   boundaries, so a matching generic weather label is insufficient.
5. **Bundles and conditional requirements matter.** OpenFOAM, EPIC, SWMM, CIME
   hosts and groundwater cases consume complete directories/decks, often mixing
   datasets, coefficients, state and run settings. SWAN and wflow variants have
   scenario-dependent needs. One requirement is not necessarily one file and a
   declared item is not necessarily required for every project.
6. **Cross-KI merging is presentation, not binding.** `_merge_requirements` at
   `preparation.py:232` groups by lane/name and preserves some per-model variants.
   It does not encode a producer/preparer/consumer path graph or distinguish
   shared raw data from model-specific derived artifacts. Keep explicit
   per-consumer bindings even when presenting one shared scientific requirement.
7. **Generic prose must not override specific workflow evidence.** The short
   shared forcing paragraphs at `dfnWorks/SKILL.md:69–75` and
   `pyGIMLi/SKILL.md:70–74` mention CMFD/MSWX/NASA POWER despite their actual
   fracture/inversion input workflows. Agents can resolve this from detailed
   DAG/stage instructions; a naive frontend using the paragraph would create
   irrelevant weather-download requirements.

## Design implications, not a proposed KI rewrite

- Reuse existing DAG/format-spec facts plus SKILL/tool evidence to let the agent
  propose project-specific requirements and bindings. Do not require all 43 KIs
  to grow identical declarative path maps before they can work.
- Keep scientific quantities, parameters, run settings, and artifact bundles
  distinct. Defaults are conditional proposals requiring suitability checks.
- GeoForge DB is an optional source candidate, alongside user data, existing
  local artifacts, public services and upstream model results.
- Record selected source/value, actual acquired paths, preparation operation,
  prepared output paths and consuming-step/config references separately.
- An agent may author the mapping; the host should check paths/permissions,
  existence and evidence without claiming these checks prove scientific validity.
- Restart/relocation needs regeneration or explicit repair of embedded case
  references, not only a different project-root string.

## Verification boundary

Executed only catalogue/parser calls with bytecode writes disabled. All 43
assigned `_model_inputs` calls returned nonempty lists. Explicit parser-loss
example above was reproduced with the actual current preparation function.
Tool routines were inspected, not imported or executed. There is **no claim**
that this audit revalidated any model, source dataset, installed runtime, or
scientific conversion.
