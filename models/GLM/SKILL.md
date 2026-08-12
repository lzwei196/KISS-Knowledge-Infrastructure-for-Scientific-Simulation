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

> **CMFD direct reader available:** Use `from ki_tools_common.netcdf_utils import load_cmfd_daily_all` to read CMFD 3-hourly data directly. Returns daily precip (mm), temp (°C with Tmin/Tmax), radiation (W/m²), wind, humidity. Handles subdirectory search (Prec/, Temp/, etc.) and unit conversions automatically.
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
Then convert to GLM met format using this KI's tool: `tools/s2_met_forcing/convert_met_to_glm.py`

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# GLM v3.3.3 (General Lake Model) — Knowledge Infrastructure

**Package**: `hydrocraft-glm-lake` v1.0.0
**Model**: GLM v3.3.3 + AED2 water quality library
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-21
**Stats**: 16 tools | 12 skill documents | 30 diagnostic triplets | 7 error log entries | ~4,630 lines of validated Python
**Validation status**: `production_validated` (Miyun Reservoir, 2001-2010)

---

## Overview

This knowledge infrastructure enables fully autonomous simulation of lake and reservoir thermodynamics using GLM (General Lake Model) on any lake worldwide, **without manual data preparation**. The 13 validated tools replace the standard R-based GLM workflow with a Python pipeline that integrates directly with HydroCraft's forcing, routing, and water quality infrastructure.

**What GLM does**: 1D vertical hydrodynamic model for lakes and reservoirs. Simulates:
- Thermal stratification (adaptive Lagrangian layers, up to 500)
- Surface/deep mixing (wind stirring, convective overturn, Kelvin-Helmholtz)
- Water balance (inflows, outflows, rainfall, evaporation, seepage)
- Ice cover (snow-ice formation, growth/decay, albedo feedback)
- Light penetration (multi-band Beer-Lambert extinction)
- Inflow dynamics (density-driven insertion at neutral buoyancy depth)
- Outflow/withdrawal at specified elevation
- Optional AED2 water quality (DO, nutrients, phytoplankton, carbon)

**Key difference from other HydroCraft models**: GLM operates on a single lake/reservoir (1D vertical), not a gridded basin. It couples with CaMa-Flood (upstream discharge as inflow) and VIC (shared meteorological forcing with unit conversions).

---

## Installation

### Binary

```
GLM v3.3.3:  model/glm/bin/glm
Version:     model/glm/bin/VERSION  (glm_3.3.3)
Platform:    Ubuntu 24.04, x86-64, dynamically linked
Source:      github.com/AquaticEcoDynamics/glm-aed
```

### Dependencies (all available on server)

```
libnetcdf.so.19, libgd.so.3, libgfortran.so.5, libhdf5_serial.so.103
```

### Python dependencies (all in HydroCraft venv)

```
netCDF4, numpy, pandas, xarray, geopandas, shapely, matplotlib
```

### Test example

```
model/glm/examples/Sparkling/     # Sparkling Lake, Wisconsin, USA
  glm3.nml                        # Calibrated namelist (1980-2012)
  bcs/nldas_driver.csv            # Hourly meteorological forcing
  bcs/sparkling_lter_temp.csv     # Observed temperature profiles
  output/output.nc                # 32 MB output (32 years)
  output/lake.csv                 # Lake-integrated time series
```

**Validated**: GLM runs successfully on the Sparkling Lake example. Runtime: <1 second for 32 years.

---

## Pipeline (11 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Lake selection, period, forcing source, AED2 on/off |
| 1 | Lake identification | `lookup_hydrolakes`, `build_morphometry` | Find lake in HydroLAKES, build depth-area curve |
| 2 | Met forcing | `convert_met_to_glm` | CMFD/MSWX/VIC forcing to GLM CSV (unit conversions) |
| 3 | Inflow | `convert_inflow_to_glm` | CaMa-Flood/VIC discharge to GLM inflow CSV |
| 4 | Outflow | `configure_outflow` | Dam operation rules, spillway, withdrawal config |
| 5 | Init profiles | `build_init_profiles` | Initial temperature/salinity depth profiles |
| 6 | Namelist | `generate_glm_nml` | Assemble glm3.nml (13 Fortran namelist blocks) |
| 7 | AED2 config | `generate_aed_config`, `configure_inflow_wq` | Water quality modules + inflow nutrient loading |
| 8 | Execution | `run_glm` | Run GLM with preflight checks and output validation |
| 9 | Output analysis | `parse_glm_output`, `parse_aed_output`, `plot_glm_results`, `calibrate_glm` | Parse output.nc/lake.csv, WQ analysis, visualize, calibrate |
| 10 | Coupling | `glm_to_cama_outflow` | GLM outflow to CaMa-Flood downstream |

### Parallelism

