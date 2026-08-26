#!/usr/bin/env python3
"""
configure_simulation.py -- Generate CaMa-Flood configuration for a basin.

Performs the full map preparation pipeline:
  Step 1: Regionalize (cut from global 15min river network)
  Step 2: Generate input matrix (source grid -> CaMa grid mapping)
  Step 3: Generate channel parameters (width, depth, Manning's n)
  Step 4: Generate run script (gosh/run_{basin}_1d_nc.sh)

This is Stage 2 of the CaMa-Flood pipeline.

Usage:
    python configure_simulation.py \\
        --basin_name bengbu \\
        --west 111.75 --east 117.75 --south 31.0 --north 35.0 \\
        --grid_resolution 0.25 \\
        --start_year 2000 --end_year 2005 \\
        --runoff_dir /path/to/cama_input \\
        --runoff_prefix "bengbu_runoff_1d_"

    # Or with a VIC basin_grid.nc for automatic extent detection:
    python configure_simulation.py \\
        --basin_name bengbu \\
        --grid_nc /path/to/basin_grid.nc \\
        --start_year 2000 --end_year 2005 \\
        --runoff_dir /path/to/cama_input \\
        --runoff_prefix "bengbu_runoff_1d_"
"""

import argparse
import math
import os
import shutil
import subprocess
import sys
import textwrap

import numpy as np

CAMA_ROOT = "KISSPATH_BINARIES/cmf_v420_pkg"
GLB_MAP = os.path.join(CAMA_ROOT, "map", "glb_15min")
GPCC_CLIM = os.path.join(CAMA_ROOT, "map", "data",
                         "ELSE_GPCC_coastmod_dayclm-1981-2010.one")


def snap_to_15min(val, direction="down"):
    """Snap a coordinate to the nearest 0.25-degree boundary."""
    step = 0.25
    if direction == "down":
        return math.floor(val / step) * step
    return math.ceil(val / step) * step


def read_grid_nc(grid_nc_path):
    """Read grid extents from a VIC basin_grid.nc file."""
    try:
        import xarray as xr
    except ImportError:
        print("ERROR: xarray required for --grid_nc. Install: pip install xarray")
        sys.exit(1)

    ds = xr.open_dataset(grid_nc_path)
    lat_name = "lat" if "lat" in ds.coords else "y"
    lon_name = "lon" if "lon" in ds.coords else "x"
    lats = ds[lat_name].values
    lons = ds[lon_name].values
    res = 0.25
    if len(lons) > 1:
        res = abs(float(lons[1] - lons[0]))

    info = {
        "west": float(lons.min()) - res / 2,
        "east": float(lons.max()) + res / 2,
        "south": float(lats.min()) - res / 2,
        "north": float(lats.max()) + res / 2,
        "resolution": res,
        "nlat": len(lats),
        "nlon": len(lons),
    }
    ds.close()
    return info


def compute_domain(west, east, south, north, buffer_deg=0.5):
    """Compute CaMa domain with buffer, snapped to 0.25-degree boundaries."""
    return {
        "west": snap_to_15min(west - buffer_deg, "down"),
        "east": snap_to_15min(east + buffer_deg, "up"),
        "south": snap_to_15min(south - buffer_deg, "down"),
        "north": snap_to_15min(north + buffer_deg, "up"),
    }


def run_cmd(cmd, cwd=None, desc=""):
    """Run a shell command with error checking."""
    print(f"  CMD: {cmd}")
    if desc:
        print(f"  ({desc})")
    result = subprocess.run(cmd, shell=True, cwd=cwd,
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"  FAILED (exit code {result.returncode})")
        if result.stderr:
            print(f"  STDERR: {result.stderr[:500]}")
        if result.stdout:
            print(f"  STDOUT: {result.stdout[:500]}")
        return False
    if result.stdout.strip():
        for line in result.stdout.strip().split("\n")[:5]:
            print(f"    {line}")
    return True


# ===========================================================================
# Step 1: Regionalization
# ===========================================================================

