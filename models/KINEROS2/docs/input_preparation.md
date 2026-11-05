# KINEROS2 input preparation plan (real engine)

Sources: the ARS manual chapters shipped with the source (`src/doc/Input.pdf`, `Infilt.pdf`,
`Rain.pdf`, `Erosion.pdf`, `Channel.pdf`, `Overland.pdf`), the K2shell driver source
(`K2shell.f90`, `reader.for`, `rain.for`, `infilt_test.for`, `pond.for`, `inject.for`,
`kinsed*.f*`), and the two official ARS sample cases (`examples/ars_samples/`).

KINEROS2 is **not** a gridded, daily, forcing-driven model. One run = one storm. The watershed is a
hand-built (or AGWA-built) cascade of elements; the only time series input is breakpoint rainfall
in minutes. So "input preparation" here is: (1) describe the elements, (2) give each element its
soil/roughness parameters, (3) give the storm, (4) choose run settings. There is no PET, no
temperature forcing and no spin-up.

## 0. Three files and one batch line

| File | What | Who writes it |
|---|---|---|
| parameter file `.par` | GLOBAL block + one block per element, in processing order | copy an existing file, edit with `tools/edit_kineros2_par.py` / `kineros2_soil_params.py` / `configure_kineros2_sediment.py` / `add_kineros2_element.py` |
| rainfall file `.pre` | one block per rain gage: cumulative depth (or intensity) vs minutes | `tools/build_kineros2_rainfall.py` |
| multiplier file (optional) | 7 (or 13) lines of factors applied to every element | `tools/run_kineros2_engine.py --mult` / `calibrate_kineros2_multipliers.py` |
| `kin.fil` (batch) | `par,pre,out,"title",tfin,dt,courant,sed,mult|N,table` -- no spaces after commas | `tools/run_kineros2_engine.py` (never by hand) |

**File format (verified with `cat -A` and reader.for).** Tagged, not fixed-width: `TAG = v1, v2` lists
or a column header line (`KS G DIST POR ROCK`) with one value row per layer. Delimiters are any
non-"alpha" character; "alpha" is `0-9 A-Z . - / : \ _` -- so `+` is a separator (`1.6e+06` is read as
`1.6E` and `06`). Lines are upper-cased and only columns 1-200 are read. The ARS samples use CRLF line
endings; the engine reads them unchanged and the tools preserve them.

**Tag lookup (reader.for).** The engine asks for a short name (e.g. `KS`, `SA`, `PRI`, `CO`) and takes
the FIRST token in the block that starts with it and follows a comma or a line start. Consequences:
`PR = 2` is NOT a print flag (the engine asks for `PRI`); a list ends at the end of its line (the manual
says lists may continue -- the code does not).

## 1. GLOBAL block

| Tag | Meaning | Unit | New case | If missing |
|---|---|---|---|---|
| UNITS | METRIC or ENGLISH -- fixes the unit of EVERY other number, incl. the rain file | - | choose once | engine stops "units not specified" |
| CLEN | characteristic length (longest channel / plane cascade) | m / ft | longest flow path; sets the spatial step (CLEN-based increment warnings) | engine stops |
| DIAMS, DENSITY, TEMP | sediment classes (<=5), densities, water temperature | mm or in; g/cc; degC or degF | only for sediment runs (s4) | engine stops when sediment is on |
| SAT | uniform initial saturation for all elements (overrides gages and elements) | - | optional | per-element / per-gage SAT used |
| CHR / PR / GR / DIAG | rain on channels / on ponds / gage-by-element order / diagnostics.txt | Y/N | rarely | defaults N |

## 2. PLANE (overland flow element)

| Tag | Meaning | Unit (metric / english) | Where it comes from for a new case | Fallback |
|---|---|---|---|---|
| ID | element id (1-999999) | - | your discretisation | required |
| UPSTREAM | plane draining into this plane (cascade) | - | discretisation | none |
| LENGTH, WIDTH (or AREA/HA/ACRES) | flow length, width | m / ft | GIS: flow length to the channel, area / length | required |
| SLOPE | plane slope | m/m | DEM | required |
| MANNING (or CHEZY) | roughness | s m^-1/3 | land cover tables (AGWA lookups) | required |
| KS | saturated hydraulic conductivity | mm/hr / in/hr | `kineros2_soil_params.py` (HWSD + Rawls 1982), x(1-ROCK) | 0 = impervious |
| G | net capillary drive | mm / in | KINEROS2 Table 1 by texture | 0 = constant rate KS |
| DIST | pore size distribution index (<= 1.5) | - | Table 1 | engine stops if G>0 |
| POR | porosity | - | Table 1 | engine stops if G>0 |
| ROCK | volumetric rock fraction | - | HWSD gravel % / 100 | 0 |
| SAT | initial relative saturation (event specific) | - | antecedent rain / soil moisture; or per gage in the .pre | engine stops if G>0 and no gage SAT |
| CV | coefficient of variation of KS | - | literature 0.5-1.0 for rangeland | 0 |
| THICK + 2nd row of KS/G/DIST/POR/ROCK | two-layer soil | mm / in | soil survey horizons | single layer |
| INTER, CANOPY | interception depth, cover fraction | mm / in; - | vegetation | 0 |
| RELIEF, SPACING | micro-topography | mm / in; m / ft | field survey | none |
| X, Y | centroid for gage interpolation | same CRS as gage X/Y | GIS | required if >1 gage |
| ALF | infiltration function: <=0.04 Green-Ampt, >=0.96 Smith-Parlange, else 3-parameter (default 0.8) | - | keep default | 0.8 |
| PRINT (=PRI...) | 0 none, 1 summary, 2 + hydrograph table, 3 + CSV file (FILE=) | - | 2 on the outlet | 0 |

