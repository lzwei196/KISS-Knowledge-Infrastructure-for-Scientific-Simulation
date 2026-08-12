# S4 — Parameter Calibration

## Purpose

Select and tune the erosion, diffusion, and transport parameters in pyBadlands to
match observed landscape characteristics (denudation rates, relief, drainage density).
This stage maps from geological observations and literature to the dimensioned
coefficients used by the model.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Published denudation rates | scalar | m/year or mm/kyr from cosmogenic studies |
| Drainage density | scalar | km/km² from DEM analysis |
| Relief metrics | scalar | Local relief (m) from DEM analysis |
| Lithology map | CSV | Rock type per spatial unit |
| Literature Kd values | table | SPL Kd for given m, n, rock type |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| XML erosion section | `<erosion>` block | SPLm, SPLn, SPLero |
| XML creep section | `<creep>` block | caerial, cmarine, cslp |
| Erodibility layers | `<erocoeff>` block | Multi-layer Kd |
| Parameter report | JSON | Chosen values with justification |

## Procedure

### 1. Stream Power Law Parameters (SPL)

The core erosion equation is: **E = Kd · A^m · S^n**

| Parameter | Symbol | Typical Range | Sensitivity |
|-----------|--------|--------------|-------------|
| Erodibility | Kd (SPLero) | 1e-8 – 1e-3 m^(1-2m)/yr | VERY HIGH |
| Area exponent | m (SPLm) | 0.3 – 0.7 | HIGH |
| Slope exponent | n (SPLn) | 0.7 – 2.0 | HIGH |

**Starting point**: m=0.5, n=1.0 (standard detachment-limited model).

**Kd estimation from denudation rate**:
For a basin with known mean denudation rate D (m/year), drainage area A (m²),
and mean channel slope S:
```
Kd ≈ D / (A^m · S^n)
```

**CRITICAL (dt_006)**: Kd has units m^(1−2m)/year. When m=0.5, Kd is in 1/year.
When m≠0.5, Kd values from literature MUST be re-scaled. Do not mix Kd values
calibrated with different m, n combinations.

### 2. Hillslope Diffusion Parameters

| Parameter | Symbol | Typical Range | Context |
|-----------|--------|--------------|---------|
| Aerial diffusion | caerial | 0.001 – 1.0 m²/yr | Subaerial soil creep |
| Marine diffusion | cmarine | 0.001 – 5.0 m²/yr | Submarine slope processes |
| Critical slope | cslp | 0 – 1 | Non-linear diffusion threshold |
| Failure slope | sfail | 0 – 1 | Mass wasting threshold |
| Failure coeff | cfail | 0 – 10 m²/yr | Mass failure diffusion |

**CRITICAL (dt_007)**: Literature often reports κ in m²/kyr. Convert:
`κ_m2_per_year = κ_m2_per_kyr / 1000`

**Starting values** by lithology:
| Rock Type | caerial (m²/yr) | cmarine (m²/yr) |
|-----------|-----------------|-----------------|
| Hard crystalline | 0.001 – 0.005 | 0.005 – 0.01 |
| Soft sedimentary | 0.01 – 0.1 | 0.05 – 0.5 |
| Unconsolidated | 0.1 – 1.0 | 0.5 – 5.0 |

### 3. Relief-Dependent Regime Selection

**CRITICAL INSIGHT** — validated on two real sites (Pearl River USA, Modder River
South Africa): the dominant erosion process depends on landscape relief.

**Low-relief landscapes (< 200 m relief, coastal plains):**
- Hillslope diffusion (caerial) controls denudation, NOT Kd
- Kd spanning 1000× (5e-7 to 5e-4) had zero effect on denudation when caerial
  was low (all gave 1.2 mm/kyr on a synthetic dome sweep)
- caerial = 0.5 m²/yr brought denudation from 1.2 to 31.7 mm/kyr regardless of Kd
- SPL term E = Kd·A^m·S^n is tiny because S is tiny on flat terrain
- **Calibrate caerial first, then Kd is secondary**