Stages 1, 2, 3, 4, 5, 7 can run in parallel after stage 0.
Stage 6 depends on 1-5 (and optionally 7).
Stage 8 depends on 6.
Stages 9 and 10 depend on 8.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `lookup_hydrolakes` | s1 | `tools/s1_lake_identification/lookup_hydrolakes.py` | 190 | Find lake in HydroLAKES by name or coordinates |
| `build_morphometry` | s1 | `tools/s1_lake_identification/build_morphometry.py` | 230 | Build depth-area hypsographic curve |
| `convert_met_to_glm` | s2 | `tools/s2_met_forcing/convert_met_to_glm.py` | 370 | CMFD/MSWX/VIC to GLM met CSV (VP->RH, mm->m/day) |
| `convert_inflow_to_glm` | s3 | `tools/s3_inflow/convert_inflow_to_glm.py` | 260 | CaMa/VIC discharge to GLM inflow CSV |
| `configure_outflow` | s4 | `tools/s4_outflow/configure_outflow.py` | 200 | Outflow CSV + namelist params |
| `build_init_profiles` | s5 | `tools/s5_init_profiles/build_init_profiles.py` | 130 | Initial T/S profiles |
| `generate_glm_nml` | s6 | `tools/s6_namelist/generate_glm_nml.py` | 380 | Assemble glm3.nml from all upstream outputs |
| `generate_aed_config` | s7 | `tools/s7_aed_config/generate_aed_config.py` | 470 | Generate aed2.nml (incl. phytoplankton) |
| `configure_inflow_wq` | s7 | `tools/s7_aed_config/configure_inflow_wq.py` | 310 | Add nutrient concentrations to inflow CSV |
| `run_glm` | s8 | `tools/s8_execution/run_glm.py` | 170 | Execute GLM with preflight checks |
| `parse_glm_output` | s9 | `tools/s9_output_analysis/parse_glm_output.py` | 380 | Parse output.nc + lake.csv (thermal); `--depths a,b,c --depth_timeseries out.csv` interpolates the Lagrangian profile onto FIXED depths below the surface (dt_036) |
| `load_ismn_obs` | s9 | `tools/s9_output_analysis/load_ismn_obs.py` | 190 | Load ISMN in-situ temperature/moisture obs (`/mnt/datasets/ismn_clean.db`); station discovery + QC-filtered daily series at true metre depths (dt_037) |
| `parse_aed_output` | s9 | `tools/s9_output_analysis/parse_aed_output.py` | 400 | Parse AED2 WQ output (Chl-a, DO, nutrients) |
| `plot_glm_results` | s9 | `tools/s9_output_analysis/plot_glm_results.py` | 230 | Temperature heatmap + timeseries plots |
| `calibrate_glm` | s9 | `tools/s9_output_analysis/calibrate_glm.py` | 260 | GLUE-style parameter calibration |
| `glm_to_cama_outflow` | s10 | `tools/s10_coupling/glm_to_cama_outflow.py` | 150 | GLM outflow to CaMa-Flood lateral inflow |

**Total**: 15 tools, ~4,630 lines of validated Python code.

### Skill Knowledge

**Note**: `docs/` currently holds only the reference material (`format_spec.yaml`,
`reference/Hipsey2019_GLM_GMD.pdf`, `REFERENCES.md`) — there are no per-stage skill
documents. All critical domain knowledge is documented inline in this SKILL.md file (see "Critical Domain Knowledge" section below and diagnostic triplets). The following topics are covered inline:

| Stage | Topic | Where in this document |
|-------|-------|----------------------|
| s0 | Lake selection, period, forcing source | Pipeline table above |
| s1 | HydroLAKES search, morphometry | Tools Reference + Critical Domain Knowledge |
| s2 | Unit conversions (VP->RH, mm->m/day) | Critical Domain Knowledge #1, #2 |
| s3 | Inflow temperature estimation | Tools Reference |
| s4 | Dam operation modes, withdrawal depth | Tools Reference |
| s5 | Spinup strategy, initialization | Tools Reference |
| s6 | 13 namelist blocks, Fortran format | Critical Domain Knowledge #3-#8 |
| s7 | AED2 module selection, phytoplankton config | Tools Reference + AED2 Phytoplankton section |
| s7 | Inflow WQ loading, nutrient concentrations | AED2 Phytoplankton section |
| s8 | Runtime expectations, error messages | Critical Domain Knowledge + Error Handling |
| s9 | output.nc structure, validation | Validated Results section |
| s9 | AED2 WQ output: Chl-a, DO, nutrients | AED2 Phytoplankton section |
| s10 | GLM-CaMa coupling | Tools Reference |
| calib | Calibration parameters | Validated Results section |

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a corresponding diagnostic triplet.

### 1. Rain is in m/day, NOT mm/day (dt_001)

GLM expects precipitation in **meters per day**. CMFD/MSWX give mm/3hr. Conversion: `mm/3hr * 8 / 1000 = m/day`. Off by 1000x if you skip the /1000 step. The lake will flood continuously with no error message.

### 2. RelHum is percentage (0-100), NOT fraction (0-1) (dt_002)

GLM expects relative humidity as 0-100%. VIC uses vapor pressure (kPa). Conversion: `RH = 100 * VP / (0.6108 * exp(17.27*T/(T+237.3)))`. If RH is 0.7 instead of 70, GLM computes extreme evaporation.

### 3. H[] and A[] must be ascending (bottom to top) (dt_006)

The morphometry arrays must go from the deepest point (bottom) to the surface. H[0] is the bottom elevation, H[n] is the crest elevation. A[0] should be 0 (point at bottom). Reversed arrays crash GLM.

### 4. bsn_vals must exactly match H/A array length (dt_008)

`bsn_vals` is the count of elevation-area pairs. A mismatch crashes GLM at startup. Always auto-compute from `len(H)`.

### 5. Fortran namelist requires single quotes (dt_005)

String values in glm3.nml must use `'single quotes'`. Double quotes `"like this"` cause a Fortran parse error. Python's default string formatting uses double quotes -- always override with single.

### 6. Inflow salinity must be 0 for freshwater lakes (dt_022)

Non-zero inflow salinity changes the density calculation, causing the inflow to insert at the wrong depth. This creates artificial intrusion layers and disrupts thermal structure silently.

### 7. LongWave double-counting (dt_020)

If `lw_type = 'LW_IN'`, GLM uses the LongWave column from the forcing CSV. If `lw_type = 'LW_CC'`, it computes LW from cloud cover. Using `LW_IN` with incorrect LW values causes systematic temperature bias (3-5 degC warm bias in summer).

### 8. dt_iceon_avg MUST be set for ice simulation (dt_027)

