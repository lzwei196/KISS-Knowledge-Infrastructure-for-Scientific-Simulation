# s2 — Soil / Infiltration Parameters

## Purpose

Map soil properties from global or regional datasets (HWSD, SSURGO, SoilGrids)
to SWMM infiltration model parameters. The [INFILTRATION] section controls how
much rainfall infiltrates vs becomes surface runoff — this is the single most
important factor in total runoff volume prediction.

## Inputs

| Input              | Source               | Format                    |
|--------------------|----------------------|---------------------------|
| Soil texture       | HWSD / SoilGrids     | Sand%, Clay%, Silt%       |
| Hydrologic group   | SSURGO / HWSD        | A, B, C, or D             |
| Organic content    | SoilGrids            | Percentage                |
| Land use type      | NLCD / Sentinel-2    | Classification code       |

## Outputs

| Output             | File           | Format                    |
|--------------------|----------------|---------------------------|
| [INFILTRATION]     | model.inp      | SWMM .inp text            |
| Soil parameter log | soil_params.json| JSON                     |

## Procedure

### Horton Method (Most Common)

1. **Classify soil texture** from sand/clay percentages using USDA triangle
2. **Look up Horton parameters** by texture class:

   | Texture       | MaxRate (in/hr) | MinRate (in/hr) | Decay (1/hr) |
   |---------------|-----------------|-----------------|--------------|
   | Sand          | 5.0             | 1.20            | 4.0          |
   | Sandy Loam    | 3.0             | 0.50            | 4.0          |
   | Loam          | 2.0             | 0.30            | 4.0          |
   | Silt Loam     | 1.5             | 0.25            | 3.0          |
   | Clay Loam     | 1.0             | 0.10            | 3.0          |
   | Clay          | 0.2             | 0.02            | 2.0          |

3. **Set DryTime** = 7 days (typical recovery period)
4. **Set MaxInfil** = 0 (unlimited cumulative infiltration)

### Green-Ampt Method

1. **Classify soil texture** as above
2. **Look up Green-Ampt parameters:**

   | Texture       | Suction (in) | Conductivity (in/hr) | InitDeficit |
   |---------------|-------------|---------------------|-------------|
   | Sand          | 1.93        | 4.74                | 0.34        |
   | Sandy Loam    | 4.33        | 0.43                | 0.33        |
   | Loam          | 3.50        | 0.13                | 0.31        |
   | Clay          | 12.45       | 0.01                | 0.17        |

### SCS Curve Number Method

1. **Determine Hydrologic Soil Group** (A=sandy, B=loamy, C=silty, D=clay)
2. **Select CN by land use and HSG:**

   | Land Use             | HSG-A | HSG-B | HSG-C | HSG-D |
   |----------------------|-------|-------|-------|-------|
   | Open space           | 39    | 61    | 74    | 80    |
   | Residential 1/4 ac   | 61    | 75    | 83    | 87    |
   | Commercial           | 89    | 92    | 94    | 95    |
   | Parking/paved        | 98    | 98    | 98    | 98    |

3. **Set Conductivity** = 0.5 in/hr (used for recovery between events)
4. **Set DryTime** = 7 days

## Verification

- [ ] MaxRate > MinRate for all subcatchments (Horton)
- [ ] Infiltration rates in correct units (in/hr for US, mm/hr for SI)
- [ ] CN values between 30–98 (outside range → likely error)
- [ ] Conductivity > 0 for all methods
- [ ] Soil textures physically reasonable for study area

## Traps

| Trap ID | Description                                          | Severity |
|---------|------------------------------------------------------|----------|
| UT-009  | Infiltration rate in mm/day instead of in/hr → 24x error | CRITICAL |
| DT-004  | Using Horton parameters for Green-Ampt or vice versa | HIGH     |
| DT-005  | CN > 98 silently accepted but physically meaningless | MEDIUM   |
| DT-006  | Suction head in mm when inches expected (SI/US mix)  | HIGH     |

## Example

```ini
;; Horton method, US units
[INFILTRATION]
;;Subcatchment   MaxRate    MinRate    Decay      DryTime    MaxInfil
S1               3.0        0.5        4          7          0
S2               2.0        0.3        4          7          0
S3               1.5        0.25       3          7          0

;; Green-Ampt method, US units
[INFILTRATION]
;;Subcatchment   Suction    Conduct.   InitDef.
S1               4.33       0.43       0.33
S2               3.50       0.13       0.31
S3               6.69       0.26       0.32
```

## Tool

```bash
python ki/tools/convert_soil_to_inp.py \
    --input soil_data.csv \
    --output infiltration_block.txt \
    --method horton \
    --unit-system US
```
