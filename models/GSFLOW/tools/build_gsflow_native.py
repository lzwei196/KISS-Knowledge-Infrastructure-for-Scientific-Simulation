"""Build the pinned GSFLOW source using its genuine upstream pymake driver."""
from pathlib import Path
import subprocess,sys
root=Path(sys.argv[1]).resolve();workspace=Path.cwd().resolve()
if root!=workspace and workspace not in root.parents:raise SystemExit('Source outside working directory')
subprocess.run([sys.executable,str(Path(__file__).with_name('prepare_gsflow_build_cli.py')),str(root)],check=True)
subprocess.run([sys.executable,'make_gfortran.py','-fc','gfortran','-cc','clang','-sd','-mc','../GSFLOW/src','gsflow'],cwd=root/'autotest',check=True)
if not (root/'autotest/gsflow').is_file():raise SystemExit('Native product missing')
