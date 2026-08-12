# Stage 02 — Weather forcing conversion

## Purpose
Build the EPIC daily weather file (`<stn>.DLY`) and its monthly-statistics
companions (`<stn>.WP1`, `<stn>.WND`) from a HydroCraft forcing source.

## Inputs
- Forcing source: `cmfd` | `nasa_power` | `mswx`
- Site lat, lon
- Start year, end year
- Station name prefix

## Outputs
| File          | Contents                                               |
|---------------|--------------------------------------------------------|
| `<stn>.DLY`   | Daily: YR MO DY SRAD TMX TMN PRCP RH WSPD              |
| `<stn>.WP1`   | Monthly mean stats + rainfall distribution parameters  |
| `<stn>.WND`   | Monthly wind                                           |

## Procedure
1. Call `ki_tools_common.load_forcing.load_daily_forcing(...)`.
2. Apply unit conversions:
   - PRCP kg/m2/s → mm/day (x86400)
   - Tmax/Tmin K → degC (−273.15)
   - SRAD W/m2 → MJ/m2/day (×0.0864)
   - RH % → fraction (×0.01)
3. Clamp TMIN ≤ TMAX.
4. Run `_validate_ranges(...)` (rejects physically implausible means).
5. Write `.DLY` with `(3I4, 6F6.2)`.
6. Compute 12 monthly means/SDs and write `.WP1`.
7. Write `.WND` from monthly mean wind speed.

## Verification
- Line count of `.DLY` ≈ (years)×365.
- `awk 'NR>1 {p+=$7} END {print p/NR}' <stn>.DLY` gives mean daily precip.
- `.ANN` PRCP column after run is consistent.

## Traps
- **Unit confusion** is the #1 source of wrong yields. See triplets
  EPIC_002/003/004. The `_validate_ranges` guardrail catches most.
- **SRAD auto-detect**: heuristic — if mean > 60 assume W/m2.
- **RH units**: NASA POWER %; CMFD fraction. Tool normalizes.
- **Proxy issues** for NASA POWER API.

## Example
```bash
python tools/convert_forcing_to_epic.py --source cmfd \
    --lat 35.86 --lon -78.74 --start 2000 --end 2010 \
    --workspace /tmp/epic_run --stn RALEIGH
```
