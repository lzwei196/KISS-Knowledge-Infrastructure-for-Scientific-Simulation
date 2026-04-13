# S0: SWAP Configuration

## Purpose
Define the simulation site, period, forcing source, crop schedule, and output options. This stage establishes all parameters needed to assemble a complete SWAP .swp file.

## Inputs
- **Site location**: Latitude (°N), longitude (°E)
- **Simulation period**: Start date (YYYY-MM-DD), end date (YYYY-MM-DD)
- **Forcing source**: CMFD, MSWX, or local met station data
- **Crop schedule**: Crop type(s), emergence/harvest dates, CROPTYPE (1=simple, 2=WOFOST, 3=grass)
- **Soil type**: USDA texture class or HWSD lookup
- **Bottom boundary**: Type (free drainage, prescribed GWL, etc.)
- **Drainage**: Method (none, Hooghoudt, multi-level)

## Outputs
- Configuration dictionary or JSON with all parameters
- Validated parameter ranges

## Procedure
1. Select study site and extract coordinates
2. Define simulation period (ensure meteorological data coverage)
3. Choose forcing dataset (CMFD for China, MSWX for global)
4. Define crop rotation: CROPSTART, CROPEND, CROPFIL, CROPTYPE for each crop
5. Set soil profile: number of layers, compartment sizes (HSUBLAY, HCOMP, NCOMP)
6. Choose bottom boundary condition (SWBOTB = 7 for free drainage is simplest)
7. Set output options: SWBLC=1, SWINC=1, SWVAP=1 recommended minimum
8. Set numerical parameters: DTMIN=1e-6, DTMAX=0.04, MAXIT=30

## Verification
- All dates within forcing data coverage
- Crop dates do not overlap
- Soil layer thicknesses sum to profile depth
- NCOMP = HSUBLAY / HCOMP for each sub-layer

## Traps
- **TSTART before met data**: SWAP will crash with "meteorological data not available"
- **Overlapping crop dates**: Causes array overflow or incorrect rotation
- **NPRINTDAY > 1 with SWMETDETAIL=0**: Sub-daily output with daily forcing gives interpolation artifacts
- **Missing PATHWORK trailing slash**: SWAP may fail to find output directory

## Example
```
TSTART = 2002-01-01
TEND = 2004-12-31
METFIL = '283.met'
LAT = 52.0
SWETR = 0        ! Use Penman-Monteith
ALT = 10.0
ALTW = 10.0
SWCROP = 1
SWBOTB = 7       ! Free drainage
DTMIN = 0.000001
DTMAX = 0.04
```
