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
| to run the pipeline stages | `tools/` (8 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (9 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (35 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (20 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-10-07 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_lpjguess_cf_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_lpjguess_cf_forcing.py --help` |
| `tools/build_lpjguess_co2_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_lpjguess_co2_file.py --help` |
| `tools/convert_forcing_to_lpjguess.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_lpjguess.py --help` |
| `tools/convert_parameters_to_lpjguess.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters_to_lpjguess.py --help` |
| `tools/parse_lpjguess_engine_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_lpjguess_engine_output.py --help` |
| `tools/parse_output_lpjguess.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output_lpjguess.py --help` |
| `tools/run_lpjguess.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_lpjguess.py --help` |
| `tools/run_lpjguess_engine.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_lpjguess_engine.py --help` |

*8 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# LPJ-GUESS -- Knowledge Infrastructure Skill Document

> **Version**: LPJ-GUESS 4.1.1 (real engine) — KI rewired 2026-10-07
> **Domain**: terrestrial biogeochemistry / dynamic vegetation (C, N, water)
> **Last updated**: 2026-10-07
> **Validation status**: real engine; official demo reproduced exactly; one FLUXNET site scored as validation, untuned (manifest tier `tested`)
> **Default run route**: `tools/run_lpjguess_engine.py` (the real `guess` binary). The surrogate is never the default.

> **SURROGATE WARNING.** `tools/run_lpjguess.py`, `convert_forcing_to_lpjguess.py`,
> `convert_parameters_to_lpjguess.py` and `parse_output_lpjguess.py` are a **Python
> light-use-efficiency SURROGATE** (LUE GPP + Q10 respiration) kept for history. They are
> **not LPJ-GUESS** and their numbers (e.g. a calibrated GPP NSE ~0.90) must never be reported
> as LPJ-GUESS results (dt_lpjguess_033). Their old contract is kept apart in
> `docs/surrogate_lpjguess_lue_dag.yaml`; their old scores sit only under
> `validation.surrogate_metrics_not_lpjguess` in `knowledge_infrastructure.yaml`. Triplets
> dt_lpjguess_001-004 and 011-014 apply to the surrogate only (`applies_to: surrogate`). Every
> result in this document comes from the real engine through the four `*_engine*` /
> `build_lpjguess_*` tools.

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | Lund-Potsdam-Jena General Ecosystem Simulator |
| Version | 4.1.1 research release |
| Source | Zenodo record 8065737 (doi 10.5281/zenodo.8065737), linked from https://web.nateko.lu.se/lpj-guess/download.html |
| License | MPL-2.0 |
| Language | C++ (cmake), NetCDF C for the CF input module |
| Binary | `KISSPATH_HOME/engine_builds_20261006/LPJ_GUESS/build/guess` (ELF, 1.4 MB) |
| Engine source | `KISSPATH_HOME/engine_builds_20261006/LPJ_GUESS/src/` |
| Build log | `KISSPATH_HOME/engine_builds_20261006/LPJ_GUESS/BUILD_LOG.md` |
| Key papers | Smith et al. 2001 (GEB 10:621); Smith et al. 2014 (Biogeosciences 11:2027); Sitch et al. 2003 (GCB 9:161) |

## 2. What This Model Does

LPJ-GUESS simulates vegetation and soil carbon, nitrogen and water from daily weather and
CO2. Plants are individuals/cohorts of plant functional types (12 global PFTs in
`global.ins`) that compete for light and water on replicate patches; establishment,
mortality and disturbance run yearly. Daily processes: photosynthesis and stomatal
conductance (`canexch.cpp`), multi-layer soil water and snow (`soil.cpp`), autotrophic
respiration; CENTURY soil organic matter with a coupled N cycle (`somdynam.cpp`,
`ntransform.cpp`); fire (GLOBFIRM here; BLAZE needs files not on the server).

The engine reads climate through **input modules**: `demo` (toy monthly climate, used for
the official demo), `cru` (CRU binary archives, not on the server) and `cf` (CF-NetCDF —
what this KI uses for real sites).

Capabilities wired by this KI (full list: `docs/input_preparation.md` §1):

1. **[PRIMARY] Site carbon/water fluxes** — GPP, Ra, Rh, Reco, NEE, NPP, ET components, monthly and annual.
2. **Official demo / install check** — 13 cells, byte-exact against the build-time run.
3. **Vegetation composition** — PFT selection via `--set 'pft "X" ( include 0 )'`.
4. **Fire model choice** — `--firemodel GLOBFIRM|NOFIRE|BLAZE`.
5. **Spin-up / patch / any `.ins` switch** — `--nyear_spinup`, `--npatch`, `--set`.
6. **Water fluxes** — transpiration, soil evaporation, interception, runoff, PET + water-balance check.
7. **Scoring against FLUXNET2015** monthly GPP/NEE/RECO/ET.

Not wired yet: crops/land cover/managed forest, transient N deposition, sub-daily output.

## 3. Input Requirements

Exact shapes: `docs/format_spec.yaml` (projected from `dag.yaml`). Preparation plan with the
verified shared-library schema: `docs/input_preparation.md`.

### 3.1 Meteorological Forcing (CF input, daily)

| Variable | Unit the engine checks | CF standard_name | Built from loader key |
|---|---|---|---|
| temp | K | air_temperature | temp_mean_c + 273.15 |
| prec | kg m-2 s-1 | precipitation_flux | precip_mm / 86400 |
| insol | W m-2 (24-h mean) | surface_downwelling_shortwave_flux_in_air | srad_wm2 |
| min_temp / max_temp | K | air_temperature | temp_min_c / temp_max_c + 273.15 |
| relhum | 1 (fraction) | relative_humidity | from shum_kgkg, pres_pa, temp |
| wind | m s-1 | wind_speed | wind_ms (10 m) |

At least **30 full years** are required (spin-up climate = first 30 years; dt_lpjguess_021).
Data source used: **NASA POWER** (global, proxy-safe, ~4 s/yr; shortwave from 1984). FLUXNET
met is too short (≤26 yr); CMFD is China-only; MSWX is slow and its 1979 file is broken.

### 3.2 Static Inputs

| Input | File | Note |
|---|---|---|
| CO2 | `models/LPJ_GUESS/inputs/co2/co2_1901_2014.txt` | Law Dome (pre-1959) + NOAA Mauna Loa; not shipped with 4.1.1 (dt_lpjguess_022) |
| Soil code | shipped `src/data/env/soils_lpj.dat` | run tool adds an exact site line (dt_lpjguess_019/020) |
| Gridlist | `gridlist_cf.txt` | `0 0 <site>` — array INDICES (dt_lpjguess_024) |
| N deposition | none | constant pre-industrial 2 kgN/ha/yr (dt_lpjguess_035) |

### 3.3 Configuration Files

Copied from `src/data/ins/`: `global.ins` (PFTs + switches), `global_cf.ins` (file paths,
imports `global.ins` and `global_soiln.ins`), `global_demo.ins`. The cf mode writes
`site_cf.ins` = `global_cf.ins` with only the `param "file_*"` values replaced on active lines,
plus appended overrides (later lines win). Nothing is generated from scratch.

## 4. Build Instructions

Already built — do not rebuild for KI work. For reference (BUILD_LOG.md):
```bash
cd KISSPATH_HOME/engine_builds_20261006/LPJ_GUESS/build
cmake ../src -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5
make -j4        # 7 s, warnings only; NetCDF found -> cf input compiled in
```

## 5. Execution

```bash
PY=KISSPATH_PYTHON_ENV/bin/python; KI=KISSPATH_KI_ROOT/LPJ_GUESS/knowledge_infrastructure
$PY $KI/preflight_check.py
# official demo (~4 min), compared with the build-time reference:
$PY $KI/tools/run_lpjguess_engine.py example --out_dir /tmp/lpj_demo
# a FLUXNET site:
$PY $KI/tools/build_lpjguess_cf_forcing.py --site DE-Tha --lat 50.9624 --lon 13.5652 \
    --start_year 1984 --end_year 2014 --source nasa_power --out_dir forcing
$PY $KI/tools/run_lpjguess_engine.py cf --forcing_meta forcing/forcing_meta.json \
    --co2_file KISSPATH_KI_ROOT/LPJ_GUESS/inputs/co2/co2_1901_2014.txt --out_dir run_detha
$PY $KI/tools/parse_lpjguess_engine_output.py --run_dir run_detha/run --out_dir parsed \
    --fluxnet_dir KISSPATH_OBS/fluxnet/sites/DE-Tha \
    --forcing_meta forcing/forcing_meta.json --figure fig.png --site DE-Tha
# (a run with several cells: add --cell LON LAT; cells are never averaged)
```
The example mode needs the complete build-time reference `<engine>/run_global_demo` (19 `.out`
files); a missing, empty or incomplete reference is exit 5, never a pass. `--reference_dir ''`
skips the check and the JSON then says `"reproduced": false`.
Headless command underneath: `cd <run> && guess -input cf site_cf.ins` (or `-input demo global_demo.ins`).
Run tool exit codes: 0 ok, 2 bad input, 3 engine failed (rc≠0, no `Finished`, timeout),
4 outputs missing/incomplete, 5 demo differs from reference. The engine's own failures exit 99
with a bare message in `guess.log` (no "Error" prefix — dt_lpjguess_030).

## 6. Output Description

From `dag.yaml` (authoritative). The rank-1 output is **GPP** — "Gross Primary Production
(terrestrial vegetation carbon assimilation flux)." (`umol/m2/s`).

| dag var | rank | dag unit | engine table (native unit) |
|---|---|---|---|
| GPP | 1 | umol/m2/s | `mgpp.out` kgC m-2 month-1 (GPP minus leaf respiration) |
| NPP | 2 | umol/m2/s | `mnpp.out` (= mgpp − mra) |
| Ra | 3 | umol/m2/s | `mra.out` |
| Rh | 4 | umol/m2/s | `mrh.out` |
| Reco | 5 | umol/m2/s | `mra.out` + `mrh.out` |
| NEE | 6 | umol/m2/s | `mnee.out` (= mrh − mnpp; + = source; fire C excluded) |

Other tables: annual `cmass` (kgC m-2 per PFT), `lai`, `fpc`, `agpp`, `anpp`, `aaet`,
`cflux`, `cpool`, `dens`, `tot_runoff`; monthly `maet` (transpiration only), `mevap`,
`mintercep`, `mrunoff`, `mpet`, `mlai`. Tables are whitespace columns `Lon Lat Year ...`,
3 decimals. The parser's `annual.csv` keeps every annual table of the run (incl. `dens`, `doc`,
`cton_leaf` and the nitrogen tables) and every column of each, as `<table>_<column>` (per-PFT
`cmass_TeBS`, `cflux_Fire`, `cpool_SoilC`, `npool_SoilN`, ...).

## 7. Tool Inventory

| Tool | Kind | Purpose | Output |
|---|---|---|---|
| `tools/build_lpjguess_cf_forcing.py` | engine | daily CF NetCDF forcing via `load_daily_forcing` + validate_outputs | 7 `.nc`, gridlist, forcing_meta.json |
| `tools/build_lpjguess_co2_file.py` | engine | annual CO2 file from Law Dome + Mauna Loa | `<year> <ppm>` text |
| `tools/run_lpjguess_engine.py` | engine | run `guess` (example / cf) with success checks | run dir + JSON |
| `tools/parse_lpjguess_engine_output.py` | engine | tables → CSV, water balance, FLUXNET metrics, figure | CSV, summary.json, PNG |
| `tools/run_lpjguess.py` | SURROGATE | Python LUE stand-in | not LPJ-GUESS |
| `tools/convert_forcing_to_lpjguess.py` | SURROGATE | CSV forcing for the stand-in | — |
| `tools/convert_parameters_to_lpjguess.py` | SURROGATE | LUE parameter JSON | — |
| `tools/parse_output_lpjguess.py` | SURROGATE | parses stand-in CSV | — |

Stage docs: `docs/s6_build_cf_forcing.md`, `docs/s7_build_co2_file.md`, `docs/s8_run_engine.md`,
`docs/s9_parse_engine_output.md` (engine); `docs/s1_preflight.md`; `docs/s2`–`s5` (surrogate).

### Shared Utilities (ki_tools_common)

`load_forcing.load_daily_forcing` (forcing), `validation.validate_forcing_ranges` and
`validate_water_balance`, `metrics.all_metrics` (keys `NSE KGE PBIAS RMSE r`).

## 8. Unit Conversion Table

| Variable | Source unit (verified) | Engine unit | Operation |
|---|---|---|---|
| Air temperature | °C (loader) | K | + 273.15 |
| Precipitation | mm/day (loader) | kg m-2 s-1 | ÷ 86400 |
| Shortwave | W m-2 daily mean (loader) | W m-2 | × 1 |
| Humidity | kg/kg + Pa + °C | fraction | e = q·p/(0.622+0.378q); RH = e/es(T) |
| Monthly carbon out | kgC m-2 month-1 | gC m-2 d-1 | × 1000 ÷ days in month |
| Carbon flux | gC m-2 d-1 | µmol CO2 m-2 s-1 | × 1e6/12.011/86400 = 0.9636 |
| Monthly water out | mm month-1 | mm d-1 | ÷ days in month |
| Tower LE | W m-2 | mm d-1 | × 0.0864/2.45 |

## 8b. CMFD/MSWX Data Conventions

The loader returns °C, mm/day and W m-2 for every source; this KI converts once, in
`build_lpjguess_cf_forcing.py`. CMFD covers China only. MSWX `P_1979.nc` has a faulty time
axis, so MSWX runs start in 1980.

## 8c. Sign Conventions and Output Units

NEE: positive = carbon source (same as FLUXNET NEE_VUT_REF). GPP, Ra, Rh, NPP positive.
FLUXNET2015 MM files are in gC m-2 d-1, so scoring is done in that unit.

## 9. Diagnostic Triplets (Top 5)

35 entries in `diagnostics/triplets.yaml`; dt_lpjguess_019–035 are real-engine traps
reproduced on this server. Most important:

- **dt_lpjguess_019** — `searchradius_soil` segfaults `-input cf` (engine bug); the tool adds a site soil line instead.
- **dt_lpjguess_021** — CF forcing needs ≥30 years.
- **dt_lpjguess_026** — `maet` is transpiration only; ET = maet + mevap + mintercep.
- **dt_lpjguess_027** — default run = potential natural vegetation, not the planted stand.
- **dt_lpjguess_033** — surrogate output is not LPJ-GUESS.

## 10. Coupling Interfaces

Inputs are CF-NetCDF files and text; outputs are whitespace tables. A coupler can feed any
daily CF forcing on a lat/lon grid (gridlist = indices) and read the monthly tables.

## 11. Validated Results

### Official example (global_demo)

`run_lpjguess_engine.py example` (2026-10-07): rc 0, `Finished`, 252 s, years 500–599,
**19/19 `.out` files byte-identical** to the build-time run (max abs diff 0). Matches the
build log (e.g. final-year total cmass: Amazon 16.497, C. Europe 8.466, Canada boreal 4.847 kgC m-2).

### Test site: DE-Tha (Tharandt, Germany; 50.9624 N, 13.5652 E; planted Norway spruce)

**Role: validation only. Nothing was calibrated.** Default, untuned run: all 12 global PFTs
as shipped in `global.ins` (potential natural vegetation, PNV), GLOBFIRM fire, 500-year
spin-up, constant pre-industrial N deposition. Forcing NASA POWER 1984-2014 at the tower
point (not tower meteorology); CO2 Law Dome + NOAA Mauna Loa (1901-2014); soil code 2 from the
0.5-degree cell (13.75, 50.75). Engine run 15 s, last year 2014.

Scored run (2026-10-07, KDT detached run):
`KISSPATH_KI_ROOT/LPJ_GUESS/detached/real_case/752ec75aabc741d9b7a241e383174692/work/run_detha/run`
(an earlier identical run, same `mgpp.out` bytes: `KISSPATH_OUTPUTS/lpjguess_detha_real_engine/run`).
Figure: `KISSPATH_KI_ROOT/LPJ_GUESS/figures/s8_validation.png`.

Observations: FLUXNET2015 FULLSET_MM for DE-Tha. Months kept where `NEE_VUT_REF_QC >= 0.5`;
the same 221 months for every variable, 1996-07 .. 2014-12. Compared in gC m-2 d-1 (mm d-1 for ET):

| Variable (monthly) | engine | tower | NSE | KGE | r | PBIAS % | RMSE |
|---|---|---|---|---|---|---|---|
| GPP (dag rank 1) | `mgpp` (GPP minus leaf resp.) | `GPP_NT_VUT_REF` | 0.690 | 0.611 | 0.963 | −34.8 | 2.22 |
| Reco | `mra + mrh` | `RECO_NT_VUT_REF` | 0.851 | 0.853 | 0.950 | −12.0 | 0.89 |
| NEE | `mnee` (= mrh − mnpp, no fire C) | `NEE_VUT_REF` | 0.006 | 0.048 | 0.826 | −83.5 | 1.77 |
| ET (not a dag output) | `maet + mevap + mintercep` | `LE_F_MDS` × 0.0864/2.45 | 0.686 | 0.655 | 0.927 | +8.8 | 0.43 mm d-1 |

Means: GPP obs 5.36 vs engine 3.49; NEE obs −1.67 vs engine −0.28; Reco obs 3.66 vs 3.22;
ET obs 1.11 vs 1.20. Water balance over 1984-2014: P 22408 mm, ET 13483 mm, runoff 8836 mm,
residual 89 mm (0.4 %). Re-scored from the existing outputs with `ki_tools_common.metrics.all_metrics`
and plain numpy (they agree): `KISSPATH_HOME/ki_fix_campaign/kdt_real_engine/review_LPJ-GUESS/score_detha.py`.

**Judged against `docs/validation_convention.yaml`** (GPP, Reco, NEE: headline NSE, only
cited band = satisfactory NSE ≥ 0, walker2014; no good/very-good tier is cited): GPP 0.69
and Reco 0.85 pass the floor. NEE 0.006 is above the floor by a hair, i.e. no real skill
beyond the observed mean; treat NEE as **not reproduced**. ET has no dag entry.

**Known bias (why GPP and NEE are too small).** The default run grows PNV, not the planted
spruce stand: in 2014 `cmass` is 5.96 of 6.77 kgC m-2 temperate broadleaf summergreen (TeBS)
and only 0.21 needleleaf (BNE + BINE). So winter GPP is near zero (Dec-Feb calendar-month means: engine 0.02-0.07 vs
tower 0.51-0.97 gC m-2 d-1) and the summer peak is low (June mean 8.2 vs 11.2; dt_lpjguess_027); `mgpp` also excludes
leaf respiration (dt_lpjguess_025). NEE: the 500-year spin-up grows unmanaged natural vegetation
(no planting, thinning or harvest), so the stand has no young managed-stand history and the
sink is far too small (dt_lpjguess_034).
Zhu et al. 2020 report a site-mean GPP RMSE of 2.13 gC m-2 d-1 as context (not a gate).

Side test (a configuration choice, not calibration, and NOT the reported result): only BNE +
C3G allowed (`--set 'pft "X" ( include 0 )'` for the other 10 PFTs), same forcing:
GPP NSE 0.80, PBIAS −25.8 %; Reco NSE 0.87; ET NSE 0.72; NEE NSE −0.22
(`KISSPATH_OUTPUTS/lpjguess_detha_real_engine/sensitivity_needleleaf_only/`).

### Data Replacement Tracking

| Component | Source | Status |
|---|---|---|
| Forcing | NASA POWER via load_daily_forcing | real data |
| CO2 | Law Dome + NOAA Mauna Loa | real data |
| Soil | shipped LPJ soil-code map | shipped data |
| N deposition | constant pre-industrial | default (file missing) |
| Engine | LPJ-GUESS 4.1.1 binary | real model |
| Observations | FLUXNET2015 DE-Tha | independent |

## 12. Parameter Selection by Region

No parameter calibration is done; PFT traits stay as shipped. Choose PFTs for managed
stands (e.g. spruce: BNE; pine: BNE/TeNE; beech: TeBS); for tropical sites keep TrBE/TrIBE/TrBR.
Soil code comes from the 0.5° map.

## 13. Known Limitations

- Weather is reanalysis at the tower point, not tower met.
- No N-deposition file; no BLAZE fire; no crops/land-cover in the KI tools.
- Monthly tables have 3 decimals (~0.03 gC m-2 d-1 resolution).
- `dag.yaml` was updated by hand on 2026-10-07 to the real engine (outputs kept); it was not regenerated by ki_dag_generator.

## 14. Spinup Requirements

`nyear_spinup 500` (shipped default), cycling the first 30 forcing years (detrended
temperature). The calendar starts 500 years before the first forcing year and CO2 is read
by calendar year (`cfinput.cpp` `set_first_calendar_year`, `co2[date.get_calendar_year()]`);
years before the CO2 file's first year get its first value (`globalco2file.cpp`). For DE-Tha
(forcing 1984-2014, CO2 file 1901-2014) the spin-up covers 1484-1983: 1484-1900 at 296.2 ppm,
then 1901-1983 with the real rising CO2 record. Then the real years. N limitation
is off for the first 100 spin-up years (`freenyears`). Boreal/peat sites may need 1000+ years
(dt_lpjguess_010).

## 15. References

- Smith, B., Prentice, I.C., Sykes, M.T. (2001) Global Ecology & Biogeography 10, 621-637.
- Smith, B. et al. (2014) Biogeosciences 11, 2027-2054.
- Sitch, S. et al. (2003) Global Change Biology 9, 161-185.
- Walker, A.P. et al. (2014) JGR Biogeosciences, doi 10.1002/2013JG002553 (NSE floor).
- Zhu, Z. et al. (2020) ESSD 12, 2725 (GPP RMSE context).
- Etheridge et al. (1996); MacFarling Meure et al. (2006) — Law Dome CO2; NOAA GML Mauna Loa CO2.
- Full list: `docs/gathered_papers.json`, `docs/papers_index.md`.
