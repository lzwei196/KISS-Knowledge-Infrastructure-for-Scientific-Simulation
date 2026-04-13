# S3 — Initial Snow and Soil Profiles

## Purpose

Generate initial snow/soil stratigraphy (.sno files) for each grid cell in the
Alpine3D domain. These files define the starting state of the snowpack and soil
at the simulation start date.

## Inputs

| Item | Format | Source | Required |
|------|--------|--------|----------|
| DEM grid | ARC ASCII | Stage s0 output | Yes |
| Profile date | ISO 8601 | Simulation start date | Yes |
| Soil properties | Lookup table or field data | HWSD, SoilGrids, or custom | Yes |
| Initial snow state | Observations or zero | Remote sensing, field data | Optional |

## Outputs

| File | Format | Path |
|------|--------|------|
| One .sno file per pixel | SMET 1.1 ASCII | `input/snowfiles/{row}_{col}.sno` |

## Procedure

### 1. Choose Initialization Strategy

| Strategy | When to Use | Pros | Cons |
|----------|------------|------|------|
| Bare ground (no snow) | Start simulation before snow season (Oct) | Simple, robust | Must start early |
| Spinup | Multi-year simulation | Accurate initial state | Expensive |
| From observations | Dense observation network | Most accurate | Rarely available |
| From restart files | Continuing a previous run | Perfect continuity | Need prior run |

**Recommended**: Start simulations on October 1 with bare ground (no snow layers).
The SNOWPACK model will build up the snow profile as precipitation falls.

### 2. Define Soil Properties

Each .sno file needs soil layer properties:

| Property | Field | Unit | Typical Range |
|----------|-------|------|---------------|
| Layer thickness | Layer_Thick | m | 0.05–2.0 |
| Temperature | T | K | 270–290 |
| Ice volume fraction | Vol_Frac_I | 0–1 | 0.0 (unfrozen) |
| Water volume fraction | Vol_Frac_W | 0–1 | 0.10–0.35 |
| Void volume fraction | Vol_Frac_V | 0–1 | 0.15–0.45 |
| Soil volume fraction | Vol_Frac_S | 0–1 | 0.40–0.65 |
| Soil density | Rho_S | kg/m³ | 1200–2700 |
| Thermal conductivity | Conduc_S | W/(m·K) | 0.3–3.0 |
| Heat capacity | HeatCapac_S | J/(kg·K) | 750–1500 |
| Grain radius | rg | mm | 0.1–5.0 |
| Bond radius | rb | mm | 0.1–2.0 |

**CRITICAL**: Volume fractions must sum to 1.0:
`Vol_Frac_I + Vol_Frac_W + Vol_Frac_V + Vol_Frac_S = 1.0`

### 3. Run the Generator

```bash
python tools/generate_sno_files.py \
    --dem ./input/surface-grids/dischma.dem \
    --output ./input/snowfiles/ \
    --date 2014-10-01T00:00 \
    --n-soil-layers 3 \
    --soil-type mineral
```

Available soil types: `mineral`, `organic`, `sandy`, `clay`, `rock`

### 4. Configure io.ini

```ini
[Input]
SNOW = SMET
SNOWPATH = ./input/snowfiles
```

### 5. Soil Properties from HWSD/SoilGrids

For realistic soil, map global soil databases to Alpine3D parameters:

| HWSD Texture | Density (kg/m³) | Conductivity (W/m·K) | Heat Cap (J/kg·K) | Water Frac |
|--------------|-----------------|---------------------|-------------------|------------|
| Sand | 1600 | 1.8 | 800 | 0.10 |
| Loamy sand | 1650 | 1.5 | 850 | 0.15 |
| Sandy loam | 1700 | 1.4 | 880 | 0.20 |
| Loam | 1750 | 1.3 | 900 | 0.25 |
| Clay loam | 1850 | 1.2 | 950 | 0.30 |
| Clay | 2000 | 1.1 | 1000 | 0.35 |
| Organic/peat | 1200 | 0.5 | 1400 | 0.40 |
| Rock | 2600 | 3.0 | 750 | 0.02 |

### 6. Spinup Strategy

For multi-year accuracy, run a spinup:
1. Generate bare-ground .sno files for Year 1
2. Run Year 1 simulation with `SNOW_WRITE = TRUE`
3. Use Year 1 output snowfiles as input for Year 2
4. Repeat until soil temperatures equilibrate (typically 3–5 years)

```bash
# Year 1: bare ground initialization
python tools/run_alpine3d.py --iofile setup/io_spinup.ini \
    --startdate 2010-10-01T01:00 --enddate 2011-09-30T00:00

# Year 2: use previous output as input
cp output/snowfiles/*.sno input/snowfiles/
python tools/run_alpine3d.py --iofile setup/io_spinup.ini \
    --startdate 2011-10-01T01:00 --enddate 2012-09-30T00:00
```

## Verification

```bash
# Check number of .sno files matches DEM valid pixels
echo "SNO files: $(ls input/snowfiles/*.sno | wc -l)"
python3 -c "
with open('input/surface-grids/dischma.dem') as f:
    h = {}
    for _ in range(6):
        k, v = f.readline().split()
        h[k.lower()] = float(v)
    nd = float(h.get('nodata_value', -9999))
    valid = sum(1 for line in f for v in line.split() if float(v) != nd)
    print(f'DEM valid pixels: {valid}')
"

# Validate a sample .sno file
head -25 input/snowfiles/40_50.sno
# Check: ProfileDate matches start date
# Check: Vol_Frac sums to 1.0
# Check: Rho_S > 500 (not in g/cm³)
# Check: T > 200 K (not in °C)

# Check volume fraction consistency
python3 -c "
with open('input/snowfiles/40_50.sno') as f:
    for line in f:
        if line.startswith('[DATA]'): break
    for line in f:
        parts = line.split()
        if len(parts) >= 8:
            ice, water, void, soil = float(parts[3]), float(parts[4]), float(parts[5]), float(parts[6])
            total = ice + water + void + soil
            print(f'Vol fracs: I={ice} W={water} V={void} S={soil} Sum={total:.4f}')
"
```

## Traps

| Trap ID | Issue | Symptom | Fix |
|---------|-------|---------|-----|
| dt_010 | Layer_Thick in cm or mm | Absurd column height | Convert to meters |
| dt_011 | rg in µm instead of mm | Wrong albedo/metamorphism | Convert to mm |
| dt_012 | Rho_S in g/cm³ | No soil thermal mass | Multiply by 1000 |
| — | Vol_Frac sum ≠ 1.0 | Mass conservation error | Recalculate fractions |
| — | T in °C instead of K | Soil at ~20 K | Add 273.15 |
| — | Missing .sno files | Crash: "cannot read snow file" | Generate for all valid pixels |

## Example

```bash
# Generate .sno files for Dischma catchment with organic alpine soil
python tools/generate_sno_files.py \
    --dem ./input/surface-grids/dischma.dem \
    --output ./input/snowfiles/ \
    --date 2014-10-01T00:00 \
    --n-soil-layers 5 \
    --soil-type organic

# Output:
# {"status": "success", "n_pixels_written": 3842, "n_soil_layers": 5, ...}
```
