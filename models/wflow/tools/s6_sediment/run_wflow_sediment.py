#!/usr/bin/env python3
"""
run_wflow_sediment.py — Execute wflow_sediment model via Julia subprocess.

wflow_sediment runs as a post-processor using wflow_sbm hydrological outputs.
The SBM model must be run first to produce overland flow and precipitation data.

Usage:
    python run_wflow_sediment.py \
      --toml /path/to/wflow_sediment.toml \
      --timeout 3600
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HYDROCRAFT_ROOT = Path("/mnt/disk1/Hydrocraft_server")
JULIA_BINARY_DEFAULT = str(HYDROCRAFT_ROOT / "model" / "julia-1.10.7" / "bin" / "julia")
JULIA_ENV_DEFAULT = str(
    HYDROCRAFT_ROOT / "models" / "wflow" / "knowledge_infrastructure" / "julia"
)
WFLOW_RUNNER = str(
    HYDROCRAFT_ROOT / "models" / "wflow" / "knowledge_infrastructure" / "julia" / "wflow_runner.jl"
)


def main():
    parser = argparse.ArgumentParser(description="Run wflow_sediment model")
    parser.add_argument("--toml", type=str, required=True)
    parser.add_argument("--julia_binary", type=str, default="")
    parser.add_argument("--julia_env", type=str, default="")
    parser.add_argument("--threads", type=str, default="auto")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    # Validate
    if not os.path.exists(args.toml):
        print(json.dumps({"status": "error", "error": f"TOML not found: {args.toml}"}))
        sys.exit(1)

    julia_bin = args.julia_binary or JULIA_BINARY_DEFAULT
    if not os.path.exists(julia_bin):
        import shutil
        julia_bin = shutil.which("julia") or julia_bin

    julia_env = args.julia_env or JULIA_ENV_DEFAULT

    cmd = [
        julia_bin,
        f"--project={julia_env}",
        f"--threads={args.threads}",
        WFLOW_RUNNER,
        os.path.abspath(args.toml),
    ]

    print(f"Running wflow_sediment...", file=sys.stderr)
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=args.timeout,
            cwd=os.path.dirname(os.path.abspath(args.toml)),
        )
        elapsed = time.time() - start_time

        output = {
            "status": "success" if result.returncode == 0 else "failed",
            "return_code": result.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "stdout_last": result.stdout.strip().split("\n")[-10:] if result.stdout else [],
            "stderr_last": result.stderr.strip().split("\n")[-5:] if result.stderr else [],
        }
    except subprocess.TimeoutExpired:
        output = {
            "status": "timeout",
            "timeout_seconds": args.timeout,
        }
    except Exception as e:
        output = {"status": "error", "error": str(e)}

    print(json.dumps(output, indent=2))
    sys.exit(0 if output["status"] == "success" else 1)


if __name__ == "__main__":
    main()