## 3. CHANNEL (and compound OVERBANK)

| Tag | Meaning | Unit | Source | Fallback |
|---|---|---|---|---|
| UPSTREAM (<=10), LATERAL (<=2 planes) | topology | - | network | none |
| LENGTH, WIDTH, SLOPE, MANNING, SS1, SS2 | trapezoid geometry/roughness (1 value or upstream,downstream) | m / ft | survey / DEM / AGWA hydraulic geometry | required |
| KS, G, DIST, POR, ROCK, SAT, CV, THICK | bed infiltration (transmission losses) | as plane | bed material; WG11 uses KS ~11 in/hr | impervious |
| WOOL = YES, WCOEFF | Woolhiser effective wetted perimeter | - | ephemeral sand channels | off |
| QB | baseflow at the outlet | m3/s / ft3/s | gauging | 0 |
| TYPE = COMPOUND + OVERBANK block | overbank section | - | cross sections | simple |

## 4. Other elements (s5)

POND (rating table V/D/SU, N<=49, STORAGE, K seepage), INJECT (FILE time/Q[/conc], OFFSET),
PIPE (D, LENGTH, SLOPE, MANNING -- "beta" per ARS), URBAN (impervious/pervious mix tags
CA CI CP CS DCI DCP ICI ICP), ADDER, DIVERTER. Only POND and INJECT have a tool; the others are
edited by hand from the manual, then checked with `edit_kineros2_par.py validate`.

## 5. Rainfall (s1)

| Item | Unit | Source | What changes for a new case | When not available |
|---|---|---|---|---|
| gage blocks with TIME (min) + DEPTH (cumulative) or INTENSITY | min; mm or in = PARAMETER FILE units | recording gages (WGEW DAP via `fetch_wgew_dap.py`) | gage list, one clock origin for all gages | single gage: X/Y optional |
| X, Y per gage | same CRS as element X/Y | gage coordinates | | |
| SAT per gage (optional) | - | antecedent moisture | overrides element SA silently | element SA is used |
| gridded fallback | mm per hour step | `load_hourly_forcing('nasa_power'|'cmfd'|'mswx')` | one pseudo-gage | peaks smeared -- documented under-prediction |

## 6. Run settings

| Setting | Meaning | Choice |
|---|---|---|
| tfin | run length, min | storm + recession (WG11: 360) |
| dt | output (and nominal compute) step, min | 1-3 min for small catchments; Courant Y lets the engine shorten the compute step |
| sed | route sediment | Y only with sediment tags |
| multipliers | Ks, n, CV, G, interception, cohesion, splash (+6 channel/saturation factors) | 1.0 unless calibrating |

## 7. Shared-library schemas (verified by calling them, 2026-10-06)

- `lookup_hwsd(31.72, -110.06)` -> dict with keys `mu_id, sand, silt, clay, oc, ph, bulk_density, sub_*,
  cec, gravel, sub_gravel, texture ('sandy_clay_loam'), hwsd_component{...}, hydraulics{texture,
  wilting_point, field_capacity, saturation, ksat_cm_hr (0.43)}`. `gravel` is volume %.
- `rosetta_vgn(50, 21)` -> `texture, theta_r, theta_s, alpha_1_per_m, alpha_1_per_cm, n, ksat_cm_day,
  ksat_m_s, field_capacity, wilting_point` (not used: KINEROS2 is Brooks-Corey; Table 1 gives G/DIST).
- `load_hourly_forcing('nasa_power', 31.72, -110.06, 2006, 2006, variables=['P'])` -> keys `dates`
  (ISO strings, hourly), `precip_mm` (mm per step), `temp_c, srad_wm2, lrad_wm2, pres_pa, shum_kgkg,
  wind_ms, wind2_ms, wind_height_m (10.0), timestep_seconds (3600)`; 8760 steps; wettest hour 1.87 mm.
  `variables` takes the loader's own names ('P','Tair',...), not output keys.
- `all_metrics(obs, sim)` -> `{'NSE','KGE','PBIAS','RMSE','r'}`.
- `validate_water_balance(P, ET, Q, delta_storage_mm=, period_days=1)` -> `residual_mm, residual_pct,
  status, components, diagnostics, daily_rates`; for one storm its annual-rate diagnostics are
  meaningless (it scales the event to a year) -- use `residual_pct` only.

## 8. Unusual structure, stated plainly

- No spin-up and no continuous water balance: antecedent state is the SAT number(s).
- Parameters are per element; calibration is by global multipliers (ARS practice).
- Units are global (UNITS tag) and are NOT converted anywhere -- the rain file and every tag follow it.
- Building a new watershed's element cascade needs a DEM discretisation (ARS uses AGWA). This KI
  does not ship a discretiser; it starts from an existing `.par` (copy-first) and edits it.
