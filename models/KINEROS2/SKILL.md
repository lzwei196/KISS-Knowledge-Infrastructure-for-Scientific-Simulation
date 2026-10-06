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

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (15 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (9 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (53 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (16 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-10-06 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/add_kineros2_element.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/add_kineros2_element.py --help` |
| `tools/build_kineros2_rainfall.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_kineros2_rainfall.py --help` |
| `tools/calibrate_kineros2_multipliers.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calibrate_kineros2_multipliers.py --help` |
| `tools/configure_kineros2_sediment.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/configure_kineros2_sediment.py --help` |
| `tools/convert_forcing_to_kineros2.py` (**SURROGATE, not KINEROS2**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_kineros2.py --help` |
| `tools/convert_soil_to_kineros2.py` (**SURROGATE, not KINEROS2**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_kineros2.py --help` |
| `tools/edit_kineros2_par.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/edit_kineros2_par.py --help` |
| `tools/fetch_wgew_dap.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/fetch_wgew_dap.py --help` |
| `tools/kineros2_soil_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/kineros2_soil_params.py --help` |
| `tools/parse_kineros2_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_kineros2_output.py --help` |
| `tools/parse_output_kineros2.py` (**SURROGATE, not KINEROS2**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output_kineros2.py --help` |
| `tools/run_kineros2.py` (**SURROGATE, not KINEROS2**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_kineros2.py --help` |
| `tools/run_kineros2_engine.py` (**default run route: the REAL engine**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_kineros2_engine.py --help` |
| `tools/score_kineros2_event.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/score_kineros2_event.py --help` |

*14 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

# KINEROS2 -- Knowledge Infrastructure Skill Document

> **Version**: KINEROS2 K2shell 25-Oct-2019 (ARS-SWRC/KINEROS2 commit f0bbae2), gfortran build
> **Domain**: hydrology -- event rainfall-runoff and erosion on small watersheds
> **Last updated**: 2026-10-06 (rebuilt around the real engine)
> **Validation status**: production_validated on the official ARS samples (reproduced exactly);
> one real-observation comparison (Walnut Gulch flume 11, 4 Aug 1980, in-sample)

> **SURROGATE WARNING.** `tools/run_kineros2.py` (+ `convert_forcing_to_kineros2.py`,
> `convert_soil_to_kineros2.py`, `parse_output_kineros2.py`, docs in `docs/surrogate/`) is a
> **Python SURROGATE** -- a lumped, daily, Green-Ampt + two-reservoir stand-in written before the real
> engine existed on this server. It is **not KINEROS2**. Never report its output (e.g. the Huaihe at
> Bengbu, 121,330 km2, NSE 0.851 still recorded in the models DB) as KINEROS2 results. The real model
> is run by `tools/run_kineros2_engine.py`.

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | KINEROS2 -- KINematic runoff and EROSion model, version 2 |
| Version | K2shell 25-Oct-2019 (ARS-SWRC/KINEROS2 HEAD f0bbae2a19238fe98d5b42fbc9e55a993bfbba41) |
| Language | Fortran 77/90 (K2shell.f90 driver + .for modules) |
| License | MIT (repository LICENSE), USDA-ARS public software |
| Repository | https://github.com/ARS-SWRC/KINEROS2 ; samples https://www.tucson.ars.ag.gov/kineros/ |
| Citation | Goodrich et al. 2012, K2/AGWA: model use, calibration, and validation, Trans. ASABE 55(4):1561-1574 |
| Primary domain | event runoff, infiltration, erosion/sediment, small agricultural/rangeland/urban watersheds |
| Spatial mode | Distributed cascade of 1-D elements (planes, channels, ponds, pipes, urban, injections) |
| Binary | `KISSPATH_HOME/engine_builds_20261006/KINEROS2/build_github/k2` (sha256 d3efaef0...a3348d) |

---

## 2. What This Model Does

KINEROS2 simulates ONE storm at minute steps on a small watershed (hectares to a few km2) described as
a cascade of overland-flow planes and trapezoidal channels (plus optional ponds, pipes, urban elements
and injected inflows). Rain from one or more recording gages is interpolated to each element,
intercepted, infiltrated with the Smith-Parlange/Green-Ampt family (one or two soil layers,
redistribution between bursts), and the excess is routed by the 1-D kinematic wave; channels lose
water into their beds. Optionally it erodes, deposits and transports up to five particle classes.
Outputs are the outlet hydrograph, event volumes, peaks and sediment yield. There is no
evapotranspiration, no continuous soil-moisture accounting and no spin-up: antecedent wetness is an
input (SAT).

---

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from dag + triplets -- regenerate it,
never hand-edit). The full preparation plan, per tag, is `docs/input_preparation.md`.

### 3.1 Meteorological Forcing

| Variable | Unit model expects | Source dataset | Source unit | Conversion |
|----------|-------------------|----------------|------------|------------|
| Rainfall (cumulative depth vs minutes, per gage) | mm if UNITS=METRIC, in if UNITS=ENGLISH | USDA-ARS WGEW DAP recording gages (`tools/fetch_wgew_dap.py precip`) | in or mm (chosen at download) | none -- download in the parameter file's unit; times = local start - clock origin + elapsed min |
| Rainfall (last resort, ungauged) | as above | `load_hourly_forcing('nasa_power'|'cmfd'|'mswx')` | mm per step | cumulative sum; x 1/25.4 for ENGLISH; peaks smeared (dt_kineros2_036) |

No temperature, radiation, wind or humidity input exists (GLOBAL TEMP is only the water temperature
for sediment settling).

### 3.2 Static Inputs

| Input | Source | Tool that prepares it |
|-------|--------|----------------------|
| Element cascade (LENGTH, WIDTH, SLOPE, topology) | existing .par (ARS sample, AGWA export) -- copy-first | `tools/edit_kineros2_par.py` |
| Infiltration (KS, G, DIST, POR, ROCK) | HWSD + KINEROS2 manual Table 1 (Rawls 1982) | `tools/kineros2_soil_params.py` |
| Roughness, interception, CV, SAT | land cover tables / field data / antecedent rain | `tools/edit_kineros2_par.py set` |
| Sediment classes and erodibility | particle analysis / literature | `tools/configure_kineros2_sediment.py` |
| Ponds (rating table), injected inflows | design data / measured flows | `tools/add_kineros2_element.py` |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| parameter file `.par` | tagged blocks (`BEGIN PLANE ... END`), `TAG = v1, v2` lists or column headers | upper-cased, columns 1-200 only, `+` is a separator, tags matched by prefix |
| rainfall file `.pre` | one tagged block per gage | depth in the parameter file's UNITS |
| multiplier file | 7 lines (Ks, n, CV, G, interception, cohesion, splash) [+6 channel/saturation lines] | values > 0 |
| `kin.fil` | one line per run: `par,pre,out,"title",tfin,dt,Y|N,Y|N,mult|N,Y` | written by the run tool; no spaces after commas |

---

## 4. Build Instructions

```bash
# already built (2026-10-06); to rebuild from the official source:
git clone https://github.com/ARS-SWRC/KINEROS2 src            # source, docs (src/doc/*.pdf), x64/k2_x64.exe
# patched copy: CRLF stripped; kinsed_wepp.for:155 reshape (/5,1/) -> (/5/) (gfortran rank check)
KISSPATH_HOME/engine_builds_20261006/KINEROS2/build.sh KISSPATH_HOME/engine_builds_20261006/KINEROS2/src_patched OUTDIR
# compiles k2mods.for, kinsed.f90 first, then the rest, K2shell.f90 last; links OUTDIR/k2
```

**Known build issues:**
- No makefile in the repository; module order matters (k2mods, kinsed first).
- Leave out fmt10_new.for, pond_dcg.for, sedbf.for, inject.for.bak (duplicates / fragments).
- gfortran flags: `-O2 -fno-automatic -ffixed-line-length-none -ffree-line-length-none -std=legacy -fallow-argument-mismatch`.
- Cross-check: the official ARS Windows `k2_x64.exe` under WINE (needs a pty: `script -qec "wine k2_x64.exe -b kin.fil"`) agrees to the 6th-7th digit (dt_kineros2_020).

---

## 5. Execution

```bash
python3 preflight_check.py                                                  # binary + EX1 smoke run
python3 tools/run_kineros2_engine.py --example wg11 --check --out-dir OUT/wg11
python3 tools/run_kineros2_engine.py --par case.par --rain storm.pre --tfin 360 --dt 3 --courant \
        --mult ks=0.5,g=1.5 [--sediment] --out-dir OUT/case
```

The tool copies inputs into a fresh workspace, writes `kin.fil`, runs `k2 -b kin.fil`, judges success
from the output text (the engine's exit status is ALWAYS 0, dt_kineros2_027) and writes
`run_result.json`. Exit codes: 0 ok, 2 input invalid, 3 engine failure, 4 binary missing, 5 example
mismatch. Binary lookup: `--binary` > `$KINEROS2_BIN` > models DB `binary_path` > builder default.

**Expected runtime**: < 0.1 s per storm for 2-17 elements (both ARS samples); 40 calibration trials on
WG11 take about 2 s.

---

## 6. Output Description

Sourced from `dag.yaml` (the dag wins if the two ever disagree).

**Headline output** (the dag's `validation_rank: 1` variable):

> `discharge` — Surface water discharge (stream / channel flow) at the watershed outlet element, as an event hydrograph at the user time step in minutes. (m3/s)

| Output variable (dag `var`) | rank | File | Unit | Medium |
|----------------|------|------|------|--------|
| discharge | 1 | `.out` hydrograph table (PRINT=2) / PRINT=3 CSV; `hydrograph_<type>_<id>.csv` | m3/s (printed cu m/s or cu ft/s) | surface water (channel) |
| runoff_volume | 2 | `.out` Event Volume Summary, Outflow | m3 (printed cu m or cu ft) | surface water |
| peak_discharge | 3 | `.out` "Peak flow = ... at ... min" of the outlet | m3/s | surface water (channel) |
| sediment_yield | 4 | `.out` "Sediment yield =" (+ by class) | t/ha (printed tons/ha or short tons/ac) | sediment |
| infiltration | - | Event Volume Summary (plane / channel infiltration) | mm | soil |
| sediment_discharge | - | hydrograph column / PRINT=3 per-class columns | kg/s (lb/s ENGLISH) | sediment in water |

`run_kineros2_engine.py` puts all of these, converted to SI, into `run_result.json`
(`event_summary_si`, `outlet.peak_discharge_m3s`); `parse_kineros2_output.py` does the same for an
existing `.out`.

---

## 7. Tool Inventory

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `tools/run_kineros2_engine.py` | run the REAL engine headless, honest status, parse | .par, .pre, tfin, dt, flags, multipliers | .out, run_result.json, hydrograph CSVs |
| `tools/parse_kineros2_output.py` | parse an existing .out (+ PRINT=3 CSV) | .out | JSON + CSV, SI values |
| `tools/edit_kineros2_par.py` | list / validate / get / set tags with the engine's lookup rules (copy-first) | .par [.pre] | new .par, validation report |
| `tools/kineros2_soil_params.py` | KS, G, DIST, POR, ROCK from HWSD or texture | lat/lon or texture | JSON, filled .par copy |
| `tools/build_kineros2_rainfall.py` | write a .pre from WGEW DAP gages, CSV or gridded hourly rain | breakpoints / forcing | .pre |
| `tools/fetch_wgew_dap.py` | download WGEW flume runoff and rain-gage data (USDA-ARS DAP) | ids, dates, units | DAP text with provenance |
| `tools/configure_kineros2_sediment.py` | check / set sediment classes and erosion tags | .par | sediment-ready .par |
| `tools/add_kineros2_element.py` | insert a POND or an INJECT element and re-wire | .par, rating / hydrograph CSV | new .par (+ inject data file) |
| `tools/score_kineros2_event.py` | event metrics vs an observed hydrograph, figure | run_result.json, obs file, clock offset | score.json, PNG |
| `tools/calibrate_kineros2_multipliers.py` | grid / Nelder-Mead on multipliers, real engine per trial | case + obs | trials.csv, best.json, best/ |
| `tools/_k2lib.py` | shared private helpers (binary lookup, tag reader mirror, kin.fil, parser) | - | - |
| `tools/run_kineros2.py` | **SURROGATE** (Python lumped daily stand-in) -- not KINEROS2 | forcing JSON | surrogate JSON (stamped model_identity) |
| `tools/convert_forcing_to_kineros2.py` | **SURROGATE** helper (daily basin forcing) | NetCDF | JSON |
| `tools/convert_soil_to_kineros2.py` | **SURROGATE** helper (lumped parameters) | texture | JSON |
| `tools/parse_output_kineros2.py` | **SURROGATE** helper (daily series metrics) | surrogate JSON | CSV/metrics |

### Shared Utilities (ki_tools_common)

```python
from ki_tools_common.soil_utils import lookup_hwsd                  # kineros2_soil_params.py (Ks, texture, gravel)
from ki_tools_common.load_forcing import load_hourly_forcing        # build_kineros2_rainfall.py --from-gridded
from ki_tools_common.metrics import all_metrics                     # score_kineros2_event.py (NSE, KGE, PBIAS, RMSE, r)
from ki_tools_common.validation import validate_water_balance       # run_kineros2_engine.py event balance (residual only)
```

---

## 8. Unit Conversion Table

> KINEROS2 converts nothing between unit systems: GLOBAL `UNITS` fixes every number in the parameter
> AND rainfall files. Rows below were verified on the engine output and source (`conv`, `wconv`).

| Variable | Source unit (verified) | Model unit | Factor | Type |
|----------|----------------------|------------|--------|------|
| Rain depth (WGEW DAP) | in or mm (export header) | in (ENGLISH) / mm (METRIC) | 1 (download in the right unit) | none |
| Gridded hourly rain (loader) | mm per step | mm or in cumulative | cumsum; /25.4 for ENGLISH | multiplicative |
| KS (Rawls / HWSD ksat_cm_hr) | cm/hr | mm/hr / in/hr | x10 / x10/25.4, then x(1-ROCK) | multiplicative |
| G (manual Table 1) | cm | mm / in | x10 / x10/25.4 | multiplicative |
| ROCK (HWSD gravel) | volume % | fraction | /100 | multiplicative |
| Discharge printed | cu ft/s (ENGLISH) | m3/s | x0.028316847 | multiplicative |
| Volume printed | cu ft | m3 | x0.028316847 | multiplicative |
| Depth printed | in | mm | x25.4 | multiplicative |
| Area printed | ac | ha | x0.404686 | multiplicative |
| Sediment yield printed | short tons/ac | t/ha | x2.2417 | multiplicative |
| Sediment discharge printed | lb/s | kg/s | x0.453592 | multiplicative |
| WGEW flume runoff (mm, in) | per NOMINAL flume area | -- | do not compare depths; use cfs/ft3 | trap (dt_kineros2_033) |

## 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|------------------------|-------------------|-----------------|
| Evapotranspiration | not simulated | - | none |
| Infiltration | positive = loss from the surface (volume, depth over total watershed area) | per element area | depth mis-scaled |
| Runoff / discharge | absolute flow at an element outlet (m3/s or cu ft/s); rates mm/hr over the CONTRIBUTING area | depth over the gauge's nominal area | volume bias when areas differ |
| Time | minutes after the rain-file clock origin | local clock time | shifted hydrograph (dt_kineros2_049) |

**Output unit verification checklist:** `run_result.json` `units` (metric|english) comes from the
printed labels ('cu m' vs 'cu ft'); the SI block is computed from it; peak lines include both the
discharge and the rate per contributing area.

---

## 9. Diagnostic Triplets (Top 5)

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| 1 | `dt_kineros2_027` run "succeeds" (exit 0) with no event summary | every engine error path ends in `stop`, status 0 | judge from text; use run_kineros2_engine.py (exit 3) |
| 2 | `dt_kineros2_029` no hydrograph although `PR = 2` | engine asks for `PRI`; `PR`/`Plot` are not read | `--set <outlet>:PRINT=2` |
| 3 | `dt_kineros2_030` element SA edits change nothing | gage SAT overrides element SA | keep SAT in one place |
| 4 | `dt_kineros2_032` runoff ~0 or huge | rain file read in the parameter file's UNITS | build the .pre with matching `--units` |
| 5 | `dt_kineros2_033` volume/depth error vs a flume | gauge depth uses nominal area (WG11 1551 vs 2035 ac) | compare m3/s and m3 |

Also frequent: `dt_kineros2_031` ('+' splits 1.6e+06), `dt_kineros2_044` (element order),
`dt_kineros2_046` (surrogate output mistaken for KINEROS2). Original ids 013/018/020/021/024/026 were
corrected on 2026-10-06; ids tagged `applies_to: python_surrogate` concern the stand-in only.

---

## 10. Coupling Interfaces

| Upstream model | Variable exchanged | Unit | Temporal resolution |
|---------------|-------------------|------|-------------------|
| Recording rain gages / radar / nowcast | cumulative rain depth per gage | mm or in | breakpoints (minutes) |
| Any hydrologic/hydraulic model or gauge | injected inflow (+ sediment concentration) via INJECT | m3/s or ft3/s | minutes |

| Downstream model | Variable exchanged | Unit | Temporal resolution |
|-----------------|-------------------|------|-------------------|
| Hydraulic models (e.g. HEC-RAS, as in Nguyen et al. 2015) | outlet discharge hydrograph | m3/s | user dt (minutes) |
| Reservoir / pond / sediment budgets | event runoff volume, sediment yield by class | m3, t/ha | per event |

---

## 11. Validated Results

### Test Basin: Walnut Gulch subwatershed 11 (USDA-ARS WGEW, Arizona), storm of 4 Aug 1980

| Property | Value |
|----------|-------|
| Location | flume 11, UTM 12N 595224 E 3512227 N (about 31.72 N, 110.06 W) |
| Area | 627.7 ha modelled contributing area (1551.03 ac); flume nominal 2035 ac |
| Period | one storm, 360 min from 12:35 local, 3-min output |
| Resolution | 17 elements (12 planes, 5 channels), 10 recording rain gages |

**Official samples reproduced (2026-10-06, `run_kineros2_engine.py --example ... --check`)**: EX1
rain 77.0 mm, plane infiltration 41.51009 mm, outflow 35.29868 mm (705.974 m3), sediment 5.172343
t/ha; WG11 rain 1.3642 in, outflow 0.292209 in (1,645,201 ft3), outlet peak 668.4023 cfs at 64.7 min
-- every value identical to the build log (tolerance rel 1e-4). The WG11 rain file rebuilt from the
raw ARS gage export is identical to the shipped one (10/10 gages).

### Performance Metrics — judged against the field's bar, not intuition

> Bar for `discharge` (NSE, per `leta2023` and `cirilo2020`, Moriasi-style classes transferred from
> daily/monthly flow): satisfactory ≥ 0.50, good ≥ 0.65, very good ≥ 0.75; PBIAS within ±25 %
> satisfactory. Achieved on WG11 4 Aug 1980 with the ARS readme multipliers: NSE 0.812 → **very good
> by that band**, but PBIAS (on the 3-min grid) +26.6 % → **just outside satisfactory**; one event, in-sample.

| Metric | Calibration | Validation | Full Period | Bar (convention, cited) |
|--------|-------------|------------|-------------|-------------------------|
| NSE | 0.855 (multipliers re-fit, in-sample) | - | 0.812 (ARS readme multipliers) | satisfactory/good/very good 0.50/0.65/0.75, `leta2023` |
| KGE | - | - | 0.720 | no cited threshold |
| PBIAS (%) | - | - | +26.6 (3-min grid) | ±25 satisfactory, `leta2023` |
| r | - | - | 0.910 | no cited threshold |
| Peak error | -31.0 % | - | -25.6 % (18.84 vs 25.32 m3/s) | no cited threshold (null band) |
| Time to peak | - | - | 66 vs 72 min | no cited threshold |
| Event volume | +4.7 % | - | +27.6 % (46,544 vs 36,490 m3) | ±25 satisfactory (`leta2023`, transferred) |

Validation tier: **real** observation (independent flume data), but **in-sample**: the readme
multipliers were chosen by ARS for this storm. No blind multi-event test has been run yet.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | WGEW DAP recording gages via fetch + build tools | Validated | rebuilt 4Aug80.pre identical to ARS file |
| Soil | HWSD + Table 1 tool | Pending | class KS 0.135 in/hr vs ARS 0.40-0.52 in/hr (dt_kineros2_053) |
| Land cover | ARS sample values | Pending | no roughness tool; edit by hand |
| DEM / elements | ARS sample cascade | Pending | no discretiser in this KI (AGWA) |
| Initial conditions | ARS gage SAT 0.09-0.13 | Validated (sample) | event specific |

---

## 12. Parameter Selection by Region

| Climate / Region | Key parameters | Rationale |
|---|---|---|
| Semi-arid rangeland, SE Arizona (WGEW) | planes KS 0.40-0.52 in/hr, G 6.7-7.3 in, POR 0.453, ROCK 0.38-0.41, DIST 0.6, CV 0.8, n 0.05-0.10, INTER 0.014 in; channels KS 7.8-11 in/hr, WOOL=YES; multipliers Ks 0.5, G 1.5 | ARS wg11.par + readme; gravelly soils, sandy ephemeral channels with large transmission losses |
| Small plot / hypothetical (metric) | KS 10/50 mm/hr two layers, G 500/250 mm, CV 0.12, SAT 0.2, n 0.04 | ARS EX1.PAR (format example) |
| Ungauged start point (any) | KS, G, DIST, POR from texture (manual Table 1), ROCK from HWSD gravel; calibrate Ks then n | Goodrich et al. 2012 calibration order |
| Humid / saturation-excess catchments | out of scope | KINEROS2 generates Hortonian runoff only |

---

## 13. Known Limitations

- Event model: no ET, no continuous moisture, no baseflow dynamics; one storm per run line.
- Hortonian runoff only; saturation-excess catchments are outside its physics.
- Needs an element cascade; this KI copies and edits existing ones but has no DEM discretiser.
- Gridded hourly rain cannot represent convective intensities (dt_kineros2_036).
- The WG11 comparison is a single, in-sample event; volume +27.6 % and a slow simulated recession.
- `PIPE`, `URBAN`, `ADDER`, `DIVERTER` and compound channels are edited by hand (no tool).
- The models DB still stores the surrogate's daily metrics (NSE 0.851 / KGE 0.882 / r 0.923, Huaihe at Bengbu) and tier
  for KINEROS2. `knowledge_infrastructure.yaml` lists them only under `validation.surrogate_metrics_not_kineros2`;
  its `validation.metrics` hold the real-engine WG11 score (NSE 0.8115, 121 points, in-sample). Regenerating the
  manifest with generate_ki_manifest.py would project the DB's surrogate metrics again -- re-check it after any regeneration.

---

## 14. Spinup Requirements

| Parameter | Value |
|-----------|-------|
| Spinup length | none (event model) |
| Why | antecedent soil moisture is the SAT input per element / gage / global |
| Discard from metrics | No -- but align clocks and trim to the event window |

---

## 15. References

1. Goodrich, D.C., et al. 2012. KINEROS2/AGWA: model use, calibration, and validation. Trans. ASABE 55(4):1561-1574. doi:10.13031/2013.42264
2. Woolhiser, D.A., R.E. Smith, D.C. Goodrich. 1990. KINEROS, a kinematic runoff and erosion model: documentation and user manual. USDA-ARS ARS-77.
3. Smith, R.E., D.C. Goodrich, D.A. Woolhiser, C.L. Unkrich. 1995. KINEROS -- a kinematic runoff and erosion model. In Computer Models of Watershed Hydrology, V.P. Singh (ed.), 697-732.
4. KINEROS2 manual chapters shipped with the source: Input, Infiltration, Overland, Channel, Erosion, Rain, Source (src/doc/*.pdf).
5. Stone, J.J., M.H. Nichols, D.C. Goodrich, J. Buono. 2008. Long-term runoff database, Walnut Gulch Experimental Watershed. WRR 44, W05S05. doi:10.1029/2006WR005733
6. Goodrich, D.C., et al. 2008. Long-term precipitation database, Walnut Gulch Experimental Watershed. WRR 44, W05S04. doi:10.1029/2006WR005782
7. Rawls, W.J., D.L. Brakensiek, K.E. Saxton. 1982. Estimation of soil water properties. Trans. ASAE 25:1316-1320.
8. Sensitivity: Hantush & Kalin 2005 (doi:10.1623/hysj.2005.50.6.1151); Al-Qurashi et al. 2008 (doi:10.1016/j.jhydrol.2008.03.006); Korgaonkar et al. 2020 (doi:10.1016/j.envsoft.2020.104814).
9. Full literature list: `docs/papers_index.md` (16 papers).

---

## Pipeline walk (stage docs)

| Stage | Doc | Tools |
|---|---|---|
| plan | `docs/input_preparation.md` | - |
| s1 rainfall | `docs/s1_rainfall_input.md` | fetch_wgew_dap.py, build_kineros2_rainfall.py |
| s2 infiltration | `docs/s2_infiltration_soil_parameters.md` | kineros2_soil_params.py |
| s3 watershed | `docs/s3_watershed_parameter_file.md` | edit_kineros2_par.py |
| s4 sediment | `docs/s4_sediment_erosion.md` | configure_kineros2_sediment.py |
| s5 ponds / inflow | `docs/s5_ponds_injection_elements.md` | add_kineros2_element.py |
| s6 execution | `docs/s6_execution_real_engine.md` | run_kineros2_engine.py |
| s7 output | `docs/s7_output_parsing.md` | parse_kineros2_output.py |
| s8 calibration | `docs/s8_calibration_multipliers.md` | calibrate_kineros2_multipliers.py |
| s9 validation | `docs/s9_validation_wg11.md` | score_kineros2_event.py |

Surrogate history: `docs/surrogate/README.md`.

*Generated by the Knowledge Dissection Toolkit; rebuilt for the real engine 2026-10-06.*
