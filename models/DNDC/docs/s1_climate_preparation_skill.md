# S1 -- Climate Data Preparation

## Purpose

Convert raw meteorological data from global forcing datasets (CMFD, MSWX, NASA POWER,
ERA5, station records) into the daily text file format required by DNDCv.CAN v9.6.0.  This
skill covers unit conversions, file format selection, naming conventions, and the optional
MultiYear CO2 file.

## Inputs

| Input | Source | Typical Native Units | Notes |
|---|---|---|---|
| Daily maximum air temperature | Forcing dataset | K or C | Must be converted to Celsius |
| Daily minimum air temperature | Forcing dataset | K or C | Must be converted to Celsius |
| Daily precipitation | Forcing dataset | mm/day or kg/m2/s | **Must be converted to cm** |
| Shortwave radiation | Forcing dataset | W/m2 (mean) or MJ/m2/day | Must be in MJ/m2/day |
| Wind speed | Forcing dataset | m/s | At measurement or 10 m height |
| Relative humidity | Forcing dataset | % (0-100) or fraction (0-1) | Must be % for DNDC |
| Mean temperature (for format types 0-1) | Forcing dataset | C | Only needed for simplified formats |
| Annual CO2 concentrations | Scenario / observations | ppm | For MultiYear_CO2 file |

## Outputs

| Output | Description |
|---|---|
| One climate `.txt` file per simulation year | Space-delimited daily records, 365 or 366 lines (+ optional header) |
| MultiYear_CO2.txt (optional) | One CO2 concentration (ppm) per line, one line per year |

## Procedure

### Step 1 -- Identify the Target Climate Format Type

DNDC supports 9 format types (0-8).  The format type chosen here must match the value set
in the S0 Configuration skill.

| Type | Columns |
|---|---|
| 0 | Jday, MeanT(C), Prec(cm) |
| 1 | Jday, MaxT(C), MinT(C), Prec(cm) |
| 2 | Jday, MaxT(C), MinT(C), Prec(cm), Radiation(MJ/m2/day) |
| 3 | Jday, MaxT(C), MinT(C), Prec(cm), WindSpeed(m/s) |
| 4 | Jday, MaxT(C), MinT(C), Prec(cm), WindSpeed(m/s), Radiation(MJ/m2/day), Humidity(%) |
| 5 | Jday, MaxT(C), MinT(C), Prec(cm), WindSpeed(m/s), Humidity(%) |
| 6 | Jday, MaxT(C), MinT(C), Prec(cm), Humidity(%) |
| 7 | Jday, MaxT(C), MinT(C), Prec(cm), Radiation(MJ/m2/day) |
| 8 | Prec(cm), Radiation(MJ/m2/day), WindSpeed(m/s), Humidity(%) |

**Recommendation:** Use **type 4** or **type 8** whenever all variables are available.  Providing
radiation, wind, and humidity allows DNDC to compute Penman-Monteith ET internally
instead of relying on empirical proxies.

### Step 2 -- Apply Unit Conversions

**Temperature (C):**

```
T_celsius = T_kelvin - 273.15
```

If the source is already in Celsius, no conversion is needed.  Verify by checking that values
fall within a physically plausible range for the site (e.g., -40 to +45 C).

**Precipitation (cm):**

```
Prec_cm = Prec_mm / 10.0
```

> **CRITICAL TRAP: DNDC expects precipitation in centimeters, NOT millimeters.**
> Failing to divide by 10 inflates precipitation by 10x, causing waterlogging, unrealistic
> runoff, depressed yields, and wildly overestimated N leaching.

If the source provides a flux rate (kg/m2/s), first convert to mm/day:

```
Prec_mm = flux_kg_m2_s * 86400.0
Prec_cm = Prec_mm / 10.0
```

**Radiation (MJ/m2/day):**

```
Rad_MJ = Rad_W_m2 * 0.0864
```

This conversion applies when the source provides mean daily shortwave irradiance in W/m2.
The factor is `0.001 (MJ/J) * 86400 (s/day) = 0.0864`.

If the source already provides daily accumulated radiation in MJ/m2/day, no conversion
is needed.

If the source provides radiation in J/m2/day:

```
Rad_MJ = Rad_J / 1e6
```

**Wind speed (m/s):**

Most datasets already provide m/s.  If the source is in km/h:

```
Wind_ms = Wind_kmh / 3.6
```

**Humidity (%):**

DNDC expects relative humidity as a percentage (0-100).  If the source provides a fraction
(0-1):

```
RH_pct = RH_frac * 100.0
```

If the source provides specific humidity (kg/kg), convert through saturation vapor pressure
using the Magnus formula at the daily mean temperature.

### Step 3 -- Assemble Daily Records

For each simulation year, create one text file containing 365 lines (366 for leap years).
Each line corresponds to one Julian day (Jday 1 = January 1).

Columns are **space-delimited**.  No header line is required (the model reads raw numeric
rows).  Field widths are flexible as long as values are separated by whitespace.

Example line for type 4 (Jday 150, 28.3 C max, 12.1 C min, 0.15 cm precip, 21.4 MJ/m2/day
radiation, 2.3 m/s wind, 65% humidity):

```
150  28.3  12.1  0.15  2.3  21.4  65.0
```