The `&snowice` block requires `dt_iceon_avg` and `min_ice_thickness` parameters. Without them, the ice model is **silently disabled** -- the surface temperature will asymptote to ~0.002 C but never freeze, producing zero ice even with -15 C air temperatures. Set `dt_iceon_avg = 0.02` (days) and `min_ice_thickness = 0.001` (m). For deep reservoirs (>50m), `dt_iceon_avg` must be <= 0.04 days; values >= 0.05 disable ice again.

### 9. Kw controls everything (dt_019)

Light extinction coefficient Kw is the single most sensitive parameter. Too high (>3): no stratification. Too low (<0.1): unrealistic deep heating. Start with `Kw ~ 1.7 / Secchi_depth_m`. Default: 0.5 for moderate clarity.

---

## AED2 Phytoplankton Simulation

This section covers how to enable and configure AED2 phytoplankton simulation in GLM. Phytoplankton is the most common AED2 use case -- predicting chlorophyll-a concentrations, algal bloom risk, and eutrophication response.

### 10. Phytoplankton module dependencies (dt_028)

The `&aed_phytoplankton` block requires these modules to be active in the `&aed_models` list:
- `aed_oxygen` -- photosynthetic O2 production, respiratory consumption
- `aed_nitrogen` -- N uptake (NO3, NH4)
- `aed_phosphorus` -- P uptake (PO4/FRP)
- `aed_organic_matter` -- excretion/mortality products (DOC, POC, DON, etc.)
- `aed_silica` -- required **only if diatoms** are simulated (Si uptake)
- `aed_sedflux` -- sediment nutrient recycling (recommended)

If phytoplankton is enabled without its dependencies, GLM-AED2 will crash at startup or produce zero phytoplankton. The `generate_aed_config.py` tool auto-adds missing dependencies.

### 11. Inflow WQ loading is essential (dt_029)

Without nutrient concentrations in the inflow CSV, AED2 receives zero external nutrient loading. This means:
- Nutrients deplete rapidly from the initial pool
- No sustained phytoplankton growth after the first few weeks
- Unrealistically oligotrophic conditions regardless of actual trophic state

**Solution**: Use `configure_inflow_wq.py` to add nutrient columns to the inflow CSV. The tool provides trophic-state presets (oligotrophic, mesotrophic, eutrophic, hypereutrophic) and optional seasonal patterns.

Required AED2 inflow variables (in addition to FLOW, TEMP, SALT):
```
NIT_nit, NIT_amm, PHS_frp, OGM_don, OGM_pon, OGM_dop, OGM_pop,
OGM_doc, OGM_poc, OXY_oxy, SIL_rsi, PHY_diatom, PHY_green, PHY_cyano
```

After adding WQ columns, update `glm3.nml` `&inflow` block:
```fortran
inflow_varnum = 17   ! was 3 (FLOW, TEMP, SALT)
inflow_vars = 'FLOW','TEMP','SALT','NIT_nit','NIT_amm','PHS_frp',
              'OGM_don','OGM_pon','OGM_dop','OGM_pop','OGM_doc',
              'OGM_poc','OXY_oxy','SIL_rsi','PHY_diatom','PHY_green',
              'PHY_cyano'
```

### 12. WQ initial conditions must match module list (dt_030)

The `&init_profiles` block in `glm3.nml` needs WQ initial values when AED2 is enabled:
```fortran
num_wq_vars = 14
wq_names = 'OXY_oxy','NIT_nit','NIT_amm','PHS_frp','OGM_don','OGM_pon',
           'OGM_dop','OGM_pop','OGM_doc','OGM_poc','SIL_rsi',
           'PHY_diatom','PHY_green','PHY_cyano'
wq_init_vals = 300,300,300,    ! OXY_oxy at 3 depths (mmol O2/m3)
               5,5,5,          ! NIT_nit
               2,2,2,          ! NIT_amm
               0.1,0.1,0.1,   ! PHS_frp
               5,5,5,          ! OGM_don
               2,2,2,          ! OGM_pon
               0.5,0.5,0.5,   ! OGM_dop
               0.2,0.2,0.2,   ! OGM_pop
               50,50,50,       ! OGM_doc
               10,10,10,       ! OGM_poc
               50,50,50,       ! SIL_rsi
               5,5,5,          ! PHY_diatom (mmol C/m3)
               3,3,3,          ! PHY_green
               1,1,1           ! PHY_cyano
```

Each WQ variable needs one value per `num_depths` depth level. The total number of values = `num_wq_vars * num_depths`.

