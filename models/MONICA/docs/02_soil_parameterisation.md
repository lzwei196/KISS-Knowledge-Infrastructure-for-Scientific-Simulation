# Stage 2: Soil Parameterisation

## Purpose

Convert soil profile data from global databases (HWSD, SoilGrids) or local
surveys into the MONICA `site.json` soil profile format. Each soil layer needs
thickness, organic carbon, bulk density, and texture information.

## Inputs

| Source        | Format          | Key variables                              |
|---------------|----------------|--------------------------------------------|
| HWSD v1.2     | CSV / raster   | T_SAND, T_CLAY, T_OC, T_BULK_DENSITY, pH  |
| SoilGrids     | GeoTIFF / API  | sand, clay, soc, bdod per depth            |
| Local survey  | CSV            | Layer-wise sand%, clay%, OC%, BD, pH       |

## Outputs

File: `site.json` — JSON file with `SiteParameters` and `SoilProfileParameters`.

### Site-level parameters

| Parameter    | Unit               | Description                    | Default   |
|--------------|--------------------|--------------------------------|-----------|
| Latitude     | decimal degrees    | Site latitude                  | required  |
| Slope        | m/m                | Surface slope                  | 0         |
| HeightNN     | m                  | Elevation above sea level      | 0         |
| NDeposition  | kg N ha⁻¹ yr⁻¹    | Atmospheric N deposition       | 30        |

### Soil layer parameters (per layer, 20 layers × 0.1 m = 2 m)

| Parameter          | Unit      | Description                         |
|--------------------|-----------|-------------------------------------|
| Thickness          | m         | Layer thickness (typically 0.1)     |
| SoilOrganicCarbon  | %         | Organic carbon content              |
| SoilRawDensity     | kg m⁻³   | Bulk density                        |
| KA5TextureClass    | code      | German KA5 texture class            |
| Sand               | fraction  | Sand mass fraction [0–1]            |
| Clay               | fraction  | Clay mass fraction [0–1]            |
| pH                 | –         | Soil pH (H₂O)                      |

## Procedure

1. **Extract soil data** — query HWSD grid cell or SoilGrids API at (lat, lon)
2. **Map depth layers** — HWSD: topsoil (0–30 cm) + subsoil (30–100 cm);
   SoilGrids: 0–5, 5–15, 15–30, 30–60, 60–100, 100–200 cm
3. **Discretise to 10 cm** — split coarse layers into MONICA's 0.1 m layers
4. **Convert units** — see table below
5. **Assign texture class** — derive KA5 code from sand/clay fractions
6. **Pad to 2 m depth** — extrapolate deepest layer properties with reduced SOC
7. **Assemble site.json** — wrap layers in MONICA JSON structure
8. **Validate** — check physical ranges and monotonicity

## Unit Conversion Table

| Variable        | Source unit     | MONICA unit  | Conversion    |
|-----------------|----------------|--------------|---------------|
| Thickness       | cm             | m            | ÷ 100         |
| SOC             | g kg⁻¹         | %            | ÷ 10          |
| SOC             | kg C kg⁻¹      | %            | × 100         |
| Bulk density    | g cm⁻³         | kg m⁻³       | × 1000        |
| Sand / Clay     | %              | fraction     | ÷ 100         |
| NDeposition     | kg N ha⁻¹ d⁻¹ | kg N ha⁻¹ yr⁻¹ | × 365      |

## KA5 Texture Class Lookup (simplified)

| Sand %  | Clay %  | KA5 class | Description         |
|---------|---------|-----------|---------------------|
| > 85    | < 5     | Ss        | Pure sand           |
| > 70    | < 10    | Su2       | Slightly silty sand |
| > 50    | < 15    | Sl2       | Slightly loamy sand |
| > 50    | < 25    | Sl4       | Strongly loamy sand |
| 30–50   | 15–25   | Ls3       | Sandy clay loam     |
| 20–50   | 10–20   | Ls2       | Sandy loam          |
| < 20    | < 15    | Ut4       | Silty loam          |
| < 40    | > 35    | Lt2       | Clayey loam         |
| any     | > 45    | Tt        | Clay                |

## Verification

- [ ] Total depth is ≤ 2.0 m (MONICA default max)
- [ ] Layer thicknesses are in metres, not cm
- [ ] SOC is in %, not g/kg (values > 10% are unusual except peat)
- [ ] Bulk density in kg m⁻³ range [500, 2000]
- [ ] Sand + Clay fractions ≤ 1.0 (as fractions) or ≤ 100 (as %)
- [ ] SOC typically decreases with depth

## Traps

| ID  | Symptom                          | Cause                             | Fix                      |
|-----|----------------------------------|-----------------------------------|--------------------------|
| UT7 | Negative soil moisture / crash   | Thickness in cm instead of m      | Divide by 100            |
| UT8 | Wrong water balance              | Bulk density in g cm⁻³ not kg m⁻³| Multiply by 1000         |
| UT9 | Unrealistic decomposition rates  | SOC in g/kg not %                 | Divide by 10             |
| UT12| Wrong PTF results                | Sand/Clay as % not fraction       | Divide by 100            |

## Example

```bash
python convert_soil_to_monica.py \
    --input hwsd_extract.csv --format hwsd \
    --output site.json --lat 52.8 --lon 13.8 --elevation 50 \
    --n-deposition 25
```
