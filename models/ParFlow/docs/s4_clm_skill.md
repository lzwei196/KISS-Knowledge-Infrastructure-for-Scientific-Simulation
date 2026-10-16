# S4: CLM Land Surface Setup — Skill Document

## Purpose

Configure CLM 4.5 as the upper boundary condition. CLM provides evapotranspiration, snow, canopy interception, and radiation balance.

## Prerequisites

- Domain definition (s1)
- Surface mask (s1)
- AVHRR land cover data (`data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif`)
- HWSD global soil raster + table (`data/soil/HWSD_RASTER/hwsd.bil`, `data/soil/HWSD_DATA.csv`), the same soil s2 uses
- A soil colour class (1-8) that YOU choose (`--soil_color`, required, no default; see below)

## Procedure

1. **Run** `setup_clm_driver.py` with domain JSON, mask, dates and `--soil_color N`.
2. **Verify** drv_vegm.dat has correct IGBP vegetation types (not all zeros/bare soil) and per-cell sand/clay (columns 5-6 vary with the soil map). `clm_provenance.json` records the sources, class counts, sand/clay ranges and the soil colour assumption.
3. **Verify** drv_clmin.dat timestep matches ParFlow timestep.

## drv_vegm.dat: every cell gets real data

Line format (CLM `drv_readvegtf.F90`, two header lines, rows y outer / columns x inner): `x y lat lon sand clay color frac1..frac18`.

- **Every cell of the Box grid**, inside and outside the basin mask, gets its own values: the s7 run script uses Box geometry, so CLM computes every cell. (Outside cells used to be written as IGBP 17 water.)
- **Vegetation**: AVHRR (UMD classes) -> IGBP, one class per cell (fraction 1.0). A cell outside the raster, at nodata, or with a value that has no IGBP mapping stops the tool. There is no default class (the old silent grassland default is gone).
- **sand / clay**: HWSD topsoil (0-30 cm) T_SAND / T_CLAY of the dominant component (largest SHARE, ties -> lowest SEQ), divided by 100 (CLM reads fractions; `drv_clmini.F90` multiplies by 100). Same reader as s2 (`sample_hwsd_topsoil`), so CLM and ParFlow use the same soil. CLM applies the value to all its soil layers. A cell with no HWSD texture (e.g. a water body, ISSOIL 0) stops the tool with the count and the first 10 cells; there is no default (the old fixed 0.40 / 0.20 was made up). In ParFlow-CLM sand/clay set CLM's soil thermal properties (tkm, csol) and its bsw/sucsat/xksat; the soil water itself is ParFlow's.
- **soil colour** (`color`): CLM soil colour class 1 (lightest) .. 8 (darkest); `clm_varcon.F90` gives saturated / dry visible albedo 0.12/0.24 (class 1) down to 0.05/0.10 (class 8), used by `clm_soilalb.F90` for bare-soil albedo. No soil-colour map exists on this server, so the class is **required from the user** (`--soil_color`) and written to every cell. It is a stated assumption, recorded in the tool output (`stated_assumptions`, `provenance.soil_color`) and `clm_provenance.json`. The shipped washita reference (`drv_vegm.alluv.dat`) uses class 2 everywhere. Pick it from local knowledge (dark organic / black soils -> high class; light sandy / desert soils -> low class) and report it with results.

## Critical Knowledge

- **Zero vegetation** (dt_pf_030): All-zero vegmap produces no transpiration (silent error).
- **File naming** (dt_pf_031): CLM forcing files must be named `NLDAS.<run>.NNNNNN.pfb` with sequential numbers starting from IstepStart.
- **IGBP types**: 1-14 are vegetated, 15=snow/ice, 16=barren, 17=water. A realistic basin should have types 1-14 dominant.
- **CLM timestep**: Must match ParFlow base timestep. CLM does not interpolate.
- **LAI seasonality**: Default values are annual means. For seasonal accuracy, provide monthly LAI.
