# Stage 3: Soil and Vegetation Parameter Definition

## Purpose

Create parameter definition files (`.def`) for soil, vegetation, land use, and
other spatial objects. These files control the physical and biogeochemical
properties that drive RHESSys processes.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Soil properties | HWSD / SoilGrids / SSURGO | Sand%, clay%, depth, bulk density |
| Vegetation type | NLCD / GlobeLand30 / literature | Species, LAI, allometric parameters |
| Land use | NLCD / manual | Impervious fraction, fertilizer, irrigation |

## Outputs

| File | Location | Description |
|------|----------|-------------|
| `soil_*.def` | `defs/` | Soil hydraulic and biogeochemical parameters |
| `veg_*.def` | `defs/` | Vegetation ecophysiological parameters |
| `lu_*.def` | `defs/` | Land use parameters |
| `basin.def` | `defs/` | Basin-level defaults |
| `hill.def` | `defs/` | Hillslope-level defaults |
| `zone.def` | `defs/` | Zone-level defaults |

## Procedure

### Step 1: Soil Parameters

Key soil parameters and their units:

| Parameter | Unit | Typical Range | Description |
|-----------|------|---------------|-------------|
| `Ksat_0` | **m/day** | 0.001-100 | Surface saturated hydraulic conductivity |
| `m` | m | 0.01-20 | Transmissivity decay parameter |
| `porosity_0` | **m^3/m^3** | 0.2-0.7 | Surface porosity (fraction) |
| `porosity_decay` | 1/m | 0-10 | Porosity decay with depth |
| `pore_size_index` | dimensionless | 0.1-0.8 | Brooks-Corey parameter |
| `psi_air_entry` | **m** | 0.01-3.0 | Air entry pressure |
| `soil_depth` | **m** | 0.5-5.0 | Total soil depth |

**UNIT TRAPS:**
- `Ksat_0`: Must be m/day. HWSD reports cm/hr → multiply by 0.24 (dt_005)
- `porosity_0`: Must be fraction. Some databases report % → divide by 100 (dt_006)
- `soil_depth`: Must be m. Most databases report cm → divide by 100 (dt_004)
- `psi_air_entry`: Must be m (head). Some sources use kPa → divide by 9.81 (dt_010)

Pedotransfer functions (Cosby et al. 1984):
```
Ksat (inch/hr) = 10^(-0.6 + 0.0126*sand% - 0.0064*clay%)
porosity = 0.489 - 0.00126 * sand%
psi_ae (cm) = 10^(1.54 - 0.0095*sand% + 0.0063*silt%)
b = 3.10 + 0.157*clay% - 0.003*sand%
```

### Step 2: Vegetation Parameters

Key vegetation parameters:

| Parameter | Unit | Typical Range | Description |
|-----------|------|---------------|-------------|
| `epc.max_lai` | m^2/m^2 | 1-12 | Maximum leaf area index |
| `epc.proj_sla` | m^2/kg C | 0.01-1.0 | Specific leaf area |
| `epc.leaf_turnover` | 1/day | 0.0001-0.01 | Daily leaf turnover |
| `epc.livewood_turnover` | 1/day | 0.0001-0.01 | Livewood turnover |
| `epc.height_to_stem_coef` | m/(kgC/m^2) | 1-30 | Allometric coefficient |
| `epc.allocation_flag` | integer | 1-3 | C allocation strategy |
| `epc.veg_type` | integer | 1=tree, 2=grass | Vegetation type flag |

**TRAP:** Carbon/nitrogen pool values in the worldfile must be in **kg/m^2**,
not g/m^2 (dt_009). Initializing with g/m^2 values gives 1000x too much carbon.

### Step 3: Land Use Parameters

```
1       landuse_default_ID
0.0     impervious_fraction        (0-1)
0.0     irrigation                 (m/day)
0.0     fertilizer_NO3             (kg N/m^2/year)
0.0     fertilizer_NH4             (kg N/m^2/year)
```

### Step 4: Basin/Hillslope/Zone Defaults

These are typically minimal:

**basin.def:**
```
1       basin_parm_ID
```

**zone.def:**
```
1       zone_parm_ID
0.0     atm_trans_lapse_rate
0.0     dewpoint_lapse_rate
-0.006  lapse_rate                 (C/m, temperature lapse rate)
```

## Verification

```bash
# Check soil parameter ranges
python3 -c "
for line in open('defs/soil_sandyloam.def'):
    parts = line.strip().split()
    if len(parts) >= 2 and parts[0][0].isdigit():
        val, name = float(parts[0]), parts[1]
        if name == 'Ksat_0' and val > 200:
            print(f'WARNING: Ksat_0={val} m/day too high (cm/hr not converted?)')
        if name == 'porosity_0' and val > 1:
            print(f'WARNING: porosity_0={val} > 1 (% not converted to fraction?)')
        if name == 'soil_depth' and val > 50:
            print(f'WARNING: soil_depth={val} m (cm not converted to m?)')
"
```

## Tool

```bash
python ki/tools/convert_soil_params.py \
  --sand 45 --clay 20 --depth 150 \
  --output-dir defs/ --prefix soil_loam

# Or from CSV:
python ki/tools/convert_soil_params.py \
  --input hwsd_extract.csv \
  --output-dir defs/ --prefix soil_site
```

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Ksat in cm/hr | Drainage 4x too fast | Multiply by 0.24 for m/day | dt_005 |
| Porosity as % | Porosity > 1 crashes model | Divide by 100 | dt_006 |
| Soil depth in cm | Model treats as m, 100x too deep | Divide by 100 | dt_004 |
| C/N pools in g/m^2 | 1000x excess biomass | Divide by 1000 | dt_009 |
| Psi air entry in kPa | Wrong suction curve | Convert to m of water | dt_010 |

## Example

See `source/repo/Testing/defs/soil_sandyloam.def` and
`source/repo/Testing/defs/veg_douglasfir.def` for complete examples.
