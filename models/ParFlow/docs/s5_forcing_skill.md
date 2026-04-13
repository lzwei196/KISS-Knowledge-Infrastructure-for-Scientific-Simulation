# S5: Meteorological Forcing — Skill Document

## Purpose

Convert CMFD/MSWX forcing to ParFlow/CLM PFB format with correct units.

## CRITICAL UNIT CONVERSION TABLE

| Variable | CLM Unit | CMFD Unit | Conversion | If Wrong (Silent Error) |
|----------|----------|-----------|------------|-------------------------|
| DSWR | W/m2 | W/m2 | None | - |
| DLWR | W/m2 | W/m2 | None | - |
| **APCP** | **mm/s** | mm/hr | **divide by 3600** | 3600x too much rain (dt_pf_002) |
| **Tmp** | **K** | K | None | If C: model thinks -248C (dt_pf_006) |
| UGRD | m/s | m/s | None (scalar->U) | - |
| VGRD | m/s | 0 | Set to 0 | - |
| **Press** | **Pa** | Pa | None | If hPa: 100x too low (dt_pf_007) |
| SPFH | kg/kg | kg/kg | None | - |

## Procedure

1. **Run** `convert_forcing_to_pfb.py` with forcing source and domain JSON.
2. **Verify** output file count matches expected timesteps.
3. **Verify** NLDAS naming convention: `NLDAS.<run>.000001.pfb` etc.
4. **Spot-check** one file: precipitation should be 0-0.01 mm/s range.

## Common Pitfalls

- **Precipitation units** (dt_pf_002): The most common ParFlow forcing error.
- **Temperature units** (dt_pf_006): CMFD is already K, but verify.
- **File numbering gaps** (dt_pf_031): CLM reads sequentially -- any gap crashes.
- **MSWX is slower**: 3-16 GB files take ~3 min each to clip.
