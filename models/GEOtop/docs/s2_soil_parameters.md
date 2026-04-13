# s2: Soil Parameter Derivation

## Purpose

Derive Van Genuchten soil hydraulic parameters for each soil layer and write them
in GEOtop's `soilXXXX.txt` format. This stage is critical because incorrect units
are the most common source of silent model failures.

## Inputs

| Input                | Source               | Format    | Units                |
|----------------------|----------------------|-----------|----------------------|
| Soil texture         | HWSD, SoilGrids      | CSV/NetCDF| % sand, silt, clay   |
| Bulk density         | HWSD, SoilGrids      | Scalar    | kg/m3                |
| Organic carbon       | HWSD, SoilGrids      | Scalar    | % by weight          |
| Layer discretization | User decision        | List      | mm (CRITICAL!)       |

## Outputs

| Output               | File                  | Format    | Notes                |
|----------------------|-----------------------|-----------|----------------------|
| soilXXXX.txt         | sim_dir/soil/soilXXXX.txt | CSV   | One per point        |

### Soil File Columns

| Column   | Name                        | Unit    | Typical Range        | Trap           |
|----------|-----------------------------|---------|----------------------|----------------|
| Dz       | Layer thickness             | **mm**  | 10-500               | dt_001: not m! |
| Kh       | Lateral hydraulic cond.     | **m/s** | 1E-7 to 1E-3        | dt_002: not cm/day|
| Kv       | Normal hydraulic cond.      | **m/s** | 1E-7 to 1E-3        | dt_002         |
| vwc_r    | Residual water content      | m3/m3   | 0.02-0.15            |                |
| vwc_w    | Wilting point               | m3/m3   | 0.05-0.30            |                |
| vwc_fc   | Field capacity              | m3/m3   | 0.15-0.45            |                |
| vwc_s    | Saturated water content     | m3/m3   | 0.30-0.60            |                |
| alpha    | Van Genuchten alpha         | **1/mm**| 0.0001-0.01          | dt_003: not 1/cm|
| n        | Van Genuchten n             | -       | 1.1-3.0              |                |
| stor     | Specific storativity        | 1/m     | ~5E-7                |                |

## Procedure

1. **Obtain soil texture** from HWSD or SoilGrids for the simulation location
2. **Determine texture class** using USDA triangle (sand/silt/clay percentages)
3. **Look up Van Genuchten parameters** from Schaap et al. (2001) or run Rosetta PTF
4. **CONVERT UNITS** (most critical step):
   - Layer thickness: cm -> mm (multiply by 10)
   - Ksat: cm/day -> m/s (divide by 8,640,000)
   - alpha: 1/cm -> 1/mm (divide by 10)
5. **Write soil file** with CSV header and one row per layer
6. **Validate** parameter ranges and unit consistency

### Unit Conversion Reference

| Parameter | HWSD/Literature | GEOtop    | Conversion                         |
|-----------|-----------------|-----------|------------------------------------|
| Dz        | cm              | mm        | multiply by 10                     |
| Ksat      | cm/day          | m/s       | divide by 86400, divide by 100     |
| Ksat      | mm/hr           | m/s       | divide by 3,600,000                |
| alpha     | 1/cm            | 1/mm      | divide by 10                       |
| alpha     | 1/m             | 1/mm      | divide by 1000                     |

### Layer Discretization Guidelines

- Top layers: thin (10 mm) for surface energy balance accuracy
- Middle layers: moderate (20-50 mm)
- Deep layers: thick (100-200 mm) for computational efficiency
- Total depth: typically 1-3 m for hydrological applications
- Typical scheme: `10,10,10,20,20,30,50,50,50,50,100,100,100,100,150,150`

## Verification

- [ ] Dz values are in mm (smallest should be >= 5 mm)
- [ ] Kh and Kv are in m/s (typical: 1E-7 to 1E-3)
- [ ] alpha is in 1/mm (typical: 0.0001 to 0.01, NOT 0.01 to 1.0)
- [ ] n > 1.0 (Van Genuchten constraint)
- [ ] vwc_r < vwc_w < vwc_fc < vwc_s
- [ ] Total soil depth is reasonable (500-5000 mm)
- [ ] Number of layers matches SoilLayerTypes or SoilLayerNumber in geotop.inpts

## Traps

| Trap ID | Symptom                                   | Severity |
|---------|-------------------------------------------|----------|
| dt_001  | Dz in meters -> solver diverges instantly | fatal    |
| dt_002  | Ksat in cm/day -> unrealistic infiltration| silent   |
| dt_003  | alpha in 1/cm -> wrong retention curve    | silent   |
| dt_014  | vwc_r > vwc_s -> solver crash             | fatal    |
| dt_015  | n < 1.0 -> invalid Van Genuchten          | fatal    |

## Example

For a sandy loam soil (40% sand, 35% silt, 25% clay):

```csv
Dz,Kh,Kv,vwc_r,vwc_w,vwc_fc,vwc_s,alpha,n,stor
10,2.86E-04,2.86E-04,0.05,0.08,0.25,0.53,0.00131,1.5,5.00E-07
10,2.86E-04,2.86E-04,0.05,0.08,0.25,0.53,0.00131,1.5,5.00E-07
20,2.86E-04,2.86E-04,0.05,0.08,0.25,0.53,0.00131,1.5,5.00E-07
50,2.86E-04,2.86E-04,0.05,0.08,0.25,0.53,0.00131,1.5,5.00E-07
100,2.86E-04,2.86E-04,0.05,0.08,0.25,0.53,0.00131,1.5,5.00E-07
```

Tool command:
```bash
python convert_soil.py --source manual --sand 40 --silt 35 --clay 25 \
    --layers "10,10,20,50,100" --output soil/soil0001.txt
```
