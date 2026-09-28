"""Apply the reviewed Python 3 build-generator port to the pinned CISM source."""
import subprocess
import sys
from pathlib import Path

PIN = "eb7bef68bc3164968330f6109fab2af252148520"
root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
patch = Path(__file__).resolve().parent.parent / "docs/cism-python3-generator.patch"
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
if head != PIN:
    raise SystemExit("CISM generator patch requires the manifest's exact upstream commit")
check = subprocess.run(["git", "apply", "--check", str(patch)], cwd=root, capture_output=True)
if check.returncode:
    reverse = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=root, capture_output=True)
    if reverse.returncode:
        raise SystemExit("CISM source does not match the reviewed build-generator patch")
    print("CISM Python 3 generator port already applied")
else:
    subprocess.run(["git", "apply", str(patch)], cwd=root, check=True)
    print("Applied CISM Python 3 build-generator port")
