# S3: Soil Setup Skill

## Purpose

Create, configure, and validate a DSSAT soil profile within a .SOL file so that it accurately represents the physical, chemical, and hydraulic properties of the soil at the experimental site. This document specifies the exact format, parameter definitions, layer construction rules, and quality checks needed for a valid soil input.

## Prerequisites

- [ ] Soil texture, depth, and basic properties of the target site are known (from field measurements, soil survey, or pedotransfer estimation).
- [ ] A 10-character pedon code has been assigned or chosen.
- [ ] The .SOL file to which the profile will be added has been located (typically `SOIL.SOL` in the soil directory).
- [ ] The user understands the distinction between lower limit (SLLL), drained upper limit (SDUL), and saturation (SSAT).
- [ ] Layer depth boundaries have been decided based on horizon data or standard layering scheme.

## Inputs

| Parameter | Type | Units | Description | Example |
|-----------|------|-------|-------------|---------|
| Pedon code | 10-char string | -- | Unique soil profile identifier | `IBMZ910014` |
| Source institution | 10-char string | -- | Data source | `IBSNAT` |
| Soil texture class | 3-char string | -- | USDA texture abbreviation | `SIC` |
| Profile depth | Integer | cm | Total soil depth | `210` |
| Description | Free text | -- | Profile description | `DEFAULT - DEEP SILTY CLAY` |
| SALB | Float | 0-1 | Soil albedo | `0.11` |
| SLU1 | Float | mm | Stage 1 evaporation upper limit | `6.0` |
| SLDR | Float | 0-1 | Drainage rate fraction | `0.30` |
| SLRO | Float | -- | SCS runoff curve number | `85.0` |
| SLNF | Float | 0-1 | N mineralization factor | `1.00` |
| SLPF | Float | 0-1 | Photosynthesis/growth factor | `1.00` |
| Layer data | Table | Various | Per-layer soil properties | See procedure |

## Procedure

### Step 1: Understand the .SOL File Structure

A single .SOL file can contain MULTIPLE soil profiles. Each profile is delimited by a line starting with `*` followed by the 10-character pedon code. Profiles are read sequentially; the model searches for the profile matching ID_SOIL from the FileX.

**File-level structure**:
```
*SOILS: General DSSAT Soil Input File
! DSSAT v4.8; comments
!
! ... comment block ...
!
*IB00000001  IBSNAT      SIC     210 DEFAULT - DEEP SILTY CLAY
@SITE        COUNTRY          LAT     LONG SCS FAMILY
 ...
@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE
 ...
@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
 ...layer data rows...

*IB00000002  IBSNAT      SIC     150 DEFAULT - MEDIUM SILTY CLAY
...next profile...
```

**Rule**: Each profile starts with `*` on column 1. The parser reads everything between one `*` line and the next `*` line (or end of file) as a single profile.

### Step 2: Construct the Pedon Code

The 10-character pedon code (ID_SOIL) is the primary key that links the FileX to the soil profile.

**Convention**: `[SS][CC][NN][NNNN]`
- `SS` = 2-character source code (e.g., `IB` = IBSNAT, `US` = US, etc.)
- `CC` = 2-character country or crop code
- `NN` = 2 digits for soil category
- `NNNN` = 4-digit sequence number

**Examples**:
- `IB00000001` = IBSNAT generic profile #1
- `IBMZ910014` = IBSNAT, maize-related, profile from 1991, #14
- `UFGA000001` = University of Florida, Gainesville, #1

**Rules**:
1. Must be exactly 10 characters (padded with spaces if needed, but convention uses numbers/letters to fill).
2. Must be unique within the .SOL file.
3. Must match EXACTLY (character-for-character) what appears in the FileX ID_SOIL field.

### Step 3: Write the Profile Header Line

```
*IBMZ910014  IBSNAT      SIC     210 DEFAULT - DEEP SILTY CLAY
```

**Format** (fixed-width):

| Position | Content | Description |
|----------|---------|-------------|
| 1 | `*` | Profile delimiter marker |
| 2-11 | Pedon code (10 chars) | Unique identifier |
| 13-24 | Source (12 chars) | Institution/source |
| 25-30 | Texture class (5 chars) | USDA soil texture abbreviation |
| 31-37 | Depth (6 chars) | Profile depth in cm |
| 38+ | Description (free text) | Profile description |

**Valid USDA texture classes**: S, LS, SL, SCL, SC, SIC, SICL, SIL, SI, CL, L, C

### Step 4: Write the Site Information Lines

```
@SITE        COUNTRY          LAT     LONG SCS FAMILY
 Generic     Generic          -99      -99 Generic
```

**Fields**:
- SITE: Site name (up to 12 chars)
- COUNTRY: Country name (up to 12 chars)
- LAT: Latitude (decimal degrees, -99 if unknown)
- LONG: Longitude (decimal degrees, -99 if unknown)
- SCS FAMILY: Soil classification family (free text)

**Decision rule**: If site coordinates are unknown, use -99. This line is metadata and does not affect simulation. However, populating it aids future users.

### Step 5: Write the Surface Parameters Line

```
@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE
   -99  0.11   6.0  0.30  85.0  1.00  1.00 IB001 IB001 IB001
```

**Parameter definitions**:

| Parameter | Width | Units | Description | Range | Default |
|-----------|-------|-------|-------------|-------|---------|
| SCOM | 5 | -- | Soil color (code, -99 if unknown) | -99, BL, BR, etc. | -99 |
| SALB | 6 | 0-1 | Soil surface albedo (bare, dry) | 0.05-0.25 | Texture-dependent |
| SLU1 | 6 | mm | Stage 1 evaporation upper limit | 2.0-12.0 | 6.0 |
| SLDR | 6 | 0-1 | Drainage rate (fraction/day) | 0.05-0.80 | 0.30 |
| SLRO | 6 | -- | SCS curve number | 40-99 | Texture/slope-dependent |
| SLNF | 6 | 0-1 | Nitrogen mineralization factor | 0.5-1.5 | 1.00 |
| SLPF | 6 | 0-1 | Photosynthesis/growth factor | 0.5-1.0 | 1.00 |
| SMHB | 6 | code | pH in buffer method code | IB001, etc. | IB001 |
| SMPX | 6 | code | Extractable phosphorus method code | IB001, etc. | IB001 |
| SMKE | 6 | code | Exchangeable potassium method code | IB001, etc. | IB001 |

**Guidance for SALB**:
| Soil Color/Texture | SALB |
|---------------------|------|
| Dark clay soils | 0.09-0.11 |
| Medium-textured soils | 0.12-0.14 |
| Sandy soils | 0.15-0.20 |
| Light/calcareous soils | 0.20-0.25 |

**Guidance for SLDR**:
| Drainage Class | SLDR |
|----------------|------|
| Very poorly drained | 0.05-0.10 |
| Poorly drained | 0.10-0.20 |
| Moderately drained | 0.20-0.40 |
| Well drained | 0.40-0.60 |
| Excessively drained | 0.60-0.80 |

