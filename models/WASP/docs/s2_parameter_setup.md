# s2 Parameter setup (real engine): build a case .wif through EPA's API

## Purpose
Turn a working EPA `.wif` into a new case by changing listed values only, through
`wasptool.exe` (EPA's data API), so the binary `.wif` stays valid. The old surrogate parameter
doc is in `surrogate/`.

## Inputs
- Template: `test_cases/steady_state/inputs/SteadyState.wif` (EPA, sha256 checked)
- Weather CSV from s1
- Site and case values: depth, area, lat/lon, elevation, SOD, CBOD, initial DO and temperature

## Outputs
`<out-dir>/<name>.wif`, `<name>_commands.txt` (every API command, for audit) and
`<name>_case.json` (inputs, hashes, structure read from the template, read-back checks).

## Procedure
```bash
python tools/build_wasp_lake_case.py --weather weather_nasa_power.csv --start 2004-01-01 \
    --end 2014-12-31 --depth 12 --lat 41.95 --lon -81.55 --elev 174 --sod 0 --do0 13 \
    --temp0 2 --out-dir case --name erie_cb_surface
```
For any other edit use the general tool:
```bash
python tools/wasp_wif_api.py --wif in.wif --get GNUMSEG "GSYSNAME 3" GSEEDDATE
python tools/wasp_wif_api.py --wif in.wif --commands edits.txt --out out.wif
```

### Verified keywords (WASP 8.5.0)
| purpose | GET | PUT |
|---|---|---|
| load / save | — | `PWASPINIT`, `PLOADWIF f`, `PSAVEWIF f` |
| counts | `GNUMSEG`, `GNUMSYS`, `GNFIELD`, `GNINQ fld`, `GNOBC sys`, `GNOWK sys`, `GNPRINT`, `GMODELTYPE` | — |
| systems | `GSYSNAME i` (name, sys_key) | — |
| dates | `GSEEDDATE`, `GENDJULIAN` | `PSEEDDATE m d y`, `PSEEDTIME h m s`, `PENDJULIAN days` |
| step / print | `GMAXDT`, `GPRINTFUNC k` | `PMAXDT d`, `PPRINTFUNC k day value` |
| hydraulics | `GIQOPT`, `GFLOWTYPE s`, `GVOLUME s`, `GDMULT s` … | `PIQOPT n`, `PFLOWTYPE s n`, `PVOLUME s v`, `PDMULT/PDEXP/PVMULT/PVEXP s v`, `PINITIALDEPTH s d`, `PSEGLENGTH/PSEGWIDTH s v` |
| flows | `GNBRKQ f fn`, `GNOQFUNC f fn k` | `PNBRKQ f fn n`, `PNOQFUNC f fn k day q` |
| boundaries | `GNBFP sys bc`, `GBOUNDFUNC sys bc k` | `PNBFP sys bc n`, `PBOUNDFUNC sys bc k day v` |
| initial conc. | `GINITC sys seg` | `PINITC sys seg v` |
| constants | `GCONSTVALUEBYISC isc inst`, `GCONSTISUSED isc inst` | `PCONSTVALUEBYISC isc inst v`, `PCONSTISUSED isc inst 1` |
| segment params | `GCONSTPARAM seg isc inst`, `GPARAMISUSED isc inst` | `PCONSTPARAM seg isc inst v`, `PPARAMISUSED isc inst 1` |
| time functions | `GTFDESC isc inst`, `GNBRKTF isc inst`, `GBRKTF isc inst k`, `GTFISUSED isc inst` | `PNBRKTF isc inst n`, `PBRKTF isc inst k day v`, `PTFISUSED isc inst 1` |

ISC numbers and meanings come from the engine's own `C:\WASP8\wasp\etc\epa.sqlite`
(`constants`, `parameters`, `time_functions` tables, model 11).

## Verification
- `wasp_wif_api.py` checks that every PUT echo equals the requested value, that each command got
  a result block, and reloads the saved file.
- `build_wasp_lake_case.py` reads back seed date, flow option, depth, weather length and elevation.
- After the run, the `.OUT` echo must list every parameter and constant you set (dt_wasp_027).

## Traps
- **"used" flags**: a value with used = 0 is silently ignored (dt_wasp_027, dt_wasp_028).
- **seed date first**: series are relative to the current seed date (dt_wasp_030).
- **never shrink segments** (`PNUMSEG`): the API crashed on the next query (dt_wasp_031).
- **box depth**: compare a 12 m surface box with surface samples; a 20 m box peaks 4–5 °C low
  in August (dt_wasp_038).

## Example
`outputs/wasp_lake_erie_central_real_engine/case/erie_cb_surface.wif` — 20,459 API commands,
4,018 days, 10 isolated 12 m boxes.
