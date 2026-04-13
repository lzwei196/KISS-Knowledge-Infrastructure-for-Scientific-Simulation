# Stage 1: River Network Connectivity

## Purpose

Build the river network topology files that RAPID needs to route flows through a
basin. RAPID requires two CSV files:

1. **rapid_connect_file**: Full connectivity matrix listing each reach, its
   downstream reach, number of upstream reaches, and upstream reach IDs.
2. **riv_bas_id_file**: Ordered list of reach IDs in the simulation subbasin.

These files define the sparse network matrix `ZM_Net` used in the Muskingum
routing linear system.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| River network shapefile | SHP/GeoJSON | NHDPlus, MERIT-Hydro, HydroSHEDS | Polyline features with reach IDs and flow direction |
| Reach attributes | CSV/DBF | Same source | Length (m), downstream ID, Pfafstetter codes |
| Basin boundary | SHP/GeoJSON | User-defined | Polygon to clip the full network |

## Outputs

| Output | Format | Variables | Description |
|--------|--------|-----------|-------------|
| rapid_connect.csv | Space-delimited CSV | reach_id, down_id, n_up, up_id_1, ..., up_id_n | Network connectivity |
| riv_bas_id.csv | One ID per line | reach_id | Subbasin reach list |
| IS_riv_tot | Integer | — | Total reaches in full domain |
| IS_riv_bas | Integer | — | Reaches in subbasin |
| IS_max_up | Integer | — | Maximum upstream reach count |

## Procedure

1. **Load the river network** from NHDPlus (COMID field), MERIT-Hydro (COMID),
   or HydroSHEDS (HYRIV_ID).

2. **Identify the basin outlet** reach and trace upstream to define the subbasin.

3. **Build connectivity**: For each reach, find its downstream reach from the
   `NextDownID` or `TOCOMID` attribute. Count upstream reaches by inverting
   the downstream relationship.

4. **Write rapid_connect.csv**: One line per reach in the FULL domain:
   ```
   74120836  74120842  2  74120830  74120834
   ```
   Meaning: reach 74120836 flows into 74120842, has 2 upstream reaches.

5. **Write riv_bas_id.csv**: List of reach IDs in the simulation subbasin,
   one per line. Order must match the Vlat NetCDF `rivid` dimension.

6. **Verify counts**: `IS_riv_tot` = lines in rapid_connect.csv, `IS_riv_bas`
   = lines in riv_bas_id.csv.

## Verification

```bash
# Count reaches
wc -l rapid_connect.csv riv_bas_id.csv

# Check maximum upstream count
awk '{print $3}' rapid_connect.csv | sort -n | tail -1

# Verify all riv_bas_id entries exist in rapid_connect
comm -23 <(sort riv_bas_id.csv) <(awk '{print $1}' rapid_connect.csv | sort) | wc -l
# Should be 0
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Mismatched reach IDs | FATAL | If riv_bas_id contains IDs not in rapid_connect, RAPID segfaults during matrix assembly (dt_004) |
| Wrong IS_max_up | FATAL | If IS_max_up in namelist < actual max upstream count, RAPID reads past array bounds |
| Outlet not marked | SILENT | Outlet reach must have downstream_id = 0; if not, flow leaves the domain silently |
| Duplicate reach IDs | FATAL | Each reach must appear exactly once in rapid_connect |
| Wrong reach order | SILENT | riv_bas_id ordering must match Vlat NetCDF rivid dimension; mismatch causes silently wrong routing |

## Example

For a small 5-reach network where reach 5 is the outlet:

```
# rapid_connect.csv
1  3  0
2  3  0
3  4  2  1  2
4  5  1  3
5  0  1  4

# riv_bas_id.csv
1
2
3
4
5
```

The `IS_max_up = 2` (reach 3 has 2 upstream reaches).
