# S3 -- Crop and Farming Management Configuration

## Purpose

Define the crop selection, growth parameters, rotation structure (time blocks), and all
farming management events (tillage, fertilization, manure, irrigation, grazing, controlled
drainage) for a DNDCv.CAN v9.6.0 simulation.  This skill produces the Cropping and
Farming Management Practices sections of the `.dnd` input file.

## Inputs

| Input | Source | Units / Format | Notes |
|---|---|---|---|
| Crop type and parameters | Agronomic knowledge / calibration | DNDC crop ID + growth params | See crop type table below |
| Rotation structure | Experiment design | Time blocks x years x crops | Must span all simulation years |
| Planting and harvest dates | Regional practice / field records | Month + Day | Harvest mode: 1 = same year, 2 = next year (winter crops) |
| Tillage events | Management records | Type, date, depth | Inversion vs. non-inversion |
| Fertilizer applications | Management records | kgN/ha per form | Up to multiple events per year |
| Manure amendments | Management records | kgC/ha, C/N, N forms | Includes type, method, timing |
| Irrigation events | Management records | cm water per event | Method: furrow, sprinkler, drip |
| Grazing schedule | Livestock management | Heads/ha, dates, hours/day | By animal type |
| Controlled drainage schedule | Water management | Date ranges, depth (m) | Requires dynamic water table |

## Outputs

| Output | Description |
|---|---|
| `.dnd` crop and management sections | All time blocks, crop parameters, and event schedules encoded in line-by-line format |

## Procedure

### Step 1 -- Select Crop Type

DNDC has 18+ built-in crop types:

| ID | Crop Type | Notes |
|---|---|---|
| 1 | Corn | Annual C4 grain |
| 2 | Winter wheat | Harvest mode 2 (next year) |
| 3 | Soybean | Legume; N-fixation index = 1 |
| 4 | Spring wheat | Annual C3 grain |
| 5 | Barley | Annual C3 grain |
| 6 | Oat | Annual C3 grain |
| 7 | Canola | Annual C3 oilseed |
| 8 | Potato | Tuber crop |
| 9 | Rice | Requires flooded conditions |
| 10 | Alfalfa | Perennial legume; has winterkill params |
| 11 | Grass / hay | Perennial; can be grazed or cut |
| 12 | Timothy | Perennial C3 grass |
| 13 | Corn silage | Whole-plant harvest |
| 14 | Flax | Annual C3 |
| 15 | Sunflower | Annual C3 |
| 16 | Dry bean | Annual legume |
| 17 | Sugar beet | Annual root crop |
| 18+ | Other / user-defined | Varies |

Each crop type has default parameters that can be overridden.

### Step 2 -- Configure Crop Parameters

Key parameters per crop:

| Parameter | Units | Typical Corn Value | Description |
|---|---|---|---|
| Max biomass production (Grain) | kgC/ha/yr | 5000-7000 | Maximum grain carbon |
| Max biomass production (Leaf) | kgC/ha/yr | 1000-2000 | Maximum leaf carbon |
| Max biomass production (Stem) | kgC/ha/yr | 1500-2500 | Maximum stem carbon |
| Max biomass production (Root) | kgC/ha/yr | 1500-2500 | Maximum root carbon |
| Biomass fraction (Grain/Leaf/Stem/Root) | 0-1 | 0.40/0.15/0.20/0.25 | Must sum to 1.0 |
| Biomass C/N (Grain/Leaf/Stem/Root) | ratio | 40/20/50/40 | Lower = more N-rich tissue |
| Annual N demand | kgN/ha/yr | 150-250 | Total crop N requirement |
| Thermal degree days for maturity | degree-days | 1200-1800 | Accumulated GDD to maturity |
| Water demand | g water/g DM | 200-400 | Transpiration efficiency |
| N fixation index | 0-1 | 0 (corn), 1 (soybean) | 0 = no fixation, 1 = full fixation |
| Optimum temperature | C | 25-30 | Peak photosynthetic efficiency |
| Maximum root length | m | 1.5-2.5 | Rooting depth in profile |
| Root density shape function | 1-8 | 5 | 1 = surface-concentrated, 8 = uniform |
| PGI grain filling stage | 0-1 | 0.5 | Plant growth index at which grain fill begins |
| LAI maximum | m2/m2 | 4-6 | Important for ET calculations |
| FrostKill temperature | C | -2 to -5 | Lethal temperature for cover crops |
| Fraction leaves+stems left after harvest | 0-1 | 0.05-0.5 | Residue returned to soil |

**Perennial crops (alfalfa)** have additional winterkill parameters:
- CHRMX: hardening rate (default 0.184)
- CDRMX: dehardening rate (default 0.82)
- cTMX: maximum cold tolerance (default -15.0 C)
- pDFMX: plant population death rate (default 0.108)

