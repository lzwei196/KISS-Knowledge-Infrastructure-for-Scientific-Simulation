"""Prepare the pinned DART compiler configuration without generating example data."""
from pathlib import Path
import subprocess
import sys

PIN = '80502a8e030f5308f557a326819c18cb5079c494'
root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
if head != PIN:
    raise SystemExit('This DART build configuration requires the exact manifest commit')
templates = root / 'build_templates'
source = (templates / 'mkmf.template.gfortran').read_text()
(templates / 'mkmf.template').write_text('NETCDF = /opt/homebrew\n' + source)
script = root / 'models/lorenz_63/work/quickbuild.sh'
text = script.read_text()
marker = '# Installation-only build: omit example NetCDF data generation.'
if '\ncdl_to_netcdf\n' in text:
    text = text.replace('\ncdl_to_netcdf\n', '\n' + marker + '\n', 1)
    script.write_text(text)
elif marker not in text:
    raise SystemExit('DART quickbuild layout differs from the reviewed source')
print('Prepared native gfortran/netCDF build; scientific source unchanged')