**Guidance for SLRO** (SCS Curve Number):
| Soil Hydrologic Group | SLRO Range |
|----------------------|------------|
| Group A (sand, loamy sand) | 40-60 |
| Group B (silt loam, loam) | 55-75 |
| Group C (sandy clay loam) | 70-85 |
| Group D (clay, silty clay) | 80-95 |

**Decision rule for SLPF**: Set SLPF = 1.00 unless you have evidence of a site-specific yield limitation not captured by other soil parameters (e.g., toxic levels of aluminum, unnamed nutrient deficiency). SLPF < 1.0 reduces potential photosynthesis and biomass. SLPF is sometimes used as a calibration factor during model evaluation; initial setup should use 1.00.

### Step 6: Design the Layer Structure

DSSAT soil profiles consist of discrete layers, each defined by its bottom depth (SLB in cm). Layer structure must follow these rules:

**Hard limits**:
1. **Maximum 20 layers** (NL=20 in the DSSAT code). More than 20 layers will be silently truncated -- layers beyond the 20th will be ignored without warning.
2. **Layer depths must be strictly monotonically increasing**: Each SLB must be greater than the previous.
3. **First layer top is always 0 cm** (the soil surface).

**Recommended layer structure**:

| Layer | Bottom Depth (SLB) | Thickness | Rationale |
|-------|-------------------|-----------|-----------|
| 1 | 5 cm | 5 cm | Thin surface layer for seed zone and evaporation |
| 2 | 15 cm | 10 cm | Root zone near surface |
| 3 | 30 cm | 15 cm | Mid-root zone |
| 4 | 45 cm | 15 cm | Transition zone |
| 5 | 60 cm | 15 cm | Main root zone |
| 6 | 90 cm | 30 cm | Deep root zone |
| 7 | 120 cm | 30 cm | Subsoil |
| 8 | 150 cm | 30 cm | Deep subsoil |
| 9 | 180 cm | 30 cm | Deep subsoil |
| 10 | 210 cm | 30 cm | Profile bottom |

**Decision rules for layer design**:
1. **Top layer must be <= 5 cm**: A top layer thicker than 5 cm causes numerical instability in the surface energy balance and evaporation calculations. If your soil survey reports a 0-20 cm horizon, split it into 0-5 and 5-15 (or 5-20) cm layers.
2. **Thinner layers near surface, thicker at depth**: The surface layers control evaporation, germination, and early root growth. Use 5 cm for layer 1, 10 cm for layers 2-3, then progressively thicker layers (15, 30, 45 cm).
3. **Match layer boundaries to soil horizons if possible**: If your soil survey reports an A horizon at 0-25 cm and a B horizon at 25-60 cm, set layer boundaries at 25 and 60 cm.
4. **Shallow soils**: If the total soil depth is < 20 cm, DSSAT may encounter division-by-zero errors in some calculations. The minimum recommended total soil depth is 20 cm. If the actual soil is shallower, set the last layer to at least 20 cm and use very low root growth factor (SRGF) for the deeper portion.

### Step 7: Write the Layer Data Header and Rows

```
@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC
     5   -99 0.228 0.385 0.481 1.000   -99  1.30  1.75  50.0  45.0   0.0 0.170   6.5   -99   -99   -99
    15   -99 0.228 0.385 0.481 1.000   -99  1.30  1.75  50.0  45.0   0.0 0.170   6.5   -99   -99   -99
    30   -99 0.249 0.406 0.482 0.638   -99  1.30  1.60  50.0  45.0   0.0 0.170   6.5   -99   -99   -99
```

**Layer parameter definitions**:

| Parameter | Width | Units | Description | Required | Typical Range |
|-----------|-------|-------|-------------|----------|---------------|
| SLB | 6 | cm | Layer bottom depth | YES | 5-300 |
| SLMH | 6 | code | Master horizon (A, B, C, etc.) | No (-99) | -99, A, AP, B, etc. |
| SLLL | 6 | cm3/cm3 | Lower limit of plant-available water (wilting point) | YES | 0.02-0.35 |
| SDUL | 6 | cm3/cm3 | Drained upper limit (field capacity) | YES | 0.10-0.50 |
| SSAT | 6 | cm3/cm3 | Saturated water content | YES | 0.30-0.60 |
| SRGF | 6 | 0-1 | Root growth factor (relative root density) | YES | 0.0-1.0 |
| SSKS | 6 | cm/hr | Saturated hydraulic conductivity. Write 3 decimals below 10 (` 0.002`) and 2 decimals from 10 up (` 12.35`). DSSAT reads 0.00 and -99 alike as "no drainage limit" | No (-99) | 0.001-63.0 |
| SBDM | 6 | g/cm3 | Bulk density (moist, DSSAT SOIL.CDE). DSSAT computes its pore space from it: 1 - SBDM/2.65 | YES | 0.90-1.80 |
| SLOC | 6 | % | Organic carbon (% by weight) | YES | 0.01-10.0 |
| SLCL | 6 | % | Clay content (% by weight) | Recommended | 0-100 |
| SLSI | 6 | % | Silt content (% by weight) | Recommended | 0-100 |
| SLCF | 6 | % | Coarse fragment content (% by volume) | No | 0-80 |
| SLNI | 6 | % | Total nitrogen (% by weight) | Recommended | 0.001-1.0 |
| SLHW | 6 | -- | Soil pH in water | Recommended | 3.5-9.5 |
| SLHB | 6 | -- | Soil pH in buffer | No (-99) | -99 |
| SCEC | 6 | cmol/kg | Cation exchange capacity | No (-99) | 1-60 |
| SADC | 6 | -- | Additional category/code | No (-99) | -99 |

**How DSSAT reads the layer table**: by header position, not by spaces (`READS.for` PARSE_HEADERS, `IPSOIL_Inp.for`).
Under each right-aligned 6-wide header such as `  SSKS`, DSSAT reads only the last 5 characters of the 6-wide field.
So the first character of every field must be a blank. A value that fills all 6 characters loses its first digit:
`12.345` under SSKS is read as 2.345, and `1.552 ` under SLOC (a field written one column early) is read as 0.552.
`validate_soil_profile.py` reads every number both ways and reports any difference as an error.

### Step 8: Enforce Water Limit Ordering

For every layer, the following constraint must hold:

```
SLLL < SDUL < SSAT
```

**Minimum gap enforcement**: this KI requires these gaps (DSSAT itself only repairs a layer where two limits are
equal: SAT = DUL + 0.01, LL = DUL - 0.01, `IPSOIL_Inp.for`):
- `SDUL > SLLL` (the KI converters keep at least 0.005 between them; the validator checks SLLL < SDUL)
- `SSAT - SDUL >= 0.01`
- `(1 - SBDM/2.65) - SDUL >= 0.01`: the gap DSSAT itself uses. DSSAT computes the pore space from the bulk
  density (`SOILDYN.for`: `POROS = 1 - BD/2.65`; where that is below DUL it takes SAT instead), and its soil N code
  divides by pore space minus DUL. In Route B maize runs, every cell that stopped in `daycent_diffusivity` (224 cells)
  had a layer with this pore space below SDUL; no cell without that state stopped there.