### Step 3 -- Build the Rotation / Time Block Structure

DNDC organizes multi-year management using **time blocks**.  Each time block defines:
- Number of years this rotation runs
- Number of unique crop-years within the block
- Management details for each crop-year

**Example:** A 3-year corn-soybean-corn rotation run for 6 simulation years:

| Time Block | Years in Block | Unique Years | Crops |
|---|---|---|---|
| Block 1 | 6 | 3 | Year 1: Corn, Year 2: Soybean, Year 3: Corn |

Or equivalently with 2 blocks:

| Time Block | Years in Block | Unique Years | Crops |
|---|---|---|---|
| Block 1 | 3 | 3 | Year 1: Corn, Year 2: Soybean, Year 3: Corn |
| Block 2 | 3 | 3 | Year 1: Corn, Year 2: Soybean, Year 3: Corn |

The total years across all blocks must equal the number of simulation years.

**IMPORTANT BUILD ORDER (GUI):** When using the graphical interface, follow this exact
sequence to avoid data corruption:
1. Build ALL time block structures first (set block counts and year counts) without
   entering crop/management data.
2. Verify the structure spans all simulation years.
3. Only then go back and fill in crop parameters and management events for each year.
4. Failure to follow this order can corrupt the `.dnd` file.

### Step 4 -- Define Tillage Events

| Parameter | Description |
|---|---|
| Number of tillage events | Per crop-year (0 or more) |
| Date (month, day) | When tillage occurs |
| Tillage type | Conventional, conservation, no-till |
| Depth (cm) | Tillage incorporation depth |

Inversion tillage (moldboard plow) has been improved in v9.6.0.  It physically inverts soil
layers, mixing surface residue into subsurface.

### Step 5 -- Define Fertilization

DNDC supports four fertilization modes:

**Manual fertilization:**
- Specify each application: date, method (surface/injection), depth (cm), and amount
  (kgN/ha) for each N form:
  - Urea, Anhydrous ammonia, Ammonium bicarbonate, Nitrate
  - Ammonium, Sulphate, Phosphate
- Multiple applications per year are supported.
- Units are **kgN/ha** for each individual form (not total).
- Application depth: surface (0 cm) or injection (specify depth in cm, e.g., 0.2 m = 20 cm).

**Auto-fertilization:**
- Urea is automatically applied at planting day at a rate determined by crop N demand and
  soil available N.
- Uses the built-in smart farmer algorithm that adjusts rates based on the last 10
  occurrences of that crop type in the rotation.

**Precision fertilization:**
- Urea is applied daily whenever N stress is detected.
- Results in many small applications tracking actual crop demand.

**Fertigation:**
- Fertilizer applied through irrigation water.
- Requires a separate fertigation schedule file.

**Enhanced efficiency options (all modes):**
- Controlled release fertilizer: specify days for total N release.
- Nitrification inhibitor: efficiency (0-1) and duration (days).
- Urease inhibitor: efficiency (0-1) and duration (days).

### Step 6 -- Define Manure Amendment

| Parameter | Units | Description |
|---|---|---|
| Applications per year | count | 0 or more events |
| Date (month, day) | -- | Application timing |
| Manure type | dropdown | Dairy, beef, swine, poultry, compost, biosolid (v9.6.0) |
| Solid C/N ratio | ratio | Carbon to nitrogen ratio of solid fraction |
| Organic C | kgC/ha | Total organic carbon applied |
| Organic N | kgN/ha | Total organic nitrogen applied |
| Urea and NH4 | kgN/ha | Mineral N in manure |
| NO3 | kgN/ha | Nitrate N in manure |
| Manure pH | pH | Affects NH3 volatilization |
| Manure dry matter % | % | Solid content |
| Application method | selection | Surface spread, Incorporation (over depth), Injection (at depth) |
| Depth | cm | For incorporation or injection methods |

### Step 7 -- Define Irrigation

**Event-based irrigation:**
- Number of events, each with date, amount (cm of water), and method.
- Methods: Furrow, Sprinkler, Drip (0 cm surface), Drip (15 cm subsurface).
- Subsurface irrigation via tile drains is also available.

**Index-based irrigation:**
- Irrigation index (0-1) triggers automatic irrigation when soil moisture drops below the
  threshold.

**Controlled drainage:**
- Number of drainage control periods.
- Each period: start date, end date, controlled drainage depth (m).
- Requires dynamic water table to be ON (water table = 0 in `.dnd`).

### Step 8 -- Define Grazing (Perennial Crops)