> **CRITICAL (dt_032, 2026-06-22): enabling phytoplankton/silica/noncohesive
> SILENTLY NaNs the entire AED2 state on the v3.3.3 binary.** With this binary +
> the shipped `aed2_phyto_pars.nml` diatom group, adding `aed2_phytoplankton`
> (and/or `aed2_silica`, `aed2_noncohesive`) poisons the coupled ODE: ALL
> water-column WQ vars become NaN/fill (output.nc all-fill; csv_point columns
> print `-nan` from row 1; TOT_tn/TOT_tp read 0.0) while GLM still exits 0 with
> "Model Run Complete". `repair_state` does NOT recover it. The shipped
> `glm_aed2_phyto_test` reference is itself broken this way (its wq_summary.json
> reports TN/TP mean 0.0) — do not trust it as a working template.
> **For nutrient (TN/TP/NH3-N/DO) validation use the simplified core-nutrient set:**
> `models = 'aed2_oxygen','aed2_nitrogen','aed2_phosphorus','aed2_organic_matter','aed2_totals'`
> (10 WQ vars). Set `num_wq_vars=10` and match `wq_names` to the registered
> S(1..10) order; drop SIL_rsi/PHY_diatom/NCS_ss1 from `inflow_vars`. **Always
> verify the first csv_point WQ row is finite (not `-nan`) before trusting a run.**
>
> **WQ timeseries extraction (dt_033): use the csv_point output, not output.nc
> layer extraction.** In `&output` set `csv_point_nlevs`, `csv_point_at` (depth
> from surface with `csv_point_frombot=.false.`), and `csv_point_vars` listing the
> AED2 var names (e.g. `'temp','salt','OXY_oxy','NIT_amm','NIT_nit','PHS_frp','TOT_tn','TOT_tp'`).
> GLM writes a clean daily `WQ<depth>.csv`. Note `generate_glm_nml.py` does NOT
> wire AED2 — you must manually add `&wq_setup`, the `&init_profiles` WQ block,
> and `inflow_varnum`/`inflow_vars` after running it.
>
> **DEPTH-RESOLVED / COLUMN WQ validation (dt_034, 2026-06-28): csv_point is
> single-point only — do NOT use it for column statistics.** A fixed depth-below-surface
> csv_point level intermittently writes spurious `0.0` when the lake level/Lagrangian
> layers move it onto a boundary (e.g. DeGray AR showed exact-0.0 DO at 5 m & 20 m
> sandwiched between oxic 1 m/10 m/40 m). For a full DO/WQ profile read `output.nc`
> **one timestep at a time** at only the dates you need — `np.squeeze(ds['OXY_oxy'][i])[:NS[i]]`
> with `NS` (active layers) and `H` (layer heights); a bulk `[:]` read of the padded
> z=500 variable **segfaults libnetcdf** (no traceback). Thickness-weight (diff(H))
> for a column mean; top/bottom active layer = surface/bottom DO; OXY_oxy ×32/1000 → mg/L.
> **SOD lever:** shipped `Fsed_oxy=-40` over-depletes meso-/oligotrophic hypolimnia
> (DeGray DO col-mean PBIAS −48%); `Fsed_oxy≈-12`, `Ksed_oxy≈50` → PBIAS −6%, surface
> DO r 0.89/NSE 0.53. For depthless WQP grab profiles the unambiguous pairing is
> per-date obs-max ↔ sim top-layer (surface DO).

> 
> **PRIMARY metric for OXY_oxy vs DEPTHLESS obs = SURFACE DO only (dt_035,
> 2026-06-28).** The dag exposes `OXY_oxy` solely as `point_time_series`; for a
> 1-D column model a "point" is one DEPTH. A thickness-weighted COLUMN-MEAN is an
> INVENTED aggregate (not a dag-prescribed support) and MUST NOT be the headline
> metric -- it masks the epilimnion/hypolimnion split the model resolves (DeGray
> col-mean NSE 0.06 hid a surface PASS r 0.89 and a bottom FAIL PBIAS -95%). When
> obs carry NO sample depth (e.g. WQP DeGray station ARDEQH2O_WQX-LOUA019A/B -- ALL
> ActivityDepth/ActivityTop/Bottom/ResultDepth fields empty AT THE PROVIDER,
> verified by fresh WQP pull), score ONLY surface DO: sim top active layer vs
> per-date near-surface (epilimnetic = max) obs. Validating BOTTOM / hypolimnetic
> DO requires a DEPTH-RESOLVED obs source; none exists for DeGray in WQP, so
> hypolimnetic-DO validation is data-limited (requires_data), NOT a model verdict.

### How to Enable Phytoplankton (Step by Step)

```bash
# 1. Generate aed2.nml with phytoplankton
python tools/s7_aed_config/generate_aed_config.py \
    --modules oxygen,nitrogen,phosphorus,organic_matter,silica,phytoplankton,sedflux,totals \
    --phyto_groups diatom,green,cyano \
    --output aed2.nml

# 2. Add nutrient concentrations to inflow CSV
python tools/s7_aed_config/configure_inflow_wq.py \
    --inflow_csv bcs/inflow_1.csv \
    --trophic mesotrophic --seasonal \
    --phyto_groups diatom,green,cyano \
    --output bcs/inflow_1_wq.csv

# 3. Update glm3.nml:
#    - Add to &glm_setup: aed_filename = 'aed2.nml'
#    - Update &inflow: inflow_varnum, inflow_vars (see above)
#    - Update &init_profiles: num_wq_vars, wq_names, wq_init_vals

# 4. Run GLM+AED2
python tools/s8_execution/run_glm.py --run_dir .

# 5. Parse WQ output
python tools/s9_output_analysis/parse_aed_output.py \
    --output_nc output/output.nc --summary wq_summary.json
```

### Phytoplankton Functional Groups

| Group | Description | R_growth | T_opt | I_S | K_N | K_P | w_p | Chl range |
|-------|-------------|----------|-------|-----|-----|-----|-----|-----------|
| diatom | Bacillariophyceae | 1.5/day | 18C | 100 W/m2 | 3.5 | 0.15 | -0.2 (sinks) | Spring bloom |
| green | Chlorophyceae | 1.8/day | 25C | 150 W/m2 | 4.0 | 0.1 | -0.1 (sinks) | Summer peak |
| cyano | Cyanobacteria | 0.8/day | 28C | 120 W/m2 | 2.0 | 0.05 | +0.05 (floats) | Late summer |
| crypto | Cryptophyceae | 1.2/day | 20C | 80 W/m2 | 3.0 | 0.1 | -0.05 | Year-round |

Key differences between groups:
- **Diatoms**: Fast growers at cool temperatures, sink rapidly, require silica. Dominate spring.
- **Green algae**: Fastest growth rate, prefer warm temperatures. Common in summer.
- **Cyanobacteria**: Slowest growth but lowest nutrient half-saturation (competitive at low N/P). **Buoyant** (positive w_p). Dominate late summer in eutrophic lakes. Bloom risk.
- **Cryptophytes**: Shade-adapted (low I_S), moderate in all conditions. Fill-in species.

### Key Calibration Parameters for Phytoplankton

