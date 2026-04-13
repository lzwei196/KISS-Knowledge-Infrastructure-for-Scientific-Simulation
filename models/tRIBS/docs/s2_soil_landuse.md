# S2: Soil and Land-Use Parameter Tables

## Purpose

Create soil reclassification (.sdt) and land-use (.ldt) parameter tables that
define the hydraulic and vegetation properties for each soil/land-use class
in the tRIBS domain. These tables are referenced by node-level class IDs in
the mesh and control infiltration, evapotranspiration, and runoff generation.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Soil texture/properties | CSV, shapefile, database | varies | HWSD, SSURGO, SoilGrids |
| Land-use / land-cover | Raster, CSV | class IDs | NLCD, MODIS, ESA CCI |
| Soil depth to bedrock | Grid or single value | meters (source) → mm (tRIBS) | HWSD, literature |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Soil table (`.sdt`) | Tab-delimited text | Hydraulic parameters per soil class |
| Land-use table (`.ldt`) | Tab-delimited text | Vegetation parameters per class |

## Procedure

### Step 1: Obtain soil data
1. Download HWSD or SSURGO data for the study area
2. Extract: texture class (or sand/clay/silt %), bulk density, depth

### Step 2: Convert soil parameters to tRIBS units

**CRITICAL UNIT CONVERSIONS:**

| Parameter | Source unit | tRIBS unit | Conversion |
|-----------|-----------|------------|------------|
| Ks (saturated hydraulic conductivity) | m/s (HWSD) | **mm/hr** | × 3,600,000 |
| Porosity (ThetaS) | % (sometimes) | **fraction (0–1)** | ÷ 100 |
| Depth to bedrock | m (HWSD) | **mm** | × 1000 |
| Surface soil depth | m | **mm** | × 1000 |
| Root zone depth | m | **mm** | × 1000 |
| Air-entry pressure (PsiB) | cm | **mm** | × 10 |

### Step 3: Use pedotransfer functions if needed
If only texture data is available, use Saxton & Rawls (2006) or Clapp & Hornberger
(1978) to estimate:
- Ks from sand/clay percentages
- PsiB (air-entry pressure)
- Pore-size distribution index
- Residual moisture content

```bash
python convert_soil_params.py \
    --source hwsd \
    --input hwsd_data.csv \
    --output tables/ \
    --sdt-file soil_params.sdt
```

### Step 4: Create land-use table
Map each land-use class to vegetation parameters:
- **a, b1**: interception coefficients
- **P, S**: rainfall partitioning parameters
- **K**: canopy extinction coefficient
- **bv**: vegetation fraction
- **LAI**: leaf area index (m²/m²)

### Step 5: Set soil depth parameters in control file
```
DEPTHTOBEDROCK
2000
SURFACESOILDEPTH
100
ROOTZONEDEPTH
1000
```
Note: All values in **mm**.

## Verification

- [ ] Ks values are in **mm/hr** (typical range: 0.1–200 mm/hr)
- [ ] Porosity (ThetaS) is **fraction 0–1** (typical: 0.3–0.6)
- [ ] ThetaR < ThetaS for every soil class
- [ ] Soil depths are in **mm** (DEPTHTOBEDROCK typically 500–5000 mm)
- [ ] All soil class IDs in the mesh have a matching row in .sdt
- [ ] All land-use class IDs in the mesh have a matching row in .ldt
- [ ] PsiB values are positive and in mm

## Traps

| Trap ID | Symptom | Root Cause | Fix |
|---------|---------|------------|-----|
| dt_005 | Immediate saturation, massive runoff | Soil depth in m instead of mm (1m → 1mm) | Multiply by 1000 |
| dt_006 | No infiltration, 100% surface runoff | Ks in m/s instead of mm/hr (1e-6 → 1e-6) | Multiply by 3.6e6 |
| dt_007 | ET exceeds rainfall, negative storage | Porosity > 1 (given as %) | Divide by 100 |
| — | Crash: "Soil class not found" | Missing class ID in .sdt | Add missing row |
| — | Wrong runoff partitioning | PsiB in cm instead of mm | Multiply by 10 |

## Example

### Soil table (.sdt)
```
ID	Ks	ThetaS	ThetaR	PsiB	PoreSize	Conductivity	Residual
1	26.0000	0.4100	0.0400	146.60	0.3800	26.0000	0.0400
2	13.2000	0.4300	0.0300	111.50	0.2500	13.2000	0.0300
3	6.8000	0.4500	0.0200	207.60	0.2300	6.8000	0.0200
```

### Land-use table (.ldt)
```
ID	a	b1	P	S	K	bv	LAI
1	0.5000	0.8000	2.0000	0.5000	0.1000	0.5000	5.0000
2	0.2000	0.4000	1.0000	0.3000	0.0500	0.3000	2.0000
```