### Step 4 -- Name Files by Convention

Use a consistent naming pattern.  DNDC reads file paths from the `.dnd`, so the name itself
is not parsed, but a clear convention prevents operator errors in multi-decade runs:

```
<SiteName><Year>.txt
```

Examples:

```
OTT2018.txt
OTT2019.txt
OTT2020.txt
```

All files for a given simulation should reside in the same directory.

### Step 5 -- Create the MultiYear CO2 File (Optional)

If CO2 concentration varies across simulation years (e.g., historical transient or RCP/SSP
scenario), create a plain text file with one value per line:

```
399.4
403.1
407.2
```

Line 1 = year 1 of the simulation, line 2 = year 2, and so on.  The file must contain at
least as many lines as the number of simulation years.

Save as `MultiYear_CO2.txt` (or any name) and reference its full path in the S0
configuration.

### Step 6 -- Validate the Prepared Files

For each climate file:

1. Count the number of data lines.  Must be 365 (non-leap) or 366 (leap).
2. Verify Jday sequence runs from 1 to 365/366 without gaps or duplicates.
3. Spot-check unit ranges:
   - MaxT > MinT for every day.
   - Precipitation values are in the 0-5 cm range for most days (values > 10 cm/day
     are extreme events -- verify against source).
   - Radiation is 0-35 MJ/m2/day.
   - Wind speed is 0-25 m/s.
   - Humidity is 0-100%.
4. Confirm no missing values or NaN entries.  DNDC does not handle missing data
   gracefully.

## Verification

- Compute annual precipitation totals from the prepared files (sum of Prec_cm column)
  and compare against known annual totals for the site/dataset.  A 10x discrepancy
  immediately flags the mm-vs-cm error.
- Plot daily temperature and radiation time series; check for seasonal patterns consistent
  with the latitude and hemisphere.
- Run a 1-year DNDC simulation with daily output and compare the `Day_Climate1` output
  against the input file to confirm all columns were parsed correctly.

## Traps

| Trap | Consequence | Prevention |
|---|---|---|
| **Precipitation in mm instead of cm** | 10x too much water; waterlogging, yield collapse, extreme leaching | Always divide mm by 10; verify annual totals (e.g., ~80 cm for temperate sites, not 800) |
| Radiation in W/m2 instead of MJ/m2/day | ~12x too high radiation; unrealistic ET and crop growth | Multiply W/m2 by 0.0864; check that values do not exceed ~35 MJ/m2/day |
| Temperature in Kelvin instead of Celsius | ~300 C temperatures crash the model or produce nonsense | Subtract 273.15; spot-check that values are in the -50 to +50 C range |
| Humidity as fraction (0-1) instead of percent | Near-zero humidity; extreme evaporative demand | Multiply by 100; verify range is 0-100 |
| Wrong number of days in file | Model reads into next year's data or crashes | Count lines; handle leap years explicitly |
| Missing or NaN values | Unpredictable model behavior; silent corruption of results | Screen for NaN/NA/missing before writing; gap-fill or interpolate |
| Climate format type mismatch with actual columns | Model maps wrong variable to wrong column | Double-check the type ID in S0 against the actual file layout |
| Leap year file used for non-leap year (or vice versa) | Day 366 is read as Day 1 of next year, shifting all subsequent data | Match file day count to the calendar year |
| BOM or encoding issues (UTF-8 BOM, Windows line endings under Wine) | Parser may fail on first line or insert invisible characters | Save as plain ASCII or UTF-8 without BOM; use Unix line endings (LF) |

## Example

Converting NASA POWER daily data for Ottawa, 2018:

```python
import pandas as pd

df = pd.read_csv("nasa_power_ottawa_2018.csv")

# Unit conversions
df["MaxT_C"]   = df["T2M_MAX"]                # already Celsius in POWER
df["MinT_C"]   = df["T2M_MIN"]                # already Celsius
df["Prec_cm"]  = df["PRECTOTCORR"] / 10.0     # mm -> cm  (CRITICAL)
df["Rad_MJ"]   = df["ALLSKY_SFC_SW_DWN"]      # POWER provides MJ/m2/day directly
df["Wind_ms"]  = df["WS2M"]                   # m/s at 2 m
df["RH_pct"]   = df["RH2M"]                   # already %

# Assemble type 4 format: Jday MaxT MinT Prec Wind Rad Hum
with open("OTT2018.txt", "w") as f:
    for i, row in df.iterrows():
        jday = i + 1
        f.write(f"{jday}  {row.MaxT_C:.1f}  {row.MinT_C:.1f}  "
                f"{row.Prec_cm:.4f}  {row.Wind_ms:.1f}  "
                f"{row.Rad_MJ:.2f}  {row.RH_pct:.1f}\n")

# Validation
assert len(df) == 365, "Expected 365 days for 2018"
assert (df["MaxT_C"] >= df["MinT_C"]).all(), "MaxT must be >= MinT"
assert df["Prec_cm"].sum() < 200, "Annual precip > 200 cm is suspect"
print(f"Annual precipitation: {df['Prec_cm'].sum():.1f} cm")
```

Expected output for a temperate site: annual precipitation around 80-100 cm (NOT 800-1000).
