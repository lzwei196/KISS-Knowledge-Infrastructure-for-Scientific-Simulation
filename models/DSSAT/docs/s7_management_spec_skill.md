# S7: Management Specification

## Purpose

Define all crop management operations (planting, irrigation, fertilization, tillage, residue application, harvest, and environment modifications) in the appropriate sections of the FileX experiment file, ensuring correct date sequencing, valid operation codes, and proper linkage to the treatment structure.

## Prerequisites

- [ ] S3 (FileX structure) completed: the experiment file exists with `*TREATMENTS`, `*CULTIVARS`, `*FIELDS`, and `*INITIAL CONDITIONS` sections.
- [ ] S5 (Weather) completed: simulation start date (SDATE) and weather coverage period are known.
- [ ] S6 (Initial Conditions) completed: ICDAT is set and soil state is initialized.
- [ ] The management schedule for the experiment is available (planting dates, fertilizer amounts, irrigation events, etc.).
- [ ] You know whether automatic or fixed-date management will be used (check IPLTI, IIRRI, IFERI switches in simulation controls).

## Inputs

| Parameter         | Type    | Source              | Description                                              |
|-------------------|---------|---------------------|----------------------------------------------------------|
| Management events | Various | Experiment protocol | Dates, amounts, methods for each operation               |
| SDATE             | YYDDD   | Simulation controls | Simulation start date (all operations must be >= SDATE)  |
| IPLTI             | CHAR*1  | Simulation controls | Planting method switch: R=reported, A=automatic          |
| IIRRI             | CHAR*1  | Simulation controls | Irrigation switch: R=reported, A=automatic, N=none, D=days|
| IFERI             | CHAR*1  | Simulation controls | Fertilizer switch: R=reported, A=automatic, N=none, D=days|

## Procedure

### Section 1: Planting Details (*PLANTING DETAILS)

#### Step 1.1: Write the Planting Header

Write the section header exactly as:
```
*PLANTING DETAILS
@P  PDATE   EDATE  PPOP  PPOE  PLME  PLDS  PLRS  PLRD  PLDP  PLWT  PAGE  PENV  PLPH  SPRL
```

Source reference: `OPTEMPXY2K.for` lines 436-438.

#### Step 1.2: Write the Planting Data Line

Write one data line per planting level. The `@P` level number must match the planting level referenced in the `*TREATMENTS` section.

Example:
```
 1  86076   86080   6.0   6.0     S     R  61.0     0   5.0   -99   -99   -99   -99   -99
```

#### Step 1.3: Define Each Field

| Field | Name                      | Units         | Valid Range       | Notes                                                    |
|-------|---------------------------|---------------|-------------------|----------------------------------------------------------|
| PDATE | Planting date             | YYDDD         | >= SDATE          | Must be within weather file coverage                     |
| EDATE | Emergence date            | YYDDD or -99  | > PDATE or -99    | Set to -99 to let model simulate emergence               |
| PPOP  | Plants per m2 at planting | plants/m2     | 0.1-100           | Depends on crop: maize 6-9, wheat 150-400, soybean 20-40|
| PPOE  | Plants per m2 at emergence| plants/m2     | 0.1-100           | Typically <= PPOP. Set equal to PPOP if unknown          |
| PLME  | Planting method           | Code          | S, T, P, N        | S=seed, T=transplant, P=pregerminated, N=nursery         |
| PLDS  | Planting distribution     | Code          | R, H, B           | R=rows, H=hills, B=broadcast                            |
| PLRS  | Row spacing               | cm            | 10-300            | Maize: 60-90, wheat: 15-25, soybean: 30-76              |
| PLRD  | Row direction             | degrees       | 0-360 or -99      | 0=N-S, 90=E-W. Set -99 if unknown                       |
| PLDP  | Planting depth            | cm            | 1-20              | Maize: 4-7, wheat: 3-5, soybean: 3-6                    |
| PLWT  | Planting material weight  | kg/ha or -99  | 0-50000           | Seed weight. Set -99 to use default                      |
| PAGE  | Planting material age     | days or -99   | 0-365             | Age of transplant. Set -99 for direct seeding            |
| PENV  | Planting temp environment | C or -99      | 0-50              | Nursery temperature for transplants. Set -99 if N/A      |
| PLPH  | Plants per hill           | count or -99  | 1-10              | Only for PLDS=H. Set -99 for row planting               |
| SPRL  | Sprout length             | cm or -99     | 0-30              | For potato/cassava. Set -99 for seed crops               |

