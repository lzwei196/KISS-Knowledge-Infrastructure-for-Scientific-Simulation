# S3: Atmospheric Forcing Data Configuration

## Purpose

Configure the atmospheric forcing data that drives FATES through the host land model.
FATES does not read forcing data directly — the host model's data atmosphere component
(DATM in CESM/CTSM, DATM in E3SM) provides the meteorological boundary conditions.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| DATM forcing dataset | NetCDF | GSWP3, CRU-NCEP, CRUJRA, ERA5 | Yes |
| Site coordinates | lat/lon | Manual | Yes |
| Simulation period | Start/stop dates | Manual | Yes |

### Required Forcing Variables

| Variable | Name in DATM | Units | Frequency | Notes |
|----------|-------------|-------|-----------|-------|
| Air temperature | TBOT | K (Kelvin) | 3-hourly | NOT °C (dt_005) |
| Precipitation | PRECTmms | mm/s | 3-hourly | NOT mm/day (dt_006) |
| Shortwave radiation | FSDS | W/m² | 3-hourly | NOT MJ/m²/day (dt_007) |
| Longwave radiation | FLDS | W/m² | 3-hourly | Downwelling only |
| Specific humidity | QBOT | kg/kg | 3-hourly | NOT relative humidity |
| Wind speed | WIND | m/s | 3-hourly | Scalar (not U/V components) |
| Surface pressure | PSRF | Pa | 3-hourly | NOT hPa or mbar |
| CO₂ concentration | — | ppmv | Annual/fixed | Via `co2_ppmv` namelist |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| DATM streams configuration | XML | Points DATM to forcing files |
| `user_nl_datm` | Namelist | DATM configuration overrides |

## Procedure

1. **Select forcing dataset**: Common choices for CTSM:
   - **GSWP3** (1901–2014): Global, 0.5°, 3-hourly — default for CTSM
   - **CRU-NCEP** (1901–2016): Global, 0.5°, 6-hourly
   - **CRUJRA** (1901–2019): Global, 0.5°, 6-hourly
   - Custom single-point forcing (NetCDF or tower data)

2. **Configure DATM in case**:
   ```bash
   # In the CTSM case directory
   ./xmlchange DATM_CLMNCEP_YR_START=2000
   ./xmlchange DATM_CLMNCEP_YR_END=2010
   ./xmlchange DATM_CLMNCEP_YR_ALIGN=2000
   ```

3. **Single-point custom forcing**: For tower sites with observed meteorology:
   ```bash
   # Create forcing NetCDF from tower CSV
   # Variables must use DATM names and units
   # Add to user_nl_datm:
   #   stream_fldfilename_datm = '/path/to/custom_forcing.nc'
   ```

4. **CO₂ concentration**: Set in `user_nl_clm`:
   ```
   co2_ppmv = 400.0
   co2_type = 'constant'
   ```
   Or use time-varying CO₂:
   ```
   co2_type = 'diagnostic'
   ```

## Verification

- [ ] Temperature values are in Kelvin (typical range: 220–320 K)
- [ ] Precipitation is in mm/s (NOT mm/day — max realistic: ~0.05 mm/s = 180 mm/hr)
- [ ] Shortwave radiation is non-negative and ≤ solar constant (~1361 W/m²)
- [ ] Longwave radiation is positive (typical range: 100–500 W/m²)
- [ ] Specific humidity is in kg/kg (NOT g/kg — typical range: 0.001–0.025 kg/kg)
- [ ] Surface pressure is in Pa (typical: 85000–105000 Pa, NOT hPa)
- [ ] Forcing time period covers or exceeds simulation period

## Traps

| Trap ID | Description | Detection |
|---------|-------------|-----------|
| dt_005 | Temperature in °C instead of K | Range check (values < 100 = °C) |
| dt_006 | Precipitation in mm/day instead of mm/s | Range check (max > 1 = mm/day) |
| dt_007 | Radiation in MJ/m²/day instead of W/m² | Range check (max < 50 = MJ) |
| dt_012 | CO₂ in mol/mol instead of ppmv | Magnitude check |

### Critical: Unit Conversion Chain

The most dangerous trap is the **unit conversion chain** from raw forcing data to
DATM-expected units. Each step can introduce a silent factor error:

```
Raw data (various)
  → Temperature:  °C + 273.15 = K
  → Precipitation: mm/day ÷ 86400 = mm/s    (86400 seconds/day)
  → Radiation:     MJ/m²/day × 1e6 / 86400 = W/m²
  → Pressure:      hPa × 100 = Pa
  → Humidity:      g/kg ÷ 1000 = kg/kg
  → Humidity:      RH (%) → q (kg/kg) via Tetens formula
```

Missing any one conversion produces a simulation that **runs without errors**
but produces physically meaningless results.

## Example

**Scenario**: Configure GSWP3 forcing for a tropical site at BCI, Panama,
for the period 2000–2010.

```bash
cd ~/cases/bci_fates

# Set forcing period
./xmlchange DATM_CLMNCEP_YR_START=2000
./xmlchange DATM_CLMNCEP_YR_END=2010

# Set CO₂ at modern levels
cat >> user_nl_clm << 'EOF'
co2_ppmv = 390.0
co2_type = 'constant'
EOF
```

**Verification**: After the run, check that FATES received reasonable forcing
by examining the `RAIN` and `TBOT` variables in the CLM history output. If
GPP is zero everywhere, the most likely cause is a forcing unit error.
