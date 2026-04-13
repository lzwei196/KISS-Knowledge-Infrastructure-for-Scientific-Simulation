# S2: Aquifer Properties — Soil/Geology to Hydraulic Parameters

## Purpose

Convert soil texture or geological data (HWSD, borehole logs, geological maps) into MODFLOW aquifer property arrays: hydraulic conductivity (K), specific storage (Ss), and specific yield (Sy). These go into the NPF package (MF6) or LPF/BCF package (MF2005).

## Inputs

| Input | Format | Source | Units |
|-------|--------|--------|-------|
| Soil texture map | GeoTIFF with USDA class codes | HWSD v1.2/v2.0 | Class codes (1-15) |
| Grid metadata | JSON | build_grid_from_dem | — |
| Borehole K values | CSV (optional) | Field tests | m/day or cm/s |
| Custom lookup table | JSON (optional) | Literature/calibration | m/day, 1/m, — |

## Outputs

| Output | Format | Consumed by | Units |
|--------|--------|-------------|-------|
| `hk.npy` | NumPy (nlay, nrow, ncol) | NPF/LPF `k` parameter | m/day |
| `ss.npy` | NumPy (nlay, nrow, ncol) | STO `ss` parameter | 1/m |
| `sy.npy` | NumPy (nlay, nrow, ncol) | STO `sy` parameter | dimensionless (0-1) |
| `aquifer_metadata.json` | JSON | Documentation | — |

## Procedure

1. **Load soil data**: Read HWSD raster or geological map
2. **Resample**: Match to model grid (nearest-neighbor)
3. **Lookup**: Map texture classes to K/Ss/Sy values
4. **Depth decay**: Optionally reduce K with depth (K_layer = K_surface × 0.5^layer)
5. **Apply multiplier**: Optional calibration multiplier for K
6. **Validate**: Check physical ranges

### USDA Texture → K Lookup (Typical Values)

| Texture | K (m/day) | Ss (1/m) | Sy |
|---------|-----------|----------|-----|
| Sand | 8.64 | 1×10⁻⁵ | 0.30 |
| Loamy sand | 5.04 | 2×10⁻⁵ | 0.28 |
| Sandy loam | 1.22 | 3×10⁻⁵ | 0.25 |
| Loam | 0.504 | 4×10⁻⁵ | 0.22 |
| Silt loam | 0.264 | 5×10⁻⁵ | 0.20 |
| Clay loam | 0.192 | 7×10⁻⁵ | 0.16 |
| Clay | 0.048 | 1×10⁻⁴ | 0.10 |
| Gravel | 86.4 | 5×10⁻⁶ | 0.25 |

### Unit Conversion Table

| Source Unit | To m/day | Multiply by |
|-------------|----------|-------------|
| cm/s | m/day | 864 |
| m/s | m/day | 86,400 |
| ft/day | m/day | 0.3048 |
| gal/day/ft² | m/day | 0.04075 |

### FloPy Usage

```python
# MODFLOW 6 — NPF + STO packages
npf = flopy.mf6.ModflowGwfnpf(
    gwf,
    k=hk_array,              # (nlay, nrow, ncol) in m/day
    k33=hk_array * 0.1,      # Vertical K (often 10% of horizontal)
    save_specific_discharge=True
)

sto = flopy.mf6.ModflowGwfsto(
    gwf,
    ss=ss_array,              # (nlay, nrow, ncol) in 1/m
    sy=sy_array,              # (nlay, nrow, ncol) dimensionless
    steady_state={0: True},   # First period steady
    transient={1: True}       # Second period transient
)
```

## Verification

- [ ] K values in physical range: 0.001 (clay) to 100 (gravel) m/day
- [ ] Ss in range 1×10⁻⁶ to 1×10⁻⁴ (1/m)
- [ ] Sy in range 0.01 to 0.35
- [ ] No zero or negative K values
- [ ] K decreases with depth (unless geology says otherwise)
- [ ] Vertical K (K33) is typically 0.01-0.1 × horizontal K

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| K in cm/s not m/day | Heads barely change; flat water table | Multiply by 864 |
| K in m/s not m/day | Same as above but worse | Multiply by 86,400 |
| Ss too large (>0.01) | Unrealistic storage release | Use typical 1e-5 to 1e-4 |
| Sy > 0.5 | Non-physical | Maximum for clean gravel ≈ 0.35 |
| No depth decay | Deep layers too permeable | Apply K_deep = K_surface × 0.1-0.5 |

## Example

```bash
python tools/convert_soil_to_aquifer.py \
    --hwsd data/hwsd_texture.tif \
    --grid_meta grid_output/grid_metadata.json \
    --k_multiplier 1.5 \
    --output_dir aquifer_props/
```