def step1_regionalize(map_dir, domain):
    """Cut regional map from global 15-minute river network."""
    print("\n" + "=" * 60)
    print("  STEP 1: Regionalization (cut from glb_15min)")
    print("=" * 60)

    src_region = os.path.join(map_dir, "src_region")
    os.makedirs(src_region, exist_ok=True)

    # Copy source files from glb_15min
    glb_src = os.path.join(GLB_MAP, "src_region")
    if not os.path.isdir(glb_src):
        print(f"ERROR: Global src_region not found: {glb_src}")
        return False

    # Copy source files and Makefile
    for item in os.listdir(glb_src):
        src_path = os.path.join(glb_src, item)
        dst_path = os.path.join(src_region, item)
        if item.startswith("."):
            continue
        if os.path.isfile(src_path) and not os.path.exists(dst_path):
            shutil.copy2(src_path, dst_path)

    # Compile (binaries are platform-specific)
    print("  Compiling regionalization tools...")
    if not run_cmd("make clean && make all", cwd=src_region, desc="compile"):
        print("  WARNING: Compilation failed. Checking if pre-built binaries exist...")
        if not os.path.isfile(os.path.join(src_region, "cut_domain")):
            print("  ERROR: No cut_domain binary. Cannot proceed.")
            return False

    # Create region_info.txt
    region_info = os.path.join(src_region, "region_info.txt")
    with open(region_info, "w") as f:
        f.write(f"../../glb_15min/\n")
        f.write(f"{domain['west']}\n")
        f.write(f"{domain['east']}\n")
        f.write(f"{domain['south']}\n")
        f.write(f"{domain['north']}\n")

    # Create and run regionalization script
    script = os.path.join(src_region, "s01-regional_map.sh")
    with open(script, "w") as f:
        f.write(textwrap.dedent(f"""\
            #!/bin/sh
            SOURCE="../../glb_15min/"
            WEST="{domain['west']}"
            EAST="{domain['east']}"
            SOUTH="{domain['south']}"
            NORTH="{domain['north']}"

            echo "$SOURCE" > region_info.txt
            echo "$WEST" >> region_info.txt
            echo "$EAST" >> region_info.txt
            echo "$SOUTH" >> region_info.txt
            echo "$NORTH" >> region_info.txt

            ./cut_domain
            ./cut_bifway
            ./set_map

            HDIRS="1min 30sec 15sec 3sec"
            for HIRES in $HDIRS; do
              if [ -f $SOURCE/$HIRES/location.txt ]; then
                echo "Processing high-res: $HIRES"
                mkdir -p ../$HIRES
                ./combine_hires $HIRES
              fi
            done

            ./s02-wrte_ctl_map.sh 2>/dev/null || true
        """))
    os.chmod(script, 0o755)

    if not run_cmd("./s01-regional_map.sh", cwd=src_region, desc="regionalize"):
        return False

    # Verify essential output files
    essential = ["nextxy.bin", "ctmare.bin", "elevtn.bin", "nxtdst.bin",
                 "rivlen.bin", "fldhgt.bin"]
    missing = [f for f in essential if not os.path.isfile(os.path.join(map_dir, f))]
    if missing:
        print(f"  ERROR: Missing map files after regionalization: {missing}")
        return False

    print("  STEP 1 COMPLETE: Regional map files generated.")
    return True


# ===========================================================================
# Step 2: Input Matrix Generation
# ===========================================================================

