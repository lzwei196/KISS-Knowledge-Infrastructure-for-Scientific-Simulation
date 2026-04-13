# S4: CLM Land Surface Setup — Skill Document

## Purpose

Configure CLM 4.5 as the upper boundary condition. CLM provides evapotranspiration, snow, canopy interception, and radiation balance.

## Prerequisites

- Domain definition (s1)
- Surface mask (s1)
- AVHRR land cover data

## Procedure

1. **Run** `setup_clm_driver.py` with domain JSON, mask, and dates.
2. **Verify** drv_vegm.dat has correct IGBP vegetation types (not all zeros/bare soil).
3. **Verify** drv_clmin.dat timestep matches ParFlow timestep.

## Critical Knowledge

- **Zero vegetation** (dt_pf_030): All-zero vegmap produces no transpiration (silent error).
- **File naming** (dt_pf_031): CLM forcing files must be named `NLDAS.<run>.NNNNNN.pfb` with sequential numbers starting from IstepStart.
- **IGBP types**: 1-14 are vegetated, 15=snow/ice, 16=barren, 17=water. A realistic basin should have types 1-14 dominant.
- **CLM timestep**: Must match ParFlow base timestep. CLM does not interpolate.
- **LAI seasonality**: Default values are annual means. For seasonal accuracy, provide monthly LAI.