0.01 is the floor every soil file must meet (`validate_soil_profile.py` checks it). The KI's own converters write a
larger gap, `min_gap` (default 0.05, tested on maize; Step 10b).

Check these on the **printed** numbers (3 decimals for SLLL, SDUL, SSAT; 2 for SBDM), because those are what DSSAT
reads. Rounding SBDM can move the pore space by up to 0.002.

**Validation procedure for each layer**:
1. Check: `SLLL >= 0.0` (lower limit cannot be negative)
2. Check: `SDUL > SLLL` (if equal, add 0.01 to SDUL)
3. Check: `SSAT > SDUL` (if equal, add 0.01 to SSAT)
4. Check: `SSAT <= 1.0 - (SBDM / 2.65)`, compared at SSAT's 3 printed decimals (SSAT cannot exceed the pore space;
   particle density 2.65 g/cm3). SSAT may be lower: in DSSAT's own site soils SSAT is a median 0.85 to 0.95 of it.
5. Check: `(1 - SBDM/2.65) - SDUL >= 0.01`. If it fails, lower SBDM or SDUL; never fix it by raising SSAT alone,
   because DSSAT's pore space comes from SBDM, not from SSAT.

**Failure mode**: If water limits are inverted (e.g., SLLL > SDUL), DSSAT will compute negative available water, causing division-by-zero or negative soil water content, which crashes the simulation.

### Step 9: Compute Root Growth Factor (SRGF)

SRGF controls the relative root density distribution. It ranges from 0 (no roots) to 1 (maximum root presence).

**Default calculation** (from DSSAT documentation):
```
For SLB <= 15 cm: SRGF = 1.000
For SLB > 15 cm:  SRGF = 1.0 * EXP(-0.02 * layer_center)
                   where layer_center = (SLB_previous + SLB_current) / 2
```

**Example**:
| SLB (cm) | Layer Center (cm) | SRGF |
|----------|-------------------|------|
| 5 | 2.5 | 1.000 |
| 15 | 10.0 | 1.000 |
| 30 | 22.5 | 0.638 |
| 45 | 37.5 | 0.472 |
| 60 | 52.5 | 0.350 |
| 90 | 75.0 | 0.223 |
| 120 | 105.0 | 0.122 |
| 150 | 135.0 | 0.067 |
| 180 | 165.0 | 0.037 |
| 210 | 195.0 | 0.020 |

**Decision rule**: If you have measured root distribution data, use those values directly. If not, use the exponential decay function above. For shallow-rooted crops (e.g., rice), you may want steeper decay (larger coefficient). For deep-rooted crops (e.g., sugarcane), use shallower decay.

### Step 10: Use Pedotransfer Functions When Hydraulic Data Is Unavailable

If measured SLLL, SDUL, and SSAT are not available, estimate them from texture data using pedotransfer functions.