| Parameter | Description | Range | Sensitivity | Effect |
|-----------|-------------|-------|-------------|--------|
| R_growth | Max growth rate (/day) | 0.3-3.0 | HIGH | Total biomass level |
| I_S | Light saturation (W/m2) | 50-300 | HIGH | Light limitation depth |
| K_N | N half-saturation (mmol/m3) | 1-10 | MEDIUM | N limitation threshold |
| K_P | P half-saturation (mmol/m3) | 0.01-0.5 | MEDIUM | P limitation threshold |
| T_opt | Optimum temperature (degC) | 15-30 | MEDIUM | Seasonal timing |
| w_p | Sedimentation velocity (m/day) | -1.0 to +0.1 | HIGH | Loss rate, vertical position |
| Xcc | C:Chl ratio (mg C/mg Chl) | 20-100 | MEDIUM | Chl-a diagnostic value |
| R_resp | Respiration rate (/day) | 0.02-0.15 | MEDIUM | Net growth = growth - resp |
| R_mort | Mortality rate (/day) | 0.01-0.1 | LOW | Background loss |
| Fsed_frp | Sediment P release (mmol/m2/d) | 0.01-2.0 | HIGH | Internal P loading |
| Fsed_oxy | Sediment O2 demand (mmol/m2/d) | -20 to -100 | HIGH | Hypolimnetic DO |
| Kw | Light extinction (m^-1) | 0.1-3.0 | HIGH | Light for phyto AND thermal |

### Expected Chlorophyll-a Ranges

| Trophic State | Mean Chl-a | Max Chl-a | Total P | Secchi | TSI |
|---------------|-----------|-----------|---------|--------|-----|
| Oligotrophic | <2 ug/L | <5 ug/L | <10 ug/L | >4 m | <40 |
| Mesotrophic | 2-8 ug/L | 5-20 ug/L | 10-30 ug/L | 2-4 m | 40-50 |
| Eutrophic | 8-25 ug/L | 20-80 ug/L | 30-100 ug/L | 1-2 m | 50-70 |
| Hypereutrophic | >25 ug/L | >80 ug/L | >100 ug/L | <1 m | >70 |

### AED2 Output Variables

When phytoplankton is enabled, GLM output.nc will contain:
- `PHY_tchla` — Total chlorophyll-a (ug/L) — **primary validation target**
- `PHY_diatom`, `PHY_green`, `PHY_cyano` — Group biomass (mmol C/m3)
- `OXY_oxy` — Dissolved oxygen (mmol O2/m3)
- `NIT_nit`, `NIT_amm` — Nitrogen species
- `PHS_frp` — Phosphorus
- `TOT_tn`, `TOT_tp` — Total N and P

Use `parse_aed_output.py` to extract these, compute TSI, bloom frequency, and N:P ratios.

### Unit Conversions (AED2 internal to common)

```
Chl-a:  ug/L  = PHY_group (mmol C/m3) * 12.01 / Xcc  [summed over groups]
DO:     mg/L  = OXY_oxy (mmol O2/m3) * 32.0 / 1000
NO3-N:  mg/L  = NIT_nit (mmol N/m3) * 14.01 / 1000
NH4-N:  mg/L  = NIT_amm (mmol N/m3) * 14.01 / 1000
PO4-P:  mg/L  = PHS_frp (mmol P/m3) * 30.97 / 1000
DOC:    mg/L  = OGM_doc (mmol C/m3) * 12.01 / 1000
SiO2:   mg/L  = SIL_rsi (mmol Si/m3) * 60.08 / 1000
```

---

## Validation: Miyun Reservoir (2026-03-22)

**Basin**: Miyun Reservoir (密云水库), Beijing, China
**Coordinates**: 40.48N, 116.97E
**Period**: 2001-2010 (10 years)
**Forcing**: CMFD daily (from VIC Chaohe simulation)
**Runtime**: 3-4 seconds for 10 years

### Morphometry
- Max depth: 60 m, Surface area: 188 km2, Volume: ~4,521 MCM
- Crest elevation: 155 m ASL, 13 depth-area levels
- Inflow: Chaohe River VIC routing output (x2 approximate)
- Outflow: constant 15 m3/s (Beijing water supply withdrawal)

### Results vs Published Data

| Metric | Simulated | Published | Status |
|--------|-----------|-----------|--------|
| Summer surface T (JJA) | 28.2 C | 24-28 C | PASS |
| Winter surface T (DJF) | 3.4 C | 0-2 C | Warm bias |
| Annual mean T | 15.5 C | 10-12 C | Warm bias |
| Max surface T | 33.0 C | 28-32 C | Reasonable |
| Min surface T | -0.36 C | < 0 (ice) | PASS |
| Ice days/year | 71 | ~120 | REASONABLE |
| Max ice thickness | 0.28 m | 0.3-0.5 m | REASONABLE |
| Lake level variation | 0.007 m | 5-15 m | Water balance issue |

### Key Findings

1. **Seasonal thermal cycle is correct**: Summer heating to 28-33 C and winter cooling to near-zero matches published data well. The seasonal pattern is realistic.

2. **Ice model requires `dt_iceon_avg` parameter (dt_027 -- THE critical finding)**: Without `dt_iceon_avg` and `min_ice_thickness` in the `&snowice` block, the ice model is silently disabled. The surface asymptotes to 0.002 C but never freezes. Adding `dt_iceon_avg = 0.02` and `min_ice_thickness = 0.001` enables ice formation. This parameter controls the averaging period (days) for ice onset temperature check. Values >0.04 days disable ice again on this lake. This is the single most important GLM configuration parameter for ice simulation and is undocumented in most examples.

3. **Annual mean T is ~3-5 C warm**: Published annual mean is 10-12 C, simulated is 15.4 C. The warm bias is primarily from overestimating summer surface temperatures (28.4 vs published 24-28 C upper bound).

4. **Precipitation missing from forcing (dt_024)**: CMFD-to-GLM conversion did not include precipitation. Rain=0 and Snow=0 for entire simulation. This affects water balance (lake level stuck at crest) but not thermal performance significantly.