#### Step 1.4: Planting Decision Rules

- **PDATE must be >= SDATE**: If PDATE < SDATE, the planting event will be missed and the model will never plant. This produces HWAH = 0 or -99.
- **PPOP and PPOE**: If PPOE > PPOP, this is physically impossible. Set PPOE <= PPOP.
- **Automatic planting (IPLTI = 'A')**: When auto-planting is enabled in simulation controls, the PDATE in the FileX becomes the earliest possible planting date (planting window start). The model triggers planting when soil moisture and temperature conditions are met. If conditions are never met, the simulation hangs indefinitely -- see S8 pitfalls.
- **Row spacing and plant population**: Verify internal consistency. For row planting: PPOP approximately equals 10000 / (PLRS * plant_spacing_in_row_cm). This relationship does not need to be exact but gross inconsistencies indicate errors.

---

### Section 2: Irrigation (*IRRIGATION AND WATER MANAGEMENT)

#### Step 2.1: Write the Irrigation Management Header

```
*IRRIGATION
@I  EFIR  IDEP  ITHR  IEPT  IOFF  IAME  IAMT
```

Source reference: `OPTEMPXY2K.for` lines 469-470. Note: the source writes `IEFF` but the variable name in the format is `EFIR`.

#### Step 2.2: Write the Irrigation Management Data Line

Example:
```
 1  .750    30    50   100 GS000 IR001  10.0
```

| Field | Name                      | Units    | Valid Range | Notes                                              |
|-------|---------------------------|----------|-------------|----------------------------------------------------|
| EFIR  | Irrigation efficiency     | fraction | 0.0-1.0     | 0.75 typical for sprinkler, 0.90 for drip          |
| IDEP  | Management depth          | cm       | 1-200       | Soil depth for auto-irrigation trigger              |
| ITHR  | Threshold for auto-irrig  | % AWC    | 1-100       | Below this available water %, irrigation triggered  |
| IEPT  | End point for auto-irrig  | % AWC    | 1-100       | Irrigate until this % AWC reached                   |
| IOFF  | End of auto-irrig stage   | Code     | GS000-GS999 | Growth stage code at which auto-irrig stops         |
| IAME  | Auto-irrig method code    | Code     | IR001-IR011 | Method for auto-irrigation events                   |
| IAMT  | Auto-irrig amount         | mm       | 0-500       | Fixed amount per auto event. 0 = compute from IEPT  |

#### Step 2.3: Write the Irrigation Event Data

Write the event header and data lines:
```
@I  IDATE  IROP IRVAL
 1  86080 IR001  50.0
 1  86100 IR004  25.0
```

| Field | Name                  | Units   | Valid Range | Notes                                              |
|-------|-----------------------|---------|-------------|----------------------------------------------------|
| IDATE | Irrigation date       | YYDDD   | >= SDATE    | Must be within simulation period                   |
| IROP  | Irrigation method     | Code    | See table   | Operation code defining how water is applied       |
| IRVAL | Irrigation amount     | mm/cm   | 0-500       | mm for most methods, cm for water table depth      |

#### Step 2.4: Irrigation Method Codes (IROP)

Source reference: `DETAIL.CDE` lines 526-536.

| Code  | Description                  | IRVAL Units | Typical Use                       |
|-------|------------------------------|-------------|-----------------------------------|
| IR001 | Furrow                       | mm          | Surface irrigation, row crops     |
| IR002 | Alternating furrows          | mm          | Water-saving furrow irrigation    |
| IR003 | Flood                        | mm          | Paddy rice, basin irrigation      |
| IR004 | Sprinkler                    | mm          | Overhead irrigation               |
| IR005 | Drip or trickle              | mm          | Micro-irrigation                  |
| IR006 | Flood depth                  | mm          | Set flood water depth (rice)      |
| IR007 | Water table depth            | cm          | Controlled drainage/sub-irrigation|
| IR008 | Percolation rate             | mm/day      | Rice paddy percolation control    |
| IR009 | Bund height                  | mm          | Rice bund height setting          |
| IR010 | Puddling                     | (flag)      | Rice-only; initiates puddling     |
| IR011 | Constant flood depth         | mm          | Maintain constant flood (rice)    |

