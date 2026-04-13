#!/usr/bin/env python3
"""
generate_namelists.py  --  WRF-Hydro Phase 3, Tool 2
=====================================================
Generate namelist.hrldas and hydro.namelist for a WRF-Hydro offline
(NoahMP + gridded routing) simulation.

The namelists are written relative to the run directory, assuming the
standard layout:
    run_dir/
      DOMAIN/          (wrfinput_d01.nc, geo_em.d01.nc, Fulldom_hires.nc, ...)
      FORCING/         (YYYYMMDDHH.LDASIN_DOMAIN1 files)
      namelist.hrldas
      hydro.namelist
      wrf_hydro.exe    (symlinked)
      *.TBL            (symlinked)

Usage
-----
    python generate_namelists.py \\
        --domain_dir   outputs/chaohe_wrf_test/DOMAIN \\
        --forcing_dir  outputs/chaohe_wrf_test/FORCING \\
        --output_dir   outputs/chaohe_wrf_test \\
        --start_date   2001-01-01 \\
        --end_date     2001-01-07 \\
        --nproc 4 \\
        --output_timestep 3600
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import netCDF4 as nc


def compute_khour(start_date, end_date):
    """Total simulation hours (inclusive of end_date)."""
    dt = end_date - start_date + timedelta(days=1)
    return int(dt.total_seconds() // 3600)


def detect_grid_params(domain_dir):
    """
    Read Fulldom_hires.nc to detect routing grid resolution and
    aggregation factor.

    Returns
    -------
    dict with keys: dxrt, aggfactrt, e_sn, e_we, e_sn_rt, e_we_rt
    """
    domain_dir = Path(domain_dir)

    # LSM grid dimensions from wrfinput
    ds_wrf = nc.Dataset(str(domain_dir / 'wrfinput_d01.nc'))
    e_sn = len(ds_wrf.dimensions['south_north'])
    e_we = len(ds_wrf.dimensions['west_east'])
    dx = float(ds_wrf.DX) if hasattr(ds_wrf, 'DX') else 1000.0
    ds_wrf.close()

    # Routing grid dimensions from Fulldom
    ds_full = nc.Dataset(str(domain_dir / 'Fulldom_hires.nc'))
    e_sn_rt = len(ds_full.dimensions['y'])
    e_we_rt = len(ds_full.dimensions['x'])
    ds_full.close()

    # Compute aggregation factor
    aggfactrt = e_we_rt // e_we
    if e_sn_rt // e_sn != aggfactrt:
        print(f"  WARNING: x-agg ({e_we_rt // e_we}) != y-agg ({e_sn_rt // e_sn})")
        aggfactrt = e_we_rt // e_we

    dxrt = dx / aggfactrt

    return {
        'dx': dx,
        'dxrt': dxrt,
        'aggfactrt': aggfactrt,
        'e_sn': e_sn,
        'e_we': e_we,
        'e_sn_rt': e_sn_rt,
        'e_we_rt': e_we_rt,
    }


def generate_namelist_hrldas(start_date, end_date, khour,
                              output_timestep=3600,
                              restart_freq=-9999):
    """Generate namelist.hrldas content."""
    return f"""&NOAHLSM_OFFLINE

HRLDAS_SETUP_FILE = "./DOMAIN/wrfinput_d01.nc"
INDIR = "./FORCING"
SPATIAL_FILENAME = "./DOMAIN/soil_properties.nc"
OUTDIR = "./"

START_YEAR  = {start_date.year}
START_MONTH = {start_date.month:02d}
START_DAY   = {start_date.day:02d}
START_HOUR  = 00
START_MIN   = 00

! Simulation length in hours
KHOUR = {khour}

! Physics options (NoahMP defaults for WRF-Hydro)
DYNAMIC_VEG_OPTION                = 4
CANOPY_STOMATAL_RESISTANCE_OPTION = 1
BTR_OPTION                        = 1
RUNOFF_OPTION                     = 3
SURFACE_DRAG_OPTION               = 1
FROZEN_SOIL_OPTION                = 1
SUPERCOOLED_WATER_OPTION          = 1
RADIATIVE_TRANSFER_OPTION         = 3
SNOW_ALBEDO_OPTION                = 2
PCP_PARTITION_OPTION              = 1
TBOT_OPTION                       = 2
TEMP_TIME_SCHEME_OPTION           = 3
GLACIER_OPTION                    = 2
SURFACE_RESISTANCE_OPTION         = 4

