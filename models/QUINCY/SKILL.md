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
| to run the pipeline stages | `tools/` (11 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (44 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (16 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-10-07 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_quincy_climate.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_quincy_climate.py --help` |
| `tools/build_quincy_site_config.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_quincy_site_config.py --help` |
| `tools/convert_forcing_to_quincy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_quincy.py --help` |
| `tools/convert_parameters_to_quincy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters_to_quincy.py --help` |
| `tools/edit_quincy_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/edit_quincy_parameters.py --help` |
| `tools/parse_output_quincy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output_quincy.py --help` |
| `tools/parse_quincy_engine_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_quincy_engine_output.py --help` |
| `tools/run_quincy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_quincy.py --help` |
| `tools/run_quincy_engine.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_quincy_engine.py --help` |
| `tools/score_quincy_vs_fluxnet.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/score_quincy_vs_fluxnet.py --help` |

*10 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

> **SURROGATE WARNING.** `tools/run_quincy.py`, `tools/convert_forcing_to_quincy.py`,
> `tools/convert_parameters_to_quincy.py` and `tools/parse_output_quincy.py` are an older
> **Python stand-in** (analytic re-implementation, monthly step, no C-N-P pools). They are
> kept for the record and labelled SURROGATE in their headers and `--help`. **Their output is not
> QUINCY output and must never be reported as such** (their old FI-Hyy scores, NSE 0.95 after
> calibration, sit under `validation.surrogate_metrics_not_quincy` in knowledge_infrastructure.yaml).
> Triplets dt_quincy_001-025 and `docs/surrogate/` (incl. the stand-in's own contract
> `docs/surrogate/surrogate_quincy_analytic_dag.yaml`) belong to that stand-in. Everything else in
> this document is the real engine.
>
> **Default run route = the real engine:** `tools/run_quincy_engine.py`.

# QUINCY — Knowledge Infrastructure Skill Document

> **Version**: QUINCY standalone qs-2026.04-public (real engine `qs.bin`)
> **Domain**: terrestrial biogeochemistry (coupled C-N-P, water and energy)
> **Last updated**: 2026-10-07
> **Validation status**: real engine (tier `tested`); built-in self-tests reproduced byte for byte
> (no official site example is public); FI-Hyy (FLUXNET2015) 1996-2014 scored against tower
> fluxes as a validation run (untuned engine defaults, nothing calibrated)

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | QUINCY — QUantifying Interactions between terrestrial Nutrient CYcles and the climate system |
| Version | qs-2026.04-public, commit 2851ba3120a268fbdf7947537c12c071493b1735 |
| Language | Fortran (gfortran 13.3 build, ASCII text output) |
| License | BSD-3-Clause (public release since March 2025) |
| Repository | https://git.bgc-jena.mpg.de/quincy-model/qs-open-access (DOI 10.17871/quincy-model-2019) |
| Binary | `KISSPATH_HOME/engine_builds_20261006/QUINCY/src/x86_64-gfortran/bin/qs.bin` (sha256 1460dc68…0bab) |
| Engine folder | `KISSPATH_HOME/engine_builds_20261006/QUINCY` (binary, `src/data`, `src/src`, `run_builtin_*` references); set `QUINCY_ENGINE_ROOT` to use another build, `QUINCY_BIN` for the binary only |
| Citation | Thum et al. 2019, GMD 12:4781, doi:10.5194/gmd-12-4781-2019 |
| Primary domain | site-scale ecosystem C, N, P, water and energy fluxes |
| Spatial mode | Point (0-D column), half-hourly time step |

---

## 2. What This Model Does

QUINCY simulates a single site's vegetation and soil with fully coupled carbon, nitrogen and
phosphorus cycles, canopy photosynthesis with N- and chlorophyll-dependent capacity, plant
allocation and growth, soil organic matter and microbes, soil water, snow and the surface
energy balance. A site run starts from bare ground, spins up for centuries by cycling the site's
forcing years, then simulates the forcing period at a 30-min step.

---

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from dag + triplets). The full plan
for every input, what is derived and what the user must supply, is `docs/input_preparation.md`.

### 3.1 Meteorological forcing — `climate.dat` (tools/build_quincy_climate.py)

| Variable | Unit the engine expects | Source dataset | Source unit | Conversion |
|----------|-------------------|----------------|------------|------------|
| Shortwave down | W m-2 (daily route: 24-h mean) | FLUXNET `SW_IN_F` / loader `srad_wm2` | W m-2 | clip < 0 |
| Longwave down | W m-2 | `LW_IN_F` / `lrad_wm2` | W m-2 | none |
| Air temperature (t_air or tmin, tmax) | **K** | `TA_F` / `temp_min_c`, `temp_max_c` | °C | +273.15 |
| Specific humidity | **g kg-1** | from `TA_F`, `VPD_F`, `PA_F` / `shum_kgkg` | hPa, kPa / kg kg-1 | Tetens; ×1000 |
| Pressure | **hPa** | `PA_F` / `pres_pa` | kPa / Pa | ×10 / ÷100 |
| Precipitation | **mm day-1 rate on every row** | `P_F` / `precip_mm` | mm per step / mm day-1 | ×86400/dt / none |
| Wind | m s-1 | `WS_F` / `wind_ms` (10 m) | m s-1 | none |
| CO2 | ppm | `CO2_F_MDS`, gaps from Law Dome + Mauna Loa annual record | ppm | none |
| N deposition (NHx, NOy) | mg N m-2 day-1 | user (`--ndep_kgN_ha_yr`, cite it) | kg N ha-1 yr-1 | ×100/365 |
| P deposition | mg P m-2 day-1 | user (`--pdep_kgP_ha_yr`) | kg P ha-1 yr-1 | ×100/365 |

Data source choice: FLUXNET2015 tower met (`--source fluxnet`) is the default for FLUXNET sites
— it is how QUINCY site runs are driven and it is half-hourly, so the engine needs no synthetic
diurnal cycle. Elsewhere use `--source nasa_power` (global, daily, network) or `mswx` (global) or
`cmfd` (China); the engine then builds the diurnal cycle (`is_daily_forcing`).

### 3.2 Static inputs (tools/build_quincy_site_config.py)

| Input | Source | Tool that prepares it |
|-------|--------|----------------------|
| PFT (1-14) | engine site lists `fluxnet2_siteset_pft_info.csv`, `cruncep_v7_siteset_pft_info.csv`, or `--pft` | `build_quincy_site_config.py` |
| Soil texture, bulk density, pH | HWSD (`lookup_hwsd`) or explicit site values | `build_quincy_site_config.py` |
| Soil depth, elevation | user / site metadata | `build_quincy_site_config.py` |
| PFT library | `src/data/lctlib_quincy_nlct14.def` (copied unchanged) | `run_quincy_engine.py` |

### 3.3 Configuration files

| File | Format | Notes |
|------|--------|-------|
| `qs.namelist` | Fortran namelist | copy of `templates/qs.namelist.template` with single values replaced; each group once (dt_quincy_031) |
| `parameter_slm_run.list` | Fortran namelist | optional multipliers from `edit_quincy_parameters.py` |

---

## 4. Build Instructions

Built 2026-10-06 (do not rebuild for KI work; see `KISSPATH_HOME/engine_builds_20261006/QUINCY/BUILD_LOG.md`):

```bash
git clone --branch qs-2026.04-public https://git.bgc-jena.mpg.de/quincy-model/qs-open-access src
cd src && ./compile_quincy.sh gs      # gfortran 13.3, -O2, ASCII output; 27 s
```

**Known build facts:**
- The public release ships no run script, no `qs.namelist` and no site forcing; those live in the
  DKRZ development repository (login required). This KI supplies the namelist template and
  builds `climate.dat` itself.
- The text-output build (no NetCDF) only LOGS forcing-year mismatches (dt_quincy_027, dt_quincy_043).

---

## 5. Execution

```bash
PY=KISSPATH_PYTHON_ENV/bin/python
KI=KISSPATH_KI_ROOT/QUINCY/knowledge_infrastructure
# REFERENCE CHECK = engine self-tests, compared byte for byte with the build-time runs
# (default reference <engine>/run_builtin_<mode>; prints "reproduced": true, exit 0)
$PY $KI/tools/run_quincy_engine.py --mode test_canopy   --run_dir /tmp/q_can   # 10/10 files
$PY $KI/tools/run_quincy_engine.py --mode test_radiation --run_dir /tmp/q_rad  # 2/2 files
# site run, step by step (the FI-Hyy validation run, ~10 min):
C=/tmp/q_fihyy
$PY $KI/tools/build_quincy_climate.py --source fluxnet --site FI-Hyy --start_year 1996 --end_year 2014 \
    --ndep_kgN_ha_yr 7.4 --pdep_kgP_ha_yr 0.05 --out_dir $C/climate
$PY $KI/tools/build_quincy_site_config.py --lat 61.8474 --lon 24.2948 --site FI-Hyy --soil hwsd \
    --elevation_m 181 --out $C/site_config.json
$PY $KI/tools/run_quincy_engine.py --mode land --run_dir $C/run --climate_dir $C/climate \
    --site_config $C/site_config.json --spinup_years 500
$PY $KI/tools/parse_quincy_engine_output.py --run_dir $C/run --out_dir $C/parsed
$PY $KI/tools/score_quincy_vs_fluxnet.py --daily_csv $C/parsed/quincy_daily.csv --site FI-Hyy \
    --out_dir $C/score --figure $C/score/fluxnet_fit.png
```

The same chain as one script (outside the KI, server only):
`$PY KISSPATH_KI_ROOT/QUINCY/run_and_score.py <out_dir>`.
Optional calibration lever: `edit_quincy_parameters.py` → `run_quincy_engine.py --param_list`.
Stage docs: `docs/s0_configuration.md` … `docs/s5_validation.md`.

**Expected runtime**: 1-4 s per simulated year at a 30-min step (machine load); FI-Hyy
500-yr spin-up + 19 years took 573 s on 2026-10-07. Self-tests < 1 s.

**Exit codes** of `run_quincy_engine.py`: 0 success, 2 bad input (engine not started), 3 engine
failed (exit code, missing "End QUINCY model", non-empty `.err`, or a "Please check!" log line —
the engine itself exits 0 after a fatal `finish()`, dt_quincy_026), 4 outputs missing/short or
different from `--reference_dir`.

---

## 6. Output Description

Sourced from `dag.yaml` (the dag wins if they disagree).

**Headline output** (`validation_rank: 1`):

> `GPP` — Terrestrial ecosystem gross primary production of the vegetation canopy (gross carbon
> assimilation), daily mean; engine writes mol C/m2/day in vegflux_c_daily.txt, the parser
> converts (also g C/m2/day as GPP_gC). (umol CO2/m2/s)

| Output variable (dag `var`) | rank | Engine file → parsed | Unit | Medium |
|----------------|------|------|------|--------|
| GPP | 1 | vegflux_c_daily.txt → quincy_daily.csv | umol CO2/m2/s (and GPP_gC g C/m2/day) | vegetation canopy |
| LE | 2 | vegflux_energy_daily.txt (Qle, MJ/m2/day) | W/m2 | land surface → atmosphere |
| NEE | 3 | vegflux_c + soilflux_cdc13dc14 | umol CO2/m2/s, positive = source | ecosystem ↔ atmosphere |
| Reco | 4 | as NEE | umol CO2/m2/s | ecosystem |
| Ra | 5 | vegflux_c_daily.txt | umol CO2/m2/s | vegetation |
| Rh | 6 | soilflux_cdc13dc14_daily.txt (HetResp) | umol CO2/m2/s | soil |
| LAI | 7 | veg_diagnostics_daily.txt | m2/m2 | vegetation canopy |
| H | 8 | vegflux_energy_daily.txt (Qh) | W/m2 | land surface → atmosphere |

Further engine outputs (basic set): vegetation and soil C/N/P pools (mol m-2), N and P fluxes,
mycorrhiza, soil water and temperature by layer, canopy-layer diagnostics, matter-conservation test.

---

## 7. Tool Inventory

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `tools/build_quincy_climate.py` | forcing: FLUXNET tower met (timestep) or NASA POWER/MSWX/CMFD (daily) + CO2 + N/P deposition | site or lat/lon, years, deposition | climate.dat, climate_meta.json |
| `tools/build_quincy_site_config.py` | PFT selection, soil (HWSD or explicit), depth, elevation | lat/lon, site id or PFT | site_config.json |
| `tools/edit_quincy_parameters.py` | calibration/sensitivity lever: proportional parameter changes, names checked against engine source | NAME=MULT | parameter_slm_run.list |
| `tools/run_quincy_engine.py` | run the REAL engine (land/plant/canopy, self-tests) with honest success checks | climate dir, site config | run dir + run_manifest.json |
| `tools/parse_quincy_engine_output.py` | dated daily series in FLUXNET units; water-balance, LE/ET and spin-up drift checks | run dir | quincy_daily.csv, summary |
| `tools/score_quincy_vs_fluxnet.py` | metrics vs FLUXNET2015 FULLSET_DD (daily, monthly, annual) + figure | quincy_daily.csv, site | score.json, pairs csv, png |
| `tools/_quincy_common.py` | helper (paths, 365-day calendar, namelist editing, success test) | – | – |
| `tools/run_quincy.py` + 3 converters | **SURROGATE** Python stand-in — not QUINCY | – | – |

Capabilities without a dedicated tool are namelist switches passed with
`run_quincy_engine.py --nml group.key=value`: stand-replacing harvest
(`lnd_q_syl_nml.flag_stand_harvest`, `stand_replacing_year`), fire (`lnd_dist_fire_nml.flag_dfire`),
N/P cycle switches (`base_ctl.include_nitrogen/include_phosphorus`), optimal leaf-N
(`lnd_q_assimi_nml.flag_optimal_Nfraction`), deposition schemes (`jsb_forcing_ctl.n_deposition_scheme`),
spin-up accelerator (`base_ctl.flag_slow_sb_pool_spinup_accelerator`), output file sets (`--output_set`).
These switches were not exercised in a scored run yet.

Shared utilities used: `load_daily_forcing`, `lookup_hwsd`, `all_metrics`, `validate_water_balance`.

---

## 8. Unit Conversion Table

| Variable | Source unit (verified) | Model unit | Factor | Type |
|----------|----------------------|------------|--------|------|
| Air temperature | °C (FLUXNET TA_F, loader temp_*_c) | K | +273.15 | additive |
| Pressure | kPa (FLUXNET PA_F) / Pa (loader) | hPa | ×10 / ÷100 | multiplicative |
| Specific humidity | kg kg-1 (loader) | g kg-1 | ×1000 | multiplicative |
| Precipitation | mm per half hour (FLUXNET P_F) | mm day-1 rate | ×48 (×86400/dt) | multiplicative |
| N deposition | kg N ha-1 yr-1 | mg N m-2 day-1 | ×100/365 | multiplicative |
| Soil texture | % (HWSD) | fraction | ÷100 | multiplicative |
| Bulk density | g cm-3 (HWSD) | kg m-3 | ×1000 | multiplicative |
| Engine C flux output | mol C m-2 day-1 | umol CO2 m-2 s-1 / g C m-2 day-1 | ×1e6/86400 / ×12.011 | multiplicative |
| Engine energy output | MJ m-2 day-1 | W m-2 | ×1e6/86400 | multiplicative |
| FLUXNET DD carbon | g C m-2 day-1 (NOT umol, dt_quincy_033) | g C m-2 day-1 | 1 | none |

## 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|------------------------|-------------------|-----------------|
| Qle, Qh (engine) | upward positive (writer negates the internal flux) | downward positive | LE/H sign flips |
| NEE (parsed) | Reco − GPP, positive = source (FLUXNET) | GPP − Reco | sign flip, NSE < 0 |
| Fluxes in text files | SUMS over the output interval | rates | ×86400 errors |
| Water outputs | mm per interval; Evaporation = bare soil only | total ET | ET too low by T + I |
| Monthly interval | 30 model days, not calendar months (dt_quincy_042) | calendar months | phase drift |

---

## 9. Diagnostic Triplets (Top 5)

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| 1 | dt_quincy_026: exit 0 but no output, `.err` has FINISH | engine finish() exits 0 | trust run_quincy_engine.py status, not the exit code |
| 2 | dt_quincy_027: years repeat, log "Please check!" | short climate.dat rewound silently | build whole years with build_quincy_climate.py |
| 3 | dt_quincy_030: run far too dry | precipitation must be a mm/day rate on every row | P_F × 86400/dt |
| 4 | dt_quincy_031: namelist edits ignored | duplicated namelist group | one group each; run tool checks read-back |
| 5 | dt_quincy_034: GPP/LAI low, trending | spin-up too short | `--spinup_years 500`, check spin-up drift |

Full corpus: `diagnostics/triplets.yaml` (dt_quincy_026-044 real engine; 001-025 surrogate only).

---

## 10. Coupling Interfaces

| Upstream model | Variable exchanged | Unit | Temporal resolution |
|---------------|-------------------|------|-------------------|
| Weather data (FLUXNET, NASA POWER, MSWX, CMFD) | climate.dat forcing | see §3.1 | half-hourly or daily |

| Downstream model | Variable exchanged | Unit | Temporal resolution |
|-----------------|-------------------|------|-------------------|
| Hydrology models | ET, runoff, drainage | mm day-1 | daily |
| Carbon budgets | GPP, NEE, pools | g C m-2 day-1, mol m-2 | daily / yearly |

---

## 11. Validated Results

### Engine check — built-in self-tests (the public release has no official site example)

The public release qs-2026.04-public ships no official site example (run scripts and site
forcing are in the DKRZ development repository, login required; contact qs-open-access@bgc-jena.mpg.de).
The only reference check is therefore the engine's built-in code self-tests run at build time
(BUILD_LOG.md). These are code self-tests, NOT a site simulation.
`test_canopy`: fort.10-17 response tables, engine log and stdout byte-identical to the build-log
run (10/10 files). `test_radiation`: log and stdout byte-identical (2/2). Run 2026-10-07 through
`tools/run_quincy_engine.py` (default reference = the build-time run).

### Real case: FI-Hyy (Hyytiälä, Finland), FLUXNET2015

| Property | Value |
|----------|-------|
| Location | 61.8474 N, 24.2948 E, 181 m; boreal Scots pine, QUINCY PFT 5 (BNE, engine site list) |
| Period | 1996-2014 (19 years) after a 500-yr spin-up cycling 1996-2014 |
| Forcing | FLUXNET2015 FULLSET_HH tower met (half-hourly), CO2_F_MDS; N deposition 7.4 kg N ha-1 yr-1 (Korhonen et al. 2013), P deposition 0.05 kg P ha-1 yr-1 (assumption) |
| Soil | HWSD topsoil (silty clay, pH 4.3) — not the site's sandy podzol (dt_quincy_038) |
| Parameters | engine defaults, untuned |
| Role | **validation** — nothing calibrated; all 19 years are scored |
| Outputs | `KISSPATH_KI_ROOT/QUINCY/detached/real_case/38e41ff2e4094bf4bfb5c2e4a3b084d0/case/` (climate, run, parsed, score); an identical earlier run (byte-identical forcing and GPP file) in `KISSPATH_OUTPUTS/quincy_fihyy_real_engine/` |

### Performance metrics — judged against the field's bar

> Bar for `GPP` (r², per `docs/validation_convention.yaml`, cites tramontana2016, thum2025, thum2019):
> satisfactory ≥ 0.7, good / very good: no cited threshold.
> Achieved: daily r² = 0.937 (r 0.968) → **satisfactory (passes)**.

| Variable | n days | Daily NSE | Daily r (r²) | KGE | PBIAS % | Monthly NSE | Bar (convention, cited) |
|--------|-----|------|------|------|------|------|-------|
| GPP | 6260 | 0.917 | 0.968 (0.937) | 0.828 | −11.5 | 0.956 | r² ≥ 0.7 satisfactory → passes |
| LE | 6585 | 0.550 | 0.864 (0.746) | 0.614 | +29.7 | 0.732 | r² ≥ 0.7 → passes |
| Reco | 6260 | 0.812 | 0.943 (0.889) | 0.775 | +9.2 | 0.874 | r² ≥ 0.6 → passes |
| NEE | 6260 | 0.493 | 0.822 (0.676) | −0.069 | −95.9 | 0.455 | no cited threshold (null) |
| H | 6671 | 0.339 | 0.658 (0.432) | 0.400 | −47.5 | 0.617 | r² ≥ 0.7 → fails |

Annual sums: GPP 986 vs tower 1159 g C m-2 yr-1; Reco 977 vs 914; NEE −9.5 vs −246 (equilibrium
stand, dt_quincy_044). Water balance residual 7.8 % of P; LE/(λ·ET) 1.18 (snow sublimation,
dt_quincy_039); ecosystem C still rising 3.5 % per 100 yr at the end of spin-up.
Days with daily QC < 0.75 and Feb 29 excluded; carbon fluxes compared in g C m-2 d-1 (FULLSET_DD;
its yearly sums equal FULLSET_YY). Carbon variables share the same 6,260 days 1996-06-13..2014-12-31.
Tower met drives the model, the scored fluxes are independent eddy-covariance measurements.

**How to read GPP NSE 0.92.** Checked 2026-10-07 from the raw engine file and the raw FLUXNET file
(`KISSPATH_HOME/ki_fix_campaign/kdt_real_engine/review_QUINCY/rescore_fihyy_independent.py`): model GPP
is the engine's own output (no day equals the tower value; max 9.7 g C m-2 d-1; no negative days;
mean seasonal cycle Jan 0.02 → Jul 7.3 against tower 8.5 g C m-2 d-1). At this boreal site the
seasonal cycle dominates: the tower's own day-of-year climatology scores NSE 0.893 on the same
days, and a linear fit of tower GPP on tower SW and air temperature 0.817. So the engine adds only
a little day-to-day skill on top of the seasonal cycle; the high NSE is mostly a correct season.

Figure: `KISSPATH_KI_ROOT/QUINCY/figures/s8_validation.png`.

### Data replacement tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | FLUXNET2015 tower / NASA POWER | Validated (tower); engine-run only (NASA POWER) | daily NASA POWER route ran 2004-2005 without spin-up, not scored |
| Soil | HWSD | Pending | wrong texture at FI-Hyy |
| PFT | engine site list | Validated | |
| Initial conditions | 500-yr spin-up | Validated | drift 3.5 %/100 yr |

---

## 12. Parameter Selection by Region

| Climate / Region | Key settings | Rationale |
|---|---|---|
| Boreal conifer (FLUXNET ENF) | PFT 5 (BNE), 500-yr spin-up, site N deposition | engine site list; untuned GPP NSE 0.92 at FI-Hyy |
| Temperate broadleaf | PFT 4 (BDS) | engine fluxnet2 site list |
| Grassland / pasture | PFT 7/8 (C3/C4 grass), 9/10 pasture | PFT parameter edits only for PFT ≤ 8 (dt_quincy_037) |
| Tropical | PFT 1/2/3; keep `include_phosphorus` on | P limitation matters (Yu et al. 2020) |

---

## 13. Known Limitations

- Point model; ASCII output build (no NetCDF, no restart files, no `bc_*.nc` land-use or fertiliser inputs).
- No official site example in the public release; engine check = built-in self-tests.
- Spun-up equilibrium stand: no age or management history (NEE sink underestimated).
- N and P deposition are user inputs (no gridded dataset on the server).
- HWSD soil can be wrong at the site scale.

---

## 14. Spinup Requirements

| Parameter | Value |
|-----------|-------|
| Spinup length | 500 years (default `--spinup_years 500`), cycling the forcing years |
| Why | starts from bare ground; in 2026-10-07 probes with the engine's default soil, a 38-yr spin-up gave GPP 699 vs 934 g C m-2 yr-1 after 500 yr, daily NSE 0.66 vs 0.89 (dt_quincy_034; the scored run with HWSD soil: 986, NSE 0.917) |
| Discard from metrics | yes — spin-up goes to `*_spinup_yearly.txt`, scoring uses the forcing period only |

---

## 15. References

1. Thum, T. et al. (2019) A new model of the coupled carbon, nitrogen, and phosphorus cycles in the terrestrial biosphere (QUINCY v1.0; revision 1996). GMD 12, 4781-4802. doi:10.5194/gmd-12-4781-2019
2. Thum, T. et al. (2025) Modelling decadal trends and the impact of extreme events on carbon fluxes in a temperate deciduous forest. Biogeosciences 22, 1781. doi:10.5194/bg-22-1781-2025
3. Korhonen, J. F. J. et al. (2013) Nitrogen balance of a boreal Scots pine forest. Biogeosciences 10, 1083. doi:10.5194/bg-10-1083-2013
4. Tramontana, G. et al. (2016) Predicting carbon dioxide and energy fluxes across global FLUXNET sites with regression algorithms. Biogeosciences 13, 4291. doi:10.5194/bg-13-4291-2016
5. Blyth, E. et al. (2010) Evaluating the JULES land surface model energy fluxes using FLUXNET data. J. Hydrometeorol. 11, 509. doi:10.1175/2009JHM1183.1
6. Full list: `docs/gathered_papers.json`, `docs/papers_index.md`.

---

*Generated by the Knowledge Dissection Toolkit (real-engine rebuild 2026-10-07).*