5. **subdaily forcing parsing fails (dt_026)**: 3-hourly CMFD forcing with `subdaily=.true.` produces unrealistic output (max T = 4.5 C). Must use daily forcing with `subdaily=.false.`.

6. **timefmt must match date format (dt_025)**: `generate_glm_nml.py` hardcoded `timefmt=3` but generated datetime strings. Fixed to auto-detect: `timefmt=2` for strings, `timefmt=3` for seconds.

### Tuned Parameters (Miyun)

```
coef_mix_conv = 0.05       # reduced from 0.2 (less convective mixing)
coef_wind_stir = 0.18      # reduced from 0.402 (sheltered reservoir)
coef_mix_hyp = 0.3         # reduced from 0.5 (less deep mixing)
wind_factor = 0.7          # CMFD wind overestimates for sheltered valley
lw_factor = 0.95           # slight LW reduction
min_layer_thick = 0.05     # thinner surface layers
max_layer_thick = 0.5      # matches Sparkling example
sed_temp_mean = 5.0        # colder for 40.5N
sed_temp_amplitude = 6.0   # moderate amplitude
dt_iceon_avg = 0.02        # CRITICAL: ice onset averaging period (days)
min_ice_thickness = 0.001  # CRITICAL: minimum ice thickness (m)
```

---

## Calibration Parameters (Priority Order)

| Parameter | Block | Range | Controls | Sensitivity |
|-----------|-------|-------|----------|-------------|
| Kw | light | 0.1 - 3.0 m^-1 | Thermocline depth, light penetration | HIGH |
| coef_wind_stir | mixing | 0.1 - 1.0 | Surface mixed layer depth | HIGH |
| wind_factor | meteorology | 0.5 - 2.0 | Wind speed scaling | MEDIUM |
| coef_mix_hyp | mixing | 0.1 - 1.0 | Deep mixing rate | MEDIUM |
| sw_factor | meteorology | 0.8 - 1.2 | Solar radiation scaling | MEDIUM |
| ce, ch | meteorology | 0.001 - 0.003 | Evaporation / sensible heat | MEDIUM |

---

## Coupling Points

| # | Source | Target | Variable | Tool |
|---|--------|--------|----------|------|
| 1 | CaMa-Flood | GLM | Discharge at lake inlet | `convert_inflow_to_glm` |
| 2 | VIC | GLM | Met forcing (unit conversion) | `convert_met_to_glm` |
| 3 | GLM | CaMa-Flood | Outflow discharge | `glm_to_cama_outflow` |
| 4 | GLM | CaMa-Flood | Outflow temperature | `glm_to_cama_outflow` |
| 5 | SWAT+ | GLM | Nutrient loading | (via AED2 inflow WQ vars) |
| 6 | CMIP6 | GLM | Future climate forcing | (delta-change on met CSV) |

---

## Data Requirements

| Data | Source | Status | Path |
|------|--------|--------|------|
| GLM binary | GitHub glm-aed | Installed | `model/glm/bin/glm` |
| HydroLAKES v10 | hydrosheds.org | **TO DOWNLOAD** (~2.5 GB) | `data/lakes/HydroLAKES_polys_v10.shp` |
| Met forcing | CMFD/MSWX | Available | `data/forcing/` or `/mnt/disk3/msxw/` |
| River inflow | CaMa-Flood/VIC | From pipeline | Simulation output |
| Example data | glm-aed repo | Installed | `model/glm/examples/Sparkling/` |

---

## Quick Start

```bash
# 1. Build morphometry (manual params if no HydroLAKES)
python tools/s1_lake_identification/build_morphometry.py \
  --area_km2 0.64 --depth_max 18.3 --depth_avg 6.1 \
  --elevation 320 --lat 46.0 --lon -89.7 --name "Sparkling" \
  --output morphometry.json

# 2. Convert forcing to GLM met format.
#    NASA POWER is the default for lakes OUTSIDE CMFD (China) / MSWX coverage —
#    daily, point, ~5 s/year, no local files needed. USE THIS unless a VIC/CMFD
#    forcing set for the lake already exists.
python tools/s2_met_forcing/convert_met_to_glm.py \
  --forcing_source nasa_power \
  --lat 34.1932 --lon -86.8052 \
  --start_date 2014-01-01 --end_date 2020-12-31 \
  --output bcs/met.csv
#    (VIC-coupled alternative)
python tools/s2_met_forcing/convert_met_to_glm.py \
  --vic_forcing_dir outputs/run/vic_temp/forcing/forcing_final \
  --lat 46.0 --lon -89.7 \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --output bcs/met_hourly.csv

# 2b. Inflow + outflow (do NOT skip: with no inflow the lake is a closed bucket)
python tools/s3_inflow/convert_inflow_to_glm.py \
  --constant_flow <HydroLAKES dis_avg_m3s> --met_csv bcs/met.csv --salinity 0.0 \
  --start_date 2014-01-01 --end_date 2020-12-31 --output bcs/inflow.csv
python tools/s4_outflow/configure_outflow.py --mode balance \
  --inflow_csv bcs/inflow.csv --crest_elev <crest> \
  --start_date 2014-01-01 --end_date 2020-12-31 \
  --output bcs/outflow.csv --output_json outflow_config.json

# 3. Generate initial profiles
python tools/s5_init_profiles/build_init_profiles.py \
  --strategy uniform --temp 10 --depth 18.3 \
  --output init_profiles.json

# 4. Generate namelist
python tools/s6_namelist/generate_glm_nml.py \
  --morphometry morphometry.json \
  --init_profiles init_profiles.json \
  --met_csv bcs/met_hourly.csv \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --timezone 8 --output glm3.nml

# 5. Run GLM
python tools/s8_execution/run_glm.py --run_dir .

# 6. Parse and plot results
python tools/s9_output_analysis/parse_glm_output.py \
  --output_nc output/output.nc --lake_csv output/lake.csv \
  --summary results.json

python tools/s9_output_analysis/plot_glm_results.py \
  --output_nc output/output.nc --lake_csv output/lake.csv \
  --output glm_results.png --title "Lake Simulation"
```