**Decision point**: For upland crops, use IR001 (furrow), IR004 (sprinkler), or IR005 (drip). For paddy rice, use IR003/IR006 for flooding plus IR009 for bund height plus IR008 for percolation. IR007 is for water table management scenarios.

#### Step 2.5: Irrigation Validation

- All IDATE values must be >= SDATE and within the simulation period.
- For automatic irrigation (IIRRI='A'), the event data lines can be omitted; the model uses EFIR, IDEP, ITHR, IEPT, and IAME to schedule events.
- For reported irrigation (IIRRI='R'), each event must have a data line.
- EFIR must be > 0 and <= 1.0. If EFIR = 0, all applied water is lost. If EFIR is not set (left at default), efficiency may default to 1.0, overestimating water delivery.
- Total irrigation across the season should be physically plausible: 0-1500 mm for most crops.

---

### Section 3: Fertilizers (*FERTILIZERS (INORGANIC))

#### Step 3.1: Write the Fertilizer Header

```
*FERTILIZERS
@F  FDATE  FMCD  FACD  FDEP  FAMN  FAMP  FAMK  FAMC  FAMO  FOCD
```

Source reference: `OPTEMPXY2K.for` lines 491-493.

#### Step 3.2: Write Fertilizer Application Lines

Example:
```
 1  86076 FE005 AP001     5    60     0     0     0     0   -99
 1  86120 FE005 AP002    10    40     0     0     0     0   -99
```

Format reference (`OPTEMPXY2K.for` line 498):
```
FORMAT(I3,1X,I7,2(1X,A5),6(1X,F5.0),1X,A5)
```

#### Step 3.3: Define Each Field

| Field | Name                    | Units     | Valid Range | Notes                                           |
|-------|-------------------------|-----------|-------------|-------------------------------------------------|
| FDATE | Fertilizer date         | YYDDD     | >= SDATE    | Must be after simulation start                  |
| FMCD  | Fertilizer material     | Code      | See table   | Determines N, P, K content fractions            |
| FACD  | Application method      | Code      | See table   | How fertilizer is placed                        |
| FDEP  | Application depth       | cm        | 0-30        | 0 for surface, 5-15 for incorporated            |
| FAMN  | N amount applied        | kg N/ha   | 0-500       | Elemental N, not fertilizer weight              |
| FAMP  | P amount applied        | kg P2O5/ha| 0-500       | As P2O5, not elemental P                        |
| FAMK  | K amount applied        | kg K2O/ha | 0-500       | As K2O, not elemental K                         |
| FAMC  | Ca amount applied       | kg Ca/ha  | 0-500       | Usually 0 unless liming                         |
| FAMO  | Other elements          | kg/ha     | 0-500       | Micronutrients or S                             |
| FOCD  | Fertilizer other code   | Code      | -99         | Additional code, set -99 if unused              |

#### Step 3.4: Common Fertilizer Material Codes (FMCD)

Source reference: `DETAIL.CDE` lines 348-413.

| Code  | Material                        | Typical N%  | Notes                                  |
|-------|---------------------------------|-------------|----------------------------------------|
| FE001 | Ammonium nitrate                | 34% N       | Split N: half NH4, half NO3            |
| FE002 | Ammonium sulfate                | 21% N       | All NH4 form; also supplies S          |
| FE005 | Urea                            | 46% N       | Hydrolyzes to NH4; most common N source|
| FE006 | Diammonium phosphate (DAP)      | 18% N, 46% P2O5 | Supplies both N and P             |
| FE010 | Urea ammonium nitrate (UAN)     | 28-32% N    | Liquid fertilizer                      |
| FE014 | Triple superphosphate (TSP)     | 0% N, 46% P2O5  | P source only (DETAIL.CDE:361)    |
| FE016 | Potassium chloride (KCl, MOP)   | 0% N, 50% K     | K only (DETAIL.CDE:363; K by weight, FERCH048.SDA) |
| FE019 | Urea super granules (USG)       | 46% N       | Deep-placed urea for rice              |

