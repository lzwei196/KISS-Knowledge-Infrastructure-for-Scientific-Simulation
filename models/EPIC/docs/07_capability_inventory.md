# Stage 07 — Capability inventory

EPIC 1102 is a general-purpose field-scale agro-ecosystem model. Every
capability in this table has a matching configuration pathway and an
output-parser entry.

| #  | Capability                                  | How to configure                                   | Output location                 |
|----|---------------------------------------------|----------------------------------------------------|---------------------------------|
| 1  | Crop growth (150+ crops)                    | `select_crop.py` + `build_opc_file.py --crop NAME` | `.ACY` YLDG, BIOM, HI           |
| 2  | Crop rotation (multi-year)                  | `build_opc_file.py` (multi op blocks)              | `.ACY` rows per RT#/year        |
| 3  | Soil water balance                          | `build_soil_file.py`                               | `.ANN` PET, ET, Q               |
| 4  | CN-curve runoff (SCS)                       | `.SIT` row 5 (CN2, slope)                          | `.ANN` Q                        |
| 5  | Percolation and deep drainage               | `.SOL` depth + Ksat                                | `.ANN` SSF, PRK, QDRN           |
| 6  | Water erosion (USLE, MUSLE, MUST)           | `.SIT` slope + P factor                            | `.ANN` MUSS, MUST, USLE         |
| 7  | Wind erosion                                | `.SIT` slope + WND file                            | `.ANN` AOF                      |
| 8  | Soil temperature                            | `.SOL` layers + latitude                           | `.DGN` SOLT                     |
| 9  | Soil organic C dynamics (CENTURY)           | `.SOL` org C + PARM1102                            | `.ACN`, `.ANN` YOC              |
| 10 | Nitrogen cycling (mineralization, denit)    | `.SOL` N pools + PARM1102                          | `.ANN` DN, NMN, GMN, NITR       |
| 11 | N2O emissions                               | PARM1102 denitrification                           | `.ANN` DN2O, VN2O               |
| 12 | Leaching (NO3, NH3, P)                      | `.SOL` + PARM1102                                  | `.ANN` QNO3, SNO3, YP           |
| 13 | Phosphorus cycling                          | `.SOL` P pools + FERT2012                          | `.ANN` YP, QAP, MNP             |
| 14 | Potassium dynamics                          | `.SOL` K pools                                     | `.ANN` YK, QSK, SSK             |
| 15 | Fertilization (inorganic + manure)          | FERT2012.DAT + `.OPC` fert op                      | `.ACY` FTN/FTP/FTK              |
| 16 | Tillage (30+ implements)                    | TILLCOM.DAT + `.OPC` till op                       | `.DSL` bulk density updates     |
| 17 | Pesticide fate and transport                | PESTCOM.DAT + `.OPC` spray op                      | `.ANN` PSTF                     |
| 18 | Irrigation (auto or scheduled)              | `configure_irrigation.py`                          | `.ANN` IRGA                     |
| 19 | Liming                                      | `.OPC` + PARM1102                                  | `.ANN` LIME                     |
| 20 | Crop residue dynamics (burn, graze, plow)   | `.OPC` ops                                         | `.ANN` RSDC, BURC, BURN         |
| 21 | Grazing                                     | `.OPC` graze op                                    | `.DGZ` daily grazing            |
| 22 | Weather generation (backfill missing days)  | `.WP1 + .WND + EPICCONT` flags                     | internal; shown in `.OUT`       |
| 23 | CO2 fertilization                           | `.SIT` CO2 col (line 4)                            | `.ANN` NPPC                     |
| 24 | Snow accumulation and melt                  | `.DLY tmax/tmin` + PARM1102                        | `.ANN` SNOF, SNOM               |
| 25 | Auto-calibration parameters                 | edit PARM1102.DAT (64 globals)                     | affects all outputs             |

## Calibration

`PARM1102.DAT` contains 64 global calibration parameters (root growth,
N mineralization rate, denitrification rate, ...). Shipped values are
Texas A&M Blackland defaults. To calibrate, copy the template, edit
specific rows, point your workspace at the modified copy. See
`PARM1102.TXT` for parameter names.

## Output selection

`PRNT1102.DAT` controls which output files EPIC writes and which
variables go into each. The shipped template enables the commonly
useful outputs. To add columns, consult `PARM1102.TXT` for variable
index codes. Do NOT blank the file (triplet EPIC_014).
