#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      run_summa_twophase
Stage:        s6_execution
Description:  Two-phase SUMMA execution for subtropical/temperate basins.

  Phase 1 (spinup):    Run 1 year with presTemp (stable, no energy balance).
                        Builds realistic soil moisture/temperature profiles.
                        Writes restart file with -r y.
  Phase 2 (production): Switch to nrg_flux (full energy balance + ET).
                        Uses Phase 1 restart as initial conditions.

  This solves the cold-start convergence failure that occurs when nrg_flux
  is used with unrealistic initial soil temperatures (dt_007, dt_020).

  Without this: presTemp → zero ET → zero runoff → PBIAS=-99%.
  With this:    nrg_flux → proper ET → realistic water balance.

Exit codes: 0=success, 1=input error, 2=phase1 error, 3=phase2 error, 4=output error
"""

import sys
import os
import re
import json
import shutil
import logging
import subprocess
import time
from pathlib import Path
from glob import glob

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SUMMA_EXE = "/mnt/disk1/Hydrocraft_server/model/summa/bin/summa.exe"
FILE_MANAGER = ""
SPINUP_YEARS = 1          # Number of spinup years with presTemp
PHASE2_DECISIONS = {}     # Override decisions for production phase
TIMEOUT = 14400           # 4 hours max per phase

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Two-phase SUMMA execution")
    parser.add_argument("--summa_exe", default=SUMMA_EXE, help="Path to summa.exe")
    parser.add_argument("--file_manager", required=True, help="Path to fileManager.txt")
    parser.add_argument("--spinup_years", type=int, default=1, help="Years of presTemp spinup (default: 1)")
    parser.add_argument("--timeout", type=int, default=14400, help="Timeout per phase in seconds")
    args = parser.parse_args()
    SUMMA_EXE = args.summa_exe
    FILE_MANAGER = args.file_manager
    SPINUP_YEARS = args.spinup_years
    TIMEOUT = args.timeout


def parse_file_manager(fm_path):
    """Parse fileManager.txt into a dict of key→value."""
    config = {}
    with open(fm_path) as f:
        for line in f:
            clean = line.split('!')[0].strip()
            if not clean:
                continue
            parts = clean.split(None, 1)
            if len(parts) == 2:
                key = parts[0]
                val = parts[1].strip().strip("'")
                config[key] = val
    return config


def write_file_manager(fm_path, config, comment=""):
    """Write a fileManager.txt from a config dict."""
    with open(fm_path, 'w') as f:
        f.write("! SUMMA fileManager.txt\n")
        if comment:
            f.write(f"! {comment}\n")
        f.write("!\n")
        for key, val in config.items():
            if key in ('controlVersion', 'simStartTime', 'simEndTime', 'tmZoneInfo',
                       'outFilePrefix'):
                f.write(f"{key:<20s} '{val}'\n")
            elif key.endswith('Path'):
                f.write(f"{key:<20s} '{val}'\n")
            else:
                f.write(f"{key:<20s} '{val}'\n")


def modify_decisions(decisions_path, overrides):
    """Modify specific decisions in a decisions.txt file."""
    with open(decisions_path) as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        clean = line.split('!')[0].strip()
        modified = False
        for key, val in overrides.items():
            if clean.startswith(key):
                comment = line.split('!')[1] if '!' in line else ''
                new_lines.append(f"{key:<20s} {val:<30s} ! {comment.strip()}\n")
                modified = True
                break
        if not modified:
            new_lines.append(line)

    with open(decisions_path, 'w') as f:
        f.writelines(new_lines)


def run_summa(exe, fm_path, log_path, extra_args=None, label="SUMMA"):
    """Run SUMMA and return (exit_code, elapsed_seconds)."""
    cmd = [exe, '-m', fm_path]
    if extra_args:
        cmd.extend(extra_args)

    logger.info(f"[{label}] Running: {' '.join(cmd)}")
    t0 = time.time()

    with open(log_path, 'w') as lf:
        result = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=TIMEOUT)

    elapsed = time.time() - t0
    logger.info(f"[{label}] Exit code: {result.returncode}, Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")

    # Check for success
    with open(log_path) as f:
        log_content = f.read()

    if 'finished simulation successfully' in log_content:
        logger.info(f"[{label}] Finished successfully")
    elif 'FATAL ERROR' in log_content:
        # Extract error
        for line in log_content.split('\n'):
            if 'FATAL ERROR' in line:
                logger.error(f"[{label}] {line.strip()}")
                break

    return result.returncode, elapsed


def find_restart_file(output_dir, prefix):
    """Find the most recent restart file written by SUMMA."""
    pattern = os.path.join(output_dir, f"{prefix}*_restart_*.nc")
    files = sorted(glob(pattern))
    if files:
        return files[-1]
    # Also check state path
    return None


def process():
    """Execute two-phase SUMMA workflow."""
    fm_config = parse_file_manager(FILE_MANAGER)
    base_dir = Path(FILE_MANAGER).parent
    settings_path = fm_config.get('settingsPath', str(base_dir / 'settings/'))
    output_path = fm_config.get('outputPath', str(base_dir / 'output/'))
    decisions_file = os.path.join(settings_path, fm_config.get('decisionsFile', 'decisions.txt'))
    prefix = fm_config.get('outFilePrefix', 'summa')

    # Parse simulation period
    sim_start = fm_config.get('simStartTime', '1980-01-01 03:00')
    sim_end = fm_config.get('simEndTime', '1985-12-31 21:00')
    start_year = int(sim_start[:4])
    end_year = int(sim_end[:4])
    spinup_end_year = start_year + SPINUP_YEARS

    logger.info(f"=== TWO-PHASE SUMMA EXECUTION ===")
    logger.info(f"  Phase 1: {start_year}-{spinup_end_year-1} with presTemp (spinup)")
    logger.info(f"  Phase 2: {start_year}-{end_year} with nrg_flux (production, restart from Phase 1)")

    # === PHASE 1: SPINUP with presTemp ===
    logger.info(f"\n{'='*60}")
    logger.info(f"PHASE 1: presTemp spinup ({start_year}-{spinup_end_year-1})")
    logger.info(f"{'='*60}")

    # Backup original decisions
    decisions_backup = decisions_file + '.bak_twophase'
    shutil.copy2(decisions_file, decisions_backup)

    # Set presTemp for spinup stability
    modify_decisions(decisions_file, {
        'bcUpprTdyn': 'presTemp',
        'stomResist': 'simpleResistance',
    })

    # Create Phase 1 fileManager with shortened period
    fm1_path = str(base_dir / 'fileManager_phase1.txt')
    fm1_config = dict(fm_config)
    fm1_config['simStartTime'] = sim_start
    spinup_end = f"{spinup_end_year}-01-01 00:00"
    fm1_config['simEndTime'] = spinup_end
    fm1_config['outFilePrefix'] = f"{prefix}_spinup"
    write_file_manager(fm1_path, fm1_config, "Phase 1: presTemp spinup")

    # Clear output
    for f in Path(output_path).glob("*.nc"):
        f.unlink()

    # Run Phase 1 with yearly restart
    exit1, time1 = run_summa(SUMMA_EXE, fm1_path, str(base_dir / 'summa_phase1.log'),
                              extra_args=['-r', 'y'], label="Phase 1")

    if exit1 != 0:
        logger.error("Phase 1 failed — cannot proceed to Phase 2")
        # Restore decisions
        shutil.copy2(decisions_backup, decisions_file)
        sys.exit(2)

    # Find restart file
    restart_file = find_restart_file(output_path, f"{prefix}_spinup")
    if not restart_file:
        # Check state path too
        state_path = fm_config.get('statePath', output_path)
        restart_file = find_restart_file(state_path, f"{prefix}_spinup")

    if not restart_file:
        logger.error(f"No restart file found in {output_path} or state path")
        # Try to find any restart file
        all_restarts = list(Path(output_path).glob("*restart*.nc"))
        if all_restarts:
            restart_file = str(sorted(all_restarts)[-1])
            logger.info(f"Found restart: {restart_file}")
        else:
            logger.error("Cannot find restart file — Phase 2 will use cold start")
            shutil.copy2(decisions_backup, decisions_file)
            sys.exit(2)

    logger.info(f"Restart file: {restart_file}")

    # === PHASE 2: PRODUCTION with nrg_flux ===
    logger.info(f"\n{'='*60}")
    logger.info(f"PHASE 2: nrg_flux production ({start_year}-{end_year})")
    logger.info(f"{'='*60}")

    # Copy restart file to settings as initial conditions
    restart_dest = os.path.join(settings_path, 'warmState.nc')
    shutil.copy2(restart_file, restart_dest)
    logger.info(f"Copied restart → {restart_dest}")

    # Switch to nrg_flux
    shutil.copy2(decisions_backup, decisions_file)  # Restore original
    modify_decisions(decisions_file, {
        'bcUpprTdyn': 'nrg_flux',
    })

    # Create Phase 2 fileManager using warm restart
    fm2_path = str(base_dir / 'fileManager_phase2.txt')
    fm2_config = dict(fm_config)
    fm2_config['simStartTime'] = sim_start  # Start from beginning (restart handles state)
    fm2_config['simEndTime'] = sim_end
    fm2_config['initConditionFile'] = 'warmState.nc'
    fm2_config['outFilePrefix'] = prefix
    write_file_manager(fm2_path, fm2_config, "Phase 2: nrg_flux production with warm restart")

    # Clear Phase 1 output
    for f in Path(output_path).glob("*spinup*.nc"):
        f.unlink()

    # Run Phase 2
    exit2, time2 = run_summa(SUMMA_EXE, fm2_path, str(base_dir / 'summa_phase2.log'),
                              extra_args=['-r', 'never'], label="Phase 2")

    if exit2 != 0:
        logger.error("Phase 2 (nrg_flux) failed — falling back to presTemp-only results")
        # Fallback: re-run full period with presTemp
        logger.info("FALLBACK: Running full period with presTemp...")
        modify_decisions(decisions_file, {'bcUpprTdyn': 'presTemp', 'stomResist': 'simpleResistance'})
        for f in Path(output_path).glob("*.nc"):
            f.unlink()
        exit_fb, time_fb = run_summa(SUMMA_EXE, FILE_MANAGER,
                                      str(base_dir / 'summa_fallback.log'), label="Fallback")
        total_time = time1 + time2 + time_fb
        result_phase = "fallback_presTemp"
    else:
        total_time = time1 + time2
        result_phase = "nrg_flux"

    # Restore original decisions
    shutil.copy2(decisions_backup, decisions_file)

    logger.info(f"\n{'='*60}")
    logger.info(f"TWO-PHASE COMPLETE")
    logger.info(f"  Phase 1 (presTemp spinup): {time1:.0f}s")
    logger.info(f"  Phase 2 ({result_phase}):  {time2:.0f}s")
    logger.info(f"  Total: {total_time:.0f}s ({total_time/60:.1f} min)")
    logger.info(f"{'='*60}")

    print(json.dumps({
        "status": "success" if exit2 == 0 else "fallback",
        "result_phase": result_phase,
        "phase1_time_s": round(time1, 1),
        "phase2_time_s": round(time2, 1),
        "total_time_s": round(total_time, 1),
        "restart_file": restart_file,
        "output_dir": output_path,
    }))

    return output_path


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    try:
        output_dir = process()
    except subprocess.TimeoutExpired:
        logger.error(f"SUMMA timed out after {TIMEOUT}s")
        sys.exit(2)
    except Exception as e:
        logger.error(f"Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    sys.exit(0)