**CRITICAL WARNING**: The FMCD code determines which nutrient is applied. Using FMCD=FE005 (urea) when you intended to apply P will result in N being applied instead of P. Always verify that FMCD matches the intended nutrient. If you need to apply both N and P, either use FE006 (DAP) or create two separate application lines.

#### Step 3.5: Application Method Codes (FACD)

Source reference: `DETAIL.CDE` lines 504-508.

| Code  | Description                  | FDEP Typical | Notes                                 |
|-------|------------------------------|--------------|---------------------------------------|
| AP001 | Broadcast, not incorporated  | 0            | Surface application                   |
| AP002 | Broadcast, incorporated      | 5-15         | Applied and tilled in                 |
| AP003 | Banded on surface            | 0            | Near-row surface application          |
| AP004 | Banded beneath surface       | 5-15         | Subsurface band placement             |
| AP005 | Applied in irrigation water  | 0            | Fertigation                           |

**Decision point for FDEP**: If FACD = AP001 or AP003, set FDEP = 0 (surface). If FACD = AP002 or AP004, set FDEP = 5-15 cm (depth of incorporation). If FDEP is inconsistent with FACD (e.g., AP001 with FDEP=10), the model uses FDEP, so the code overrides the physical meaning of the method.

#### Step 3.6: Fertilizer Validation

- All FDATE values must be >= SDATE and <= end of simulation.
- FDATE should be >= PDATE (fertilizer before planting is valid for pre-plant applications, but FDATE before SDATE is an error).
- Total FAMN across all applications should be physically plausible: 0-400 kg N/ha for most crops per season.
- The maximum number of management operations across ALL management sections (irrigation + fertilizer + tillage + etc.) is NAPPL = 9000 (defined in `ModuleDefs.for` line 51). Exceeding this causes array overflow.
- Automatic fertilization (IFERI='A'): The model applies N based on crop demand. Reported applications in the FileX are ignored when auto mode is active.
- For IFERI='D' (days after planting): FDATE is interpreted as days after planting, not YYDDD calendar dates.

---

### Section 4: Tillage (*TILLAGE)

#### Step 4.1: Write the Tillage Header

```
*TILLAGE
@T  TDATE TIMPL  TDEP
```

Source reference: `OPTEMPXY2K.for` lines 529-530.

#### Step 4.2: Write Tillage Event Lines

Example:
```
 1  86060 TI003  20.0
 1  86075 TI004  15.0
```

Format reference (`OPTEMPXY2K.for` line 536):
```
FORMAT (I3,1X,I7,1X,A5,1X,F5.1)
```

#### Step 4.3: Define Each Field

| Field | Name              | Units | Valid Range | Notes                               |
|-------|-------------------|-------|-------------|--------------------------------------|
| TDATE | Tillage date      | YYDDD | >= SDATE    | Must be within simulation period     |
| TIMPL | Implement code    | Code  | See table   | Defines mixing efficiency and depth  |
| TDEP  | Tillage depth     | cm    | 1-60        | Depth of soil disturbance            |

#### Step 4.4: Tillage Implement Codes (TIMPL)

Source reference: `DETAIL.CDE` lines 642-666.

| Code  | Description              | Typical TDEP (cm) | Mixing Efficiency |
|-------|--------------------------|--------------------|--------------------|
| TI001 | V-Ripper                 | 30-45              | Low                |
| TI002 | Subsoiler                | 30-60              | Low                |
| TI003 | Moldboard plow 20 cm     | 15-25              | High (inverts)     |
| TI004 | Chisel plow, sweeps      | 15-25              | Medium             |
| TI005 | Chisel plow, straight pt | 15-25              | Medium             |
| TI010 | Disk, double disk        | 8-15               | Medium             |
| TI018 | Blade cultivator         | 5-10               | Low                |
| TI025 | Drill, double-disk       | 3-5                | Very low           |

#### Step 4.5: Tillage Validation

- TDATE should typically be before PDATE (pre-plant tillage) or within the growing season for cultivation.
- TDEP should be physically reasonable for the implement.
- Multiple tillage passes are common: e.g., moldboard plow followed by disk followed by field cultivator.

---

### Section 5: Harvest Details (*HARVEST DETAILS)

#### Step 5.1: Write the Harvest Header

