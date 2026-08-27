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
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (27 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (26 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_daycent.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_daycent.py --help` |
| `tools/convert_soil_to_daycent.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_daycent.py --help` |
| `tools/parse_daycent_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_daycent_output.py --help` |
| `tools/run_daycent.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_daycent.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# DayCent — Daily Century Soil Organic Matter, Plant Production, and Trace-Gas Model

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | DayCent — Daily Century Soil Organic Matter, Plant Production, and Trace-Gas Model |
| Version | `DDcentEVI` revision 491, trunk dated 2023-07-10 |
| Language | Precompiled ELF 64-bit Linux binary; upstream Fortran/C source is not bundled |
| License | Public binary distribution from CSU NREL; consult upstream distribution terms |
| Repository/source in this KI | `source/repo/Linux_Version_491/DDcentEVI_rev491` |
| Companion executable | `source/repo/Linux_Version_491/DDlist100_rev491` |
| Primary domain | Agroecosystem biogeochemistry, plant production, soil organic matter, water balance, and trace gases |
| Spatial mode | Point/site simulation with daily weather, Century-style site files, and schedule-driven management |
| Validation status | Real benchmark tier for bundled Wooster SOC example; broader site-adaptation campaigns remain task-specific |

## 2. What This Model Does

DayCent (Daily-DAYCENT, also `DDcentEVI`) is the daily time-step version of the
Century ecosystem model. It simulates plant production, soil organic matter
dynamics, water balance, soil temperature, and trace-gas fluxes (N2O, NO, CH4,
CO2) for cropping, grassland, and savanna ecosystems. It is the de-facto
reference model for U.S. and global soil greenhouse-gas inventories (USDA,
IPCC inventory teams) and has been in continuous development at Colorado
State University / NREL for over three decades.

> **KNOWN GAP — forest ecosystems.** DayCent supports a TREE submodel in
> principle, but the public `WoosterExampleLinux` distribution used by this
> KI ships a **zero-byte `tree.100`** and no forest `.sch` template. Running
> DayCent as a forest model therefore requires a `tree.100` obtained from
> CSU NREL separately. If your task asks for DayCent at a **forest flux
> site** (e.g. DE-Tha Norway spruce, US-Ha1, US-UMB), you cannot complete it
> with KI artifacts alone — you must either (a) obtain the full DayCent
> distribution with a populated `tree.100` from CSU NREL, or (b) substitute a
> grassland (GRASS/GRAS1) parameterisation as a coarse surrogate and clearly
> flag this limitation in the run report. Do not fabricate tree parameters.

**Version:** `DDcentEVI` revision 491 (trunk, 2023-07-10)
**Binary type:** ELF 64-bit, statically linked, x86-64
**Source:** `Linux_Version_491/DDcentEVI_rev491` (precompiled in the distribution)
**Companion binary:** `DDlist100_rev491` — extracts user-selected variables from
`.bin` archives into delimited `.lis` text tables.

DayCent does NOT compile from source in the standard distribution — the upstream
release ships precompiled, statically-linked Linux and Windows binaries. The
Fortran/C source is held separately by the CSU NREL group; this KI works with
the public binary distribution.

## Why DayCent (vs. raw Century or other ESMs)

- **Daily time step**: required for trace-gas modelling (N2O pulses after
  fertiliser, nitrification/denitrification, NO/N2O/N2 partitioning).
- **Soil layer water + temperature**: explicit soil profile (1-D bucket plus
  Parton-Hartman temperature solver), enabling realistic plant water stress
  and N transformations.
- **Tested decomposition pools**: the Century 5-pool SOM scheme (active, slow,
  passive surface, structural, metabolic) calibrated against decades of
  long-term experiment SOC data (Wooster OH, Sanborn MO, Rothamsted, etc.).
- **Used by U.S. EPA and USDA** for the GHG inventory of agricultural lands,
  so its outputs are the operational reference for U.S. cropland N2O.

## 3. Input Requirements

Exact machine-readable input/output shapes live in `docs/format_spec.yaml`
(projected from `dag.yaml` plus `diagnostics/triplets.yaml`). Regenerate that
spec after changing the dag or triplets; do not hand-edit the generated spec.

DayCent inputs are Century-style site files, DayCent-specific physical site
parameters, multi-layer soil hydraulic profiles, daily weather, management
schedules, and output toggles. The detailed file reference below gives the
fixed-format expectations and common unit traps.

## Pipeline (DayCent canonical 3-step run)

DayCent simulations almost always follow the *equilibrium → base history →
treatment* pattern, taken directly from the `WoosterExampleLinux` reference
that ships with the distribution.

| Stage | ID | What it does | Key files |
|-------|----|--------------|-----------|
| s0 | configuration | Pick site, climate file, schedule files (eq, base, treatment) | `*.sch`, `outfiles.in` |
| s1 | site_setup | Build `<site>.100`, `sitepar.in`, `soils.in`, `outfiles.in` | `*.100`, `sitepar.in`, `soils.in` |
| s2 | weather | Build daily weather file (day, mon, yr, dayofyr, tmin, tmax, ppt) | `*.wth` |
| s3 | equilibrium | Long spin-up to steady-state SOM (uses `ACEQ` block) | `eq.bin`, `eq.lis` |
| s4 | base_history | Historical management without treatment (uses `-e eq`) | `base.bin` |
| s5 | treatment | Treatment / experimental scenario (uses `-e base`) | `cb_nt.bin` |
| s6 | extraction | `DDlist100` extracts `.lis` table from `.bin` archive | `<root>.lis` |
| s7 | analysis | Parse `.lis` / CSV outputs, compute metrics | `summary.out`, `harvest.csv` |

The three-stage spin-up scheme is essential: DayCent SOM pools take centuries
to equilibrate, and the `ACEQ` (Adaptive Century Equilibrium) block in a `.sch`
file lets the model stop when pools converge.

## 4. Build Instructions

The model is shipped as a precompiled statically-linked ELF binary; no build
step is required on a modern Linux x86-64 host:

```bash
# Verify the binary
file source/repo/Linux_Version_491/DDcentEVI_rev491
# ELF 64-bit LSB executable, x86-64, statically linked

# Make executable (it should already be)
chmod +x source/repo/Linux_Version_491/DDcentEVI_rev491
chmod +x source/repo/Linux_Version_491/DDlist100_rev491

# Smoke test
./DDcentEVI_rev491
# Should print: DAILYDAYCENT SOIL ORGANIC MATTER and TRACEGAS MODEL
#               trunk, 2023-07-10, revision 491
```

If you obtained DayCent source instead of the binary distribution, the build is
controlled by a Makefile in the C source tree and depends on `gfortran` plus a
C compiler (gcc/clang). The public release ships only binaries.

## Quick start (Wooster example)

```bash
cd source/repo/WoosterExampleLinux
ln -sf ../Linux_Version_491/DDcentEVI_rev491 .
ln -sf ../Linux_Version_491/DDlist100_rev491 .

# 1) Equilibrium spin-up (ACEQ converges around year 750-1000)
cp no_outfiles.in outfiles.in
./DDcentEVI_rev491 -s wooster_eq -N eq

# 2) Base history (1900-1961 historical management without treatment)
./DDcentEVI_rev491 -s wooster_base -e eq -N base

# 3) Treatment run (corn-soy no-till from 1962)
cp few_outfiles.in outfiles.in
./DDcentEVI_rev491 -s wooster_cb_nt_blk1 -e base -N cb_nt

# 4) Extract variables to .lis text table
./DDlist100_rev491 cb_nt wooster few_outvars.txt
# Produces wooster.lis with columns from few_outvars.txt
```

## Setting up a new FLUXNET site (site-adaptation recipe)

The `WoosterExampleLinux` pipeline is written for a corn-soy rotation in Ohio.
To port it to an arbitrary FLUXNET tower, copy the example directory and edit
the site-specific inputs — do not rewrite the binaries or the management
history. The minimum-edit path is:

1. **Copy the example as a template.**
   ```bash
   cp -r source/repo/WoosterExampleLinux workdir/de_tha
   cd workdir/de_tha
   ```

2. **Build the weather file with `convert_forcing_to_daycent.py --source fluxnet`.**
   This is preferred over CMFD/MSWX/NASA-POWER for FLUXNET tasks because
   every FLUXNET2015 site CSV carries `TA_F`, `P_F`, `SW_IN_F` — the exact
   variables the `.wth` needs — and it works offline.
   ```bash
   python tools/convert_forcing_to_daycent.py      --source fluxnet      --fluxnet-csv KISSPATH_ROOT/.../sites/DE-Tha/FULLSET_DD.csv      --year-start 1996 --year-end 2014      --out workdir/de_tha/de_tha.wth
   ```

3. **Edit `<site>.100`** (rename `wooster_site.100` → `de_tha_site.100`):
   - Update `sitlat` / `sitlng` to the tower coordinates
     (DE-Tha: 50.96, 13.57).
   - Replace the 12 monthly `PRECIP(1..12)`, `TMN2M(1..12)`, `TMX2M(1..12)`
     with monthly climatology computed from the `.wth` you just built.
     A 1-liner: `awk '{m=$2; p[m]+=$7; n[m]+=1} END {for(i=1;i<=12;i++) print i, p[i]/n[i]*30.44}' de_tha.wth` gives monthly PRECIP in cm.
   - Update `sand / silt / clay / bulkd / ph` from the site soil metadata
     (for FLUXNET sites, the AUXMETEO.csv or the site's ancillary CSV).
   - **Do NOT** change the SOM initial pools — the equilibrium run will
     overwrite them. Keep the Wooster defaults as a starting point.

4. **Rebuild `soils.in`** with `tools/convert_soil_to_daycent.py` using HWSD
   at the tower lat/lon (or the site soil CSV if available).

5. **Edit the schedules** (`*.sch`):
   - In `<site>_eq.sch` / `<site>_base.sch` / `<site>_treatment.sch`, set
     `wooster_site.100` → `de_tha_site.100` and `wooster_prism.wth` →
     `de_tha.wth`.
   - Replace the `CROP CORN / LAST` / `CROP SOYB / LAST` blocks with the
     ecosystem at the tower. For a **cropland** or **grassland**, pick the
     appropriate `crop.100` entry (e.g. `GRASS`, `W1`, `C3-GR`) and update
     the schedule years. For a **forest** site, see the KNOWN GAP above —
     without a populated `tree.100` you must either substitute grass or
     stop. Do not invent tree parameters.
   - Adjust the simulation year block (`1 2014 ...`) to match the target
     validation period.

6. **Run the 3 stages** exactly as in the Wooster quick-start, swapping in
   the new file names.

7. **Extract daily GPP** by parsing `summary.out` for the `cprodc` column
   (see the DayCent → FLUXNET variable map below).

This is a deliberately manual port — DayCent assumes the user has made
site-specific decisions (crop choice, rotation, fertilisation, phenology)
that cannot be auto-generated from the FLUXNET metadata alone. Document
every departure from the Wooster template in a `CHANGES.md` next to the
workdir.

## Input files reference

DayCent input files are ASCII fixed-format Century-100 style files with
parameter values in column 1 and a label in column 2.

### `<site>.100` — site climate, soil, and SOM initial conditions
Sections: `*** Climate parameters` (PRECIP(1..12), TMN2M(1..12), TMX2M(1..12)),
`*** Site and control parameters` (sitlat, sitlng, sand, silt, clay, rock, bulkd,
nlayer, nlaypg, drain, basef, stormf, swflag, ph, micosm, sitpot, ...),
`*** External nutrient input parameters` (epnfa, epnfs), and SOM initial pools
(som1ci, som2ci, som3ci, strucc, metabc, etc.). The `Linux_Version_491` example
`wooster_site.100` is the canonical reference template.

**Units (from Wooster site file):** PRECIP in cm/month, TMN2M/TMX2M in °C, sand/silt/clay
as fractions (0–1), bulkd in g/cm³, sitlat/sitlng in decimal degrees.

### `sitepar.in` — site physical parameters (DayCent-specific)
Free-format key/value with a slash separator. Defines elevation (m), slope/aspect
(deg), albedo, vegetation reflectivity, snow flag, N2O nitrification adjustment,
solar-radiation surface transmission per month, hydraulic damping, etc. The
`hours_rain` parameter tells the model how many hours each daily precip event lasts —
critical for infiltration vs runoff partitioning.

### `soils.in` — multi-layer soil hydraulic profile
One row per layer. Columns (no header):
1. Top depth (cm)
2. Bottom depth (cm)
3. Bulk density (g/cm³)
4. Field capacity (vol/vol)
5. Wilting point (vol/vol)
6. Evaporation coefficient
7. Root fraction in layer
8. Sand fraction (0–1)
9. Clay fraction (0–1)
10. OM fraction (0–1, sometimes column 9 is OM and 10 is something else)
11. Saturated hydraulic conductivity (cm/sec)
12. pH

The `DayCent_Manual_full_02.06.2024.pdf` documents the exact column meaning by
revision — read it before changing soil columns. Some columns are interpreted
differently between rev 470 and rev 491.

### `<weather>.wth` — daily weather
Columns 1-7: day-of-month, month, year, day-of-year, Tmin (°C), Tmax (°C),
precipitation (cm/day). Optional columns 8-9: solar radiation (langleys/day),
relative humidity (%), wind (m/s) — only used if `usexdrvrs=1` in `sitepar.in`.

**Trap:** precipitation is in **cm/day**, NOT mm/day. CMFD/MSWX/NASA-POWER all
return mm/day, so the converter MUST divide by 10.

### `<schedule>.sch` — model schedule
Defines simulation period, starting/initial system, climate file, and the list
of timed management events (CROP, FERT, HARV, GRAZ, FRST, LAST, SENM, FIRE,
TREE, IRRI, OMAD, CULT, ACEQ, ...). The `ACEQ` event triggers adaptive
equilibrium termination. `LAST` ends the growing season for a crop block.

### `outfiles.in` — output channel toggles
Lists 28 possible output files, one per line, with a 0/1 toggle and the
filename. The Wooster example provides three presets:
- `no_outfiles.in` — everything off (use during equilibrium)
- `few_outfiles.in` — `bio.out`, `harvest.csv`, `summary.out`, `year_summary.out`
- `outfiles.in` — full output (large files)

## 5. Execution

```
DDcentEVI_rev491 [-s] schedule-file [options]
  -s  schedule file  (required)
  -e  old-binary-file to extend  (e.g. -e eq for base history)
  -i  old-binary-file providing initial conditions only
  -n  new-binary-output-file (optional)
  -N  binary-output-file (overwrite allowed)
  -t  list-file (.lis) to be written
  -v  output variable list  (file like few_outvars.txt)
  -d<x>  delimiter: -dt tab, -dc comma
  -l  directory to search for library .100 files
  --site  site file replacing file in schedule
  --sitdbg  debug soil/sitepar input echo
```

Typical usage chains three calls (`-N` writes the eq binary, then `-e eq`
extends it through history, then `-e base` extends through treatment).

## 6. Output Description

This section restates `dag.yaml`; if this section and the dag disagree, the dag
wins. The dag's `validation_rank: 1` variable is the headline output by which
the KI is judged:

> `cprodc (daily net C production, GPP proxy)` — Daily net C production
> reported in summary.out; the closest DayCent variable to daily GPP for
> cropland/grassland (an approximation, not true gross primary productivity).
> (`gC/m2/day`)

| Output variable (dag `var`) | Rank | File / medium | Unit | Description |
|-----------------------------|------|---------------|------|-------------|
| `cprodc (daily net C production, GPP proxy)` | 1 | `summary.out` daily output | `gC/m2/day` | Daily net C production reported in summary.out; the closest DayCent variable to daily GPP for cropland/grassland (an approximation, not true gross primary productivity). |

Other dag outputs named by this KI are: `n2o_emission`, `no_emission`,
`ch4_flux`, `co2_heterotrophic`, `nee`, `reco`, `aboveground_biomass (aglivc)`,
`crop_yield (cgrain)`, `soil_organic_carbon (somsc)`, `soil_moisture_layers`,
`soil_temperature_layers`, and `evapotranspiration / water_balance`.

### Output files

| File | Frequency | Contents |
|------|-----------|----------|
| `<root>.bin` | run end | Full state archive (Century binary format) |
| `<root>.lis` | run end | Text table extracted from `.bin` (via DDlist100 or `-t`) |
| `summary.out` | daily | Climate, trace-gas, CO respiration |
| `year_summary.out` | annual | Annual trace-gas fluxes |
| `bio.out` | daily | Live above/below ground C |
| `harvest.csv` | event | State at each harvest event |
| `nflux.out` | daily | Trace gases, nitrification, denitrification |
| `watrbal.out` | daily | Water balance components |
| `vswc.out` | daily | Volumetric soil water content by layer |
| `soiltavg.out` | daily | Average soil temperature by layer |

## Extraction with DDlist100

```bash
./DDlist100_rev491 <bin-root> <out-prefix> <variable-list-file>
# Example: ./DDlist100_rev491 cb_nt wooster few_outvars.txt
# -> wooster.lis with columns from few_outvars.txt
```

The variable list file is one variable name per line (e.g. `aglivc`,
`bglivcj`, `bglivcm`, `somsc`, `agcprd`, `cgrain`, `fertot11`). The full
list of available variable names is in `Documentation/DayCent_Manual_full_02.06.2024.pdf`,
section "List of Output Variables".

### Mapping DayCent outputs to FLUXNET variables

When validating DayCent against eddy-covariance towers, use these mappings:

| FLUXNET variable | DayCent output | Notes |
|------------------|----------------|-------|
| **GPP** (g C m⁻² d⁻¹) | `cprodc` (daily C production, from `summary.out`) OR `agcprd + bgcprd` (from `.lis` via DDlist100) | DayCent prints daily **net** C production — for a cropland/grassland this is the closest to daily GPP. For `GPP_NT_VUT_REF` from FLUXNET2015, compare against `cprodc`. |
| **NEE** (g C m⁻² d⁻¹) | `NEE` column in `summary.out` (DayCent sign: positive = uptake) | Note FLUXNET sign convention is opposite (positive = release to atmosphere); **flip sign** before metric calculation. |
| **RECO** (g C m⁻² d⁻¹) | `resp` in `summary.out` (autotrophic + heterotrophic) | |
| **SOC** (g C m⁻² 0–20 cm) | `somsc` in `.lis` | Used for the Wooster validation tier. |
| **LE / ET** (mm d⁻¹) | `evap + trans` from `watrbal.out` | Requires `watrbal.out = 1` in `outfiles.in`. |

`cprodc` is output daily when `summary.out` is enabled (`few_outfiles.in`
already switches it on). Grab it with a tiny post-run parser rather than
running DDlist100 for daily GPP. The `.lis` alternative (`agcprd + bgcprd`
summed over a day) is also valid but is harder to wire up for a daily
comparison because the `.lis` tables are typically annualised.

## 7. Tool Inventory

| Tool | Purpose |
|------|---------|
| `tools/convert_forcing_to_daycent.py` | CMFD/MSWX/NASA-POWER/**FLUXNET CSV** → `<site>.wth` (cm/day, °C) |
| `tools/convert_soil_to_daycent.py` | HWSD + ROSETTA → `soils.in` (multi-layer) |
| `tools/run_daycent.py` | 3-stage execution wrapper (eq → base → treatment) with preflight |
| `tools/parse_daycent_output.py` | Parse `.lis` / `summary.out` / `harvest.csv` → tidy CSV + metrics |

Each tool follows the validate → process → validate pattern from the KDT v5.1
specification and imports shared utilities from `ki_tools_common`.

## 8. Unit Conversion Table

The table documents unit conversions that the DayCent pipeline uses or checks.
Use `docs/format_spec.yaml` as the generated contract and the model's own input
files/manual as the authority for file-level units.

| Variable | Source unit (verified) | Model unit | Factor / transform | Type |
|----------|------------------------|------------|--------------------|------|
| Precipitation forcing | mm/day (CMFD, MSWX, NASA-POWER) | cm/day in `.wth` | `cm = mm / 10` | multiplicative |
| Monthly precipitation climatology | daily `.wth` precipitation in cm/day | cm/month in `.100` | monthly daily mean times days/month | aggregation |
| Tmin, Tmax | K (CMFD raw) | °C | `°C = K - 273.15` | additive |
| Tmin, Tmax | °C (NASA-POWER, FLUXNET CSV after loading) | °C | none | identity |
| Solar radiation | W/m² | langleys/day | `ly/day ~= W/m² * 2.064` | multiplicative |
| Bulk density | kg/m³ (HWSD raw `BULK_DENS`) | g/cm³ | `g/cm³ = kg/m³ / 1000` | multiplicative |
| Sand/silt/clay | percent (HWSD `T_SAND` etc.) | fraction (0-1) | `frac = pct / 100` | multiplicative |
| Field capacity / wilting point | vol/vol (0-1) | vol/vol (0-1) | none | identity |
| Saturated hydraulic conductivity | mm/hour or m/day | cm/sec | use `ki_tools_common.units.convert` | unit conversion |
| Soil pH | unitless | unitless | none | identity |
| Latitude/longitude | decimal degrees, +N / +E | decimal degrees, +N / +E | none | identity |

### Unit traps (READ BEFORE WRITING A FORCING CONVERTER)

**Most common silent failure:** leaving precipitation in mm/day. The model
runs without error but the basin is 10× too wet, the crop drowns, soil
moisture saturates, and SOM accumulates uncontrollably. Always validate
mean annual precip in cm/year against a known reference for the site
(Wooster: ~95 cm/yr, eastern Nebraska: ~75 cm/yr).

## 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| `cprodc` | Daily net C production in `summary.out`; GPP proxy for cropland/grassland, not true gross primary productivity | Treating it as true GPP | Overstates the mechanistic meaning of the validation target |
| `NEE` | Positive = uptake in `summary.out` | FLUXNET positive = release to atmosphere | Correlation and bias can be sign-flipped unless observations are converted |
| `resp` / RECO | Autotrophic plus heterotrophic respiration in `summary.out` | Component-only respiration | Mismatched carbon-flux comparison |
| `evap + trans` / ET | Water loss reported from `watrbal.out`; use mm/day after parsing | Latent heat flux (`LE`) in energy units | Requires LE-to-ET conversion before metrics |
| Soil moisture layers | Volumetric profile values from `vswc.out` | Depth-integrated water storage | Layer aggregation errors if compared directly |

## 9. Diagnostic Triplets (Top 5)

Check `diagnostics/triplets.yaml` before debugging any failed or suspicious
run. Do not duplicate the full corpus in this file; use these five real IDs as
the fastest first scan.

| ID | Error / symptom | Diagnosis | Remedy |
|----|-----------------|-----------|--------|
| 1 | Soil moisture saturated every day; runoff in `summary.out` greater than expected. | Precipitation in the `.wth` file is in mm/day instead of cm/day. | Re-run `convert_forcing_to_daycent.py`; verify column 7 is cm/day. |
| 2 | Daily Tmin and Tmax appear around 270 in `summary.out`. | Temperature columns are in Kelvin. | Subtract 273.15 or use the converter's auto-detection. |
| 5 | Initialisation cannot find `<site>.100`. | The schedule's site file is missing from the run directory or library path. | Copy the file into place or run with `-l /path/to/100/lib`. |
| 24 | Forest flux-site task cannot run with bundled artifacts. | Public `WoosterExampleLinux` ships an empty `tree.100`. | Obtain populated `tree.100` from CSU NREL or clearly report a grassland surrogate. |
| 25 | Daily GPP requested but `.lis` variables do not include a GPP-labeled daily variable. | DayCent reports daily net C production as `cprodc` in `summary.out`. | Parse `summary.out` directly for `cprodc`. |

## 10. Coupling Interfaces

DayCent is normally run as a standalone site model in this KI. Coupling work
should bind to dag variables rather than ad hoc column names.

| Upstream model / data source | Variable exchanged | Unit | Temporal resolution |
|------------------------------|-------------------|------|---------------------|
| FLUXNET CSV | `TA_F`, `P_F`, `SW_IN_F` converted into DayCent weather columns | °C, cm/day, langleys/day | daily |
| CMFD/MSWX/NASA-POWER forcing | precipitation and temperature converted into `.wth` | cm/day and °C | daily |
| HWSD / site soil metadata | soil texture, bulk density, hydraulic properties | fractions, g/cm³, vol/vol, cm/sec | static profile |

| Downstream model / analysis | Variable exchanged | Unit | Temporal resolution |
|-----------------------------|-------------------|------|---------------------|
| FLUXNET-style validation | `cprodc (daily net C production, GPP proxy)` | `gC/m2/day` | daily |
| Greenhouse-gas analysis | `n2o_emission`, `no_emission`, `ch4_flux` | see `dag.yaml` | daily or annual by output file |
| Soil-carbon analysis | `soil_organic_carbon (somsc)` | see `dag.yaml` | annual / sampled years |

## 11. Validated Results

### Primary — Wooster SOC (bundled example, coarse annual)

- **Tier:** `real` — compared against measured SOC at the Wooster OH long-term
  Corn-Soy no-till experiment (Lal et al., 1998; Mishra et al., 2010).
- **Benchmark site:** Wooster, Ohio (Wayne County, OH; ~40.78°N, 81.93°W).
- **Observed values:** SOC at 1962, 1971, 1980, 1992 = 3402, 4789, 3885, 4266
  g C / m² (0–20 cm), reproduced from `wooster_run_rev491_Linux.R` shipped with
  the DayCent distribution.
- **Metric:** Pearson r and RMSE between simulated `somsc` and observed SOC at
  the four sample years.

### Headline Dag Variable

The dag's rank-1 validation variable is `cprodc (daily net C production, GPP
proxy)`, unit `gC/m2/day`. Its dag description is: Daily net C production
reported in summary.out; the closest DayCent variable to daily GPP for
cropland/grassland (an approximation, not true gross primary productivity).

### Performance Metrics — judged against the field's bar, not intuition

State pass/fail bars only from `docs/validation_convention.yaml`. Null bands in
that file are written here as `no cited threshold`; do not replace them with
remembered or generic cutoffs.

| Dag variable | Metric | Direction | Very good band | Good band | Satisfactory band | Citation key(s) |
|--------------|--------|-----------|----------------|-----------|-------------------|-----------------|
| `n2o_emission` | NSE | maximize | no cited threshold | no cited threshold | no cited threshold | none in convention |
| `n2o_emission` | PBIAS | zero_centered | no cited threshold | no cited threshold | `8.74` | `cui2014` |
| `no_emission` | NSE | maximize | no cited threshold | no cited threshold | no cited threshold | none in convention |

No validated numeric campaign result is embedded in this SKILL body for the
rank-1 `cprodc (daily net C production, GPP proxy)` output. Run-level reports
must compute achieved metrics from the task's observation set and judge them
against `docs/validation_convention.yaml`; if the convention has no cited band
for the metric, report `no cited threshold` instead of inventing one.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | `tools/convert_forcing_to_daycent.py` | Task-specific | FLUXNET CSV is preferred for FLUXNET tower tasks; CMFD only covers the China domain. |
| Soil | `tools/convert_soil_to_daycent.py` | Task-specific | Uses HWSD plus ROSETTA or site soil CSV when available. |
| Management schedules | Century `.sch` files | Task-specific | Site crop/grass choice, rotations, fertilisation, and phenology must be documented. |
| Initial conditions | Equilibrium run | Required | Use eq → base → treatment sequence; do not skip spin-up. |
| Output parsing | `tools/parse_daycent_output.py` | Task-specific | Parse `summary.out` directly for rank-1 daily `cprodc`. |

### Daily GPP at a FLUXNET cropland/grassland site

DayCent can be validated against eddy-covariance **daily GPP** at FLUXNET
cropland or grassland towers (but see the KNOWN GAP above for forest sites).
Reference workflow:

1. Build `.wth` with `--source fluxnet` pointing at the site's
   `FULLSET_DD.csv`.
2. Follow the site-adaptation recipe above to make `<site>_*.sch`,
   `<site>_site.100`, and `soils.in`.
3. Run eq → base → treatment with `few_outfiles.in` (produces
   `summary.out`).
4. Parse `summary.out` day-by-day; extract the `cprodc` column as daily
   GPP in g C m⁻² d⁻¹.
5. Align on date with the FLUXNET `GPP_NT_VUT_REF` column (filter out
   `-9999` missing) and compute **Pearson r, NSE, KGE** over the overlap.
6. Judge the run only against cited bars present in
   `docs/validation_convention.yaml`. If a needed metric has no cited band,
   state `no cited threshold`; do not substitute a generic pass/fail cutoff.
   Check phenology (CROP/LAST dates) and N fertilisation schedule before
   retuning.

## 12. Parameter Selection by Region

Use physically informed site inputs, not generic calibration shortcuts. For
cropland and grassland tasks, start from the `WoosterExampleLinux` schedule and
edit site climate, soil, crop/grass parameterisation, rotation, fertilisation,
and phenology to match the target. For forest tasks, the bundled public example
does not include a populated `tree.100`, so a true forest DayCent run requires
that upstream parameter library from CSU NREL or an explicitly reported
grassland surrogate.

## References

- Parton, W.J. et al. (1998). DAYCENT and its land-surface submodel.
  *Ecological Modelling* 109, 67–95.
- Del Grosso, S.J., Parton, W.J., Mosier, A.R., et al. (2001). Simulated
  interaction of soil C, N and N2O fluxes. *Global Biogeochemical Cycles* 15.
- Hartman, M., Parton, W.J., Del Grosso, S., et al. (2024). DayCent Model
  Reference Manual, revision 491. CSU NREL.
- Wooster long-term experiment SOC: Lal, R., Mahboubi, A.A., Fausey, N.R.
  (1994). Long-term tillage and rotation effects on properties of a central
  Ohio soil. *SSSAJ* 58, 517–522.

## Provenance notes

This KI was generated by KDT v5.1 from the public DayCent v491 release. The
binary was not built from source — DayCent source is not bundled with the
public release. If you need to modify the model itself, contact the CSU NREL
group for the source distribution.
