# Stage 3: Ensemble Initialization

## Purpose

Create an ensemble of model states for the DART filter. The ensemble
represents uncertainty in the model state and is the core of ensemble
data assimilation. Proper initialization is critical — poor initialization
can lead to filter divergence or slow convergence.

## Inputs

| File | Format | Description |
|---|---|---|
| `input.nml` | Fortran namelist | Ensemble configuration in `&filter_nml` |
| Initial state | NetCDF | Model state to perturb or ensemble of states |

## Outputs

| File | Format | Description |
|---|---|---|
| `filter_input*.nc` | NetCDF | Ensemble member initial conditions |
| OR `filter_input.nc` | NetCDF | Single file containing all members |

## Procedure

### Method 1: Perturb from Single Instance

For simple models, DART can create an ensemble by perturbing a single
model state.

Configure `&filter_nml`:
```fortran
&filter_nml
   ens_size                      = 20
   perturb_from_single_instance  = .true.
   perturbation_amplitude        = 0.2
   single_file_in                = .true.
   input_state_files             = 'perfect_input.nc'
/
```

DART adds Gaussian noise with standard deviation = `perturbation_amplitude`
to each state variable independently.

### Method 2: Pre-generated Ensemble

For complex models, generate ensemble members externally:

1. Run the model from different initial conditions
2. Add perturbations to boundary conditions or parameters
3. Use different physics configurations
4. Write each member to a separate NetCDF file

Configure `&filter_nml`:
```fortran
&filter_nml
   ens_size                      = 80
   perturb_from_single_instance  = .false.
   single_file_in                = .false.
   input_state_file_list         = 'input_file_list.txt'
/
```

Where `input_file_list.txt` contains one file path per line:
```
member_001.nc
member_002.nc
...
member_080.nc
```

### Method 3: Single File with Multiple Members

```fortran
&filter_nml
   ens_size        = 20
   single_file_in  = .true.
   input_state_files = 'filter_input.nc'
/
```

The file contains variables like `state(time, StateVariable)` with
`time` dimension = ens_size.

## Verification

1. **Check ensemble spread**: After initialization, verify that the
   ensemble has reasonable spread. If all members are identical, the
   filter will collapse immediately.

2. **Check for physical consistency**: Ensure perturbed states are
   physically valid (e.g., positive temperatures, valid pressures).

3. **Spinup**: For realistic models, run a short "free ensemble" run
   (no assimilation) to let the ensemble spread evolve naturally.

## Traps

1. **perturbation_amplitude too large**: For chaotic models, large
   perturbations can push ensemble members into unrealistic regimes.
   Start small (0.01-0.2) and increase if the ensemble collapses.

2. **perturbation_amplitude too small**: If perturbation is smaller
   than numerical precision, all members will be identical, and the
   ensemble covariance will be zero — filter cannot update anything.

3. **Missing ensemble members**: If `ens_size` doesn't match the
   number of input files, DART will error. Double-check file counts.

4. **Bounded variables**: Perturbations can push values below zero
   (e.g., humidity, concentration). Use QCEFF bounded normal
   distributions or manually clip after perturbation.

5. **Time mismatch**: All ensemble members must be at the same model
   time. If members are at different times, filter will fail with
   a time-mismatch error.

## Example

```bash
# Lorenz 63: perturb from single instance
cd DART/models/lorenz_63/work

# The default input.nml already has:
#   perturb_from_single_instance = .true.
#   perturbation_amplitude = 0.2
#   single_file_in = .true.
#   input_state_files = 'perfect_input.nc'

# Just run filter — it will create the ensemble internally
./filter
```

For complex models (e.g., CAM):
```bash
# Generate 80 ensemble members from different restarts
for i in $(seq 1 80); do
  echo "cam_restart_${i}.nc" >> input_file_list.txt
done

# Configure filter to read from file list
# Set: single_file_in = .false.
#      input_state_file_list = 'input_file_list.txt'
```
