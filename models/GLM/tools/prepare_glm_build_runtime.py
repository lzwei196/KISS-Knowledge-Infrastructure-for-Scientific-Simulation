"""Repair the audited upstream GLM3.3.3 Apple Silicon runtime bundle."""
from pathlib import Path
import hashlib, platform, shutil, subprocess, sys
EXPECTED = {'libavif.16.dylib': 'bcfdb544a100553a4dd9f2340b01ac767cd602c446ad558b13cf0e212b109658', 'libnetcdf.22.dylib': '5521f1efb8f9189790b2bc8c3ac3c5785220e40ef93fd6f983bd294c7a5752cc', 'libfreetype.6.dylib': '97fedfdaf3d470c1d8661968f7bb7888df4876cadcedfd7ba58429d2a10b1676', 'libhdf5.310.dylib': '5ff04fa27730f53d4d349a31905c99fa3a243aeddb56b90efdff3951105646b2', 'libaom.3.dylib': 'c9998ca704233a578f57d29e3255def7f0da79ad6dc7eac49193590b34ffd5a2', 'libgd.3.dylib': 'a1428f608d36b448de904ee0514d8bc88c9ba1f34f23ff34eafd829e032d25e3', 'libgfortran.5.dylib': '7ab7a2067674831c87bb79bdafebf79785b3f27b925f31ea746f8cc09b22fb94', 'libhdf5_hl.310.dylib': 'c891ec653ff1eb779c428eee48b6b81414cc343c454dbd3776ad9b55d6876d55', 'libfontconfig.1.dylib': '83b9e643ffb758f4bb6e2738b45a736898fcea52ff5defc5b6b0360dfbe2a150', 'libtiff.6.dylib': 'eb2a60895c29dcd3d74f1995896e083ce7f14b6dc37e778c6cf38016b68d4426'}
RUNTIMES = {'libgcc_s.1.1.dylib': {'source': '/opt/homebrew/opt/gcc/lib/gcc/current/libgcc_s.1.1.dylib', 'sha256': '92a431021184d7cd7ab028d79173191482af16d5bc280664e42d92aaed02b92f'}, 'libsharpyuv.0.dylib': {'source': '/opt/homebrew/lib/libsharpyuv.0.dylib', 'sha256': '755e13860aa122e98f1be1bb7d5fcf47b496ae27d5787fe783af3909721d2321'}}
if platform.system() != 'Darwin' or platform.machine() != 'arm64':
    raise SystemExit('Only the audited native Apple Silicon bundle is supported')
root=Path.cwd().resolve()
bundle=Path(sys.argv[1]).resolve()
if root not in bundle.parents:
    raise SystemExit('Bundle must be inside the installation workspace')
for name,digest in EXPECTED.items():
    p=bundle/name
    result=subprocess.run(['codesign','--verify',str(p)],capture_output=True)
    if result.returncode == 0:
        continue
    if hashlib.sha256(p.read_bytes()).hexdigest() != digest:
        raise SystemExit('Unexpected upstream library bytes: '+name)
    subprocess.run(['codesign','--force','--sign','-',str(p)],check=True)
    subprocess.run(['codesign','--verify',str(p)],check=True)
for name,entry in RUNTIMES.items():
    p=bundle/name
    if p.exists():
        if hashlib.sha256(p.read_bytes()).hexdigest() != entry['sha256']:
            raise SystemExit('Unexpected existing runtime: '+name)
        continue
    source=Path(entry['source'])
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
        raise SystemExit('Audited native runtime unavailable: '+str(source))
    shutil.copy2(source,p)
    subprocess.run(['codesign','--verify',str(p)],check=True)
print('Audited GLM runtime repair complete')