| Parameter | Units | Description |
|---|---|---|
| Number of grazing applications | count | Grazing periods per year |
| Start/end month and day | -- | Duration of each grazing period |
| Grazing hours per day | hours | 0-24 |
| Grazing intensity | heads/ha | By animal type: Dairy cow, Beef/veal, Sheep, Horse, Pig |
| Additional feed | kgC/head/day | Supplemental feed carbon |
| Feed C/N | ratio | C:N of supplemental feed |
| Excreta handling | selection | Deposit in field, collect and remove |
| Grazing impact on biomass regrowth | 0-1 | 1 = no stress, 0.1 = high stress |
| Fraction of live biomass C consumed | fraction | Per grazing event |
| Fraction of consumed C excreted | fraction | Returned to field |

**Biomass cutting** is configured separately from grazing:
- Number of cuts per year.
- Date and fraction of biomass removed for each cut.
- Can specify which plant parts are cut (grain, leaf, stem, root).

Livestock parameters are read from `DNDC\Library\Lib_livestock\Livestock_N.txt` files.
Input and output C/N fractions (milk, meat, urine, dung, respiration, enteric CH4) must
sum to 1.0.

## Verification

- Open the `.dnd` file in a text editor and verify:
  - Time block years sum to the total simulation years.
  - Each crop-year has the correct crop type ID.
  - Fertilizer amounts are in kgN/ha and are agronomically reasonable (e.g., corn:
    100-250 kgN/ha total, soybean: 0-30 kgN/ha).
  - Planting dates precede harvest dates (except harvest mode 2 for winter crops).
  - Biomass fractions sum to 1.0 for each crop.
- Run a 1-year simulation with daily output and verify:
  - Crop yield in summary output is in the expected range.
  - Planting and harvest appear on the correct Julian days in Day_Crop output.

## Traps

| Trap | Consequence | Prevention |
|---|---|---|
| **Time block years do not sum to simulation years** | Model crashes or skips years | Count explicitly; verify in text editor |
| Building time blocks out of order in GUI | `.dnd` structure gets corrupted | Build ALL block structure first, then fill details; or edit `.dnd` directly |
| Biomass fractions do not sum to 1.0 | Unaccounted or excess biomass; incorrect yield | Compute sum before saving |
| Fertilizer units confused (total N vs. per-form N) | Over- or under-fertilization | Each form field is kgN/ha for THAT form; total = sum of all forms |
| Harvest mode 1 for winter wheat | Model tries to harvest before maturity | Use harvest mode 2 (next year) for fall-planted crops |
| Auto-fertilizer with >10 unique crop types | Algorithm cannot track all crops | Limit to 10 or fewer unique crop types per rotation |
| N-fixation index left at 0 for legumes | Soybean/alfalfa gets no N fixation; severe N stress | Set to 1 for legumes |
| Manure application without specifying method | Default may not match intended practice; affects NH3 volatilization | Explicitly set surface/incorporation/injection |
| Controlled drainage without dynamic water table | Drainage settings are ignored silently | Ensure water table = 0 (ON) in soil configuration |
| LAI maximum set too low | Underestimated ET; water balance errors | Set LAI max to the known peak LAI for the crop type |
| Fraction of residue left in field = 0 | No residue return to soil; SOC depletion | Set to at least 0.05 unless modeling complete residue removal |

## Example

Configuring a 2-year corn-soybean rotation over 4 simulation years:

```
Time blocks: 1
  Block 1:
    Years in this block: 4
    Unique crop-years: 2

    Year 1 (Corn):
      Crop type:         1 (Corn)
      Planting:          Month 5, Day 10
      Harvest:           Month 10, Day 15
      Harvest mode:      1 (this year)
      Residue fraction:  0.5
      Max biomass:       Grain=5614  Leaf=1656  Stem=1656  Root=2246 kgC/ha/yr
      Biomass fraction:  Grain=0.01  Leaf=0.295 Stem=0.295 Root=0.4
      Thermal GDD:       1500
      N fixation:        0
      LAI max:           5

      Tillage:           1 event
        Event 1:         Month 5, Day 1, conventional, 20 cm

      Fertilization:     Manual, 1 application
        App 1:           Month 5, Day 27, surface, depth 0.2 m
                         Urea = 100 kgN/ha, all others = 0

    Year 2 (Soybean):
      Crop type:         3 (Soybean)
      Planting:          Month 5, Day 20
      Harvest:           Month 10, Day 5
      Harvest mode:      1
      N fixation:        1
      Fertilization:     None

      Tillage:           1 event
        Event 1:         Month 5, Day 10, conservation, 10 cm
```

This block repeats twice to fill the 4 simulation years (Year 1 = corn, Year 2 = soybean,
Year 3 = corn, Year 4 = soybean).
