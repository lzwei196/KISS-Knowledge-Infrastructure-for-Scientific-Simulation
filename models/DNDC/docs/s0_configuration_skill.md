# S0 -- Configuration and Site Setup

## Purpose

Initialize a DNDCv.CAN v9.6.0 simulation by defining the site identity, geographic location,
simulation duration, climate input format, and atmospheric boundary conditions.  This stage
produces the header portion of the `.dnd` input file and determines how the model interprets
all subsequent climate data.

## Inputs

| Input | Source | Units / Format | Notes |
|---|---|---|---|
| Site name | User-defined string | Plain text (no spaces recommended) | Appears in output filenames |
| Latitude | Site coordinates | Decimal degrees (-90 to +90) | Controls daylength, solar angle, and snow/frost routines |
| Number of simulation years | Experiment design | Integer >= 1 | Must match the number of climate files supplied |
| Record daily results flag | User choice | 0 = off, 1 = on | Enables Day_* output files; increases disk use substantially |
| Climate format type | See climate file structure | Integer 0-8 (see S1 skill) | Must match the column layout of every climate `.txt` file |
| Use 1-year climate file for all years | User choice | Checkbox (0/1) | When enabled, the same single climate file is recycled for every simulation year |
| N concentration in rainfall | Literature / regional data | mg N/L or ppm | Typical range 0.2-2.0; default 0.5 |
| Atmospheric background NH3 | Literature / regional data | ug N/m3 | Default 0.06 |
| Atmospheric CO2 concentration | Literature / scenario | ppm | Default 360; current ambient ~420; set higher for RCP/SSP scenarios |
| Annual CO2 increase rate | Scenario design | ppm/yr | Set to 0 when using a MultiYear_CO2 file |
| MultiYear CO2 file path | Optional external file | Text file, one CO2 value (ppm) per line per year | Overrides fixed CO2 + annual increase when provided |
| Climate file path(s) | Prepared climate files | Text file path(s) | One file per simulation year unless single-file mode is on |

## Outputs

| Output | Description |
|---|---|
| `.dnd` file header section | Lines encoding site name, latitude, simulation years, climate format type, atmospheric concentrations |
| Climate file linkage | Path references embedded in the `.dnd` that the model reads at runtime |

## Procedure

1. **Choose a site identifier.** Use a short, descriptive name with no spaces (e.g.,
   `OTT_corn_2018`).  This string propagates into output directory names.

2. **Set latitude.** Enter the decimal latitude of the field site.  DNDC uses this internally
   for solar geometry and photoperiod calculations that drive crop phenology and
   evapotranspiration.

3. **Set the number of simulation years.**  This integer must equal:
   - the number of climate files provided (when using one-file-per-year mode), OR
   - any value >= 1 (when the single-file recycle flag is on).

4. **Enable or disable daily output recording.**  Set `Record daily results` to 1 only when
   you need sub-annual diagnostics (Day_Climate, Day_Crop, Day_SoilC, etc.).  For large
   batch runs leave it at 0 to save disk space.

5. **Select the climate format type** that matches your prepared climate files.  The type ID
   (0-8) tells DNDC which columns to expect.  See the S1 Climate Preparation skill for the
   full column specifications.  The most common choice for fully characterized forcing is
   **type 8**: `Jday MaxT(C) MinT(C) Prec(cm) Radiation(MJ/m2/day) WindSpeed(m/s) Humidity(%)`.

6. **Point to climate files.**  Use the `Select Climate Files` control or, when editing the
   `.dnd` by hand, write the absolute path on the designated line.  Naming convention is
   typically `<site><year>.txt` (e.g., `OTT2018.txt`).

7. **Set atmospheric chemistry parameters:**
   - `N concentration in rainfall`: 0.5 mg N/L is a reasonable North American default.
   - `Atmospheric background NH3`: 0.06 ug N/m3 default; increase near intensive
     livestock regions.
   - `Atmospheric CO2`: set to the desired concentration for the first simulation year.
   - `Annual CO2 increase rate`: use ~2.0 ppm/yr for a simple trend, or set to 0 and
     supply a `MultiYear_CO2` file for year-specific values.

8. **If using a MultiYear CO2 file**, provide the full path.  The file contains one CO2 value
   per line, one line per simulation year.  The model reads CO2(year_i) from line i.

9. **Accept / save** the climate tab configuration before moving to the Soil tab.

## Verification

- Open the saved `.dnd` in a text editor and confirm:
  - Site name string is present and correct.
  - Latitude value is numerically reasonable for the target location.
  - Number of simulation years matches the intended experiment length.
  - Climate format type integer matches the column structure of the linked climate files.
  - Climate file paths resolve to existing files on the filesystem.
  - CO2, N-deposition, and NH3 values are physically plausible.
- If a MultiYear CO2 file is specified, verify the file has at least as many lines as
  simulation years.
- Run the model for 1 year with daily output on and inspect `Day_Climate1` to confirm
  the climate driver was read correctly (temperature range, precipitation totals).

## Traps

| Trap | Consequence | Prevention |
|---|---|---|
| Climate format type does not match file columns | Model reads wrong columns silently; yields and fluxes are nonsensical | Always cross-check the type ID against the actual file header before running |
| Number of simulation years exceeds number of climate files | Model crashes or reads garbage data for missing years | Count climate files and match exactly |
| Spaces in site name or file paths | Windows/Wine path resolution failure | Use underscores; avoid Unicode characters |
| CO2 annual increase AND MultiYear file both active | Ambiguous CO2 trajectory; model may double-count | Set annual increase to 0 when a MultiYear file is provided |
| Latitude sign error (e.g., positive for Southern Hemisphere) | Inverted seasonality in daylength and crop phenology | Verify sign convention: positive = North, negative = South |
| Forgetting to click Accept before switching tabs | Changes are silently discarded in the GUI | Always click Accept/Save Changes on every tab |
| Single-file recycle flag left on unintentionally | Every year uses year-1 weather; trend analyses are meaningless | Disable the flag for multi-year transient simulations |

## Example

Configure a 3-year corn simulation at Ottawa, Canada (lat 45.38 N):

```
Site name:            OTT_corn_2018
Latitude:             45.38
Simulated years:      3
Record daily results: 1
Climate format:       8  (Jday, MaxT, MinT, Prec, Rad, Wind, Hum)
Climate files:        /data/climate/OTT2018.txt
                      /data/climate/OTT2019.txt
                      /data/climate/OTT2020.txt
Use 1 year file:      No

N in rainfall:        0.5   mg N/L
Background NH3:       0.06  ug N/m3
CO2 concentration:    410   ppm
Annual CO2 increase:  0     ppm/yr
CO2 file:             /data/climate/MultiYear_CO2.txt
```

The corresponding lines near the top of the `.dnd` file would encode these values in the
model's fixed line-by-line format.  After saving, verify by reopening the `.dnd` in a text
editor and confirming each parameter appears on its expected line number.
