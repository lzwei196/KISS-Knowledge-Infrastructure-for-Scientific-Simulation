# S0 — Configuration

## Purpose

Define the simulation scope: which crop to model, at which location, for what
time period, and under what management regime. This is the planning stage that
determines all downstream data requirements.

## Inputs

| Input               | Format     | Example                        |
|---------------------|-----------|--------------------------------|
| Crop type           | string    | Wheat, Maize, Canola, Sorghum  |
| Cultivar            | string    | Hartog, Pioneer_3153, Hyola42  |
| Site latitude       | decimal ° | -27.18                         |
| Site longitude      | decimal ° | 151.26                         |
| Simulation start    | YYYY-MM-DD| 2000-01-01                     |
| Simulation end      | YYYY-MM-DD| 2010-12-31                     |
| Sowing date/rules   | date or rules | Fixed: 2000-05-15 or Auto |
| Fertiliser plan     | kg N/ha   | 50 kg N at sowing              |
| Irrigation plan     | mm/event  | Rainfed or 25 mm weekly        |

## Outputs

- A written specification document capturing all parameters
- Decisions on data sources (weather: SILO, ERA5, CMFD; soil: APSoil, HWSD, SoilGrids)

## Procedure

1. **Select crop and cultivar**: The cultivar must exist in APSIM's built-in database.
   Run `apsim run --list-simulations` on a template file to verify available cultivars.
   Common cultivars by crop:
   - Wheat: Hartog, Gregory, Scout, Mace, Scepter
   - Maize: Pioneer_3153, Dekalb_XL82, A6640
   - Canola: Hyola42, Karoo
   - Sorghum: CSH13R, Buster

2. **Define location**: Record latitude and longitude in decimal degrees (WGS84).

3. **Set simulation period**: Start at least 3 months before sowing to allow
   soil water initialisation. End after harvest.

4. **Define management**: Choose sowing rules (fixed date vs. rainfall trigger),
   fertiliser plan, irrigation schedule.

5. **Choose data sources**: For weather, prefer local station data in .met format.
   For global coverage, use ERA5 or CMFD (requires unit conversion).

## Verification

- [ ] Cultivar name matches an APSIM built-in cultivar
- [ ] Latitude/longitude are within the expected geographic region
- [ ] Start date is at least 3 months before expected sowing
- [ ] End date is after expected harvest

## Traps

- **Wrong cultivar name**: APSIM crashes with an unhelpful error if the cultivar
  doesn't exist. Always verify against the crop's cultivar list. (dt_010)
- **Too-short simulation period**: If the simulation starts on the sowing date,
  initial soil water is unrealistic. Start 3+ months earlier.
- **Hemisphere confusion**: Southern hemisphere sowing is typically May-July for
  winter crops, October-December for summer crops. Northern hemisphere is the reverse.

## Example

```
Crop: Wheat
Cultivar: Hartog
Location: Dalby, QLD, Australia (-27.18°, 151.26°)
Period: 1992-01-01 to 1995-12-31
Sowing: Rainfall-triggered, May-July window, 25mm/7d trigger
Fertiliser: 50 kg N/ha as NO3 at sowing
Irrigation: Rainfed
Weather source: SILO (Dalby station 041023)
Soil source: APSoil (Black Vertosol, Dalby)
```