---

## Diagnostic Triplets

29 triplets covering 7 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Rain in mm/day instead of m/day (1000x error) |
| dt_002 | **silent** | unit_conversion | RelHum as fraction instead of % (100x error) |
| dt_003 | **silent** | unit_conversion | Negative SW radiation after interpolation |
| dt_004 | degraded | unit_conversion | Inflow temperature missing or zero |
| dt_005 | fatal | parameter_format | Double quotes in Fortran namelist |
| dt_006 | fatal | parameter_format | H/A arrays not monotonically increasing |
| dt_007 | degraded | parameter_format | Too few depth-area points (<5) |
| dt_008 | fatal | parameter_format | bsn_vals mismatch with H/A length |
| dt_009 | fatal | parameter_format | lake_depth exceeds morphometry max |
| dt_010 | **silent** | parameter_format | num_inflows=0 but inflow files configured |
| dt_011 | fatal | path_resolution | Met file path not found (relative path issue) |
| dt_012 | fatal | path_resolution | Inflow file path not found |
| dt_013 | fatal | runtime | NaN from extreme forcing values |
| dt_014 | degraded | runtime | Unrealistic ice in warm climate |
| dt_015 | fatal | runtime | Layer merge error from small max_layer_thick |
| dt_016 | **silent** | dependency_mismatch | Timezone mismatch between forcing and inflow |
| dt_017 | **silent** | dependency_mismatch | CaMa grid cell mismatch at lake inlet |
| dt_018 | degraded | dependency_mismatch | Output nsave too large for thermal analysis |
| dt_019 | **silent** | silent_error | Kw too high — no stratification |
| dt_020 | **silent** | silent_error | LongWave double-counted |
| dt_021 | **silent** | silent_error | Wind mixing too strong for small lake |
| dt_022 | **silent** | silent_error | Non-zero salinity in freshwater inflow |
| dt_023 | **silent** | silent_error | Surface T stuck at 0.002 C — misdiagnosed as thermal, actually dt_027 |
| dt_024 | **silent** | silent_error | Zero precipitation in met CSV |
| dt_025 | fatal | parameter_format | timefmt=3 with datetime string start/stop |
| dt_026 | **silent** | silent_error | subdaily=.true. with 3-hourly CMFD gives flat temperature |
| dt_027 | **silent** | silent_error | **CRITICAL**: Missing dt_iceon_avg disables ice model silently |
| dt_028 | fatal | aed2_config | Phytoplankton enabled without dependency modules (O2, N, P, OM) |
| dt_029 | **silent** | aed2_config | Zero nutrient inflow loading — AED2 runs but phyto crashes to zero |
| dt_030 | fatal | aed2_config | WQ init values count mismatch (num_wq_vars * num_depths) |
| dt_036 | **silent** | output_extraction | Fixed-depth temperature read off the ADAPTIVE Lagrangian grid — must interpolate (`parse_glm_output --depths`); GLM stamps END-of-day and duplicates the final timestep |
| dt_037 | fatal/silent | observation_ingestion | ISMN db needs `immutable=1`; pair on `depth_from_m` (metres) not `depth_cm/100`; soil obs is a PROXY — score r, not PBIAS |

**Silent error count**: 16/30 (53%) — higher than cross-model average due to lake-specific physics.

**Most important triplet**: dt_027 — without `dt_iceon_avg=0.02` and `min_ice_thickness=0.001` in the `&snowice` block, GLM's ice model is silently disabled. This is undocumented in most GLM examples and caused 6 hours of debugging on Miyun Reservoir before discovery.

**AED2-specific triplets**: dt_028/029/030 cover the three most common AED2 configuration errors. dt_029 (zero nutrient inflow) is the most insidious -- AED2 runs successfully but produces unrealistically low chlorophyll because there is no external nutrient supply.

---

## File Structure

```
models/GLM/knowledge_infrastructure/
  DISSECTION_PLAN.md              # Original dissection plan
  SKILL.md                        # This file (agent entry point)
  knowledge_infrastructure.yaml   # Schema-compliant package definition
  tools/
    s1_lake_identification/
      lookup_hydrolakes.py        # HydroLAKES spatial search
      build_morphometry.py        # Depth-area curve construction
    s2_met_forcing/
      convert_met_to_glm.py       # CMFD/MSWX/VIC to GLM met CSV
    s3_inflow/
      convert_inflow_to_glm.py    # CaMa/VIC to GLM inflow CSV
    s4_outflow/
      configure_outflow.py        # Outflow configuration
    s5_init_profiles/
      build_init_profiles.py      # Initial T/S profiles
    s6_namelist/
      generate_glm_nml.py         # glm3.nml generator
    s7_aed_config/
      generate_aed_config.py      # aed2.nml generator (incl. phytoplankton)
      configure_inflow_wq.py      # Add nutrient concentrations to inflow CSV
    s8_execution/
      run_glm.py                  # GLM execution wrapper
    s9_output_analysis/
      parse_glm_output.py         # Thermal output parser
      parse_aed_output.py         # AED2 WQ output parser (Chl-a, DO, nutrients)
      load_ismn_obs.py            # ISMN in-situ temperature/moisture obs loader
      plot_glm_results.py         # Visualization
      calibrate_glm.py            # GLUE calibration
    s10_coupling/
      glm_to_cama_outflow.py      # GLM -> CaMa-Flood coupling
  docs/                           # reference only (format_spec.yaml, Hipsey2019 PDF)
  diagnostics/
    triplets.yaml                 # 30 diagnostic triplets (incl. 3 AED2-specific)
    error_log.yaml                # Errors from real runs

model/glm/
  bin/glm                         # GLM-AED v3.3.3 binary
  bin/VERSION                     # Version file
  examples/Sparkling/             # Validated reference example
```