def step2_generate_inpmat(map_dir, basin_name, vic_west, vic_east,
                          vic_south, vic_north, grid_res=0.25):
    """Generate input matrix mapping source grid to CaMa river network."""
    print("\n" + "=" * 60)
    print("  STEP 2: Input Matrix Generation")
    print("=" * 60)

    src_param = os.path.join(map_dir, "src_param")
    os.makedirs(src_param, exist_ok=True)

    # Copy source from glb_15min
    glb_param = os.path.join(GLB_MAP, "src_param")
    if os.path.isdir(glb_param):
        for item in os.listdir(glb_param):
            src = os.path.join(glb_param, item)
            dst = os.path.join(src_param, item)
            if item.startswith("."):
                continue
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)

    # Compile
    print("  Compiling inpmat tools...")
    if not run_cmd("make clean && make all", cwd=src_param, desc="compile"):
        print("  WARNING: Compilation failed. Checking pre-built binaries...")
        if not os.path.isfile(os.path.join(src_param, "generate_inpmat")):
            print("  ERROR: No generate_inpmat binary.")
            return False

    diminfo_name = f"diminfo_{basin_name}_025deg.txt"
    inpmat_name = f"inpmat_{basin_name}_025deg.bin"

    # OLAT: VIC typically has North-to-South ordering
    olat = "NtoS"

    script = os.path.join(src_param, "s02-generate_inpmat.sh")
    with open(script, "w") as f:
        f.write(textwrap.dedent(f"""\
            #!/bin/sh
            cd ..
            DIMINFO="{diminfo_name}"
            INPMAT="{inpmat_name}"
            GRSIZEIN={grid_res}
            WESTIN={vic_west}
            EASTIN={vic_east}
            NORTHIN={vic_north}
            SOUTHIN={vic_south}
            OLAT="{olat}"
            TAG="1min"

            ./src_param/generate_inpmat $TAG $GRSIZEIN $WESTIN $EASTIN $NORTHIN $SOUTHIN $OLAT $DIMINFO $INPMAT
        """))
    os.chmod(script, 0o755)

    if not run_cmd("./s02-generate_inpmat.sh", cwd=src_param, desc="generate inpmat"):
        return False

    # Verify output
    diminfo_path = os.path.join(map_dir, diminfo_name)
    inpmat_path = os.path.join(map_dir, inpmat_name)
    if not os.path.isfile(diminfo_path):
        print(f"  ERROR: diminfo not generated: {diminfo_path}")
        return False
    if not os.path.isfile(inpmat_path):
        print(f"  ERROR: inpmat not generated: {inpmat_path}")
        return False

    # Print diminfo for verification
    with open(diminfo_path, "r") as f:
        print(f"  diminfo contents:")
        for line in f:
            print(f"    {line.rstrip()}")

    print("  STEP 2 COMPLETE: Input matrix generated.")
    return True


# ===========================================================================
# Step 3: Channel Parameters
# ===========================================================================

def step3_channel_params(map_dir, basin_name, hc=0.10, hp=0.50, ho=0.00,
                         hmin=1.0, wc=2.50, wp=0.60, wo=0.00, wmin=5.0):
    """Generate channel width/depth parameters.

    CRITICAL: calc_outclm MUST run from glb_15min/ (needs full global network).
    Then calc_rivwth runs from the REGIONAL directory with REGIONAL diminfo.
    """
    print("\n" + "=" * 60)
    print("  STEP 3: Channel Parameters")
    print("=" * 60)

    # Step 3a: Run calc_outclm from glb_15min
    print("  Step 3a: Computing annual mean discharge climatology (from glb_15min)...")

    calc_outclm = os.path.join(GLB_MAP, "src_param", "calc_outclm")
    glb_diminfo = os.path.join(GLB_MAP, "diminfo_test-1deg.txt")

    if not os.path.isfile(calc_outclm):
        print(f"  ERROR: calc_outclm not found: {calc_outclm}")
        return False
    if not os.path.isfile(GPCC_CLIM):
        print(f"  ERROR: GPCC climatology not found: {GPCC_CLIM}")
        return False

    cmd = f"./src_param/calc_outclm bin inpmat ./diminfo_test-1deg.txt {GPCC_CLIM}"
    if not run_cmd(cmd, cwd=GLB_MAP, desc="calc_outclm on global grid"):
        print("  WARNING: calc_outclm may have already been run. Checking outclm.bin...")

    glb_outclm = os.path.join(GLB_MAP, "outclm.bin")
    if not os.path.isfile(glb_outclm):
        print(f"  ERROR: outclm.bin not generated in glb_15min")
        return False

    # Copy outclm.bin to regional directory
    regional_outclm = os.path.join(map_dir, "outclm.bin")
    shutil.copy2(glb_outclm, regional_outclm)
    print(f"  Copied outclm.bin to regional directory")

    # Step 3b: Run calc_rivwth from REGIONAL directory with REGIONAL diminfo
    print("  Step 3b: Computing channel width/depth (from regional dir)...")

    diminfo_name = f"diminfo_{basin_name}_025deg.txt"
    diminfo_path = os.path.join(map_dir, diminfo_name)
    if not os.path.isfile(diminfo_path):
        print(f"  ERROR: Regional diminfo not found: {diminfo_path}")
        return False

    calc_rivwth = os.path.join(map_dir, "src_param", "calc_rivwth")
    if not os.path.isfile(calc_rivwth):
        print(f"  ERROR: calc_rivwth not found: {calc_rivwth}")
        return False

    cmd = (f"./src_param/calc_rivwth bin ./{diminfo_name} "
           f"{hc} {hp} {ho} {hmin} {wc} {wp} {wo} {wmin}")
    if not run_cmd(cmd, cwd=map_dir, desc="calc_rivwth with regional diminfo"):
        return False

    # Generate GWDLR width and Manning's n
    rivwth_path = os.path.join(map_dir, "rivwth.bin")
    if os.path.isfile(rivwth_path):
        shutil.copy2(rivwth_path, os.path.join(map_dir, "rivwth_gwdlr.bin"))
        print("  Created rivwth_gwdlr.bin (copy of rivwth.bin)")

        # Generate uniform Manning's n = 0.03
        data = np.fromfile(rivwth_path, dtype="float32")
        data[:] = 0.03
        data.tofile(os.path.join(map_dir, "rivman.bin"))
        print("  Created rivman.bin (uniform n=0.03)")
    else:
        print(f"  ERROR: rivwth.bin not generated")
        return False

    # Verify file sizes match expected grid dimensions
    with open(diminfo_path, "r") as f:
        lines = f.readlines()
    nxx = int(lines[0].split()[0])
    nyy = int(lines[1].split()[0])
    expected_size = nxx * nyy * 4  # float32

    actual_size = os.path.getsize(rivwth_path)
    if actual_size != expected_size:
        print(f"  WARNING: rivwth.bin size ({actual_size}) != expected ({expected_size} = {nxx}x{nyy}x4)")
        print(f"  This may indicate the wrong diminfo was used. See dt_cama_003.")
    else:
        print(f"  File size verified: {actual_size} bytes = {nxx} x {nyy} x 4 (float32)")

    print("  STEP 3 COMPLETE: Channel parameters generated.")
    return True


