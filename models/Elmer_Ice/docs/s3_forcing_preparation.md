# S3: Forcing Preparation

## Purpose

Convert climate and environmental forcing data into Elmer/Ice-compatible
boundary condition files. This stage handles the critical unit conversions
that are the most common source of silent errors in ice sheet modeling.

## Inputs

| Input | Source | Variables | Native Units |
|-------|--------|-----------|-------------|
| Surface Mass Balance | RACMO, MAR, ERA5 | SMB | kg/m2/s or kg/m2/a |
| Surface Temperature | RACMO, ERA5, stations | T2m | K or °C |
| Basal Melt Rate | ISMIP6, ocean models | BM | m/a w.e. or m/a i.e. |
| Geothermal Heat Flux | Shapiro & Ritzwoller | GHF | mW/m2 |
| Surface Velocity (obs) | MEaSUREs, ITS_LIVE | vx, vy | m/a |

## Outputs

| Output | Format | Units | Elmer Keyword |
|--------|--------|-------|---------------|
| `smb_forcing.dat` | time-value ASCII | m/a ice eq. | `Top Surface Accumulation` |
| `temperature_forcing.dat` | time-value ASCII | °C | `Temperature` BC |
| `basal_melt_forcing.dat` | time-value ASCII | m/a ice eq. | `Bottom Surface Accumulation` |
| `ghf_nodes.dat` | value per node | W/m2 | `Heat Flux BC` |

## Procedure

1. **Identify source data units**: This is the single most important step.
   Common unit systems:

   | Source | SMB Units | Temperature | GHF |
   |--------|-----------|-------------|-----|
   | RACMO2.3 | kg/m2/s | K | — |
   | MAR | mm w.e./day | °C | — |
   | ERA5 | kg/m2/s | K | — |
   | Shapiro & Ritzwoller | — | — | mW/m2 |

2. **Run convert_forcing.py**:
   ```bash
   python convert_forcing.py --smb racmo_smb.nc --temperature racmo_t2m.nc \
       --smb_variable SMB_rec --temp_variable t2m \
       --smb_units kg/m2/s --temp_units K \
       --output_dir ./forcing
   ```

3. **Verify output ranges**: The script prints validation warnings for out-of-range values.

4. **Reference in SIF**: Point Body Force and Boundary Condition blocks to the forcing files.

## Unit Conversion Reference

### SMB Conversions (all to m/a ice equivalent)

| From | Multiply By | Formula |
|------|------------|---------|
| kg/m2/s | 34649.4 | × (86400 × 365.25) / 910 |
| kg/m2/a | 0.001099 | ÷ 910 |
| mm w.e./day | 0.4011 | × 365.25 / 1000 × (1000/910) |
| m w.e./a | 1.0989 | × (1000/910) |
| m i.e./a | 1.0 | already correct |

### Temperature Conversions

| From | To °C | Formula |
|------|-------|---------|
| Kelvin | °C | T_C = T_K - 273.15 |
| Fahrenheit | °C | T_C = (T_F - 32) × 5/9 |

### GHF Conversions

| From | To W/m2 | Formula |
|------|---------|---------|
| mW/m2 | W/m2 | ÷ 1000 |
| µW/m2 | W/m2 | ÷ 1e6 |

## Verification

- **SMB**: Typical range -10 to +2 m/a i.e. for Greenland. Max ~+1 m/a in interior.
- **Temperature**: Ice sheet surface: -60 to +10 °C. If > 50°C, still in Kelvin.
- **GHF**: 0.03 to 0.15 W/m2 typical. If > 1 W/m2, still in mW/m2.
- **Basal melt**: 0 to 50 m/a under ice shelves. If > 100, check units.

## Traps

| Trap | Effect | Prevention |
|------|--------|-----------|
| **SMB units** (dt_014) | Ice grows everywhere or ablation too strong | Verify sign and magnitude |
| **Temperature in K** (dt_004) | Viscosity wildly wrong | Convert to °C for SIF |
| **GHF in mW/m2** | 1000x too much basal heating | Divide by 1000 |
| **SMB sign convention** (dt_014) | No ablation zone | Check: negative at warm margins |
| **Velocity in m/a** (dt_001) | Comparison fails vs VTU output (m/s) | Convert when comparing |

## Example

```bash
# Synthetic forcing for testing
python convert_forcing.py --synthetic --synthetic_years 100 \
    --dt_years 1.0 --output_dir ./forcing

# Real RACMO data
python convert_forcing.py --smb RACMO2.3_SMB.nc --temperature RACMO2.3_T2m.nc \
    --ghf shapiro_ritzwoller_ghf.nc \
    --smb_variable SMB_rec --temp_variable t2m --ghf_variable ghf \
    --smb_units kg/m2/s --temp_units K --ghf_units mW/m2 \
    --output_dir ./forcing
```
