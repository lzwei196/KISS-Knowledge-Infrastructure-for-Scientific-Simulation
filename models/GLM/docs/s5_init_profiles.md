# s5 Init Profiles

## Purpose

Generate GLM initial temperature and salinity profiles for the `&init_profiles` namelist block. This initializes the vertical column before GLM begins dynamic layer splitting, mixing, and surface forcing.

## Inputs

- Lake depth from s1 morphometry: `max(H) - min(H)`.
- Start season and optional observed profile.
- Tool: `tools/s5_init_profiles/build_init_profiles.py`.

## Outputs

- Initial profile JSON, usually `init_profiles.json`, with `lake_depth`, `num_depths`, `the_depths`, `the_temps`, `the_sals`, and WQ placeholders.

## Procedure

1. Use a uniform profile for spring/autumn cold starts:

```bash
python tools/s5_init_profiles/build_init_profiles.py \
  --strategy uniform \
  --temp 10.0 \
  --depth 18.3 \
  --max_morph_depth 18.3 \
  --output init_profiles.json
```

2. Use a stratified profile for a summer start:

```bash
python tools/s5_init_profiles/build_init_profiles.py \
  --strategy stratified \
  --temp_surface 22 \
  --temp_bottom 4 \
  --depth 60 \
  --max_morph_depth 60 \
  --output init_profiles.json
```

3. Use custom observed depths and temperatures when available:

```bash
python tools/s5_init_profiles/build_init_profiles.py \
  --strategy custom \
  --custom_depths "0,5,10,20" \
  --custom_temps "18,16,9,5" \
  --depth 20 \
  --salinity 0.0 \
  --max_morph_depth 20 \
  --output init_profiles.json
```

## Verification

- `lake_depth` is positive and does not exceed the morphometry depth.
- `num_depths` equals the lengths of `the_depths`, `the_temps`, and `the_sals`.
- Freshwater salinity defaults to `0.0`.
- If AED2 is not manually configured, `num_wq_vars` remains `0`.

## Traps

- `dt_009`: `lake_depth` greater than the morphometry maximum depth crashes GLM at startup.
- `dt_022`: non-zero salinity changes density; use `0.0` for freshwater.
- `dt_030`: when AED2 is enabled later, WQ initialization values must match `num_wq_vars * num_depths`.

## Example

```bash
python tools/s5_init_profiles/build_init_profiles.py \
  --strategy isothermal \
  --depth 18.3 \
  --max_morph_depth 18.3 \
  --output init_profiles.json
```