# ===========================================================================
# Step 4: Generate Run Script
# ===========================================================================

def step4_generate_run_script(basin_name, map_dir, runoff_dir, runoff_prefix,
                              start_year, end_year, output_dir=None,
                              pmanriv=0.03, pmanfld=0.10, nspinup=2,
                              output_vars="outflw,rivdph,sfcelv,flddph,fldfrc"):
    """Generate CaMa-Flood run shell script."""
    print("\n" + "=" * 60)
    print("  STEP 4: Generate Run Script")
    print("=" * 60)

    if output_dir is None:
        output_dir = os.path.join(CAMA_ROOT, "out", f"{basin_name}_{start_year}_{end_year}_cama")

    diminfo_name = f"diminfo_{basin_name}_025deg.txt"
    inpmat_name = f"inpmat_{basin_name}_025deg.bin"

    script_path = os.path.join(CAMA_ROOT, "gosh", f"run_{basin_name}_1d_nc.sh")

    script_content = textwrap.dedent(f"""\
        #!/bin/sh

        # --- CaMa-Flood run script for {basin_name} (auto-generated) ---
        BASE="{CAMA_ROOT}"
        export OMP_NUM_THREADS=4
        export LD_LIBRARY_PATH="${{LD_LIBRARY_PATH}}"

        YSTA={start_year}
        YEND={end_year}
        RDIR="{output_dir}"
        PROG=${{BASE}}/src/MAIN_cmf
        NMLIST="./input_cmf.nam"
        MAPDIR="{map_dir}"
        INDIR="{runoff_dir}"

        SPINUP=0
        NSP={nspinup}

        mkdir -p ${{RDIR}}
        cd ${{RDIR}}

        if [ ${{SPINUP}} -eq 0 ]; then
          echo "--- New run, cleaning: ${{RDIR}} ---"
          rm -rf ./*
        fi

        ISP=1
        IYR=${{YSTA}}
        while [ ${{IYR}} -le ${{YEND}} ];
        do
          echo ""
          echo "############################################################"
          echo "--- Year: ${{IYR}} (Spin-up: ${{ISP}}) ---"
          echo "############################################################"

          CYR=`printf %04d ${{IYR}}`
          EYR=`expr ${{IYR}} + 1`

          if [ ${{IYR}} -eq ${{YSTA}} ] && [ ${{SPINUP}} -eq 0 ]; then
            LRESTART=".FALSE."
            CRESTSTO="''"
          else
            LRESTART=".TRUE."
            CRESTSTO="'./restart${{CYR}}010100.nc'"
          fi

          ln -sf $PROG ./MAIN_cmf

          cat > ${{NMLIST}} << EOF
          &NRUNVER
          LADPSTP  = .TRUE.
          LPTHOUT  = .FALSE.
          LRESTART = ${{LRESTART}}
          /
          &NDIMTIME
          CDIMINFO = '{map_dir}/{diminfo_name}'
          DT       = 86400
          IFRQ_INP = 24
          /
          &NPARAM
          PMANRIV  = {pmanriv}D0
          PMANFLD  = {pmanfld}D0
          PCADP    = 0.7
          PDSTMTH  = 10000.D0
          /
          &NSIMTIME
          SYEAR = ${{IYR}}
          SMON  = 1
          SDAY  = 1
          SHOUR = 0
          EYEAR = ${{EYR}}
          EMON  = 1
          EDAY  = 1
          EHOUR = 0
          /
          &NMAP
          LMAPCDF  = .FALSE.
          CNEXTXY  = '{map_dir}/nextxy.bin'
          CGRAREA  = '{map_dir}/ctmare.bin'
          CELEVTN  = '{map_dir}/elevtn.bin'
          CNXTDST  = '{map_dir}/nxtdst.bin'
          CRIVLEN  = '{map_dir}/rivlen.bin'
          CFLDHGT  = '{map_dir}/fldhgt.bin'
          CRIVWTH  = '{map_dir}/rivwth_gwdlr.bin'
          CRIVHGT  = '{map_dir}/rivhgt.bin'
          CRIVMAN  = '{map_dir}/rivman.bin'
          /
          &NRESTART
          CRESTSTO = ${{CRESTSTO}}
          CRESTDIR = './'
          CVNREST  = 'restart'
          LRESTCDF = .TRUE.
          IFRQ_RST = 0
          /
          &NFORCE
          LINPCDF  = .TRUE.
          LINTERP  = .TRUE.
          CINPMAT  = '{map_dir}/{inpmat_name}'
          CROFCDF  = '{runoff_dir}/{runoff_prefix}${{CYR}}.nc'
          CVNROF   = 'Runoff'
          SYEARIN  = ${{IYR}}
          SMONIN   = 1
          SDAYIN   = 1
          SHOURIN  = 0
          /
          &NOUTPUT
          COUTDIR  = './'
          CVARSOUT = '{output_vars}'
          COUTTAG  = '${{CYR}}'
          LOUTCDF  = .TRUE.
          NDLEVEL  = 0
          IFRQ_OUT = 24
          /
          &NBOUND
          /
          &NDAMOUT
          /
          &NLEVEE
          /
        EOF

          time ./MAIN_cmf

          if [ ${{IYR}} -eq ${{YSTA}} ] && [ ${{ISP}} -le ${{NSP}} ]; then
            SPINUP=1
            IYR1=`expr ${{IYR}} + 1`
            CYR1=`printf %04d ${{IYR1}}`
            mv ./restart${{CYR1}}010100.nc ./restart${{CYR}}010100.nc 2>/dev/null
            mkdir -p spinup-${{ISP}}
            mv ./*${{CYR}}.nc spinup-${{ISP}}/ 2>/dev/null
            ISP=`expr ${{ISP}} + 1`
          else
            IYR=`expr ${{IYR}} + 1`
          fi
        done

        echo "--- All simulations finished! ---"
    """)

    with open(script_path, "w") as f:
        f.write(script_content)
    os.chmod(script_path, 0o755)

    print(f"  Run script: {script_path}")
    print(f"  Output dir: {output_dir}")
    print("  STEP 4 COMPLETE: Run script generated.")
    return script_path


