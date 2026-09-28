"""Select workspace-native dependency paths without writing ~/.dfnworksrc."""
import json
import os
from pathlib import Path
import sys


def configure_native_runtime():
    if sys.platform != 'darwin':
        return
    path = Path(os.environ.get('DFNWORKS_RUNTIME_PATHS', 'binaries/dfnWorks/runtime-paths.json')).resolve()
    if not path.is_file():
        raise RuntimeError('Run the native installation helper or set DFNWORKS_RUNTIME_PATHS to its runtime-paths.json')
    data = json.loads(path.read_text())
    for key in ('dfnworks_PATH', 'PETSC_DIR', 'PETSC_ARCH', 'PFLOTRAN_EXE', 'LAGRIT_EXE'):
        if not isinstance(data.get(key), str) or not data[key]:
            raise RuntimeError('Incomplete native dependency configuration: ' + key)
    from pydfnworks.general import paths
    paths.DFNPARAMS = str(path)