**High-relief landscapes (> 500 m relief, mountains/plateaus):**
- SPL erodibility (Kd) controls denudation
- caerial has minor effect relative to fluvial incision
- Kd sweep: 3e-7→3.4, 8e-7→9.2, 1e-6→12.5, 5e-6→123 mm/kyr (Modder River)
- **Calibrate Kd first, then caerial for hillslope tuning**

### 4. Validated Real-Site Parameters

| Site | Relief | Climate | Lithology | Kd | caerial | cmarine | Denu (model) | Denu (obs) | PBIAS |
|------|--------|---------|-----------|-----|---------|---------|-------------|-----------|-------|
| Pearl River, MS/LA, USA | 200 m | Humid 1.5 m/yr | Unconsolidated alluvium | 5e-5 | **0.5** | 1.0 | 21.5 mm/kyr | 21.5 mm/kyr | 0.0% |
| Modder River, Free State, ZA | 1042 m | Semi-arid 0.5 m/yr | Karoo sandstone | **8e-7** | 0.005 | 0.01 | 12.8 mm/kyr | 5–20 mm/kyr | +2.1% |

Obs sources: Pearl River — USGS WQP SSC at stations 02489500 (86 obs) and 02492000
(291 obs). Modder River — published 10Be cosmogenic denudation (Codilean et al. 2014).

### 5. Calibration Strategy

**Step 1**: Set m=0.5, n=1.0 (standard SPL).

**Step 2**: Determine relief regime (low < 200 m vs high > 500 m).

**Step 3**: For low-relief — set caerial by lithology (unconsolidated: 0.5, soft
sedimentary: 0.1, hard: 0.01). Set Kd to a reasonable value (5e-5 for alluvium).

**Step 3 alt**: For high-relief — estimate Kd from published denudation rates.
Start with the lithology table in Section 1. Set caerial low (0.005–0.02).

**Step 4**: Run a short simulation (10% of total time) and check:
- Is the landscape eroding too fast / too slow?
- Does relief increase or decrease?
- Are hillslopes realistic?

**Step 5**: Adjust the dominant parameter by factors of 2–10.

**Step 6**: If using multiple lithologies, set up `<erocoeff>` with layer-specific Kd.

### 4. Multi-lithology Setup

For spatially varying erodibility:

```xml
<erocoeff>
    <erolayers>3</erolayers>
    <erolay>
        <erocst>1.0e-7</erocst>       <!-- Granite layer Kd -->
        <eromap>granite_layer.csv</eromap>
        <thcst>100.0</thcst>
    </erolay>
    <erolay>
        <erocst>5.0e-6</erocst>       <!-- Sandstone layer Kd -->
        <eromap>sandstone_layer.csv</eromap>
        <thcst>50.0</thcst>
    </erolay>
    <erolay>
        <erocst>1.0e-5</erocst>       <!-- Shale layer Kd -->
        <eromap>shale_layer.csv</eromap>
        <thcst>30.0</thcst>
    </erolay>
</erocoeff>
```

## Verification

- [ ] Kd is within physically reasonable range for lithology (1e-8 to 1e-3)
- [ ] Kd units match the chosen m exponent (dt_006)
- [ ] Diffusion coefficients in m²/year, not m²/kyr (dt_007)
- [ ] Short test run produces expected denudation magnitude
- [ ] Landscape doesn't flatten completely or become unrealistically steep

## Traps

| ID | Trap | Consequence |
|----|------|-------------|
| dt_006 | Kd from paper uses different m,n | Over/under-erosion by orders of magnitude |
| dt_007 | Diffusion in kyr not year | 1000× too much hillslope smoothing |
| dt_016 | maxdt too large with high Kd | Numerical instability, NaN |

## Example

Using the `convert_soil_params.py` tool:

```bash
# Convert lithology map to erodibility layers
python ki/tools/s4_parameters/convert_soil_params.py \
    --input lithology.csv \
    --output erodibility.json \
    --mode lithology \
    --spl-m 0.5 --spl-n 1.0

# Convert HWSD soil data
python ki/tools/s4_parameters/convert_soil_params.py \
    --input hwsd_extract.csv \
    --output soil_params.json \
    --mode hwsd \
    --spl-m 0.5 --spl-n 1.0
```