# ===========================================================================
# Main
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Configure CaMa-Flood simulation for a basin (map prep + run script).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--basin_name", required=True, help="Basin identifier")
    parser.add_argument("--grid_nc", help="VIC basin_grid.nc for automatic extent detection")
    parser.add_argument("--west", type=float, help="VIC grid west edge (degrees)")
    parser.add_argument("--east", type=float, help="VIC grid east edge (degrees)")
    parser.add_argument("--south", type=float, help="VIC grid south edge (degrees)")
    parser.add_argument("--north", type=float, help="VIC grid north edge (degrees)")
    parser.add_argument("--grid_resolution", type=float, default=0.25)
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--runoff_dir", required=True, help="Directory with runoff NetCDF files")
    parser.add_argument("--runoff_prefix", default="bengbu_runoff_1d_",
                        help="Runoff file prefix (default: bengbu_runoff_1d_)")
    parser.add_argument("--output_dir", help="Output directory (default: auto)")
    parser.add_argument("--buffer_deg", type=float, default=0.5,
                        help="Buffer around VIC domain for CaMa map (degrees)")
    parser.add_argument("--pmanriv", type=float, default=0.03, help="River Manning n")
    parser.add_argument("--pmanfld", type=float, default=0.10, help="Floodplain Manning n")
    parser.add_argument("--nspinup", type=int, default=2, help="Number of spin-up iterations")
    parser.add_argument("--skip_step1", action="store_true", help="Skip regionalization")
    parser.add_argument("--skip_step2", action="store_true", help="Skip inpmat generation")
    parser.add_argument("--skip_step3", action="store_true", help="Skip channel parameters")
    # Channel parameter coefficients
    parser.add_argument("--hc", type=float, default=0.10, help="Channel depth coefficient")
    parser.add_argument("--hp", type=float, default=0.50, help="Channel depth exponent")
    parser.add_argument("--wc", type=float, default=2.50, help="Channel width coefficient")
    parser.add_argument("--wp", type=float, default=0.60, help="Channel width exponent")
    parser.add_argument("--wmin", type=float, default=5.0, help="Minimum channel width (m)")
    parser.add_argument("--hmin", type=float, default=1.0, help="Minimum channel depth (m)")

    args = parser.parse_args()

    # Determine VIC grid extent
    if args.grid_nc:
        print(f"Reading grid extent from: {args.grid_nc}")
        info = read_grid_nc(args.grid_nc)
        vic_west = info["west"]
        vic_east = info["east"]
        vic_south = info["south"]
        vic_north = info["north"]
        args.grid_resolution = info["resolution"]
    elif args.west is not None and args.east is not None:
        vic_west = args.west
        vic_east = args.east
        vic_south = args.south
        vic_north = args.north
    else:
        print("ERROR: Provide either --grid_nc or --west/--east/--south/--north")
        sys.exit(1)

    print(f"{'='*60}")
    print(f"  CaMa-Flood Configuration: {args.basin_name}")
    print(f"  VIC grid: W={vic_west}, E={vic_east}, S={vic_south}, N={vic_north}")
    print(f"  Resolution: {args.grid_resolution} deg")
    print(f"  Period: {args.start_year}-{args.end_year}")
    print(f"{'='*60}")

    # CaMa domain (with buffer)
    domain = compute_domain(vic_west, vic_east, vic_south, vic_north, args.buffer_deg)
    print(f"  CaMa domain (with {args.buffer_deg} deg buffer):")
    print(f"    W={domain['west']}, E={domain['east']}, S={domain['south']}, N={domain['north']}")

    map_dir = os.path.join(CAMA_ROOT, "map", f"{args.basin_name}_15min")
    os.makedirs(map_dir, exist_ok=True)
    print(f"  Map directory: {map_dir}")

    # Step 1: Regionalize
    if not args.skip_step1:
        if not step1_regionalize(map_dir, domain):
            print("FAILED at Step 1 (Regionalization)")
            sys.exit(1)
    else:
        print("\n  SKIP: Step 1 (Regionalization)")

    # Step 2: Input matrix
    if not args.skip_step2:
        if not step2_generate_inpmat(map_dir, args.basin_name,
                                     vic_west, vic_east, vic_south, vic_north,
                                     args.grid_resolution):
            print("FAILED at Step 2 (Input Matrix)")
            sys.exit(1)
    else:
        print("\n  SKIP: Step 2 (Input Matrix)")

    # Step 3: Channel parameters
    if not args.skip_step3:
        if not step3_channel_params(map_dir, args.basin_name,
                                    hc=args.hc, hp=args.hp, ho=0.0, hmin=args.hmin,
                                    wc=args.wc, wp=args.wp, wo=0.0, wmin=args.wmin):
            print("FAILED at Step 3 (Channel Parameters)")
            sys.exit(1)
    else:
        print("\n  SKIP: Step 3 (Channel Parameters)")

    # Step 4: Run script
    script_path = step4_generate_run_script(
        args.basin_name, map_dir, args.runoff_dir, args.runoff_prefix,
        args.start_year, args.end_year, args.output_dir,
        pmanriv=args.pmanriv, pmanfld=args.pmanfld, nspinup=args.nspinup
    )

    print(f"\n{'='*60}")
    print(f"  CONFIGURATION COMPLETE")
    print(f"  Map directory:  {map_dir}")
    print(f"  Run script:     {script_path}")
    print(f"  Next step:      python tools/run_cama.py --script {script_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