```
*HARVEST DETAILS
@H  HDATE  HSTG  HCOM HSIZE   HPC  HBPC
```

Source reference: `OPTEMPXY2K.for` lines 555-556.

#### Step 5.2: Write Harvest Data Lines

Example for maturity-based harvest:
```
 1    -99 GS000     H     S   100     0
```

Example for fixed-date harvest:
```
 1  86270 GS000     H     S   100     0
```

Format reference (`OPTEMPXY2K.for` line 560):
```
FORMAT(I3,1X,I7,3(1X,A5),2(1X,F5.0))
```

#### Step 5.3: Define Each Field

| Field | Name                    | Units     | Valid Range      | Notes                                            |
|-------|-------------------------|-----------|------------------|--------------------------------------------------|
| HDATE | Harvest date            | YYDDD/-99 | > PDATE or -99   | -99 = harvest at physiological maturity          |
| HSTG  | Growth stage at harvest | Code      | GS000-GS999/-99  | Growth stage trigger; GS000 = default            |
| HCOM  | Harvest component       | Code      | H, C, G, L, etc. | H=harvest product, C=canopy, G=grain, L=leaf     |
| HSIZE | Harvest size group      | Code      | S, M, L, A       | S=small, M=medium, L=large, A=all               |
| HPC   | Harvest percentage      | %         | 0-100            | Percent of component harvested                   |
| HBPC  | By-product percentage   | %         | 0-100            | Percent of by-product removed from field         |

#### Step 5.4: Harvest Decision Rules

- **HDATE = -99**: The model harvests at physiological maturity (MDAT). This is the most common setting for grain crops. The IHARI switch in simulation controls must be set to 'M' (at maturity) for this to work.
- **HDATE = specific date**: Use for determinate harvest timing (e.g., forage crops, sugarcane). The IHARI switch must be 'R' (reported date) or 'D' (days after planting).
- **HDATE < PDATE**: This is an error. The model cannot harvest before planting. This will produce no harvest output.
- **HDATE = last day of simulation**: Use when the crop does not reach maturity within the simulation period.
- **HPC = 100**: All harvestable product is removed (typical for grain crops).
- **HBPC = 0**: All crop residue (stover, straw) remains in the field. HBPC = 100 removes all residue.

---

### Section 6: Residues and Organic Fertilizer (*RESIDUES AND ORGANIC FERTILIZER)

#### Step 6.1: Write the Residues Header

```
*RESIDUES AND ORGANIC FERTILIZER
@R  RDATE  RCOD  RAMT  RESN  RESP  RESK  RINP  RDEP  RMET
```

Source reference: `OPTEMPXY2K.for` lines 504-505.

#### Step 6.2: Write Residue Application Lines

Example:
```
 1  86060 RE001  2000  1.20  0.10  0.50    50    15 CM001
```

Format reference (`OPTEMPXY2K.for` line 510):
```
FORMAT(I3,1X,I7,1X,A5,1X,I5,3(1X,F5.2),2(1X,F5.0),1X,A5)
```

#### Step 6.3: Define Each Field

| Field | Name                     | Units    | Valid Range | Notes                                     |
|-------|--------------------------|----------|-------------|--------------------------------------------|
| RDATE | Application date         | YYDDD    | >= SDATE    | Date residue is applied                    |
| RCOD  | Residue code             | Code     | RE001, etc. | Type of organic material                   |
| RAMT  | Residue amount           | kg/ha    | 0-50000     | Dry weight of organic material applied     |
| RESN  | Residue N concentration  | %        | 0-5         | N content of applied residue               |
| RESP  | Residue P concentration  | %        | 0-2         | P content of applied residue               |
| RESK  | Residue K concentration  | %        | 0-5         | K content of applied residue               |
| RINP  | Incorporation percentage | %        | 0-100       | Percent incorporated into soil             |
| RDEP  | Incorporation depth      | cm       | 0-30        | Depth of incorporation                     |
| RMET  | Residue method           | Code     | CM001, etc. | OM composition/placement method            |

---

### Section 7: Environment Modifications (*ENVIRONMENT MODIFICATIONS)

#### Step 7.1: Write the Environment Header

```
*ENVIRONMENT MODIFICATIONS
@E  ODATE  EDAY  ERAD  EMAX  EMIN ERAIN  ECO2  EDEW EWIND
```

