# LDNDC Installation and Compilation — Skill Document

> **Stage ID**: s0_installation
> **Pipeline order**: 0 (prerequisite)
> **Depends on**: none

## Purpose

Install and compile the LandscapeDNDC (LDNDC) model binary on a Linux system. LDNDC is a C++11 biogeochemistry model built with CMake. Without a working binary, no simulation can run. This stage also verifies that all required runtime dependencies (shared libraries, parameter databases) are present.

## Prerequisites

- [ ] Linux system with GCC 7+ or Clang 5+ (C++11 support required)
- [ ] CMake 3.10+
- [ ] Build essentials: `build-essential`, `cmake`, `libxml2-dev`, `zlib1g-dev`
- [ ] Optional for MPI parallelism: `libopenmpi-dev` or `libmpich-dev`
- [ ] LDNDC source tarball or pre-built binary from KIT (https://ldndc.imk-ifu.kit.edu/)
- [ ] At least 500 MB disk space for source + build

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| ldndc_source | file/directory | KIT download or GitLab | LDNDC source tarball or repository |
| install_prefix | directory | User | Target installation directory (e.g., `/home/server/LDNDC/`) |

## Procedure

### Step 1: Install system dependencies

```bash
# Ubuntu/Debian
sudo apt-get install build-essential cmake libxml2-dev zlib1g-dev

# For MPI support (regional-scale runs):
sudo apt-get install libopenmpi-dev
```

### Step 2: Extract and build LDNDC

If using the pre-built distribution (recommended for HydroCraft):
```bash
tar -xzf ldndc-v1.30.4-linux-x86_64.tar.gz -C /home/server/LDNDC/
chmod +x /home/server/LDNDC/bin/ldndc
```

If building from source:
```bash
cd ldndc-source/
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/home/server/LDNDC -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
make install
```

**Expected result**: `ldndc` binary at `/home/server/LDNDC/bin/ldndc`.

### Step 3: Verify installation

```bash
/home/server/LDNDC/bin/ldndc --version
```

**Expected output**: Version string (e.g., `ldndc version 1.30.4`).

If the binary fails with "shared library not found":
```bash
ldd /home/server/LDNDC/bin/ldndc | grep "not found"
```
Install any missing libraries.

### Step 4: Verify parameter database

LDNDC ships with species parameter files that must be accessible:
```bash
ls /home/server/LDNDC/resources/parameters/
# Expected: parameters_species.xml, parameters_site.xml, etc.
```

### Step 5: Configure ldndc.conf (optional)

The optional `ldndc.conf` file in the user's home directory or project directory can set default paths:
```
resourcepath = /home/server/LDNDC/resources
```

### Step 6: Verify with example project

Run the bundled example to confirm the full pipeline works:
```bash
cd /home/server/LDNDC/projects/example
/home/server/LDNDC/bin/ldndc project.xml
ls output/
```

**Expected result**: Output files in `output/` directory; exit code 0.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| ldndc binary | `/home/server/LDNDC/bin/ldndc` | `ldndc --version` returns version string |
| Parameter files | `/home/server/LDNDC/resources/parameters/` | `parameters_species.xml` exists |
| Shared libraries | system libs | `ldd ldndc` shows no "not found" |

## Validation Checks

1. **Binary exists and is executable**: `test -x /home/server/LDNDC/bin/ldndc`
2. **Version check**: `ldndc --version` outputs without error
3. **No missing shared libraries**: `ldd ldndc | grep "not found"` returns empty
4. **Example project runs**: Exit code 0 from example simulation
5. **Parameter database present**: `parameters_species.xml` exists in resources

## Common Pitfalls

> **PITFALL**: Missing libxml2 causes cryptic build failure
> CMake may find partial XML support but fail at link time with undefined symbols. The error message points to internal LDNDC code, not the missing library.
> **Do this instead**: Always install `libxml2-dev` (not just `libxml2`) before building.

> **PITFALL**: Wrong compiler version for C++11
> GCC < 4.8 or Clang < 3.3 do not fully support C++11. The build may succeed but produce a broken binary.
> **Do this instead**: Verify `g++ --version` shows 7.0+ for modern LDNDC versions.

> **PITFALL**: Pre-built binary on wrong glibc version
> Pre-built LDNDC binaries link against a specific glibc version. Running on an older Linux distribution produces `GLIBC_2.XX not found`.
> **Do this instead**: Build from source on the target system, or use the Docker image at `codebase.helmholtz.cloud/landscapedndc/ldndc-docker`.

> **PITFALL**: Parameter database not found at runtime
> LDNDC looks for species/site parameter files relative to the binary or via ldndc.conf. If moved, the model crashes with a vague "file not found" during initialization.
> **Do this instead**: Set `resourcepath` in `ldndc.conf` or ensure parameter files are co-located with the binary.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 0 (prerequisite) | Tools used: none (manual installation) | Related triplets: none*
