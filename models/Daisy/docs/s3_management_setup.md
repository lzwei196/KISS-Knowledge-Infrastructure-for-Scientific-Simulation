# S3: Management and Setup Configuration

## Purpose

Create the main Daisy `.dai` setup file that combines weather, soil, crop management, and output specifications into a complete simulation definition.

## Inputs

| Input | Source | Format | Required |
|-------|--------|--------|----------|
| Weather file | S1 output | `.dwf` | Yes |
| Soil definition | S2 output | `.dai` (defcolumn) | Yes |
| Crop parameters | Daisy lib/ | `crop.dai`, `dk-sbarley.dai`, etc. | Yes (via library) |
| Fertilizer defs | Daisy lib/ | `fertilizer.dai` | Yes (via library) |
| Tillage defs | Daisy lib/ | `tillage.dai` | Yes (via library) |
| Simulation period | User | Start/stop dates | Yes |
| Management plan | User | Crop rotation + operations | Yes |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `<site>.dai` | Daisy setup file | Complete simulation definition |

## Procedure

1. **Include library files** at the top of the `.dai` file:
   ```lisp
   (input file "tillage.dai")
   (input file "crop.dai")
   (input file "log.dai")
   (input file "my-soil.dai")
   ```

2. **Define the simulation program**:
   ```lisp
   (defprogram MySimulation Daisy
     (column MySite)
     (weather default "my-weather.dwf")
     (time 1990 1 1 1)     ; start date
     (stop 1995 1 1 1)     ; end date
     (manager activity ...) ; management
     (output ...))          ; logging
   ```

3. **Define management activities**:
   - `(wait_mm_dd M D)` — wait until month M, day D
   - `(wait (at YYYY M D H))` — wait until specific date
   - `(fertilize (TYPE (weight N [kg N/ha])))` — apply fertilizer
   - `(plowing)` — plow the field
   - `(seed_bed_preparation)` — prepare seed bed
   - `(sow "Crop Name")` — sow a crop
   - `(harvest "Crop Name" (stub H [cm]) (stem F))` — harvest crop
   - `(wait (or (crop_ds_after "Crop" 2.0) (mm_dd M D)))` — wait for maturity or date

4. **Define output logs**:
   - `harvest` — harvest events with yield and N
   - `"Field nitrogen" (when monthly)` — monthly N balance
   - `"Field water" (when monthly)` — monthly water balance
   - `"Soil nitrogen" (when daily)` — daily soil N profile
   - `"Soil water" (when daily)` — daily soil water profile
   - `"Crop" (crop "Name")` — crop development
   - `checkpoint` — save simulation state for restart

5. **Run directive**:
   ```lisp
   (run MySimulation)
   ```

## Verification

- [ ] All `(input file ...)` files are accessible (in working dir or Daisy lib/)
- [ ] Weather file path is correct and .dwf exists
- [ ] Column name matches defcolumn name in soil file
- [ ] Simulation dates are within weather data range
- [ ] Crop names match library definitions exactly (case-sensitive)
- [ ] Fertilizer types match library definitions
- [ ] Management timeline is chronologically ordered
- [ ] Start date allows warmup before first management action

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Crop name mismatch | "Unknown crop" error | Use exact names from crop.dai (e.g., "Spring Barley" not "spring barley") |
| Simulation starts after first action | Management action skipped | Set start date before first wait |
| Weather period too short | "No weather data" error | Extend .dwf or adjust simulation period |
| Missing library include | "Unknown component" error | Add `(input file "crop.dai")` etc. |
| Fertilizer N in wrong units | Too much/little N applied | Must be [kg N/ha] for mineral, [T w.w./ha] for organic |
| Organic fertilizer missing volatilization | All NH4 stays in soil | Add `(volatilization 5 [%])` for slurry |
| No output defined | Simulation runs but no .dlf files | Add `(output harvest ...)` section |
| Harvest before maturity | Low yield, crop still growing | Use `(wait (crop_ds_after "Crop" 2.0))` |

## Example

```lisp
;;; taastrup-barley.dai — Spring barley at Taastrup

(input file "tillage.dai")
(input file "crop.dai")
(input file "log.dai")
(input file "taastrup-soil.dai")

(defprogram TaastrupBarley Daisy
  (column Taastrup)
  (weather default "dk-taastrup.dwf")
  (time 1986 12 1 1)
  (stop 1988 4 1 1)
  (manager activity
    (wait (at 1987 3 20 1))
    (plowing)
    (wait (at 1987 4 5 1))
    (fertilize (N25S (weight 115 [kg N/ha])))
    (seed_bed_preparation)
    (sow "Spring Barley")
    (wait (or (crop_ds_after "Spring Barley" 2.0)
              (mm_dd 08 20)))
    (harvest "Spring Barley" (stub 8 [cm]) (stem 0.70)))
  (output harvest
    ("Field nitrogen" (when monthly))
    ("Field water" (when monthly))
    ("Crop" (crop "Spring Barley"))))

(run TaastrupBarley)
```
