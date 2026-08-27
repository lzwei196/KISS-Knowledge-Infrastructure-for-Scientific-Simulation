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
| to run the pipeline stages | `tools/` (5 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (7 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (19 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (22 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/calibrate_topmodel.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calibrate_topmodel.py --help` |
| `tools/convert_forcing_to_topmodel.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_topmodel.py --help` |
| `tools/generate_twi_subcat.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/generate_twi_subcat.py --help` |
| `tools/parse_topmodel_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_topmodel_output.py --help` |
| `tools/run_topmodel.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_topmodel.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# TOPMODEL BMI (NOAA-OWP) — Knowledge Infrastructure

**Package**: `hydrocraft-topmodel` v1.0.0
**Model**: TOPMODEL BMI (Beven & Kirkby 1979, NOAA-OWP C implementation)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-28
**Stats**: 5 tools | 6 skill documents | 18 diagnostic triplets | ~2,100 lines of validated Python
**Validation status**: see `knowledge_infrastructure.yaml`

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data sources & I/O (KDT 5.0 — `data_ki/<X>/tools/...` paths are STALE)**:
- **Forcing**: `ki_tools_common.load_forcing` (CMFD/MSWX/NASA POWER, daily & hourly).
  For Bengbu/Huai use CMFD (`cmfd_china_daily_010` or `cmfd_huai_daily_025`);
  **NASA POWER hourly is 2001+ only** and does not overlap the 1950-1997 Huai
  gauge record — do NOT use it here.
- **Soil**: `ki_tools_common.soil_utils` (HWSD lookup, Rosetta van Genuchten).
- **Observed discharge**: read the gauge text file directly
  (`$ROOT/data/obs/BB/51080_bengbu.txt` for Bengbu 51080). The
  `data_ki/ObservedQ/tools/` reader does NOT exist in KDT 5.0. **Obs trap**: the
  Bengbu record uses a `-99.9` missing-data sentinel (~215 days); these become 0
  after sentinel filtering, so **mask obs > 0 before scoring** or NSE is corrupted.
  - **Alternate Huai obs source — "China Gauge Flux — 淮河"**
    (`KISSPATH_DATA/china_water_level/淮河txt/`): a TAB-separated multi-gauge set,
    header `stcd  dates  z  Q  name`, `dates` = `%Y-%-m-%-d` (no zero-pad, e.g.
    `1980-6-1`), `Q` = discharge in **m³/s**, missing sentinel is **`-99`** (mask
    `Q > 0`). 8 gauges: `蚌埠`=Bengbu, `王家坝`=Wangjiaba, `息县`=Xixian,
    `淮滨`=Huaibin, `阜阳`=Fuyang, `鲁台子`=Lutaizi, `蒋家集`=Jiangjiaji,
    `周口`=Zhoukou; records span ~1950-2024. `蚌埠.txt` (stcd 50104200) is the
    SAME physical Bengbu station as `BB/51080_bengbu.txt` — the validated
    incumbent reproduces here (1981-1990 full NSE 0.435, val NSE 0.494, PBIAS
    −18.6), so it is a drop-in cross-check obs. Q(m³/s) → daily per-step depth
    (m) = `Q * 86400 / area_m2`; equivalently convert sim m/step → m³/s via
    `Q_mhr * area_m2 / 86400` and score in m³/s (NSE/KGE/r/PBIAS identical either
    way). Use area = 121,330 km² (1.2133e11 m²) for Bengbu.


## Overview

This knowledge infrastructure enables autonomous simulation of rainfall-runoff
using TOPMODEL on any watershed, without manual data preparation. The tools
replace the standard manual workflow with a Python pipeline that integrates
with HydroCraft's forcing, observation, and soil databases.

**What TOPMODEL does**: A physically-based, semi-distributed watershed model
that predicts:
- Saturation-excess overland flow (variable contributing area)
- Subsurface (baseflow) drainage via exponential transmissivity profile
- Unsaturated zone percolation
- Evapotranspiration from root zone deficit
- Channel routing via time-delay histogram
- Optional infiltration excess (Green-Ampt) overland flow

**Key concept**: Uses the topographic wetness index (TWI = ln(a/tanB)) distribution
to represent spatial variability of soil moisture deficit across the catchment,
without requiring a full 2D grid. A single subcatchment is characterized by
its TWI histogram.

**Model lineage**: Beven & Kirkby (1979) FORTRAN → Keith Beven (1985/1995)
→ Fred Ogden C port (2009) → NOAA-OWP BMI adaptation (2021)
→ GitHub: https://github.com/NOAA-OWP/topmodel

---

## Installation

### Build from source

```bash
cd source/repo/src/
make clean && make
cd ..
# Binary: ./run_bmi
```

### Dependencies

- GCC (tested 8.3.1+)
- GNU Make
- libm (math library, standard)

### Test run (Taegu Pyungkwang River demo)

```bash
cd source/repo/
./run_bmi
# Produces: topmod.out, hyd.out
```

---

## TIMESTEP CONVENTION — daily runs use dt=1.0 (1 step = 1 day)

> **READ THIS before trusting the "m/hr" labels below.** The validated
> Bengbu/Wangjiaba pipeline runs DAILY forcing with the `inputs.dat` header
> `dt = 1.0`, so **1 step = 1 day** and the rain/PE/Qobs columns are
> **per-DAY depths in metres**, not literally m/hr. The C binary indexes
> `rain[]`/`pe[]` by integer step and is only safe at `dt = 1.0` (see hazard
> `dt_not_one_index_drift`), so daily data MUST be fed as one-step-per-day with
> the header dt left at 1.0 — do NOT set dt=24. The "m/hr" naming in the model
> and the table below is then a per-step-depth misnomer.
> - **Dimensionless metrics (NSE/KGE/r) are unaffected** by this relabeling.
> - **Only the m³/s conversion cares**: use the TRUE seconds-per-step
>   (86400 for daily), i.e. `parse_topmodel_output` must convert with
>   `--dt-hours 24`. Using 3600 makes reported m³/s 24× too high.
> - Forcing depths: divide CMFD mm/day by **1000** (mm→m), NOT by 24000, when
>   the step is a day. `convert_forcing_to_topmodel` handles this; verify with
>   the forcing preflight + water-balance closure.

## Critical Units — internal units labelled METERS and HOURS (see timestep note above)

| Variable | Internal Unit | CMFD Unit | Conversion |
|----------|--------------|-----------|------------|
| rain | **m/hr** | mm/day | ÷ 24,000 (mm→m then day→hr) |
| pe (PET) | **m/hr** | — (compute) | Must derive PET from temp/rad |
| Qobs | **m/hr** | m³/s | Q/(area_m² × 3600) then ×1 |
| dt | **hours** | — | Typically 1 hr |
| szm | **m** | — | Calibration parameter |
| t0 | **m/hr** | — | Ln(T0) often calibrated |
| td | **hr** | — | Time delay parameter |
| chv | **m/hr** | — | Channel velocity |
| rv | **m/hr** | — | Overland flow velocity |
| srmax | **m** | — | Max root zone deficit |
| Q0 | **m/hr** | — | Initial subsurface flow |
| sr0 | **m** | — | Initial root zone deficit |
| xk0 | **m/hr** | — | Surface hydraulic cond. |
| hf | **m** | — | Wetting front suction |
| dist_from_outlet | **m** | — | Channel distance |
| Qout | **m/hr** | — | Output discharge |

### UNIT TRAP TABLE — Common silent errors

| Trap ID | What goes wrong | Symptom | Fix |
|---------|----------------|---------|-----|
| UT-01 | Precip left as mm/day | Discharge 24,000× too high | Divide by 24,000 |
| UT-02 | Precip converted to m/day not m/hr | Discharge 24× too high | Divide by 24 |
| UT-03 | Precip as mm/hr not m/hr | Discharge 1,000× too high | Divide by 1,000 |
| UT-04 | PE left as mm/day | ET massively too high, no runoff | Divide by 24,000 |
| UT-05 | Qobs in m³/s not m/hr | NSE meaningless | Q_mhr = Q_m3s / (area_m2) |
| UT-06 | Channel distance in km not m | Routing delay wrong | Multiply by 1,000 |
| UT-07 | dt in seconds not hours | All fluxes wrong | Use hours |
| UT-08 | TWI distribution doesn't sum to 1 | Water balance error | Normalize |

## Unit Table — source/model conversions

Exact I/O shapes live in `docs/format_spec.yaml`; this table is the reader-facing
unit table for the model workflow. The timestep convention above remains binding:
the C model labels fluxes as `m/hr`, while the validated daily pipeline uses
`dt = 1.0` as one step per day and converts reported discharge with the true
seconds per step during post-processing.

| Variable | Source unit | Model/storage unit | Conversion / convention | Applies in |
|----------|-------------|--------------------|-------------------------|------------|
| precipitation / `rain` | CMFD/MSWX mm/day | `m/hr` label; daily per-step depth in validated daily runs | Daily validated runs divide by `1000` to get m per step; literal hourly runs use mm to m and day to hour as needed | `inputs.dat` |
| potential evapotranspiration / `pe` | computed PE, commonly mm/day | `m/hr` label; daily per-step depth in validated daily runs | Compute PE externally, then convert consistently with the selected step; do not leave PE in mm/day | `inputs.dat` |
| observed discharge / `Qobs` | m^3/s | `m/hr` label; per-step depth | For the dag convention, `Q_mhr = Q_m3s * 3600 / basin_area_m2`; for validated daily scoring, use the true daily seconds-per-step noted above | `inputs.dat`, scoring |
| `Q (simulated discharge)` | model routed outlet flow | `m/hr (per-step depth; convert to m^3/s via Q_m3s = Q_mhr * basin_area_m^2 / 3600)` | This is the dag rank-1 output unit string; daily post-processing must still honor `--dt-hours 24` as documented above | `hyd.out`, parsed outputs |
| `qb (baseflow)` | model state/output | `m/hr` label | Baseflow component contributing to routed discharge | `topmod.out` |
| `qof (saturation/Hortonian overland flow)` | model state/output | `m/hr` label | Overland-flow component contributing to routed discharge | `topmod.out` |
| `sbar (mean saturation deficit)` | model state/output | m | Mean catchment saturation deficit | `topmod.out` |
| `contrib_area (saturated contributing-area fraction)` | model state/output | fraction | Saturated contributing-area fraction | parsed outputs / dag |
| `ea (actual evapotranspiration)` | model state/output | `m/hr` label | Actual evapotranspiration reported by the model | `topmod.out` |
| `bal (water-balance residual)` | model diagnostic | model residual convention | Use for water-balance closure checks, not as the headline score | `topmod.out` |
| DEM channel distance | km or m depending source | m | Multiply km by `1000` before writing `subcat.dat` | `subcat.dat` |
| TWI distribution area | fraction | fraction | Histogram fractions must sum to approximately `1.0` | `subcat.dat` |

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Select basin, period, forcing source |
| 1 | Forcing prep | `convert_forcing_to_topmodel` | CMFD/MSWX → inputs.dat (rain, PE in m/hr) |
| 2 | TWI generation | `generate_twi_subcat` | DEM + basin → subcat.dat (TWI histogram) |
| 3 | Parameter setup | `generate_params` | Soil/landcover → params.dat |
| 4 | Config assembly | (manual) | Write topmod.run |
| 5 | Execution | `run_topmodel` | Build and run binary |
| 6 | Output analysis | `parse_topmodel_output` | Parse hyd.out → CSV, compute metrics |
| 7 | Calibration (opt) | `calibrate_topmodel` | Seed-anchored bounded search over real run_bmi, cal-only objective, held-out val |

---

## Input Files

### topmod.run (configuration)

```
1                          <- stand_alone flag (1=TRUE)
Catchment Name             <- title string
data/inputs.dat            <- path to forcing file
data/subcat.dat            <- path to subcatchment topo data
data/params.dat            <- path to parameters
topmod.out                 <- output file path
hyd.out                    <- hydrograph output path
```

Line 1 must be `1` for standalone mode, `0` for BMI framework coupling.

### inputs.dat (forcing time series)

```
950  1.0                   <- nstep  dt(hours)
  0.0010000  0.0000619  0.0000328   <- rain(m/hr)  pe(m/hr)  Qobs(m/hr)
  0.0010000  0.0000647  0.0000325
  ...
```

- First line: number of time steps, time step size in hours
- Each subsequent line: rain, PE, Qobs — all in **meters/hour**
- Qobs is optional (used only for calibration/comparison in results())

### subcat.dat (topographic index distribution)

```
1  1  0                    <- num_sub_catchments  imap  yes_print_output
Basin Name                 <- subcatchment name
30  1                      <- num_topodex_values  area(fraction, usually 1.0)
0.000001 9.382756          <- dist_area_lnaotb  lnaotb (TWI value)
0.000005 9.076504
...                        <- 30 rows: area fraction and ln(a/tanB)
3                          <- num_channels
0.0  500.  0.5  1000.  1.0  1500.  <- cum_dist_area  dist_from_outlet(m) pairs
$mapfile.dat               <- map file (not used if imap=0)
```

- TWI values ordered from HIGH to LOW
- dist_area_lnaotb[1] should be ~0 (upper limit)
- All dist_area values should sum to ~1.0
- dist_from_outlet in METERS

### params.dat (model parameters)

```
Basin Name
0.032  5.0  50.  3600.0  3600.0  0.05  0.0000328  0.002  0  1.0  0.02  0.1
```

Parameters in order:
szm(m), t0(m/hr), td(hr), chv(m/hr), rv(m/hr), srmax(m),
Q0(m/hr), sr0(m), infex(0/1), xk0(m/hr), hf(m), dth(-)

---

## Output Files

### topmod.out

Contains per-timestep: it, p, ep, Q[it], quz, qb, sbar, qof
Plus water balance summary at end.

### hyd.out

Two columns per timestep: Q_simulated  Q_observed (both in m/hr)

---

## Output Description

This section restates the dag-facing outputs for agents reading only
`SKILL.md`. If this section and `dag.yaml` ever disagree, `dag.yaml` wins.

**Headline output**: `Q (simulated discharge)` is the dag's
`validation_rank: 1` variable and the model is judged by it.

> `Q (simulated discharge)` — Per-timestep routed discharge at the catchment
> outlet (qb + qof routed through the time-delay histogram).
> Unit: `m/hr (per-step depth; convert to m^3/s via Q_m3s = Q_mhr * basin_area_m^2 / 3600)`.

| Dag output variable | Validation role | Unit / note | Description |
|---------------------|-----------------|-------------|-------------|
| `Q (simulated discharge)` | rank 1 headline output | `m/hr (per-step depth; convert to m^3/s via Q_m3s = Q_mhr * basin_area_m^2 / 3600)` | Per-timestep routed discharge at the catchment outlet (qb + qof routed through the time-delay histogram). |
| `qb (baseflow)` | other dag output | see `dag.yaml` | Baseflow output named by the dag. |
| `qof (saturation/Hortonian overland flow)` | other dag output | see `dag.yaml` | Saturation/Hortonian overland-flow output named by the dag. |
| `sbar (mean saturation deficit)` | other dag output | see `dag.yaml` | Mean saturation-deficit output named by the dag. |
| `contrib_area (saturated contributing-area fraction)` | other dag output | see `dag.yaml` | Saturated contributing-area fraction output named by the dag. |
| `ea (actual evapotranspiration)` | other dag output | see `dag.yaml` | Actual evapotranspiration output named by the dag. |
| `bal (water-balance residual)` | other dag output | see `dag.yaml` | Water-balance residual output named by the dag. |

---

## Key Equations

### Saturation deficit
```
deficit_local[i] = sbar + szm * (tl - lnaotb[i])
```
Where `tl` = areal integral of ln(a/tanB), `sbar` = mean catchment deficit.

### Baseflow
```
qb = szq * exp(-sbar / szm)
```
Where `szq = t0 * exp(-tl)` (initialized in init()).

### Unsaturated zone drainage
```
uz = stor_unsat_zone[i] / (deficit_local[i] * td * dt)
```

### Evapotranspiration
```
ea = ep * (1 - deficit_root_zone[i] / srmax)
```

### Total discharge
```
Qout = qb + qof    (then routed through time-delay histogram)
```

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_forcing_to_topmodel` | s1 | `tools/convert_forcing_to_topmodel.py` | CMFD/MSWX NetCDF → inputs.dat |
| `generate_twi_subcat` | s2 | `tools/generate_twi_subcat.py` | DEM + basin shapefile → subcat.dat |
| `run_topmodel` | s5 | `tools/run_topmodel.py` | Build, configure, and execute TOPMODEL |
| `parse_topmodel_output` | s6 | `tools/parse_topmodel_output.py` | Parse hyd.out, compute NSE/KGE/PBIAS |
| `calibrate_topmodel` | s7 | `tools/calibrate_topmodel.py` | Calibrate szm/t0/td/srmax/Q0 etc. via the REAL run_bmi binary; scores cal window only, reports held-out val. `--seed-only` just evaluates the robust incumbent. |

### Calibration — usage and the overfitting trap

```bash
python3 tools/calibrate_topmodel.py --run-dir <run_dir> --basin <NAME> \
    --start 1980-01-01 --cal 1981-01-01:1985-12-31 --val 1986-01-01:1990-12-31 --n 800
# or just reproduce the robust incumbent without searching:
python3 tools/calibrate_topmodel.py --run-dir <run_dir> --seed-only
```

`<run_dir>` must already contain `run_bmi` and `data/{inputs.dat,subcat.dat}`.
Writes `calib_result.json` (best_params + cal/val/full metrics).

**DO NOT blindly maximize cal-NSE.** At Bengbu the calibration window (1981-85)
is volume-biased (wetter, higher peaks, PBIAS −34%) relative to validation
(+5.5%); one parameter set cannot satisfy both. Three documented attempts to
push cal-NSE or select on cal-KGE COLLAPSED held-out val (val-NSE → 0.17, and
−0.97 for cal-KGE selection). The shipped incumbent (val NSE 0.494 / KGE 0.66)
is a ROBUST sweet spot, not the cal-optimum. **If a search does not beat the
incumbent's *validation* metrics, keep the incumbent.** Note also `t0` is
**ln(T0)** and must be ≈8 to match the high TL (~10.9) of a coarse-resampled
large-basin DEM — the pre-DEM seed t0=4.81 over-buffers baseflow (val NSE −0.55).

---

## Validated Results

Validated scoring is tied to the dag headline variable, not to a guessed
hydrologic preference. The rank-1 output is `Q (simulated discharge)`, with unit
`m/hr (per-step depth; convert to m^3/s via Q_m3s = Q_mhr * basin_area_m^2 / 3600)`.

### Documented Bengbu / Huai incumbent

The body-documented incumbent uses the Bengbu station with area `121,330 km²`
(`1.2133e11 m²`) and the 1981-1990 period noted above. The alternate Huai obs
source is a drop-in cross-check for the same physical Bengbu station; the
documented incumbent reproduces there with 1981-1990 full NSE `0.435`, validation
NSE `0.494`, and PBIAS `−18.6`. The calibration section also records the robust
incumbent as validation NSE `0.494` / KGE `0.66`, while failed cal-heavy searches
collapsed held-out validation NSE to `0.17` and `−0.97` for cal-KGE selection.

### Convention bars from `docs/validation_convention.yaml`

Every stated threshold below carries the citation key supplied by the convention.
When the convention stores a null band, this section writes `no cited threshold`
rather than substituting an uncited value.

| Dag variable | Metric | Direction | Very good | Good | Satisfactory |
|--------------|--------|-----------|-----------|------|--------------|
| `Q (simulated discharge)` | NSE | maximize | `>= 0.75` (`kouchi2017`, `das2020`) | `>= 0.65` (`kouchi2017`, `das2020`) | `>= 0.5` (`kouchi2017`, `das2020`) |
| `Q (simulated discharge)` | PBIAS | zero_centered | `abs(PBIAS) <= 10.0` (`kouchi2017`, `das2020`) | `abs(PBIAS) <= 15.0` (`kouchi2017`, `das2020`) | `abs(PBIAS) <= 25.0` (`kouchi2017`, `das2020`) |
| `Q (simulated discharge)` | CSI | maximize | no cited threshold (`thiemig2015`) | no cited threshold (`thiemig2015`) | `>= 0.5` (`thiemig2015`) |
| `qb (baseflow)` | NSE | maximize | no cited threshold | no cited threshold | no cited threshold |

For `Q (simulated discharge)`, the documented validation NSE `0.494` is just
below the cited satisfactory NSE threshold `0.5` (`kouchi2017`, `das2020`).
The documented PBIAS `−18.6` is within the cited satisfactory zero-centered
PBIAS band `25.0` and outside the cited good band `15.0`
(`kouchi2017`, `das2020`).

---

## Calibration Parameters

The following parameters are typically calibrated (in order of sensitivity):

1. **szm** (m): Controls baseflow recession shape. Range: 0.001–0.1
2. **t0** (m/hr): Saturated transmissivity. Range: 0.1–100. Often use ln(t0).
3. **srmax** (m): Root zone capacity. Range: 0.001–0.5
4. **td** (hr): Unsaturated zone delay. Range: 1–100
5. **Q0** (m/hr): Initial flow. Estimate from observed baseflow.
6. **sr0** (m): Initial root zone deficit. Usually 0–srmax.

### Default parameter set (after Beven)

```
szm=0.032, t0=5.0, td=50.0, chv=3600, rv=3600,
srmax=0.05, Q0=0.0000328, sr0=0.002, infex=0
```

---

## Converting model output to m³/s

TOPMODEL outputs discharge in **m/hr** (depth per unit area per hour).
To convert to volumetric discharge (m³/s):

```
Q_m3s = Q_mhr * basin_area_m2 / 3600
```

For Bengbu basin (~121,330 km²):
```
Q_m3s = Q_mhr * 121330e6 / 3600
```

---

## Potential Evapotranspiration (PE)

TOPMODEL requires PE as input. Since CMFD does not provide PE directly,
compute using Hargreaves or Penman-Monteith:

### Hargreaves (simplified, for daily PE):
```
PE_mm_day = 0.0023 * (T_mean + 17.8) * (T_max - T_min)^0.5 * Ra
```
Where Ra = extraterrestrial radiation (MJ/m²/day), T in °C.

Then convert: `PE_m_hr = PE_mm_day / 24000`

### From CMFD variables available:
- temp (K) → T_celsius = temp - 273.15
- srad (W/m²) → shortwave radiation
- wind (m/s), pres (Pa), shum (kg/kg) → for Penman-Monteith

---

## TWI Computation

The topographic wetness index ln(a/tanB) requires:
1. DEM (filled, pit-removed)
2. Flow direction grid
3. Contributing area (a) per unit contour length
4. Local slope (tanB)

For each cell: TWI = ln(a / tan(slope))

The distribution is then binned into a histogram (typically 10–30 classes)
with the fraction of catchment area in each TWI class.

---

## Limitations

- **Lumped model**: Single subcatchment, no spatial gridding
- **Shallow soils**: Assumes shallow, highly permeable soils
- **Humid climates**: Not suited for long dry periods
- **Moderate topography**: TWI concept breaks down in very flat or steep terrain
- **No snow**: No snowmelt module in standard TOPMODEL
- **PE must be provided**: Model does not compute PET internally