! Timesteps in seconds
FORCING_TIMESTEP = 3600
NOAH_TIMESTEP    = 3600
OUTPUT_TIMESTEP  = {output_timestep}

! Land surface model restart file write frequency
RESTART_FREQUENCY_HOURS = {restart_freq}

! Split output after split_output_count output times
SPLIT_OUTPUT_COUNT = 1

! Soil layers (4 Noah layers)
NSOIL = 4
soil_thick_input(1) = 0.10
soil_thick_input(2) = 0.30
soil_thick_input(3) = 0.60
soil_thick_input(4) = 1.00

! Forcing measurement height
ZLVL = 10.0

! Restart file format
rst_bi_in  = 0
rst_bi_out = 0

/

&WRF_HYDRO_OFFLINE

! Forcing data format: 1=HRLDAS-hr format
FORC_TYP = 1

/
"""


def generate_hydro_namelist(grid_params, output_timestep=3600):
    """Generate hydro.namelist content."""
    dxrt = grid_params['dxrt']
    aggfactrt = grid_params['aggfactrt']

    return f"""&HYDRO_nlist

!!!! ---------------------- SYSTEM COUPLING ----------------------- !!!!

! 1=HRLDAS (offline Noah-LSM)
sys_cpl = 1

!!!! ------------------- MODEL INPUT DATA FILES ------------------- !!!!

GEO_STATIC_FLNM = "./DOMAIN/geo_em.d01.nc"
GEO_FINEGRID_FLNM = "./DOMAIN/Fulldom_hires.nc"
HYDROTBL_F = "./DOMAIN/hydro2dtbl.nc"
LAND_SPATIAL_META_FLNM = "./DOMAIN/GEOGRID_LDASOUT_Spatial_Metadata.nc"

! No restart for cold start
RESTART_FILE = ""

!!!! --------------------- MODEL SETUP OPTIONS -------------------- !!!!

IGRID = 1

! Restart write frequency (minutes); -99999 = disable
! NOTE: rst_dt=1440 can crash on arid basins (dt_v038). Use -99999 for safety.
rst_dt = -99999

! rst_typ=0 prevents routing→LSM soil overwrite (prevents dt_v036 crash in arid basins)
rst_typ = 0
rst_bi_in  = 0
rst_bi_out = 0
RSTRT_SWC = 0

! Cold start for groundwater bucket
GW_RESTART = 0

!!!! -------------------- MODEL OUTPUT CONTROL -------------------- !!!!

