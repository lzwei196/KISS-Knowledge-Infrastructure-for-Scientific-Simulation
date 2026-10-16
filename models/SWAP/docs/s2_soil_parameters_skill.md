# S2: Soil Parameter Conversion

## Purpose
Convert soil texture/property data from HWSD or other databases to SWAP Mualem-van Genuchten (MvG) hydraulic parameters and profile discretization.

## Inputs
- **HWSD raster**: `--hwsd auto` = KISSPATH_STATIC/HWSD_RASTER/hwsd.bil
  (with KISSPATH_STATIC/HWSD_DATA.csv). This BIL has no CRS metadata, so
  `--hwsd-crs EPSG:4326` is required; without it the tool stops.
- **Site coordinates**: lat, lon
- **OR manual texture**: `--texture <class>` or `--sand --silt --clay` (topsoil), plus
  `--subsoil-texture <class>` when `--n-layers` > 1. Bulk density is then a texture-class estimate.
- Use ONE source per run. `--hwsd` together with any manual texture option is refused
  (since 2026-10-05).
- **Profile depth**: Total soil column depth (cm)

## Outputs
- MvG parameter table for .swp file: ORES, OSAT, ALFA, NPAR, KSATFIT, LEXP, ALFAW, H_ENPR, KSATEXM, BDENS
- Profile discretization table: ISUBLAY, ISOILLAY, HSUBLAY, HCOMP, NCOMP

## Procedure
1. **Extract soil texture**: Read the dominant HWSD component at the point (max SHARE, then min SEQ;
   topsoil T_ and subsoil S_ sand/silt/clay and REF_BULK_DENSITY x 1000 -> BDENS mg/cm3), or use manual
   input. Any missing HWSD value (map unit, texture, density, CRS) stops the tool; there is no default.
2. **Classify texture**: Apply USDA texture triangle → class name
3. **Pedotransfer function**: Map texture class → MvG parameters with the Carsel & Parrish (1988)
   class table in the tool (a class lookup, not a fitted Rosetta / Schaap et al. 2001 model).
   KSATEXM is set equal to the class KSATFIT (not measured); ALFAW = 2 x ALFA.
4. **Resolve each horizon**: require its texture; use source horizon density or a labeled manual class estimate. No invented subsoil contrast.
5. **Profile discretization**:
   - Fine near surface (1 cm compartments, top 10 cm)
   - Medium in root zone (5 cm, 10-60 cm)
   - Coarse at depth (10 cm, 60-200 cm)
6. **Validate parameter ranges**: All within SWAP limits

## Verification
- ORES < OSAT for all layers
- NPAR > 1.001
- ALFA > 0.0001
- KSATFIT in physically meaningful range for texture class
- Sum of HSUBLAY = total profile depth
- NCOMP × HCOMP = HSUBLAY for each sub-layer

## Traps

### TRAP 1: Ksat units
HWSD and many databases report Ksat in m/day, m/s, or cm/hr. SWAP expects cm/day.
- m/day → cm/day: × 100
- m/s → cm/day: × 8,640,000 (= 100 × 86400)
- cm/hr → cm/day: × 24

### TRAP 2: Bulk density units
SWAP BDENS is in mg/cm³, which is numerically equal to kg/m³.
- g/cm³ → mg/cm³: × 1000 (e.g., 1.35 g/cm³ = 1350 mg/cm³)
- Entering 1.35 directly: SWAP clips to minimum 100, producing nonsense

### TRAP 3: ALFA parameter sign
ALFA must be positive in SWAP. Some literature reports it as negative (e.g., HYDRUS convention). Always use absolute value.

### TRAP 4: Layer boundary mismatch
Soil physical layer boundaries (ISOILLAY) must align with sub-layer boundaries (ISUBLAY). If layer 1 extends to 30 cm but sub-layers split at 25 cm, there will be an inconsistency.

### TRAP 5: Too-coarse discretization at surface
Compartments > 5 cm near the surface cause poor representation of evaporation front and infiltration. Use 1 cm for top 10 cm.

## Example
```
* Profile discretization (200 cm total)
 ISUBLAY  ISOILLAY  HSUBLAY  HCOMP  NCOMP
       1         1     10.0    1.0     10    ! Fine near surface
       2         1     20.0    5.0      4    ! Medium in topsoil
       3         2     30.0    5.0      6    ! Transition
       4         2    140.0   10.0     14    ! Coarse at depth

* MvG parameters (sandy loam topsoil, loam subsoil)
 ORES  OSAT    ALFA   NPAR  KSATFIT    LEXP   ALFAW  H_ENPR  KSATEXM   BDENS
 0.065 0.410  0.0750  1.890   106.10   0.500  0.1500     0.0   106.10  1450.0
 0.078 0.430  0.0360  1.560    24.96   0.500  0.0720     0.0    24.96  1400.0
```

### Strict texture and layer inputs (2026-10-03)

Missing or unknown texture classes stop the converter. Sand, silt and clay
must all be finite percentages in [0,100], summing to 100 within 0.1 percentage
point; no renormalization is applied. Valid zero fractions are retained.
Class boundaries follow the [USDA Soil Survey Manual, chapter 3](https://nrcspad.sc.egov.usda.gov/distributionCenter/pdf.aspx?productID=1363).
The prior classifier misclassified some valid sandy/silty compositions; tests
cover all twelve classes and valid zero fractions.

`--hwsd auto` now reads the raster and attribute CSV directly, avoiding shared
reader defaults. It transforms point coordinates into the raster CRS, rejects
NoData/outside coverage, and selects the dominant component by maximum SHARE,
then minimum SEQ, then CSV row order for remaining ties. Missing texture or
bulk density on that component is an error. It never substitutes a minor
component or 40/40/20 texture. `--hwsd-csv` can specify the matching attributes.
Topsoil and subsoil use their own source bulk densities (g/cm3 × 1000).

For manual input, supply `--texture` or all three fraction arguments. With
`--n-layers 2` (the existing default), also supply `--subsoil-texture`. Use
`--n-layers 1` for a single layer. Giving the same explicit class for both
horizons declares a homogeneous texture assumption. No synthetic compaction,
porosity, alpha or bulk-density multipliers are applied to deeper layers.
A failed HWSD request stops the tool. Since 2026-10-05 `--hwsd` cannot be combined
with `--texture`, `--sand/--silt/--clay` or `--subsoil-texture` (the tool exits with an
error and writes nothing); run the manual texture as its own run without `--hwsd`.

Hydraulics remain **texture-class estimates** from the existing Carsel-Parrish
lookup table; this tool does not run Rosetta. Manual bulk density also remains
a labeled class estimate. `KSATEXM` is populated from that estimate for the
format, not a measured Ksat claim; `ALFAW=2*ALFA` retains the existing hysteresis
parameterization. The `.summary.json` records the source and estimation method.
All output values are validated before writing. Rebuild old derived profiles
when they used missing textures or inferred subsoil properties.

The standard global HWSD BIL lacks embedded CRS metadata. Supply
`--hwsd-crs EPSG:4326` only for a verified WGS84 latitude/longitude dataset;
this is documented for the original HWSD raster in
[Rossiter, Processing the HWSD in R, p. 3](https://www.css.cornell.edu/faculty/dgr2/_static/files/R_PDF/R_HWSD.pdf).
The converter records this explicit declaration and rejects a conflicting CRS.