**Saxton et al. (1986) method** (used by DSSAT's built-in estimation):

From clay (SLCL) and sand (100 - SLCL - SLSI) percentages:
```
SLLL = f(clay%, sand%)  -- wilting point at -1500 kPa
SDUL = f(clay%, sand%)  -- field capacity at -33 kPa
SSAT = f(porosity)      -- based on bulk density
```

**Reference ranges by texture class** (from SOIL.SOL header comments):

| Texture | SLLL Range | SDUL Range | SSAT Range |
|---------|-----------|-----------|-----------|
| C (Clay) | 0.220-0.346 | 0.330-0.467 | 0.413-0.488 |
| CL (Clay Loam) | 0.156-0.218 | 0.282-0.374 | 0.417-0.512 |
| L (Loam) | 0.083-0.156 | 0.222-0.312 | 0.415-0.501 |
| LS (Loamy Sand) | 0.059-0.110 | 0.137-0.185 | 0.355-0.416 |
| S (Sand) | 0.055-0.085 | 0.123-0.158 | 0.374-0.400 |
| SC (Sandy Clay) | 0.195-0.294 | 0.276-0.389 | 0.376-0.409 |
| SCL (Sandy Clay Loam) | 0.132-0.191 | 0.213-0.304 | 0.360-0.418 |
| SI (Silt) | 0.096-0.099 | 0.299-0.307 | 0.442-0.488 |
| SIC (Silty Clay) | 0.224-0.326 | 0.379-0.456 | 0.455-0.489 |
| SICL (Silty Clay Loam) | 0.155-0.219 | 0.324-0.392 | 0.448-0.511 |
| SIL (Silt Loam) | 0.082-0.152 | 0.240-0.333 | 0.439-0.547 |
| SL (Sandy Loam) | 0.066-0.133 | 0.164-0.243 | 0.348-0.499 |

**Bulk density estimation** (if not measured):
```
SBDM = 100 / (SOM% / 0.224 + (100 - SOM%) / mineral_BD)
where SOM% = SLOC * 1.724 (van Bemmelen factor)
and mineral_BD depends on texture (typically 1.4-1.7 g/cm3)
```

### Step 10a: Missing soil data in this KI's converters (no defaults)

Both converters stop with a clear error when a needed value is missing; they never fill a gap.
- `convert_hwsd_to_sol.py`: texture, organic carbon and pH (topsoil `T_*` and subsoil `S_*`) must be real
  numbers. Empty cells and the HWSD missing-data codes -99, -999 and -9999 count as missing, also when
  `write_sol()` is called directly. Bulk density may be missing (then the Saxton & Rawls normal density is used,
  as the method does); a missing-data code for it is treated as missing, never as a density.
- `convert_soilgrids_to_sol.py`: sand, silt, clay, soc, bdod and phh2o must be present at all six depths
  (0-5 ... 100-200 cm). A gap raises `ValueError` and nothing is written (CLI: exit code 1). There is no default
  texture/carbon/density/pH and no carbon "depth decay" from the topsoil any more. Coarse fragments (cfvo) are not
  in the current SoilGrids CSVs, so SLCF is written as -99 (DSSAT's "missing"; `SOILDYN.for` then uses 0 and
  writes a warning). `--legacy_gap_rule` still writes the old 0.0 for byte-identical old files.

### Step 10b: The minimum gap in this KI's Saxton & Rawls converters

`tools/s3_soil_setup/convert_hwsd_to_sol.py` (`saxton_rawls`, also imported by Route B's `soil01.py`) and
`tools/s3_soil_setup/convert_soilgrids_to_sol.py` (`saxton_rawls_2006`) use Saxton & Rawls (2006). Its density step
(Eqs. 7-10) takes saturation from the mapped bulk density (SSAT = 1 - BD/2.65, Eq. 8) but moves field capacity by
only a fifth as much (Eq. 9). In dense clay subsoil the gap SSAT - SDUL (Eq. 10) then becomes very small, or below
zero.

**The rule (the paper's own).** Saxton & Rawls 2006, p. 1574: *"A large adjustment of density could cause Eq. [10]
to become negative, thus a minimum difference of 0.5%v was set to limit the DF value in these cases."* So the paper
lowers the density used (the density factor DF) until the gap reaches the minimum. The converters do this:

1. Work out the layer at the input density (mapped, or the texture's normal density when none is given).
2. If its printed numbers break a rule of Step 8 with the minimum gap `min_gap` (default **0.05**), lower the
   density used to the largest 2-decimal value at which they all hold. This is the density at which Eq. 10 equals
   `min_gap`, rounded down to 2 decimals, give or take one step of 0.01 for rounding.
3. Print that density as SBDM. SSAT = 1 - SBDM/2.65 (Eq. 8), at most 0.80 (an old bound; it acts only below SBDM
   0.53, 3 of our 1.2 million layers). SDUL comes from Eq. 9 at that density, so it rises a little.
4. SSKS comes from the final gap (Eq. 16), worked out from the **unrounded** SLLL, SDUL and SSAT at the density used,
   not from the printed 3-decimal numbers. Worked out again from the printed numbers it can differ by up to 0.006
   cm/h (a check on 20,000 real layers: at min gap 0.05 it differed in 7,418 of the 12,532 changed layers, by at most
   0.006; at 0.02 by 0.001 in 855 of 6,023 changed layers and by 0.006 in 1). SSKS is printed with 3 decimals below
   10 cm/h and 2 decimals from 10 up (`format_ssks`).
5. Layers that already meet the rules are not changed.

| setting | default | why |
|---|---|---|
| `min_gap` (`--min_gap`) | **0.05** | The paper's 0.005 only stops Eq. 10 going below zero; it is not a crop rule. DSSAT maize starts cutting root uptake when a layer is within PORM = 0.05 of saturation (`MZCER048.SPE`, `ROOTWU.for`). In DSSAT CERES-Maize runs on Route B cells (below) 0.05 removed the soil faults with no new crash and no new crop failure; 0.02 removed the crashes too but did new damage. **Tested on maize only** (see "min_gap for other crops"). 0.02, the earlier provisional default, is kept as a recorded alternative (arm A1 under "Other choices"). The tool takes 0.01 to 0.2 in whole thousandths and refuses anything else. |
| `max_bd_drop` | 0.30 g/cm3 | A cap on how far the density used may fall. The earlier count without a cap needed drops of up to 1.04 (margin 0.05) and 0.94 (0.02). 0.30 is about the largest measured gap between oven-dry and 33 kPa bulk density in US clay classes (+0.26 for clay of 50 % or more, WoSIS). It is a judgment. The runs used it (at 0.05 the cap was reached in 1,592 rainfed and 156 irrigated layers of the run cells) but did not try another cap. |
| `min_bd_used` | 1.00 g/cm3 | The paper's equations were fitted without samples below 1.0 or above 1.8 g/cm3 (p. 1570). An input already below 1.00 is not lowered (beyond rounding it to 2 decimals). |
| `on_cap` | `lower_sdul` | When the cap stops the drop: keep the capped density and lower SDUL to the largest printed value that meets the rules. The layer is flagged `cap_sdul` with the cut. If SDUL would then come within 0.005 of SLLL, the tool refuses (ValueError). `raise` refuses every capped layer instead. |

What each call returns besides SLLL, SDUL, SSAT, SSKS and SBDM: `gap_rule` (`unchanged`, `paper_df`, `print_fix`
when only rounding broke a rule, `cap_sdul`), `bd_input`, `bd_source` (`mapped` or `normal`), `bd_drop`, `sdul_cut`,
`min_gap`. The writers check the printed numbers before writing and refuse a layer that breaks a rule.

`rule="legacy"` (`--legacy_gap_rule`) reproduces the old files byte for byte. Those files kept the density, pinned the
gap at 0.005 by raising SSAT (HWSD copy) or lowering SDUL (SoilGrids copy), and printed SSKS with 2 decimals. Use it
only to reproduce old work; its files fail this KI's validator wherever the pin acted.

**Writers outside this KI.** A writer that prints the layer table itself (Route B's `soil01.py`) must print the SBDM
the function returns and print SSKS with `format_ssks()` from the same file, in the same step as this rule. Never
print SSKS with 3 decimals on soils made the old way (arm E1 below), and never keep the 2-decimal print with this
rule (small SSKS values would print 0.00, read by DSSAT as "no drainage limit").

**How much it changes** (all 1,222,524 Route B maize soil layers, SoilGrids v2 at 0.1 degree; counts made with the
tools, no DSSAT run):

| | min gap 0.05 (default) | min gap 0.02 (recorded alternative) |
|---|---|---|
| layers changed | 83,888 (6.9 %) in 26,030 cells | 34,460 (2.8 %) in 12,535 cells |
| of which: density lowered (`paper_df`) / rounding only (`print_fix`) / cap reached (`cap_sdul`) | 81,678 / 370 / 1,840 | 33,840 / 244 / 376 |
| density drop in changed layers: median / 90th percentile / largest | 0.08 / 0.22 / 0.30 | 0.06 / 0.17 / 0.30 |
| SDUL change where the density was lowered (median) | +0.006 | +0.005 |
| cap reached: layers (cells); of these outside the paper's data (organic matter above 8 %, BD above 1.8 or clay 60 % or more) | 1,840 (871); 682 | 376 (159); 301 |
| layers with SSKS below 0.005 cm/h (printed 0.001 to 0.004, a drainage limit of 0.24 to 1 mm a day) | 0 | 40,503 |
| layers with pore space below SDUL / SSAT above pore space: old tool, then new | 15,837 / 19,232, then 0 / 0 | same |

The earlier count without the cap and without rounding (`soil_gap_research_20261003/a_formula`) gave 83,817 and
34,389 layers, median drops 0.08 and 0.06, largest drops 1.04 and 0.94, and 102 layers below BD 1.0 at 0.05.

**What the DSSAT runs showed** (2026-10-03, `KISSPATH_HOME/soil_fix_20261003/runs/README.md`). DSSAT CERES-Maize in
Route B's setup: 24,073 rainfed cells (all US cells with timing values, India cells with a layer gap under 0.05, the
288 test cells, the cells that stopped in R0) and 3,257 irrigated cells (all cells with a layer gap under 0.05 and the
cells that stopped in R0); 34 warm-up years, seasons 2010-2024 scored. Each value is the unchanged run R0 → the
arm, on the same cells. rf = rainfed, ir = irrigated, thin = a layer gap under 0.05.

| | DayCent stops (cells) | new stops | US rf failed seasons % | US rf sowing day | US rf runoff mm | US rf yield t/ha | India ir thin: irrigation mm | Corn Belt vs NASS: swing ratio / R / level | India vs FAO: swing ratio / R / level |
|---|---|---|---|---|---|---|---|---|---|
| min gap 0.05 (arm A2, the default) | 224 → 0 | 0 | 0.32 → 0.24 | 130.0 → 129.7 | 23 → 15 | 8.44 → 9.07 | 131 → 105 | 2.42 → 2.29 / 0.83 → 0.82 / 1.00 → 1.06 | 2.22 → 1.78 / 0.53 → 0.40 / 1.12 → 1.31 |
| min gap 0.02 (arm A1) | 224 → 0 | 0 | 0.32 → 0.75 | 130.0 → 135.7 | 23 → 57 | 8.44 → 8.67 | 131 → 372 | 2.42 → 2.21 / 0.83 → 0.84 / 1.00 → 1.02 | 2.22 → 2.15 / 0.53 → 0.54 / 1.12 → 1.16 |

- At 0.05 no layer gap under 0.05 is left, so a dense layer at field capacity no longer counts as too wet for maize
  roots (US rainfed water stress at silking 0.186 → 0.132), and the SSKS of the changed layers (about 0.04 cm/h,
  9 mm a day) is a real but open drainage limit.
- At 0.02 the SSKS of the changed layers is about 0.003 cm/h (0.7 mm a day) and nearly closes a dense layer. In the US
  rainfed cells A1 changed: runoff 45 → 129 mm a season, sowing day 125.8 → 140.3, failed seasons 0.28 → 1.27 %,
  almost all "crop died due to cold stress" (DSSAT status 32). Ohio: 24 → 475 failed seasons, R with NASS 0.64 → -0.01.
  This chain was read from season numbers, not traced day by day inside DSSAT.
- **0.05 is a model change, not a neutral fix.** US rainfed yield +7.5 %; Corn Belt level 1.00 → 1.06 of NASS; India
  1.12 → 1.31 of FAO and India R 0.53 → 0.40; Ohio R with NASS 0.64 → 0.45; N leached in India thin rainfed cells
  52 → 71 kg/ha. The printed density in the changed layers falls by a median 0.10 g/cm3 in the run cells, so soil
  mass, carbon and nitrogen per layer change there. Anything fitted on soils made the old way (timing values,
  density, calibration) needs a look before it is used with soils made this way.
- The 110 IMMOBLIMIT_C stops of R0 stay at both gaps; they are a DSSAT build fault, not the soil.

**Not known yet:** whether 0.05 suits crops other than maize (next part) and other setups (deeper roots, a timing
redo); another cap than 0.30 (the runs used only 0.30); places the runs did not cover (at 0.05 the rule also changes
9,103 Route B rainfed cells outside the run list, for example in Romania, Burkina Faso, Mexico, Argentina and Canada).
The paper was fitted on topsoil (A horizon) samples only, so all subsoil layers are outside its data. SoilGrids 2.0
bulk density is less accurate with depth (model efficiency 0.78 at 0-5 cm, 0.59 at 100-200 cm; Poggio et al. 2021).

#### min_gap for other crops

0.05 was tested with CERES-Maize only (maize PORM 0.05). DSSAT's pore-space limit (the air-filled room a layer must
keep before root water uptake is cut) differs by crop. This is the value in every crop species file installed here
(`KISSPATH_HOME/DSSAT/Data/Genotype`), read the way each model reads it: CROPGRO `IPPLNT.for` line 297 reads PORMIN
from columns 13-18 of the line `RTNO3,RTNH4,PORMIN,RTEXF` (the first two numbers there, often 0.006, are nitrate and
ammonium uptake values, not the pore limit); CERES-Maize `MZ_GROSUB.for` line 630 reads PORM after `*ROOT`; CERES-Rice
`RI_Ipcrop.for` line 104; SUBSTOR `PT_SUBSTOR.for` line 411; ALOHA `Aloha_mod.f90` line 122; CERES-Wheat
`CER_Init.for` line 715 and CROPSIM `CRP_SeasInit.for` line 905 read RWUPM by name (the CROPSIM files say "RWUPM =
PORMIN in CSM modules").

| limit in the file | crops (species file) |
|---|---|
| 0.05 | maize (MZCER, MZIXM), sweet corn (SWCER), sorghum (SGCER), pearl millet (MLCER), sugar beet (BSCER), sugarcane CANEGRO (SCCAN), wheat NWheat (WHAPS), teff NWheat (TFAPS) |
| 0.04 | peanut (PNGRO), Bambara groundnut (BGGRO) |
| 0.02 | soybean, dry bean, cowpea, faba bean, lentil, pigeon pea, green bean, velvet bean, guar (all CROPGRO); amaranth, carinata, canola, chia, cotton, hemp, quinoa, safflower, sunflower, cabbage, tomato, bell pepper, strawberry (CROPGRO); alfalfa, bahia grass, bermudagrass, brachiaria, guinea grass (CROPGRO and forage files); sunflower OILCROP (SUOIL); potato (PTSUB); pineapple (PIALO); wheat, barley and rye in CERES-Wheat and CROPSIM (WHCER, WHCRP, BACER, BACRP, RYCER: RWUPM) |
| 0.001 | chickpea (CHGRO) |
| 0.00 | rice (RICER), teff CERES (TFCER), cassava (CSCAS, CSYCA: RWUPM) |
| not in the file | sugarcane CASUPRO (SCCSP) and SAMUCA (SCSAM): not checked where the model takes it; taro and tanier (TRARO, TNARO): the code sets 0.02 (`AROIDS/TR_Ipcrop.for` line 95) |

No installed crop file has a limit above 0.05.

**How to set it.** In Python: `saxton_rawls(sand, clay, oc=..., bd=..., min_gap=0.04)`,
`saxton_rawls_2006(sand, clay, oc_pct, bd, min_gap=0.04)`, and the writers `write_sol(..., min_gap=0.04)` and
`write_soilgrids_sol(..., min_gap=0.04)`. On the command line: `--min_gap 0.04`. The value must be 0.01 to 0.2 in
whole thousandths. The first line of every written file names the gap used. Route B's `soil01.py` calls
`saxton_rawls` without `min_gap`, so it always gets the default; another value there needs a code change in soil01.

**What to choose.** What is known: in maize, 0.05 worked and 0.02 did harm, and the harm followed the very small SSKS
that a 0.02 gap gives (arms A1, E1 and E2 below). SSKS does not depend on the crop, so a gap below 0.05 may do the
same harm with other crops; that was not tested. Keeping 0.05 for a crop with a smaller limit leaves that crop more
air-filled room than its file asks for; that was not tested either. For any crop other than maize, run the crop at
0.05 and at the value you want on your own cells and compare crashes, failed seasons, sowing day, runoff and drainage
before you use it.

#### Other choices and their evidence

The tested choices (arms A1, B1, B2, C, D, E1, E2) were each run next to the default (arm A2, min gap 0.05) in the
same DSSAT CERES-Maize setup (`KISSPATH_HOME/soil_fix_20261003/runs/README.md`; only the soil changed). Choice (e) and
the paper's DF range are recorded but were not run. Each value is R0 → the arm on that arm's own
like-for-like cells (a cell that stopped in either run, or that the rule could not build, is left out of both), so the
R0 numbers differ a little from arm to arm; stop counts are on the arm's whole cell list. Sources of the choices:
`KISSPATH_HOME/soil_gap_research_20261003/ANSWER.md` part 4 and `VERIFY_NOTES.txt` (its corrections are applied here).

| arm | DayCent stops (cells) | new stops | cells not built | US rf failed seasons % | US rf runoff mm | US rf N leached kg/ha | US rf stress at silking | US rf yield t/ha | Corn Belt vs NASS: swing ratio / R / level | India vs FAO: swing ratio / R / level |
|---|---|---|---|---|---|---|---|---|---|---|
| A2 paper 0.05 (default) | 224 → 0 | 0 | 0 | 0.32 → 0.24 | 23 → 15 | 15.2 → 14.6 | 0.186 → 0.132 | 8.44 → 9.07 | 2.42 → 2.29 / 0.83 → 0.82 / 1.00 → 1.06 | 2.22 → 1.78 / 0.53 → 0.40 / 1.12 → 1.31 |
| A1 paper 0.02 | 224 → 0 | 0 | 0 | 0.32 → 0.75 | 23 → 57 | 15.2 → 13.5 | 0.186 → 0.165 | 8.44 → 8.67 | 2.42 → 2.21 / 0.83 → 0.84 / 1.00 → 1.02 | 2.22 → 2.15 / 0.53 → 0.54 / 1.12 → 1.16 |
| B1 lower SDUL 0.02 | 204 → 0 | 0 | 136 | 0.29 → 0.97 | 23 → 61 | 15.2 → 13.7 | 0.185 → 0.181 | 8.46 → 8.45 | 2.42 → 2.22 / 0.83 → 0.83 / 1.00 → 1.00 | 2.22 → 2.16 / 0.53 → 0.54 / 1.12 → 1.13 |
| B2 lower SDUL 0.05 | 176 → 0 | 0 | 409 | 0.27 → 0.30 | 23 → 15 | 15.2 → 16.9 | 0.183 → 0.180 | 8.49 → 8.47 | 2.42 → 2.41 / 0.83 → 0.84 / 1.00 → 1.00 | 2.22 → 1.91 / 0.53 → 0.66 / 1.13 → 1.23 |
| C curve PTF | 186 → 0 | 0 | 140 | 0.30 → 0.26 | 23 → 14 | 15.2 → 13.4 | 0.185 → 0.096 | 8.46 → 9.56 | 2.42 → 1.95 / 0.83 → 0.81 / 1.00 → 1.11 | 2.22 → 1.89 / 0.53 → 0.25 / 1.12 → 1.30 |
| D eGHR water (hybrid) | 224 → 18 | 17 | 1 | 0.32 → 0.24 | 23 → 1 | 15.2 → 17.3 | 0.186 → 0.108 | 8.44 → 9.44 | 2.42 → 2.12 / 0.83 → 0.81 / 1.00 → 1.10 | 2.22 → 1.69 / 0.53 → 0.40 / 1.12 → 1.33 |
| E1 SSKS 3 decimals only | 224 → 264 | 136 | 0 | 0.32 → 1.52 | 23 → 77 | 15.2 → 11.8 | 0.186 → 0.195 | 8.45 → 8.22 | 2.42 → 2.02 / 0.83 → 0.81 / 1.00 → 0.97 | 2.22 → 2.07 / 0.53 → 0.53 / 1.12 → 1.11 |
| E2 paper 0.02 + SSKS -99 | 224 → 0 | 0 | 0 | 0.32 → 0.24 | 23 → 1 | 15.2 → 16.3 | 0.186 → 0.163 | 8.44 → 8.71 | 2.42 → 2.41 / 0.83 → 0.84 / 1.00 → 1.02 | 2.22 → 2.33 / 0.53 → 0.62 / 1.12 → 1.21 |

"Stress at silking" is DSSAT's own stage mean of water stress around silking (OVERVIEW.OUT, 1 - the mean daily
factor). "Cells not built" are cells where the rule could not make a soil (counted once per cell). In every arm the
110 IMMOBLIMIT_C stops of R0 stay, except where C's and D's topsoil changes them (110 → 94 in C, 110 → 31 in D).

**A1: the paper's way at min gap 0.02** (the earlier provisional default).
- What it is: the same rule and code as the default, with `min_gap=0.02`. 0.02 was the smallest margin that kept
  DSSAT's own gap at 0.01 or more on the 288 Route B test cells. Paper: Saxton & Rawls 2006, p. 1574.
- Numbers: the table; it changes 34,460 layers (all-layer count above). In the US rainfed cells it changed: failed
  seasons 0.28 → 1.27 %, runoff 45 → 129 mm, sowing day 125.8 → 140.3. Ohio 24 → 475 failed seasons, R with NASS
  0.64 → -0.01. India irrigated thin cells: irrigation 131 → 372 mm a season.
- Why not the default: the 3-decimal SSKS of a 0.02 gap (median 0.003 cm/h in the changed layers) nearly closes a
  dense layer, and later sowing, autumn cold kills, runoff and wasted irrigation follow. A 0.02 gap with a lower
  bound on SSKS was not tested.

**B1 and B2: lower SDUL, keep the mapped density** (way A: SDUL = pore space - margin; margin 0.02 / 0.05).
- What it is: this KI's tool with `max_bd_drop=0.0`; every layer that breaks a rule keeps its density (to its
  2-decimal floor), SDUL is lowered (flag `cap_sdul`), and where the old tool had raised SSAT above the pore space,
  SSAT comes back down to it. Over all real layers it refuses 344 layers (144 cells) at 0.02 and 1,056 layers
  (456 cells) at 0.05, where SDUL would come within 0.005 of SLLL. Before the runs (d_verify part 2.6): rainfed
  cells changed at margin 0.02 / 0.05: 11,239 (8.9 % of area) / 23,069 (17.8 %); water store to 2 m in those cells
  falls by 35 / 49 mm (worst cell 173 / 197 mm).
- Papers and data: no published soil set lowers SDUL this way after the Saxton & Rawls density step. For: DSSAT's
  dense-clay site soils have SDUL 0.31 to 0.33 and WISE 0.31 (ours 0.355). Against: measured lab water at 33 kPa in
  10,765 US dense-clay subsoil layers (WoSIS) is 0.428, above our 0.367. The "Mink style" variant has no published
  DSSAT use: its code sits in an unused ORYZA converter and its density branch never runs.
- Numbers: the table. Plant water to 2 m falls (US rainfed 268 → 258 mm in B1, 238 mm in B2; India rainfed thin
  cells 233 → 208 / 169 mm). B2 gives the best India match with FAO (R 0.53 → 0.66), but its failed seasons rise a
  little (US rainfed 0.27 → 0.30 %, India rainfed thin cells 0.46 → 0.52 %).
- Why not the default: B1 does the same SSKS damage as A1 with no yield gain. B2 cannot build 409 cells, takes plant
  water away, hardly moves the water stress at silking (0.183 → 0.180; part of that number may be water shortage,
  since B2 removes water) or the Corn Belt swing (2.41), and raises N leaching (15.2 → 16.9 kg/ha).

**C: a curve PTF with density as an input** (EU-PTF, Tóth et al. 2015, EJSS 66:226, as printed for HiHydroSoil v2.0,
Simons et al. 2020, FutureWater report; Rosetta 3 was not opened).
- What it is: the van Genuchten curve of the EU-PTF with the mapped density: SDUL = water at 330 cm suction, SLLL =
  water at 15,000 cm, SSAT = theta_s capped at the pore space of the printed SBDM; SSKS = Eq. 16 on these values.
  Code: `soil_gap_research_20261003/a_formula/code/eu_ptf_on_our_layers.py`. Global maps use this route (HiHydroSoil
  v2.0 on SoilGrids 2.0, EU-SoilHydroGrids); the DSSAT soil sets we read do not.
- Numbers: the table; the largest fall of water stress at silking (0.185 → 0.096) and of the Corn Belt swing
  (2.42 → 1.95; over-reaction state-years 101 → 82); plant water to 2 m up (US 268 → 307 mm). On the 10,765 measured
  US dense-clay subsoil layers it gives 0.307 where lab water is 0.428 and our tool 0.367. At pF 2 (which HiHydroSoil
  calls field capacity) the gap in the densest clay is about 0.011. Over all our layers its field capacity (330 cm)
  has a median of 0.292 (ours 0.337); in the densest clay (clay 31 % or more, BD 1.65-1.80) the gap is 0.049 with
  SSAT capped, 51 % of those layers under 0.05 and 0.13 % under 0.01; without the cap, saturation is above the pore
  space in 69 % of our thin layers. Fitted on European soils; India not verified.
- Why not the default: every layer of every cell changes, so anything fitted on today's soils needs redoing; 140 cells
  cannot be built (field capacity at or within 0.01 of the pore space); the equations are European; the Corn Belt
  level goes to 1.11 of NASS; India gets worse against FAO (R 0.53 → 0.25) and N leaching in India thin cells rises
  (52 → 82 kg/ha).

**D: a published DSSAT soil set as a benchmark** (eGHR; GHR = Han, Ines & Koo 2019, EMS 119:70).
- What it is: a hybrid. The published eGHR profile's SLLL, SDUL, SSAT, SSKS (2 decimals, as published), SBDM, clay
  and silt at the same six depths; our root factor, carbon, SLNI, pH and profile constants. Profile per cell: Pythia's
  raster `eGHR_soils_raster.tif` at the cell centre (`soil_gap_research_20261003/c_compare/code/c02_pick.py`). eGHR
  is the copy used by DSSAT-Pythia (same water values as GHR, other organic carbon, one profile per 0.5 degree block);
  whether GGCMI phase 3 used it is not settled (ISIMIP lists its own HWSD soils for DSSAT-Pythia). Older data:
  SoilGrids 2014, 1 km, shown at 5 arc-min. GHR applies Saxton & Rawls at normal density and only prints the mapped
  density. The GHR set itself has pore space below SDUL on 1.3 % of our rainfed area (ours 4.0 %) and 2.7 % of the
  irrigated area (ours 1.9 %); the 9.08 % sometimes quoted is GHR's rule run on our SoilGrids v2 inputs, not the set.
- Numbers: the table; runoff almost disappears (US rainfed 23 → 1 mm). eGHR leaves the pore space of its own density
  below SDUL in 604 US rainfed arm cells (R0: 3,974), and keeps SSAT above the pore space of its own density in 72,805
  of 162,180 arm-cell layers.
- Why not the default: 18 cells still stop, 17 of them new; it is a hybrid, not a pure eGHR run; it keeps the
  "pore space below SDUL" state the rule removes. Use it as a benchmark arm with a crash count, not as the base.

**E1: SSKS with 3 decimals only, gaps unchanged** (old soils, new print).
- What it is: the old values (`rule="legacy"`) with SSKS printed by `format_ssks()`. Before, 12,921 rainfed cells
  (10.2 % of area) had a layer printed 0.00 = no limit; this turns it into 0.24 to 1 mm a day.
- Papers: none; it isolates the print (DSSAT `READS.for` reads the field by position, `SATFLO.for` uses SSKS above 0).
- Numbers: the table; worse on the fault and damage checks: 136 new stops (irrigated 52 → 99 cells), sowing 8 days
  later, Ohio R with NASS 0.64 → -0.28. A few numbers move the other way (India's stress and N leaching fall).
- Why not the default: it adds damage. The 3-decimal print must never come alone.

**E2: the paper rule at 0.02 with SSKS -99** (no drainage limit in any layer).
- What it is: A1's soils with SSKS written -99 in every layer. Texture-based Ksat reads low (PTF-based global maps
  under-predict Ksat 3.3 to 4.9 times in topsoil; Gupta et al. 2021, JAMES, doi:10.1029/2020MS002242), and 67 % of
  the SOIL.SOL site layers carry no SSKS. In our runs DSSAT uses SSKS to cap drainage, and only when it is above 0
  (`SATFLO.for`); it also enters tillage and water-table code, which our runs do not use.
- Numbers: the table; no stop, no new failures, sowing unchanged; India against FAO R 0.53 → 0.62, level 1.21.
- Why not the default: with no limit anywhere, runoff almost disappears (US rainfed 23 → 1 mm; US irrigated thin
  cells 91 → 1 mm), and drainage and N leaching rise (US 85 → 99 mm and 15.2 → 16.3 kg/ha; India thin rainfed cells
  202 → 412 mm and 52 → 81 kg/ha). It also removes the limit in layers the rule did not touch, so it is not a pure
  "density step only" arm.

**(e) Convert oven-dry to wet bulk density by clay** (recorded, NOT run).
- What it is: SoilGrids gives oven-dry bulk density; DSSAT's SOIL.CDE defines SBDM as "Bulk density, moist". Clays
  shrink when dried. Measured oven-dry minus 33 kPa density in WoSIS: US clay 31-40 % +0.06, 40-50 % +0.15, 50 % or
  more +0.26; India 50 % or more +0.36 (51 layers only).
- Papers: Turek et al. 2023 (ISWCR, doi:10.1016/j.iswcr.2022.08.001) publish a density-only conversion, BD at 330 cm
  suction (33 kPa) = 0.2308 + 0.8253 x oven-dry BD (error about 0.13 g/cm3). No clay-based conversion was found.
- Numbers: none from DSSAT. The paper rule's median density drop (0.08 at 0.05 over all real layers; 0.10 in the
  changed layers of the run cells) is the same size as these differences. That is a match in size, not a shown link.
- Why not the default: not run; it would be our own fitted rule, would change every clay layer, has thin India data,
  and does not touch the US clay bias (SoilGrids v2 clay about 5 points above measured clay in US cells).

**Also noted: the paper's other density limit** (recorded, not run). The paper keeps DF between 0.9 and 1.3 times the
normal density (p. 1574). Neither the old tool nor this rule applies it: with the old tool 46,517 layers have DF above
1.3 and 202,019 below 0.9; at min gap 0.05, 41,342 are still above 1.3 and the 202,019 below 0.9 are untouched
(`soil_fix_20261003/VERIFY_NOTES.txt` part 6).

### Step 11: Handle MESOL Options for Layer Redistribution

The MESOL switch in *SIMULATION CONTROLS affects how the model handles soil layers:

| MESOL Value | Behavior |
|-------------|----------|
| 1 | Original layer structure used as-is from .SOL file |
| 2 | New default: model may redistribute layers for numerical stability (DSSAT v4.8+ default) |
| 3 | User-defined layer structure with additional constraints |

**Decision rule**: Use MESOL=2 (default) for most applications. Use MESOL=1 only if you require exact layer boundaries to match specific measurement depths. Use MESOL=3 only if you have explicit layer definitions that must be preserved.

### Step 12: Validate the Complete Soil Profile

**Tool reference**: `validate_soil_profile` -- invoke this tool with the .SOL file path and pedon code to run automated validation.

Manual validation checklist:

1. **Layer depth monotonicity**: Each SLB value is strictly greater than the previous.
2. **Water limit ordering**: SLLL < SDUL < SSAT for every layer.
3. **Minimum gap**: SDUL > SLLL, SSAT - SDUL >= 0.01 and (1 - SBDM/2.65) - SDUL >= 0.01 for every layer,
   on the printed numbers; SSAT not above 1 - SBDM/2.65. (0.01 is the floor; files from the KI converters meet
   `min_gap`, default 0.05.)
4. **Bulk density plausibility**: 0.8 <= SBDM <= 2.0 for all layers.
5. **Organic carbon profile**: SLOC should decrease with depth (typical). Surface SLOC is highest.
6. **SRGF profile**: SRGF should decrease with depth. Surface layer SRGF = 1.0.
7. **Texture consistency**: SLCL + SLSI <= 100 for every layer. Sand = 100 - SLCL - SLSI.
8. **Profile depth**: Total depth (last SLB) >= 20 cm. Profiles < 20 cm may cause division-by-zero.
9. **Layer count**: Number of layers <= 20. Profiles with > 20 layers will be silently truncated.
10. **Pedon code uniqueness**: No other profile in the .SOL file has the same 10-character pedon code.

## Expected Outputs

| Output | Format | Verification |
|--------|--------|--------------|
| Updated .SOL file | Multiple profiles, each starting with `*` | File parses without error |
| New profile entry | 10-char pedon code header + surface params + layer data | Profile found by ID_SOIL search |
| Layer data | 1-20 rows of soil properties | Water limits ordered, depths monotonic |
| Metadata | Site line with LAT, LONG | Present and populated |

## Validation Checks

1. **REQUIRED**: Profile header starts with `*` and contains a 10-character pedon code.
2. **REQUIRED**: Surface parameter line contains SALB, SLU1, SLDR, SLRO, SLNF, SLPF.
3. **REQUIRED**: Layer data header (@SLB...) is present.
4. **REQUIRED**: At least 1 layer of data is present.
5. **REQUIRED**: SLLL < SDUL < SSAT for every layer; SSAT - SDUL >= 0.01; and (1 - SBDM/2.65) - SDUL >= 0.01.
   The 0.01 applies to these two gaps only. Between SLLL and SDUL the validator asks only that SDUL is larger (the
   KI converters keep at least 0.005 there). SSAT above 1 - SBDM/2.65 is a warning (an error in strict mode).
6. **REQUIRED**: SLB values are monotonically increasing.
7. **REQUIRED**: SBDM, SLOC, SLLL, SDUL, SSAT are not -99 for any layer.
8. **REQUIRED**: Layer count <= 20.
9. **RECOMMENDED**: First layer SLB <= 5 cm.
10. **RECOMMENDED**: Total profile depth >= 20 cm.
11. **REQUIRED**: Every layer number reads the same by header position (as DSSAT reads it) as by spaces.

## Common Pitfalls

1. **Layer depths not monotonic**: Setting layer bottom depths out of order (e.g., 30, 15, 60) causes the soil water balance to fail immediately. Always list layers in ascending order of SLB.

2. **Water limits inverted**: Setting SLLL > SDUL or SDUL > SSAT produces negative available water. This can cause the model to crash or produce physically impossible results (negative soil water content). Always verify the strict ordering SLLL < SDUL < SSAT.

3. **Shallow soil < 20 cm causing division-by-zero**: DSSAT calculates average soil properties over the profile depth. Very shallow soils (total depth < 20 cm) can trigger division-by-zero in layer-averaging routines. This was specifically identified and patched in recent DSSAT commits (commit d3a65881: "Prevent zero divide for shallow soils less than 20 cm"), but the safest practice is to use profiles >= 20 cm deep.

4. **More than 20 layers silently truncated**: If you define more than 20 layers, DSSAT will only use the first 20 without issuing any warning. Layers 21+ will be silently ignored, effectively cutting off the bottom of your soil profile. Always check: count the number of data rows under `@SLB` and ensure it is <= 20.

5. **Top layer > 5 cm causing instability**: If the first layer is thick (e.g., 0-20 cm), the surface energy balance calculations become numerically unstable, producing unrealistic evaporation rates and soil temperature swings. Always use a 5-cm first layer.

6. **SLOC = 0 in surface layer**: Zero organic carbon is unrealistic for agricultural soils and will cause zero N mineralization potential. Even desert soils have trace organic carbon. Use a minimum of 0.01%.

7. **Missing SBDM (bulk density)**: If SBDM is -99, the model cannot compute water storage volumes. SBDM is a critical input; estimate it from texture if not measured.

8. **SRGF = 0 in all layers**: If root growth factor is zero everywhere, the crop cannot extract water or nutrients from any layer and will die immediately. Ensure at least the surface layers have SRGF > 0.

9. **Duplicate pedon codes in .SOL file**: If two profiles share the same 10-character code, DSSAT will use the first one found and ignore the second. Ensure uniqueness.

10. **Adding a new profile without preserving existing ones**: When editing a .SOL file, always append the new profile below existing profiles. Do not overwrite the file or delete other profiles unless intentional.

11. **Fixing a thin gap by moving SSAT alone**: Raising SSAT above SDUL + 0.005 while SBDM stays put leaves SSAT
    above the pore space of SBDM, and DSSAT's own gap (1 - SBDM/2.65 - SDUL) stays near or below zero. That is the state
    in which Route B runs stopped in `daycent_diffusivity`. Lower the density used instead (Step 10b), or lower SDUL.

12. **SSKS printed as 0.00**: With 2 decimals, SSKS below 0.005 cm/h prints as 0.00, which DSSAT reads as "no
    drainage limit", while a layer with 0.01 is held to 2.4 mm a day. Print 3 decimals below 10 cm/h, but only
    together with the density rule of Step 10b at min gap 0.05. In the maize runs the 3-decimal print on the old thin
    gaps (arm E1) and on a 0.02 gap (arm A1) both did new damage: an SSKS of about 0.001 to 0.004 cm/h nearly closes a
    dense layer.