Source reference: `OPTEMPXY2K.for` lines 541-542.

#### Step 7.2: Write Modification Lines

Each modification line adjusts weather variables starting from a given date. The adjustment consists of a one-character code (A=add, S=subtract, M=multiply, R=replace) followed by a numeric value.

Example (add 2 degrees to max temperature starting day 86100):
```
 1  86100 A  0.0 A  0.0 A  2.0 A  0.0 A  0.0 A    0 A  0.0 A  0.0
```

Format reference (`OPTEMPXY2K.for` line 549):
```
FORMAT(I3,1X,I7,5(1X,A1,F4.1),1X,A1,I4,2(1X,A1,F4.1))
```

#### Step 7.3: Modification Codes

Each weather variable has a pair: operation code + value.

| Column | Variable Modified       | Operation Codes                          |
|--------|------------------------|-----------------------------------------|
| EDAY   | Solar radiation (MJ/m2)| A=add, S=subtract, M=multiply, R=replace|
| ERAD   | Solar radiation adjust  | A=add, S=subtract, M=multiply, R=replace|
| EMAX   | Maximum temperature (C) | A=add, S=subtract, M=multiply, R=replace|
| EMIN   | Minimum temperature (C) | A=add, S=subtract, M=multiply, R=replace|
| ERAIN  | Rainfall (mm)           | A=add, S=subtract, M=multiply, R=replace|
| ECO2   | CO2 concentration (ppm) | A=add, S=subtract, M=multiply, R=replace|
| EDEW   | Dewpoint temperature (C)| A=add, S=subtract, M=multiply, R=replace|
| EWIND  | Wind speed (km/d)       | A=add, S=subtract, M=multiply, R=replace|

Use A with 0 for no modification. Use R to replace the weather file value entirely.

---

### Section 8: Cross-Section Validation

#### Step 8.1: Date Sequencing

Verify the following date order for ALL management events:
```
SDATE <= ICDAT
SDATE <= TDATE (tillage before planting, if applicable)
SDATE <= FDATE (pre-plant fertilizer, if applicable)
SDATE <= PDATE
PDATE <= FDATE (in-season fertilizer)
PDATE <= IDATE (irrigation events)
PDATE < HDATE (harvest must be after planting)
```

Any management event with a date before SDATE will be ignored by the model. Any fertilizer or irrigation event with a date before SDATE will not be applied -- this is the most common management specification error.

#### Step 8.2: Level Number Consistency

Every management section uses a level number (@P, @I, @F, @T, @H, @R, @E). These level numbers must match the corresponding columns in the `*TREATMENTS` section:
- Treatment column FL -> *FIELDS level
- Treatment column IC -> *INITIAL CONDITIONS level
- Treatment column PL -> *PLANTING DETAILS level
- Treatment column IR -> *IRRIGATION level
- Treatment column FE -> *FERTILIZERS level
- Treatment column TI -> *TILLAGE level
- Treatment column HA -> *HARVEST DETAILS level
- Treatment column RE -> *RESIDUES level
- Treatment column EN -> *ENVIRONMENT MODIFICATIONS level

If a treatment references level 2 for irrigation but only level 1 is defined, the model will either error or use default values.

#### Step 8.3: Operations Count Check

The maximum number of total management operations across all sections is NAPPL = 9000 (defined in `ModuleDefs.for` line 51). Count: number of irrigation events + number of fertilizer events + number of tillage events + number of chemical events + number of residue events + number of environment modification events. If this total exceeds 9000, the model will have array overflow errors.

For typical single-season experiments, this limit is never reached. For long-term daily irrigation experiments, be aware.

#### Step 8.4: Automatic Management Consistency

If automatic management switches are set in the simulation controls, the corresponding FileX sections serve different roles:

| Switch   | Value | FileX Section Behavior                                                    |
|----------|-------|---------------------------------------------------------------------------|
| IPLTI    | R     | PDATE is the actual planting date                                         |
| IPLTI    | A     | PDATE is the earliest possible planting date (window start)               |
| IIRRI    | R     | Each irrigation event in FileX is applied on its date                     |
| IIRRI    | A     | FileX irrigation events are ignored; model irrigates based on ITHR/IEPT   |
| IIRRI    | N     | No irrigation applied regardless of FileX content                         |
| IIRRI    | D     | IDATE is days after planting, not calendar date                           |
| IFERI    | R     | Each fertilizer event in FileX is applied on its date                     |
| IFERI    | A     | FileX fertilizer events are ignored; model fertilizes based on crop demand|
| IFERI    | N     | No fertilizer applied regardless of FileX content                         |
| IFERI    | D     | FDATE is days after planting, not calendar date                           |

**CRITICAL**: When IIRRI='A' or IFERI='A', the data lines in the FileX are not used. If you set up detailed irrigation schedules but forgot to change IIRRI from 'A' to 'R', none of your specified events will be applied.

## Expected Outputs

| Output                             | Format / Location                  | Verification                                                |
|------------------------------------|------------------------------------|-------------------------------------------------------------|
| Planting section in FileX          | `*PLANTING DETAILS` section        | PDATE >= SDATE; PLME/PLDS valid codes                       |
| Irrigation section in FileX        | `*IRRIGATION` section              | All IDATE >= SDATE; IROP valid codes; EFIR 0-1              |
| Fertilizer section in FileX        | `*FERTILIZERS` section             | All FDATE >= SDATE; FMCD and FACD valid codes               |
| Tillage section in FileX           | `*TILLAGE` section                 | All TDATE >= SDATE; TIMPL valid codes                        |
| Harvest section in FileX           | `*HARVEST DETAILS` section         | HDATE > PDATE or HDATE = -99                                 |
| MgmtEvent.OUT after simulation     | Working directory                  | Lists all management events as applied by the model          |

## Validation Checks

1. **Date ordering**: All management dates >= SDATE. Planting before irrigation and in-season fertilizer. Harvest after planting.
2. **Code validity**: All FMCD, FACD, IROP, TIMPL, PLME, PLDS codes exist in `DETAIL.CDE`.
3. **Level consistency**: Every level number referenced in `*TREATMENTS` has a corresponding definition in the management sections.
4. **Nutrient accounting**: Total N applied (sum of FAMN) matches experimental protocol. Cross-check: if FMCD=FE005 (urea), the N comes from FAMN, not FAMP.
5. **Post-run check**: Open `MgmtEvent.OUT` and verify that each management operation appears on the expected date. If an operation is missing, check date sequencing and switch settings.

## Common Pitfalls

| Pitfall                                          | Symptom                                            | Resolution                                                    |
|--------------------------------------------------|----------------------------------------------------|---------------------------------------------------------------|
| Fertilizer date before SDATE                     | Fertilizer not applied; low yield                  | Ensure all FDATE >= SDATE                                     |
| Wrong FMCD code (N instead of P)                 | Wrong nutrient applied; unexpected N response      | Verify FMCD against DETAIL.CDE; FE005=urea (N), FE014=TSP (P), FE016=KCl (K)|
| Harvest date before planting date                | No harvest; HWAH = 0 or -99                        | Set HDATE > PDATE or use -99 for maturity                     |
| IIRRI='A' but detailed schedule expected         | Auto-irrigation overrides FileX schedule           | Change IIRRI to 'R' for reported irrigation                   |
| EFIR not set (defaults to 1.0)                   | Overestimating water delivery                      | Explicitly set EFIR to 0.70-0.90 based on method              |
| Operations exceeding NAPPL=9000 limit            | Array overflow; unpredictable crash                | Reduce event count or aggregate small events                   |
| Level number mismatch                            | Model uses wrong management or default values      | Cross-check treatment table against section levels             |
| PPOE > PPOP                                      | Physically impossible; model may behave oddly      | Set PPOE <= PPOP                                               |
| Auto-planting never finds suitable conditions    | Simulation hangs indefinitely                      | Widen planting window or adjust temperature/moisture triggers  |
| IIRRI='D' but IDATE given as YYDDD              | Irrigation applied on wrong dates                  | For days-after-planting mode, IDATE = integer days, not YYDDD |
| Missing management section entirely              | Model uses defaults or errors; no events applied   | Add all required sections even if empty                        |
| Forgetting FDEP for incorporated fertilizer      | N placed on surface instead of at depth; volatilization | Set FDEP to match FACD; AP002/AP004 need FDEP > 0        |
