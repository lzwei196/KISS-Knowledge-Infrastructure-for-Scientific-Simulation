# Stage 2: Observation Preparation

## Purpose

Create observation sequence files (obs_seq) that contain observation
locations, times, types, values, and error estimates. For OSSEs, this means
creating a template and running `perfect_model_obs`. For real-data
experiments, this means converting raw observations to DART format.

## Inputs

### Synthetic Observations (OSSE)

| File | Format | Description |
|---|---|---|
| `input.nml` | Fortran namelist | Configuration for obs tools |
| Interactive input | stdin | Obs type, location, error variance |

### Real Observations

| File | Format | Description |
|---|---|---|
| Raw data | HDF, BUFR, NetCDF, CSV, text | Source observations |
| Converter `input.nml` | Fortran namelist | Converter-specific config |

## Outputs

| File | Format | Description |
|---|---|---|
| `set_def.out` | DART internal | Observation set definition |
| `obs_seq.in` | obs_seq (ASCII/binary) | Observation template with locations but no values |
| `obs_seq.out` | obs_seq (ASCII/binary) | Observations with values (from perfect_model_obs or converters) |

## Procedure

### Synthetic Observations (OSSE Workflow)

#### Step 1: Define Observation Types

Run `create_obs_sequence` interactively:

```
./create_obs_sequence
  Upper bound on num obs in sequence: 1000
  Number of copies of data: 0
  Number of QC values: 0
  Input 0 for no more obs, -1 for obs type list:
    Observation type: 1  (RAW_STATE_VARIABLE)
    Location: 0.0
    Error variance: 8.0
  ...
  (repeat for each obs type/location)
  File name: set_def.out
```

#### Step 2: Replicate Across Time

Run `create_fixed_network_seq`:

```
./create_fixed_network_seq
  Input observation sequence file: set_def.out
  Regular or irregular time spacing: 1 (regular)
  Number of observation times: 1000
  Initial time (days, seconds): 0 0
  Time between obs (days, seconds): 0 3600
  Output file: obs_seq.in
```

#### Step 3: Generate Synthetic Observations

Run `perfect_model_obs`:

```bash
./perfect_model_obs
```

This reads `obs_seq.in`, advances the "true" model state to each
observation time, evaluates forward operators, adds Gaussian noise,
and writes `obs_seq.out`.

### Real Observations Workflow

DART provides 50+ observation converters in `observations/obs_converters/`.
Each converter reads a specific data format and produces `obs_seq.out`.

```bash
# Example: Convert MADIS surface observations
cd DART/observations/obs_converters/MADIS/work
./quickbuild.sh
./convert_madis_metar   # reads input.nml for file paths
```

The `obs_sequence_tool` can merge, subset, thin, or time-window
multiple obs_seq files.

## Verification

1. **Check obs_seq.out exists and has correct size**:
   ```bash
   wc -l obs_seq.out         # should have many lines
   head -20 obs_seq.out      # check header format
   ```

2. **Count observations by type**:
   ```bash
   grep "kind" obs_seq.out | sort | uniq -c
   ```

3. **Verify time coverage**: Check that observations span the intended
   assimilation window.

## Traps

1. **Error variance vs. standard deviation**: DART stores observation
   error as **variance** (σ²). If you provide σ instead, observations
   will be trusted too much (for σ < 1) or too little (for σ > 1).

2. **Longitude convention**: DART stores longitude in [0, 360] degrees
   internally. Negative longitudes (-180 to 0) must be shifted by +360.

3. **Pressure in hPa vs. Pa**: For `which_vert = 2` (pressure),
   the value must be in Pascals. Surface pressure ~101325 Pa, not 1013.25 hPa.

4. **Missing values**: Use -888888.0, not NaN or -9999. DART checks
   exact equality.

5. **Binary obs_seq endianness**: Binary obs_seq files created on
   big-endian machines cannot be read on little-endian without
   setting `read_binary_file_format = 'big_endian'` in
   `&obs_sequence_nml`.

## Example

```bash
# Complete synthetic obs workflow for Lorenz 63
cd DART/models/lorenz_63/work

# Create obs template (3 state variables observed)
echo "1000
0
0
1
0.0
0.0
8.0
1
0.3333
0.0
8.0
1
0.6667
0.0
8.0
0
set_def.out" | ./create_obs_sequence

# Replicate across 1000 hours
echo "set_def.out
1
1000
0 0
0 3600
obs_seq.in" | ./create_fixed_network_seq

# Generate truth + synthetic obs
./perfect_model_obs
# Output: obs_seq.out (with observation values)
```
