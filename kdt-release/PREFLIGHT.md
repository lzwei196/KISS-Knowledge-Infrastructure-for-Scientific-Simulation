# Pre-Flight Checklist: Before Dissecting a New Model

**Read this BEFORE starting any model dissection.** It's 2 minutes and prevents the errors that took us weeks to find across 25 models.

> **Also read `VALIDATION_PROTOCOL.md`** — it defines the mandatory three-step validation process: (1) developer test data, (2) progressive replacement with HydroCraft data, (3) full Bengbu run. A model is NOT validated until Step 3 passes.

---

## Step 1: Classify Your Model (30 seconds)

Check all that apply — each triggers specific warnings below:

- [ ] **Has Fortran/C code** → See [Fortran Traps](#fortran-traps)
- [ ] **Reads fixed-width text files** (not CSV/JSON) → See [Column Alignment](#column-alignment)
- [ ] **Will be coupled with other models** → See [Coupling Traps](#coupling-traps)
- [ ] **Has physical units** (m/s, mm/day, W/m², kg/ha) → See [Unit Traps](#unit-traps)
- [ ] **Uses spatial data** (lat/lon, shapefiles, rasters) → See [Spatial Traps](#spatial-traps)
- [ ] **Is a crop/ecosystem model** → See [Domain Traps](#domain-traps)
- [ ] **Runs on Linux but was built for Windows** → See [Platform Traps](#platform-traps)
- [ ] **Is a lake/reservoir model** → See [Lake Model Traps](#lake-model-traps)
- [ ] **Is a 2D flood/inundation model** → See [Flood Model Traps](#flood-model-traps)
- [ ] **Has a config file separate from the model input** → See [Config File Traps](#config-file-traps)
- [ ] **Can emulate multiple model structures** (Raven, SUMMA) → See [Multi-Structure Traps](#multi-structure-traps)
- [ ] **Has flow routing / drainage network** → See [Flow Network Traps](#flow-network-traps)
- [ ] **Needs long spinup** (>1 year) → See [Spinup Requirements](#spinup-requirements)

---

## Step 2: Check the Traps (1 minute)

### Unit Traps (37% of all silent errors come from here)
> **The #1 error across all 97 models. Simulation runs fine. Results are wrong. No warning.**

**GOLDEN RULE: NEVER trust data registry documentation for units. ALWAYS verify by reading the actual file:**
```python
import xarray as xr
ds = xr.open_dataset('file.nc')
print(ds['prec'].attrs)  # Check 'units' attribute — this is ground truth
```

**CMFD UNIT CORRECTION (discovered 2026-03-30):** The CMFD daily files are documented as mm/day in many places, but the actual NetCDF attribute says `kg m-2 s-1`. This caused near-zero runoff in multiple models until caught. The conversion matrix:

| CMFD variable | Actual unit (from NetCDF) | To mm/day | To mm/hr | To m/day | To inches/day |
|--------------|--------------------------|-----------|----------|----------|---------------|
| prec | **kg/m2/s** | ×86400 | ×3600 | ×86.4 | ×3401.6 |
| temp | **K** | -273.15→°C | | | ×9/5-459.67→°F |
| pres | **Pa** | ÷100→hPa | | | |

**Each model expects DIFFERENT units** — there is no universal conversion:

| Model expects | Conversion from CMFD prec (kg/m2/s) |
|--------------|-------------------------------------|
| mm/day (most models) | ×86400 |
| cm/day (BIOME-BGC, HydroCNHS) | ×8640 |
| inches/day (PRMS) | ×3401.6 |
| mm/hr (EF5, CREST, GEOtop, TopoFlow) | ×3600 |
| m/timestep (DHSVM) | ×3600×dt_hr/1000 |
| kg/m2/s native (CLM5, ELM, Noah-MP, CLASSIC) | ×1 (no conversion!) |
| m/day (PCR-GLOBWB) | ×86.4 |

| Model | What went wrong | Impact |
|-------|----------------|--------|
| **CMFD→KINEROS2** | CMFD prec read as mm/day but is kg/m2/s → **86400x too low** | Near-zero discharge |
| **CMFD→VELMA** | Same bug — no unit conversion applied | Near-zero discharge |
| **NASA POWER** | PRECTOTCORR hourly labeled "mm/hr" but is actually mm/day rate → **divide by 24** | Precip 24x too high |
| **GLM** | Rain in mm/day instead of **m/day** → 1000x too much | Lake overflows every day |
| **SFINCS** | Precip in mm/3hr not converted to **mm/hr** | Flood depths 10-100x too high |
| **Raven** | "Raven ignores units and will not do units conversion" (official docs) | Everything wrong silently |
| **mizuRoute** | VIC mm/timestep not converted to **mm/s** rate | Discharge off by timestep ratio |

### Data Source Selection (NEW — added after 97-model synthesis)
> **Not all models should use CMFD.** Choose the right forcing data based on model requirements.

| If model needs... | Use this data source | Path |
|-------------------|---------------------|------|
| Daily China forcing (default) | CMFD 0.25° daily | `/mnt/disk1/.../huai/Data_forcing_01dy_025deg/` |
| Sub-daily timestep | MSWX 0.1° 3-hourly | `/mnt/disk3/msxw/` |
| Global coverage | MSWX 0.1° 3-hourly | `/mnt/disk3/msxw/` |
| High spatial resolution China | CMFD 0.1° daily | `/mnt/disk1/.../Data_forcing_01dy_010deg/` |
| FLUXNET site-level (BGC models) | FLUXNET2015 tower data | `/mnt/disk1/.../obs/fluxnet/sites/` |
| Ocean boundary conditions | HYCOM/GLORYS | Check model-specific docs |
| **DLBreach** | Time units mixed: seconds in config, hours in timeseries | Breach timing wrong |
| WOFOST | IRRAD in kJ/m²/d instead of J/m²/d | Yield 1000x wrong |
| VIC | Precip divisor 86400 vs 10800 | Runoff 8x wrong |
| SWMM | CFS vs CMS (entire unit system flips) | All flows wrong |
| OGGM | mm w.e. vs m³/s (forgot area scaling) | Glacier runoff 10⁶x wrong |
| DSSAT | Wind m/s vs km/day | ET wrong |
| AquaCrop | Vapor pressure vs specific humidity | ET wrong |
| **CE-QUAL-W2** | Cloud cover 0-10 tenths not 0-1 fraction | Radiation wrong |
| **ParFlow** | van Genuchten alpha in 1/m not 1/cm (100x) | Infiltration wrong |
| **All POWER users** | NASA POWER SW radiation in MJ/m²/hr → multiply by **277.78** for W/m² | All energy balance wrong |
| **Multiple** | Soil Ksat: ParFlow m/hr, MODFLOW m/day, wflow mm/day, VIC mm/s | Cross-model coupling fails silently |
| **SHAW** | Solar radiation in MJ/m²/day not converted to **W/m²** (×11.574) | 11.6x too low energy, cold bias |
| **SHAW** | MTSTEP=0 (hourly) with daily weather file → wrong column parsing | Zero precip, wrong temps |
| **SHAW** | Solar noon HRNOON=0.01 instead of ~12.3 → wrong diurnal cycle | Zero effective precipitation |
| **HYPE** | CMFD precip in kg/m²/s → must **×10800** for mm/3hr | Zero discharge |

**Action**: For EVERY input variable, document: (1) what unit the model expects, (2) what unit your data is in, (3) the conversion factor. Put this in a table in the skill doc.

**Mountain basin check**: If your basin has >500m elevation range AND uses NASA POWER or coarse reanalysis:
- Check: is observed annual runoff > input annual precip? If yes, precip is too low (orographic miss)
- Apply precip scaling: ×1.5-2.0 for mountains, validate against station climatology
- Apply temperature lapse rate: -6.5°C/km from grid elevation to basin elevation
- Apply wind amplification: ×3-4 for alpine ridges (coarse grids smooth wind to ~1 m/s)
- Apply LW radiation correction: -6 W/m²/100m elevation gain

### Fortran Traps
| Pattern | Models hit | What happens |
|---------|-----------|-------------|
| Path > 72-256 chars | DSSAT, VIC routing, RZWQM2, SWAT+, mizuRoute, DLBreach, SUMMA, MODFLOW6, CE-QUAL-W2 | File not found or reads wrong file — **silently** |
| Fixed-width column off by 1 | DSSAT, RZWQM2, SWAT+, DLBreach | Reads wrong parameter value — **silently** |
| STOP exits with code 0 | DSSAT, CaMa-Flood, mizuRoute | Looks like success but produced no output |
| MODEL.ERR / .CDE files missing | DSSAT | Error 26 / Error 29 at startup |
| Needs `--conf` or resources path | LDNDC, mizuRoute | Crashes silently without resource directory |

**Action**: `grep 'CHARACTER' *.f*` to find max path lengths. Test with a path > 80 chars early.

### Column Alignment
> Fortran reads by **column position**, not delimiter. One extra space shifts everything.

| Model | What happened |
|-------|--------------|
| DSSAT CUL file | ECO# must start at column 25 (1-indexed). ljust(17) not ljust(16) |
| RZWQM2 | Soil layer params read at fixed offsets — UTF-8 encoding bloated file 3x |
| SWAT+ | Calibration params at wrong column positions |

**Action**: Read the FORMAT statement in the Fortran source. Verify with `cut -c1-80 < file | head`.

### Coupling Traps
| Pattern | Example | Fix |
|---------|---------|-----|
| **Double-counting** | VIC snow + OGGM glacier melt on same cells | One model must "own" each process — mask the other |
| **Temporal mismatch** | OGGM uses Oct-Sep water year, VIC uses Jan-Dec | Explicitly convert at coupling boundary |
| **Spatial mismatch** | VIC 0.25° feeds SWMM 10m | Use area-weighted interpolation, never bilinear for fluxes |
| **Datum mismatch** | CaMa-Flood elevation ASL vs SWMM local datum | Verify both use same vertical reference |

**Action**: For every coupling, draw a diagram showing: which model handles which process, what units cross the boundary, and what temporal/spatial alignment is needed.

### Spatial Traps
| Pattern | What happens |
|---------|-------------|
| CRS mismatch (UTM vs WGS84) | Spatial join returns 0 features — **silently** |
| Basin shapefile covers wrong area | Entire simulation is for the wrong location |

**Action**: Always `assert gdf1.crs == gdf2.crs` before spatial operations. Plot the basin on a map before running.

### Domain Traps
| Pattern | Example |
|---------|---------|
| Flag correct for one crop but wrong for another | DSSAT SYMBI=N kills soybean (legume needs N-fixation) |
| Model outside valid climate envelope | Soybean at 51°N killed by frost — not a bug, agronomic limit |
| Default planting date wrong for region | GGCMI global DOY vs actual local phenology |
| **Abstract species name** produces zero output | LDNDC "RICE" is abstract; need "PADR" (leaf node). DSSAT needs exact cultivar in CUL file |
| Crop residue format wrong for biogeochem | LDNDC expects C/N from DSSAT; internal plamox is incomplete |

**Action**: When switching crop/region/climate, review ALL model flags. Check if defaults are universal or context-specific.

### Platform Traps
| Pattern | Example |
|---------|---------|
| Backslash paths | DSSAT DSSATPRO.L48 has Windows backslashes |
| Case-sensitive filenames | `SOIL.SOL` vs `soil.sol` — works on Windows, fails on Linux |
| File encoding | RZWQM2 expects ISO-8859-1, Python writes UTF-8 by default |
| Line endings | SWMM INP with Unix LF may fail on Windows SWMM parser |

**Action**: Test on the target platform early. Check encoding with `file <filename>`.

---

## Step 3: Run the Aggregator (10 seconds)

See what errors have been found across all existing models:
```bash
python /home/server/knowledge-dissection-toolkit/tools/aggregate_errors.py
python /home/server/knowledge-dissection-toolkit/tools/aggregate_errors.py --by domain
```

If your new model is similar to an existing one (e.g., another Fortran hydrology model like VIC), check that model's triplets specifically:
```bash
python /home/server/knowledge-dissection-toolkit/tools/aggregate_errors.py --format full | grep -A3 "DSSAT\|VIC"
```

---

## Quick Stats (as of March 25, 2026)

| | Count |
|---|---|
| Models dissected | **25** (23 with KI + 2 standalone) |
| Model KI tools | **~436** |
| Total triplets | **535** (model-specific) + **28** cross-model = **563** |
| Error log entries | **~900** |
| Common failure patterns | **31** (cfp_001-cfp_031) |
| **Silent errors** | **~37%** — most dangerous |
| Top failure domain | unit_conversion — hits EVERY model |
| Top model by errors | ParFlow (36), WRF-Hydro (35), Raven (33), SHAW (31), wflow (30) |
| Production validated | **23 models** on real basins (incl. HYPE) |

---

## The Three Rules

### Rule 0: Debug by Reading, Not Reverse-Engineering

> **When something goes wrong, read the docs first. Do NOT write debug scripts.**

Follow this order STRICTLY:
1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this exact error
2. **Read official docs** — The model's PDF manual, README, or online docs describe expected input formats, variable names, and units
3. **Find working examples** — Check `outputs/` for previous successful runs, or the model's own test/example data
4. **Fix the tool** — Now that you know what "correct" looks like, make the targeted fix

**Why this matters**: During the mizuRoute and wflow revalidation (2026-04-10), agents wrote 20+ diagnostic Python scripts (`debug_remap.py`, `diagnose_deep.py`, `fix_ldd.py`, `rebuild_ldd_v2.py`, etc.) to reverse-engineer model behavior. The answers were in the official docs and working examples all along:
- mizuRoute remap format → documented in `Input_files.rst` (lines 418-464)
- wflow LDD convention → documented in `utils.jl` (PCR_DIR constant) + `io.jl` (read_standardized)
- wflow y-axis handling → `read_y_axis()` sorts to ascending, `reverse_data!()` flips

Reverse engineering is expensive, fragile, and often misses the root cause. Documentation-first is faster and more reliable.

### Rule 1: Copy-First for Control Files (cm_026)

> **NEVER generate model input/control files from scratch. ALWAYS copy from a validated example and modify values.**

This is the single most effective error prevention strategy across all 25 models. Legacy Fortran models have rigid, undocumented input formats that evolved over decades. Writing files from scratch — even following the manual — misses implicit format requirements (column positions, line ordering, flag-dependent sections, sentinel values).

**For every new model dissection:**
1. Identify the working example/tutorial files that ship with the model
2. Copy them as templates into the KI package
3. Write tools that **copy the template and update specific values** — NOT tools that generate files from scratch
4. Test the copy-update workflow before attempting any modification

**Models where this prevented errors**: SHAW (.sit format), DSSAT (.CUL/.ECO column alignment), RZWQM2 (.rzx/.cfg), CRHM (.obs header), HYPE (info.txt/GeoClass.txt), DLBreach, mizuRoute

### Rule 2: Check Units First

> **If the model runs without error but the results look wrong, check units first.** Unit mismatches are the #1 silent error across all 25 models — every single model we dissected had at least one unit trap. The second most common is fixed-width column misalignment in Fortran. The third is header/config format that causes silent parsing failure (CRHM .obs, LDNDC --conf).

### Crop-Biogeochemistry Coupling Trap
> If you run a crop model (DSSAT/WOFOST) AND a biogeochemistry model (LDNDC/DNDC) on the same grid, they MUST be coupled.

The biogeochemistry model's internal crop model is usually uncalibrated and produces wrong yields. Wrong yields → wrong residue → wrong N₂O/CH₄. Use the calibrated crop model (DSSAT) to provide residue C/N inputs to the biogeochemistry model.

**Tool**: `skills/dssat-crop-run/tools/s5_coupling/dssat_to_ldndc_coupling.py`

### Lake Model Traps (GLM, CE-QUAL-W2)
| Pattern | Example |
|---------|---------|
| Rain in mm/day instead of **m/day** | GLM: 1000x too much precip → lake overflows daily |
| Inflow units wrong | GLM expects m³/s, CaMa-Flood outputs may be mm/day over grid cell |
| Lake bathymetry inverted | Depth increasing upward vs downward — different conventions |
| Initial temperature profile wrong | Lake starts isothermal instead of stratified → wrong mixing |

**Action**: GLM uses m/day for rain, m³/s for inflows, °C for temperature. Triple-check EVERY unit.

### Flood Model Traps (SFINCS, HEC-RAS)
| Pattern | Example |
|---------|---------|
| DEM resolution too coarse | 0.25° DEM for urban flood = meaningless (need <30m) |
| Boundary condition datum mismatch | Water level ASL vs local datum → flow direction reversed |
| Manning's n spatially uniform | One value for entire domain misses buildings/vegetation |
| Timestep too large for CFL | SFINCS: subgrid approach helps but still needs dt check |

**Action**: Always validate flood extent against known events before running scenarios.

### Config File Traps (LDNDC, CRHM, mizuRoute)
| Pattern | Example |
|---------|---------|
| Model needs `--conf` or resources path | LDNDC crashes silently without it — no log, no error |
| Config separate from input data | CRHM `.prj` vs `.obs` — each has its own format rules |
| Relative paths in config | CaMa-Flood STOP 10 from relative paths; use ABSOLUTE always |
| Header format determines parsing | CRHM: `####` before variables → infinite loop; after → works |

**Action**: Always run the model's `--help` first. Check if it needs a config/settings/resources file separate from the project input.

### Multi-Structure Traps (Raven, SUMMA)
| Pattern | Example |
|---------|---------|
| Invalid physics combination | SUMMA: `fDerivMeth=numericl` crashes immediately; `qTopmodl` requires `bcLowrSoiH=zeroFlux` |
| Model emulation not exact | Raven emulating HBV ≠ actual HBV — subtle differences in implementation |
| Parameter transfer between structures | Calibrated params for one structure don't work in another |
| "Ignores units" models | Raven explicitly states it does NO unit conversion — all on you |
| **Parameter sign conventions** | SUMMA `vGn_alpha` must be NEGATIVE (matric head). Positive → NaN, no error message |
| **Boundary condition mode traps** | SUMMA `presTemp` = diagnostic only (zero ET). Must use `nrg_flux` for production, but crashes on cold-start for subtropical basins |

**Action**: When using multi-structure frameworks, test one configuration thoroughly before comparing. Document which physics options were used. Read the Fortran source for parameter bounds — docs are often incomplete.

### Land Cover Classification Mismatch (cm_029, NEW)
| Pattern | Example |
|---------|---------|
| **IGBP vs USGS class numbering** | AVHRR uses IGBP (class 11=Wetland). SUMMA VEGPARM.TBL uses USGS (class 11=Deciduous Forest, 20m). 74% of Bengbu treated as tall forest instead of cropland → convergence crash |
| **VIC vs SUMMA veg tables** | VIC has its own AVHRR→VIC class mapping. SUMMA, CRHM, WRF-Hydro each use different tables |
| **Missing crosswalk** | Directly passing raster pixel values as model class indices → silent misclassification |

**Action**: ALWAYS check which classification system the model uses (USGS, IGBP, MODIS, custom). AVHRR raster uses IGBP-DIS. If the model expects a different system, apply a crosswalk table. Verify by checking canopy heights — if cropland gets 20m canopy, the mapping is wrong.

### VIC Forcing Column Order Mismatch (cm_030, NEW)
| Pattern | Example |
|---------|---------|
| **HydroCraft vs classic VIC order** | HydroCraft: AIR_TEMP,PREC,PRES,SW,LW,VP,WIND (7 cols). Classic: PREC,TMAX,TMIN,WIND,SW,LW,PRES,QAIR (8 cols). Every column misassigned → all forcing values garbled |
| **VP vs specific humidity** | VIC `FORCE_TYPE VP` is vapor pressure (kPa), not specific humidity (kg/kg). Must convert: `q = 0.622*e/(P-0.378*e)` |

**Action**: When coupling VIC forcing to another model, check `global_param FORCE_TYPE` order. Never assume column order from documentation — read the actual file header or global_param.

### Flow Network Traps (wflow, mHM, mizuRoute)
| Pattern | Example |
|---------|---------|
| **D8 cycles on coarse grids** | Naive D8 creates cycles in flat terrain → crash or corruption. Use priority-flood D8 |
| HRU/cell ID mismatch across NetCDF files | SUMMA, mHM, wflow: `hruId` must match in ALL forcing/param files |
| WhiteboxTools D8 encoding wrong | WRF-Hydro: official D8 docs have wrong direction numbering |
| Fortran PARAMETER array too small | VIC routing NROW/NCOL, mHM hardcoded dimensions — must recompile |

**Action**: Run topological sort on flow network to detect cycles. Verify cell IDs are consistent across all NetCDF inputs.

### Spinup Requirements
| Model | Spinup needed | Why |
|-------|--------------|-----|
| **BIOME-BGC** | 1,000-6,000 years | Carbon pool equilibration |
| **MODFLOW 6** | 2-3 years | Water table stabilization |
| **AquaCrop/WOFOST/DSSAT** | 1-2 years | Soil moisture initialization |
| **GLM** | 1 year | Lake thermal stratification |
| **ParFlow** | 1-2 years | 3D pressure head equilibration |

**Action**: Always discard spinup years from performance metrics. Use the longest recommended spinup for your model family.
