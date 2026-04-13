# Stage 3: Configuration File Generation

## Purpose

Assemble the CISM .config file from validated parameters. The config file
is an INI-style text file with sections that control grid, time stepping,
physics options, I/O, and solver settings.

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| Parameter dictionary | s0 | Yes |
| Input NetCDF path | s1 output | Yes |
| Forcing NetCDF path | s2 output (if time-varying) | No |

## Outputs

| Output | Format | Used by |
|--------|--------|---------|
| simulation.config | INI-style text | s4 (cism_driver) |

## Procedure

1. **Build parameter dictionary** from stage 0 choices.

2. **Validate parameters** (critical checks):
   - Grid spacing in meters (dt_006)
   - Geothermal heat flux negative (dt_003)
   - default_flwa in valid range 1e-18 to 1e-15 (dt_002)
   - Glissade uses evolution=3 or 4, not 0 (dt_007)
   - which_ho_sparse=3 unless Trilinos built (dt_005)
   - output frequency <= total timesteps (dt_009)

3. **Write sections in order**:
   ```
   [grid]       -> ewn, nsn, upn, dew, dns
   [time]       -> tstart, tend, dt, ntem, ndiag
   [options]    -> dycore, temperature, flow_law, evolution, ...
   [ho_options] -> (only if dycore=2) approx, babc, efvs, sparse, ...
   [parameters] -> default_flwa, ice_limit, geothermal, ...
   [CF default] -> title, comment
   [CF input]   -> name, time
   [CF output]  -> name, frequency, variables
   [CF forcing] -> (optional) name
   [sigma]      -> (optional) custom sigma levels
   [isostasy]   -> (optional) lithosphere, asthenosphere
   ```

4. **Validate output** by re-reading config and checking all required
   sections exist.

## Verification

- [ ] All 7 required sections present: grid, time, options, parameters, CF default, CF input, CF output
- [ ] Section names exactly match CISM expectations (case-sensitive)
- [ ] Input file path in [CF input] points to existing NetCDF
- [ ] Output variables are valid CISM variable names
- [ ] No duplicate section names

## Traps

| ID | Trap | Prevention |
|----|------|-----------|
| dt_014 | Misspelled section name silently ignored | Validate section names against known list |
| dt_002 | default_flwa too small (no dynamics) | Check range 1e-18 to 1e-15 |
| dt_009 | Output frequency > total steps | Check freq <= (tend-tstart)/dt |
| dt_005 | which_ho_sparse=4 without Trilinos | Default to 3 |

## Example

```bash
# Dome test preset
python tools/generate_cism_config.py --test dome --output dome.config

# Higher-order with custom parameters
python tools/generate_cism_config.py --test dome_ho \
    --dt 0.5 --tend 10000 --default_flwa 1e-17 \
    --output dome_ho.config

# From JSON parameter file
python tools/generate_cism_config.py --from_json greenland_params.json \
    --output greenland.config
```
