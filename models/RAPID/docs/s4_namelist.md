# Stage 4: Namelist Assembly

## Purpose

Assemble the RAPID Fortran namelist file that configures the entire simulation.
The namelist is read by `rapid_read_namelist.F90` using Fortran NAMELIST I/O
from unit 88. It contains runtime options, temporal parameters, file paths, and
domain sizes.

## Inputs

All outputs from stages 1–3:

| Input | Source | Required |
|-------|--------|----------|
| rapid_connect.csv | Stage 1 | Yes |
| riv_bas_id.csv | Stage 1 | Yes |
| k.csv | Stage 3 | Yes |
| x.csv | Stage 3 | Yes |
| Vlat.nc | Stage 2 | Yes |
| Qinit.nc | Previous run | Optional |
| Qobs.nc | Observations | For optimization only |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| rapid_namelist | Fortran namelist text | Complete RAPID configuration |

## Procedure

1. **Count domain sizes** from input files:
   - `IS_riv_tot` = lines in rapid_connect.csv
   - `IS_riv_bas` = lines in riv_bas_id.csv
   - `IS_max_up` = max value in column 3 of rapid_connect.csv

2. **Set temporal parameters** (ALL IN SECONDS):
   - `ZS_TauM`: Total simulation duration
   - `ZS_dtM`: Main (output) time step
   - `ZS_TauR`: Routing procedure period (= Vlat time step)
   - `ZS_dtR`: Routing sub-step (must satisfy Courant condition)

3. **Set runtime options**:
   - `BS_opt_Qinit`: `.true.` to read initial conditions from Qinit.nc
   - `BS_opt_Qfinal`: `.true.` to write final state for restart
   - `BS_opt_V`: `.true.` to compute and write volume
   - `IS_opt_run`: 1 (simulation), 2 (optimization), 3-4 (data assimilation)
   - `IS_opt_routing`: 1 (matrix Muskingum), 2 (traditional), 3 (transboundary)

4. **Set file paths** using absolute paths with single quotes:
   ```fortran
   rapid_connect_file = '/absolute/path/to/rapid_connect.csv'
   ```

5. **Verify temporal consistency**:
   - `ZS_TauM mod ZS_dtM == 0`
   - `ZS_TauR mod ZS_dtR == 0`
   - `ZS_TauM mod ZS_TauR == 0`
   - Number of Vlat time steps = `ZS_TauM / ZS_TauR`

## Namelist Format

```fortran
&NL_namelist

!--- Runtime options ---
BS_opt_Qinit       = .false.
BS_opt_Qfinal      = .true.
BS_opt_V           = .true.
BS_opt_dam         = .false.
BS_opt_for         = .false.
BS_opt_hum         = .false.
BS_opt_uq          = .false.
IS_opt_routing     = 1
IS_opt_run         = 1
IS_opt_phi         = 1

!--- Temporal parameters (ALL IN SECONDS) ---
ZS_TauM            = 2592000
ZS_dtM             = 86400
ZS_TauO            = 0
ZS_dtO             = 0
ZS_TauR            = 10800
ZS_dtR             = 900
ZS_dtF             = 10800

!--- Domain sizes ---
IS_riv_tot         = 5175
IS_riv_bas         = 5175
IS_max_up          = 4

!--- Input files ---
rapid_connect_file = '/path/to/rapid_connect.csv'
riv_bas_id_file    = '/path/to/riv_bas_id.csv'
k_file             = '/path/to/k.csv'
x_file             = '/path/to/x.csv'
Vlat_file          = '/path/to/Vlat.nc'

!--- Output files ---
Qout_file          = '/path/to/Qout.nc'
V_file             = '/path/to/V.nc'
Qfinal_file        = '/path/to/Qfinal.nc'

/
```

## Verification

```bash
# Syntax check: Fortran can read it
python3 -c "
with open('rapid_namelist') as f:
    c = f.read()
assert '&NL_namelist' in c, 'Missing section start'
assert c.strip().endswith('/'), 'Missing section terminator'
print('Namelist syntax OK')
"

# Check all referenced files exist
grep "_file.*=" rapid_namelist | sed "s/.*= *'//;s/'.*//" | while read f; do
    test -f "$f" && echo "OK: $f" || echo "MISSING: $f"
done

# Verify temporal consistency
python3 -c "
import re
c = open('rapid_namelist').read()
tau_m = int(re.search(r'ZS_TauM\s*=\s*(\d+)', c).group(1))
dt_m  = int(re.search(r'ZS_dtM\s*=\s*(\d+)', c).group(1))
tau_r = int(re.search(r'ZS_TauR\s*=\s*(\d+)', c).group(1))
dt_r  = int(re.search(r'ZS_dtR\s*=\s*(\d+)', c).group(1))
assert tau_m % dt_m == 0, f'TauM ({tau_m}) not divisible by dtM ({dt_m})'
assert tau_r % dt_r == 0, f'TauR ({tau_r}) not divisible by dtR ({dt_r})'
assert tau_m % tau_r == 0, f'TauM ({tau_m}) not divisible by TauR ({tau_r})'
print(f'Time steps: {tau_m//dt_m} main, {tau_m//tau_r} Vlat, {tau_r//dt_r} routing sub-steps')
"
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Namelist read error (dt_005) | FATAL | Wrong Fortran syntax: missing `&`, wrong quotes, extra commas |
| Double quotes instead of single (dt_005) | FATAL | Fortran namelist requires single-quoted strings |
| Relative paths (dt_005) | DEGRADED | Paths resolved relative to CWD, not namelist location — use absolute |
| IS_riv_tot/IS_riv_bas mismatch | FATAL | Must exactly match file contents or RAPID crashes |
| Time step mismatch (dt_009) | DEGRADED | Non-divisible time parameters → wrong number of routing steps |
| Missing section terminator | FATAL | Namelist must end with `/` on its own line |

## Example

For a 30-day simulation with GLDAS 3-hourly forcing:

```
ZS_TauM = 2592000    # 30 days × 86400 s/day
ZS_dtM  = 86400      # output every day
ZS_TauR = 10800      # 3 hours (matches GLDAS time step)
ZS_dtR  = 900        # 15-minute routing sub-step

# Expected: 240 Vlat time steps, 30 output time steps, 12 routing sub-steps per TauR
```
