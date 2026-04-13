# S2: Material Properties

## Purpose

Define subsurface material properties (permeability, porosity, van Genuchten
parameters) for each geological zone. Converts soil/geology data from global
datasets (HWSD, GLHYMPS) into PFLOTRAN's MATERIAL_PROPERTY and
CHARACTERISTIC_CURVES blocks.

## Inputs

| Input | Format | Source | Units |
|---|---|---|---|
| Soil texture (sand/silt/clay %) | CSV / Raster | HWSD | % |
| Permeability | Shapefile | GLHYMPS v2.0 | log10(m^2) |
| Porosity | Shapefile | GLHYMPS v2.0 | % |
| Lithology | ASCII grid | GLiM | class code |

## Outputs

| Output | Format | Used By |
|---|---|---|
| Material properties JSON | JSON | s5_input_deck_assembly |
| MATERIAL_PROPERTY blocks | PFLOTRAN text | s5_input_deck_assembly |
| CHARACTERISTIC_CURVES blocks | PFLOTRAN text | s5_input_deck_assembly |
| STRATA blocks | PFLOTRAN text | s5_input_deck_assembly |

## Procedure

### Step 1: Classify Soil Texture

Use USDA texture triangle to classify sand/silt/clay percentages:

```python
texture = classify_usda_texture(sand=40, silt=35, clay=25)
# Returns: "Loam"
```

### Step 2: Look Up van Genuchten Parameters

Use Carsel & Parrish (1988) pedotransfer functions:

| Texture | alpha (1/cm) | n | theta_r | theta_s | Ks (m/s) |
|---|---|---|---|---|---|
| Sand | 0.145 | 2.68 | 0.045 | 0.43 | 8.25e-5 |
| Sandy Loam | 0.075 | 1.89 | 0.065 | 0.41 | 1.23e-5 |
| Loam | 0.036 | 1.56 | 0.078 | 0.43 | 2.89e-6 |
| Clay | 0.008 | 1.09 | 0.068 | 0.38 | 5.56e-7 |

### Step 3: Convert Units to PFLOTRAN (CRITICAL)

**van Genuchten alpha: 1/cm → 1/Pa**

```
alpha_Pa = alpha_cm / (rho_water * g)
         = alpha_cm / 9804.139
```

Example for Loam: 0.036 / 9804.139 = 3.671e-6 1/Pa

**TRAP dt_006**: Using alpha in 1/cm directly causes ~10,000x error in capillary
pressure. The soil drains instantly instead of retaining water.

**Hydraulic conductivity → Intrinsic permeability**

```
k_m2 = Ks_m_s * mu_water / (rho_water * g)
     = Ks_m_s * 1.002e-3 / 9804.139
     = Ks_m_s * 1.022e-7
```

**TRAP dt_001**: Using Darcy (≈1e-12 m^2) when meaning hydraulic conductivity
(m/s) gives wildly wrong permeability.

**Porosity: % → fraction**

```
porosity_fraction = porosity_percent / 100
```

**TRAP dt_005**: Porosity of 35 (meaning 35%) stored as 35 gives >1.0, which
causes negative saturation and immediate solver crash.

### Step 4: Build PFLOTRAN Blocks

```
MATERIAL_PROPERTY topsoil
  ID 1
  POROSITY 0.43d0
  TORTUOSITY 0.5d0
  PERMEABILITY
    PERM_ISO 2.95e-13
  /
  CHARACTERISTIC_CURVES cc_topsoil
END

CHARACTERISTIC_CURVES cc_topsoil
  SATURATION_FUNCTION VAN_GENUCHTEN
    ALPHA 3.671e-06
    M 0.3590d0
    LIQUID_RESIDUAL_SATURATION 0.078d0
  /
  PERMEABILITY_FUNCTION MUALEM_VG_LIQ
    M 0.3590d0
    LIQUID_RESIDUAL_SATURATION 0.078d0
  /
END
```

### Step 5: Assign Materials to Regions

```
STRATA
  REGION topsoil_zone
  MATERIAL topsoil
END

STRATA
  REGION bedrock_zone
  MATERIAL bedrock
END
```

## Verification

1. All porosity values between 0 and 1 (NOT 0–100)
2. All permeability values in range 1e-20 to 1e-8 m^2
3. van Genuchten alpha in range 1e-7 to 1e-3 1/Pa (NOT 1/cm)
4. van Genuchten n > 1.0
5. m = 1 - 1/n (Mualem constraint)
6. LIQUID_RESIDUAL_SATURATION < porosity
7. Each STRATA REGION covers entire domain (no gaps)

## Traps

| Trap ID | Error | Factor | Detection |
|---|---|---|---|
| dt_001 | Permeability in Darcy not m^2 | 1e12 | k > 1e-8 m^2 |
| dt_005 | Porosity in % not fraction | 100 | porosity > 1.0 |
| dt_006 | vG alpha in 1/cm not 1/Pa | ~10000 | alpha > 0.01 |
| dt_004 | K in m/day not m/s | 86400 | k unrealistic |

## Example

For Bengbu Basin alluvial aquifer (loamy sand over clay):

```python
# Topsoil: Loamy Sand
topsoil = {
    "permeability_m2": 4.13e-12,   # from Ks=4.05e-5 m/s
    "porosity": 0.41,               # fraction, NOT 41%
    "alpha_Pa": 1.265e-5,           # from 0.124/cm ÷ 9804
    "n": 2.28,
    "m": 0.561,
    "theta_r": 0.057,
}
```
