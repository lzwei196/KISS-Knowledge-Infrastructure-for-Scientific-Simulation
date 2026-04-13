# Stage 3: Input File Assembly (HYDRO.IN)

## Purpose

Assemble the complete HydroTrend input file (`{PREFIX}.IN`) with all 47
parameter lines correctly formatted and in the correct units.

## Inputs

- Monthly climate statistics (from Stage 1)
- Basin physical parameters (area, relief, length)
- River hydraulic geometry coefficients
- Groundwater parameters
- Sediment transport formula selection and parameters

## Outputs

`{PREFIX}.IN`: 47-line ASCII file controlling the entire simulation.

## Procedure

### Line-by-line assembly

**Lines 1–4: Header and control**
```
Title of simulation                        1) TITLE
ON                                         2) ASCII output (ON/OFF)
./HYDRO_OUTPUT/                            3) Output directory
1                                          4) Number of epochs
```

**Line 5: Time control**
```
1908 1000 M                                5) Start_year  N_years  Timestep(D/M/S/Y)
```
- Timestep: D=daily, M=monthly averages, S=seasonal, Y=yearly
- The model always computes daily internally; timestep affects output averaging

**Lines 6–7: Grain sizes**
```
4                                          6) Number of grain sizes (1–10)
.2 .2 .25 .35                             7) Proportions (MUST sum to 1.0)
```

**Lines 8–9: Annual climate trends**
```
24.9 0.001 1.5                            8) T_start(°C) T_change(°C/yr) T_std(°C)
1.24 0.0002 0.05                          9) P_start(m/yr) P_change(m/yr²) P_std(m)
```

**Line 10: Rainfall distribution**
```
1.4 1.1 1                                 10) Mass_balance_coeff  Exponent  Range
```

**Line 11: Base flow**
```
0.0                                        11) Constant base flow (m³/s)
```

**Lines 12–23: Monthly climate (12 lines)**
```
Jan  24 1.98   5  2.22                    12) Month T_mean T_std P_mm P_std_mm
Feb  17 1.56  10  1.90                    ...
```
**UNITS**: Temperature in °C, precipitation in **mm** (model divides by 1000)

**Line 24: Lapse rate**
```
9.9                                        24) Lapse rate (°C/km)
```
Use -9999 for automatic global default. Model divides by 1000 to get °C/m.

**Line 25: Glacier ELA**
```
2500 0                                     25) ELA_start(m) ELA_change(m/yr)
```

**Line 26–28: Evaporation parameters**
```
0.15                                       26) Dry evaporation fraction (0–1)
-0.1 0.85                                 27) Canopy interception α(mm/d) β(-)
10 1                                       28) Evapotranspiration α(mm/d) β(-)
```
**UNITS**: α values in mm/d (model divides by 1000)

**Lines 29–30: Slope and bedload**
```
1e-3                                       29) Delta plain gradient (m/m)
1.0                                        30) Bedload rating term (- ; -9999=default 1.0)
```

**Line 31: Basin length**
```
100                                        31) Basin length (km)
```
**UNITS**: km (model multiplies by 1000 to get meters)

**Line 32: Reservoir**
```
0 d0                                       32) Volume(km³) param_type + drainage_area
```
- `a` + altitude(m): reservoir at given altitude
- `d` + area(km²): reservoir draining given area
- Volume 0 = no reservoir

**Lines 33–34: Hydraulic geometry**
```
0.0504 0.5595                             33) Velocity coeff(k) exponent(m): v=kQ^m
27.466 0.2368                             34) Width coeff(a) exponent(b): w=aQ^b
```
Depth is derived: `d = (1/ka)Q^(1-m-b)`. Exponents must satisfy m+b+f=1.

**Line 35: Average velocity**
```
1.2                                        35) Average river velocity (m/s)
```

**Lines 36–37: Groundwater**
```
1.5e+8 1.5e+4                             36) GW_max(m³) GW_min(m³)
1.2e+8                                    37) Initial GW storage (m³)
```

**Lines 38–39: Subsurface flow**
```
2000 1.3                                   38) Storm flow coeff(m³/s) exponent(-)
250                                        39) Saturated hydraulic conductivity (mm/day)
```
**UNITS**: Ko in mm/day (model divides by 1000)

**Line 40: Location**
```
55.5 68.25                                 40) Longitude Latitude (decimal degrees)
```

**Lines 41–42: Outlets**
```
1                                          41) Number of outlets (1=single; u=variable)
1                                          42) Fraction per outlet (sum=1 if >1 outlet)
```

**Lines 43–47: Events and sediment**
```
n1                                         43) Event spec: n#=events/yr, q#=Qpeak threshold
0.249                                      44) Sediment filter (0–0.9, only if outlets>1)
2                                          45) Formula: 0=QRT, 1=ART, 2=BQART
0.3                                        46) Lithology factor (0.3–3, BQART only)
1                                          47) Anthropogenic factor (0.5–8, BQART only)
```

## Verification

- [ ] File has exactly the right number of lines for the epoch count
- [ ] Grain size proportions sum to exactly 1.0
- [ ] Monthly precip is in mm (not m)
- [ ] Annual precip is in m/yr (not mm/yr)
- [ ] Lapse rate is in °C/km (not °C/m)
- [ ] Basin length is in km (not m)
- [ ] Hydraulic conductivity is in mm/day (not m/day)
- [ ] Canopy/ET α values are in mm/d (not m/d)
- [ ] Hydraulic geometry exponents: m + b + f = 1
- [ ] GW initial is between GW_min and GW_max
- [ ] Output directory path ends with /
- [ ] ASCII output flag is ON for human-readable output

## Traps

### Double unit conversion
The most common error is pre-converting units that the model converts
internally. For example, providing lapse rate in °C/m when the model
expects °C/km and divides by 1000 itself.

### Grain size sum ≠ 1
The model does NOT normalize grain fractions. If they sum to 0.99 or 1.01,
total sediment mass is not conserved.

### Missing trailing slash on output directory
Line 3 (output directory) must end with `/`. Without it, output files may
be written to unintended locations or the model may fail silently.

## Example

See the Greenland Fjord test case in `source/repo/data/input/HYDRO.IN` for
a complete working example.