! Output frequency in minutes
out_dt = {output_timestep // 60}

SPLIT_OUTPUT_COUNT = 1
order_to_write = 1

! I/O format: 4 = no compression (fastest)
io_form_outputs = 4

! Retrospective mode
io_config_outputs = 5

! Write output at time 0
t0OutputFlag = 1

! Channel/bucket influx output
output_channelBucket_influx = 0

! Output file switches
CHRTOUT_DOMAIN = 1       ! Channel point timeseries (1d)
CHANOBS_DOMAIN = 0       ! Forecast/gage point timeseries
CHRTOUT_GRID   = 1       ! Gridded channel streamflow (2d)
LSMOUT_DOMAIN  = 0       ! LSM-routing exchange grid
RTOUT_DOMAIN   = 1       ! Terrain routing variables on routing grid
output_gw      = 1       ! Groundwater output
outlake         = 0       ! Lake output (no lakes for gridded)
frxst_pts_out  = 0       ! ASCII forecast points

!!!! ------------ PHYSICS OPTIONS AND RELATED SETTINGS ------------ !!!!

! Soil layers
NSOIL = 4
ZSOIL8(1) = -0.10
ZSOIL8(2) = -0.40
ZSOIL8(3) = -1.00
ZSOIL8(4) = -2.00

! Routing grid spacing (meters)
DXRT = {dxrt:.1f}

! Aggregation factor (LSM-to-routing)
AGGFACTRT = {aggfactrt}

! Channel routing timestep (seconds)
DTRT_CH = 10

! Terrain routing timestep (seconds)
DTRT_TER = 10

! Subsurface routing
SUBRTSWCRT = 1

! Overland flow routing
OVRTSWCRT = 1

! Overland routing method: 1=steepest descent (D8)
rt_option = 1

! Channel routing: 3=diffusive wave (gridded)
CHANRTSWCRT = 1
channel_option = 3

! Compound channel (only for reach-based)
compound_channel = .FALSE.

! Baseflow bucket model: 1=exponential bucket
GWBASESWCRT = 1

! Groundwater basin mask
gwbasmskfil = "./DOMAIN/GWBASINS.nc"

! Groundwater bucket parameters
GWBUCKPARM_file = "./DOMAIN/GWBUCKPARM.nc"

! User-defined mapping (NHDPlus): 0=no
UDMP_OPT = 0

/

&NUDGING_nlist

/
"""


def main():
    parser = argparse.ArgumentParser(
        description='Generate WRF-Hydro namelist.hrldas and hydro.namelist')
    parser.add_argument('--domain_dir', required=True,
                        help='Directory containing DOMAIN files')
    parser.add_argument('--forcing_dir', required=True,
                        help='Directory containing LDASIN forcing files')
    parser.add_argument('--output_dir', required=True,
                        help='Run directory where namelists are written')
    parser.add_argument('--start_date', required=True,
                        help='Start date YYYY-MM-DD')
    parser.add_argument('--end_date', required=True,
                        help='End date YYYY-MM-DD (inclusive)')
    parser.add_argument('--nproc', type=int, default=4,
                        help='Number of MPI processes (informational)')
    parser.add_argument('--output_timestep', type=int, default=3600,
                        help='Output timestep in seconds (default 3600)')
    parser.add_argument('--restart_freq', type=int, default=-9999,
                        help='Restart write frequency in hours (-9999=never)')
    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("WRF-Hydro Namelist Generator")
    print("=" * 60)

    # Compute simulation length
    khour = compute_khour(start_date, end_date)
    print(f"  Period: {start_date.date()} to {end_date.date()}")
    print(f"  Simulation length: {khour} hours ({khour/24:.1f} days)")

    # Detect grid parameters
    print("\n  Detecting grid parameters from DOMAIN files...")
    grid_params = detect_grid_params(args.domain_dir)
    print(f"  LSM grid:     {grid_params['e_sn']} x {grid_params['e_we']} @ {grid_params['dx']:.0f}m")
    print(f"  Routing grid: {grid_params['e_sn_rt']} x {grid_params['e_we_rt']} @ {grid_params['dxrt']:.0f}m")
    print(f"  AGGFACTRT:    {grid_params['aggfactrt']}")

    # Verify DOMAIN files exist
    domain_dir = Path(args.domain_dir)
    required_files = [
        'wrfinput_d01.nc', 'geo_em.d01.nc', 'Fulldom_hires.nc',
        'hydro2dtbl.nc', 'soil_properties.nc',
        'GEOGRID_LDASOUT_Spatial_Metadata.nc',
        'GWBASINS.nc', 'GWBUCKPARM.nc',
    ]
    missing = [f for f in required_files if not (domain_dir / f).exists()]
    if missing:
        print(f"\n  WARNING: Missing DOMAIN files: {missing}")

    # Verify FORCING directory has files
    forcing_dir = Path(args.forcing_dir)
    if forcing_dir.exists():
        ldasin_files = sorted(forcing_dir.glob('*.LDASIN_DOMAIN1'))
        print(f"\n  FORCING directory has {len(ldasin_files)} LDASIN files")
        if ldasin_files:
            print(f"  First: {ldasin_files[0].name}")
            print(f"  Last:  {ldasin_files[-1].name}")
    else:
        print(f"\n  WARNING: FORCING directory not found: {forcing_dir}")

    # Generate namelist.hrldas
    print("\n  Writing namelist.hrldas...")
    hrldas_content = generate_namelist_hrldas(
        start_date, end_date, khour,
        output_timestep=args.output_timestep,
        restart_freq=args.restart_freq,
    )
    hrldas_path = output_dir / 'namelist.hrldas'
    hrldas_path.write_text(hrldas_content)
    print(f"  -> {hrldas_path}")

    # Generate hydro.namelist
    print("  Writing hydro.namelist...")
    hydro_content = generate_hydro_namelist(
        grid_params,
        output_timestep=args.output_timestep,
    )
    hydro_path = output_dir / 'hydro.namelist'
    hydro_path.write_text(hydro_content)
    print(f"  -> {hydro_path}")

    # Summary
    print("\n" + "=" * 60)
    print("Namelists generated successfully!")
    print(f"  Run directory:  {output_dir}")
    print(f"  namelist.hrldas: KHOUR={khour}, FORCING_TIMESTEP=3600")
    print(f"  hydro.namelist:  DXRT={grid_params['dxrt']:.0f}m, "
          f"AGGFACTRT={grid_params['aggfactrt']}, channel_option=3")
    print(f"  MPI processes:  {args.nproc} (set when running)")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
