"""Repair invalid ad-hoc signatures in the audited swmm-toolkit0.17.0 Mac wheel."""
import hashlib
import importlib.metadata
from pathlib import Path
import platform
import subprocess
import sys
EXPECTED = {'libomp.dylib': 'b42da331bbddf694e4ba8ca2d86b19a38afe62a2f9c6194858e179bf59497965', 'libswmm-output.dylib': '91033a0ba9de6aced18fb02270fc9daeaa96e5acb8444cccda3be1ab845998dc'}
prefix=Path(sys.prefix).resolve()
if platform.system()!='Darwin' or platform.machine()!='arm64':
    raise SystemExit('This repair is only for native Apple Silicon')
if not ((prefix/'pyvenv.cfg').exists() or (prefix/'conda-meta').is_dir()):
    raise SystemExit('Use an isolated model environment')
dist=importlib.metadata.distribution('swmm-toolkit')
if dist.version!='0.17.0':
    raise SystemExit('Only audited swmm-toolkit0.17.0 is supported')
for name, expected in EXPECTED.items():
    path=Path(dist.locate_file('swmm/toolkit/'+name)).resolve()
    if prefix not in path.parents:
        raise SystemExit('Refusing library outside model environment')
    check=subprocess.run(['/usr/bin/codesign','--verify',str(path)],capture_output=True)
    if check.returncode==0:
        continue
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise SystemExit('Refusing unexpected wheel contents: '+name)
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(path)],check=True)
    subprocess.run(['/usr/bin/codesign','--verify',str(path)],check=True)
print('Audited native SWMM library signatures ready')
