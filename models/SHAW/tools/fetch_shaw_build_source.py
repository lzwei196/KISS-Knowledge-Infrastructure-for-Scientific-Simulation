"""Retrieve only the audited official SHAW 3.03 Fortran ZIP member."""
from pathlib import Path
import hashlib
import struct
import subprocess
import sys
import tempfile
import zlib

URL = "https://www.ars.usda.gov/ARSUserFiles/20520500/SHAW/303/Shaw303.zip"
SHA256 = "b10bb45c984d7f9c1831f722fcd5a27f1d091ff08da4b6d838d2bcd51066a1fe"

def main():
    root = Path.cwd().resolve()
    target = Path(sys.argv[1]).resolve()
    if not target.is_relative_to(root):
        raise SystemExit("Source target must be inside the installation workspace")
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != SHA256:
            raise SystemExit("Existing source does not match audited official source")
        print("Official SHAW source already verified")
        return
    with tempfile.TemporaryDirectory(prefix="shaw-source-") as scratch:
        entry = Path(scratch) / "entry.bin"
        subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                        "--max-time", "120", "--range", "881590-987738",
                        "--output", str(entry), URL], check=True, timeout=135)
        data = entry.read_bytes()
    if len(data) != 106149 or data[:4] != b"PK\x03\x04":
        raise SystemExit("Official archive changed or server ignored Range; audit before retrying")
    header = struct.unpack_from("<4s5H3I2H", data)
    name_length, extra_length = header[-2:]
    if data[30:30 + name_length] != b"Shaw303/Code+Debug/Shaw303.for" or header[3] != 8:
        raise SystemExit("Unexpected ZIP source member")
    start = 30 + name_length + extra_length
    source = zlib.decompress(data[start:start + 106048], -15)
    if len(source) != 482533 or hashlib.sha256(source).hexdigest() != SHA256:
        raise SystemExit("Official Fortran source hash mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source)
    print("Verified official SHAW 3.03 source: " + SHA256)

if __name__ == "__main__":
    main()