---

## Validation: Lake Catoma, Alabama vs ISMN soil temperature (2026-08-11)

**Lake**: Lake Catoma reservoir (HydroLAKES Hylak_id 113187), Cullman Co., Alabama, USA
(34.1932N, -86.8052E, 1.37 km2, HydroLAKES depth_avg 19.3 m, Dis_avg 1.631 m3/s)
**Obs**: ISMN / SCAN station `Cullman-NAHRC` (34.19492N, -86.79897E, 0.61 km from the lake),
`soil_temperature` daily means at 0.0508 / 0.1016 / 0.2032 / 0.508 / 1.016 m
**Forcing**: NASA POWER daily (`convert_met_to_glm.py --forcing_source nasa_power`)
**Period**: 2014 spin-up (discarded) + 2015-01-01..2020-12-30 scored (2191 paired days)
**Runtime**: GLM 7 years in ~2 s; whole pipeline (incl. HydroLAKES read + POWER fetch) ~3 min

| Matched depth | NSE | r | KGE | PBIAS |
|---|---|---|---|---|
| 0.0508 m (headline) | 0.723 | 0.937 | 0.835 | +14.9 % |
| 0.1016 m | 0.711 | 0.933 | 0.837 | +14.1 % |
| 0.2032 m | 0.712 | 0.942 | 0.820 | +14.3 % |
| 0.508 m | 0.681 | 0.936 | 0.801 | +14.2 % |
| 1.016 m | 0.400 | 0.910 | 0.600 | +13.7 % |

**How to reproduce the depth-matched comparison** (this is the pattern for ANY fixed-depth
temperature obs — thermistor chain, profile logger, soil sensor):

```bash
python tools/s9_output_analysis/load_ismn_obs.py --lat <lake_lat> --lon <lake_lon> \
    --radius_km 25 --variable soil_temperature --list          # discover stations
python tools/s9_output_analysis/load_ismn_obs.py --station <ID> --network <NET> \
    --variable soil_temperature --start 2015-01-01 --end 2020-12-31 --output obs_ismn.csv
python tools/s9_output_analysis/parse_glm_output.py --output_nc output/output.nc \
    --lake_csv output/lake.csv --summary glm_summary.json \
    --depths 0.0508,0.1016,0.2032,0.508,1.016 --depth_timeseries sim_depths.csv
# pair on DATE after shifting sim back one day (GLM stamps the END of the day) and
# after dropping the duplicated final timestep  -> ki_tools_common.metrics.all_metrics
```

### Findings

1. **The uncalibrated seasonal cycle is right; the offset is physical, not a bug.**
   r = 0.94 at every depth. The +14 % PBIAS is dominated by WINTER: simulated water
   ~11.5 C vs observed soil ~7.5 C. Water has far more thermal inertia than soil, so a
   soil-temperature station is a PROXY — score the pattern (r/NSE), and do NOT tune Kw /
   wind_factor to chase the magnitude offset against a non-water sensor (dt_037).
   The documented ~3-5 C summer warm bias (LW handling) shows up here too: simulated
   surface max 34.06 C vs a realistic 30-31 C for an Alabama reservoir.
2. **NSE degrades with depth (0.72 -> 0.40 at 1 m) while r stays 0.91** — the model's
   1 m water temperature is nearly as fast as its surface, whereas 1 m SOIL damps and
   lags; that divergence is the proxy limit, again not a model error.
3. **`build_morphometry --from_hydrolakes` inherits a modelled depth.** HydroLAKES gives
   Lake Catoma depth_avg 19.3 m and `lookup_hydrolakes` estimates depth_max = 2.5 x
   depth_avg = 48.2 m for a 1.37 km2 reservoir — implausibly deep. Surface/epilimnion
   temperature is insensitive to it, but ANY hypolimnetic or Schmidt-stability claim on a
   HydroLAKES-only morphometry is unsupported: get a real bathymetry or state the caveat.
4. **`configure_outflow --mode balance` keeps the water balance closed** — lake level
   range 0.24 m over 7 years with constant Dis_avg inflow, no crest pinning.

---

## Applicability Guard — REJECT non-lake / non-reservoir targets (added 2026-06-19)

GLM is a 1D **vertical lake/reservoir thermodynamic** model. It has **no rainfall-runoff process** and its `dag.yaml` `outputs[]` declare **no discharge/streamflow variable** (only temperature & salinity profiles, lake level/volume, ice thickness, evaporation, thermocline depth, Schmidt stability, AED2 WQ). The `Tot Outflow Vol` column in `lake.csv` is a *prescribed* withdrawal/spillway boundary rule, **not** a simulated discharge — never validate it against a stream gauge.

**Before s2 forcing prep, run the lake-existence gate** using `tools/s1_lake_identification/lookup_hydrolakes.py`. REJECT the case as out-of-domain (do NOT proceed, do NOT fabricate a discharge metric) if ANY of:
  - no lake/reservoir polygon is returned within the search radius;
  - the nearest feature has `dis_avg == 0.0` (closed/endorheic slough, no throughflow);
  - nearest feature `lake_area` is below a usable minimum, or its centroid is > ~5 km from the requested point;
  - the requested comparison variable is `discharge`/`streamflow`/`discharge_m3s` (not a GLM output).

Report `REJECT_WRONG_MODEL` with the lookup_hydrolakes evidence. Injecting the gauge's own discharge as inflow and reading it back as outflow is a circular pass-through and is forbidden (papering over). Valid GLM validation targets are in-lake observations: water temperature profiles, surface/bottom temperature, lake level, ice thickness.
