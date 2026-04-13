#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      verify_mf6_installation
Stage:        s1_installation
Description:  Verify MODFLOW 6 binary and FloPy are installed and functional.

Inputs:
  - MF6_PATH: path to mf6 executable (auto-detected if on PATH)

Outputs:
  - JSON with mf6_version, flopy_version, mf6_path, status

Exit codes:
  0 — success
  1 — input validation failed
  2 — processing error
  3 — output validation failed
"""

import sys
import os
import json
import shutil
import logging
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MF6_PATH = ""  # Leave empty to auto-detect from PATH

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    """Check preconditions."""
    # MF6_PATH is optional — will auto-detect
    pass


def process():
    """Check mf6 binary and FloPy installation."""
    result = {
        "mf6_version": None,
        "mf6_path": None,
        "flopy_version": None,
        "status": "error",
        "errors": [],
    }

    # Check FloPy
    try:
        import flopy
        result["flopy_version"] = flopy.__version__
        logger.info(f"FloPy version: {flopy.__version__}")
    except ImportError:
        result["errors"].append("FloPy is not installed. Run: pip install flopy")
        logger.error("FloPy is not installed")

    # Find mf6 binary
    mf6_path = MF6_PATH
    if not mf6_path:
        # Try to find mf6 on PATH
        mf6_path = shutil.which("mf6")
    if not mf6_path:
        # Try common locations
        candidates = [
            Path(__file__).resolve().parents[2] / "bin" / "mf6",
            Path("/usr/local/bin/mf6"),
            Path.home() / ".local" / "bin" / "mf6",
        ]
        for c in candidates:
            if c.exists():
                mf6_path = str(c)
                break

    if mf6_path and Path(mf6_path).exists():
        result["mf6_path"] = str(mf6_path)
        # Get version
        try:
            proc = subprocess.run(
                [mf6_path, "--version"],
                capture_output=True, text=True, timeout=10
            )
            version_line = proc.stdout.strip() or proc.stderr.strip()
            result["mf6_version"] = version_line
            logger.info(f"mf6 version: {version_line}")
        except Exception as e:
            # mf6 without --version may just try to run and look for mfsim.nam
            result["mf6_version"] = "detected but version unknown"
            logger.warning(f"Could not get mf6 version: {e}")
    else:
        result["errors"].append(
            f"mf6 binary not found. Set MF6_PATH or install: "
            f"python -c \"import flopy.utils; flopy.utils.get_modflow(bindir='./bin')\""
        )
        logger.error("mf6 binary not found")

    # Overall status
    if not result["errors"]:
        result["status"] = "ok"
    elif result["flopy_version"] and not result["mf6_path"]:
        result["status"] = "flopy_only"
    elif result["mf6_path"] and not result["flopy_version"]:
        result["status"] = "mf6_only"

    return result


def validate_outputs(result):
    """Check that at least FloPy or mf6 was found."""
    if result["status"] == "error":
        logger.error("Neither mf6 nor FloPy are available")
        print(json.dumps(result, indent=2))
        sys.exit(3)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    # Allow CLI override
    if len(sys.argv) > 1:
        MF6_PATH = sys.argv[1]

    validate_inputs()

    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    validate_outputs(result)

    print(json.dumps(result, indent=2))
    logger.info(f"Installation check complete: {result['status']}")
    sys.exit(0)
