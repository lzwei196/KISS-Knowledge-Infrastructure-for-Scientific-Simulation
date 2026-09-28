#!/usr/bin/env python3
"""Install pinned icepack with audited native Firedrake dependencies; no scientific calls."""
import argparse, hashlib, json, os, subprocess, tempfile
from pathlib import Path
PIN='6c67b51b445398cf4a6ef284ebe602c397bd6ee4'
TOOLS=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',nargs='?',default='.');p.add_argument('--verify-only',action='store_true');p.add_argument('--config');a=p.parse_args()
 source=Path(a.source).resolve(); workspace=source.parent.parent
 if not source.is_relative_to(Path.cwd().resolve()):raise SystemExit('Source must remain inside current workspace')
 config=json.loads((Path(a.config) if a.config else workspace/'icepack-build-config.json').read_text())
 python=Path(config['python']).absolute(); wheels=Path(config['native_wheel_dir']).resolve(); petsc=Path(config['petsc_dir']).resolve();arch=config['petsc_arch']
 if arch!='arch-firedrake-default':raise SystemExit('Expected audited PETSc architecture')
 if not (petsc/arch/'lib/libpetsc.3.25.5.dylib').is_file():raise SystemExit('Missing genuine PETSc3.25.5 provider')
 runtime=json.loads(subprocess.check_output([str(python),'-c','import json,sys;print(json.dumps({"version":list(sys.version_info[:2]),"prefix":sys.prefix,"base_prefix":sys.base_prefix}))'],text=True))
 if runtime['version']!=[3,11]:raise SystemExit('Native wheels require genuine Python3.11')
 if runtime['prefix']==runtime['base_prefix'] or not Path(runtime['prefix']).resolve().is_relative_to(workspace):raise SystemExit('Configured Python must be a real venv inside this workspace')
 if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()!=PIN:raise SystemExit('Wrong icepack source identity')
 hashes=json.loads((TOOLS/'_icepack_source_hashes.json').read_text())
 for f,h in hashes.items():
  if hashlib.sha256((source/'src/icepack'/f).read_bytes()).hexdigest()!=h:raise SystemExit('Altered icepack source: '+f)
 receipts=json.loads((TOOLS/'_icepack_native_wheels.json').read_text()); wheelpaths=[]
 for f,rec in receipts.items():
  path=wheels/f
  if hashlib.sha256(path.read_bytes()).hexdigest()!=rec['sha256']:raise SystemExit('Native dependency wheel hash mismatch: '+f)
  wheelpaths.append(str(path))
 env=os.environ.copy();env.update(FI_PROVIDER='tcp',FI_TCP_IFACE='en0',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PETSC_DIR=str(petsc),PETSC_ARCH=arch)
 if not a.verify_only:
  commands=[['-m','pip','install','--no-index','--no-deps',*wheelpaths],['-m','pip','install','--constraint',str(TOOLS/'_icepack_constraints.txt'),'firedrake==2026.4.2',str(source)]]
  for i,cmd in enumerate(commands,1):
   log=source/f'icepack-install-{i}.log';print('Installing genuine source/dependencies; log:',log,flush=True)
   with log.open('w') as out:r=subprocess.run([str(python),*cmd],env=env,cwd=source,stdout=out,stderr=subprocess.STDOUT,timeout=1800)
   if r.returncode:raise SystemExit(log.read_text(errors='replace')[-10000:])
 code='''import hashlib,json,importlib.metadata as m
from pathlib import Path
import icepack, firedrake, h5py, ROL, _ROL
from petsc4py import PETSc
from mpi4py import MPI
expected=json.loads(Path(HASHFILE).read_text())
root=Path(icepack.__file__).parent
assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in expected.items()), 'Installed icepack source mismatch'
assert m.version('icepack')=='1.1.0' and m.version('firedrake')=='2026.4.2'
assert PETSc.Sys.getVersion()==(3,25,5) and h5py.get_config().mpi
assert 'MPICH Version:      4.3.1' in MPI.Get_library_version()
assert callable(icepack.models.IceStream)
print('ICEPACK_NATIVE_IMPORT='+json.dumps({'icepack_version':m.version('icepack'),'firedrake_version':m.version('firedrake'),'petsc_version':PETSc.Sys.getVersion(),'icepack_file':icepack.__file__,'rol_native':_ROL.__file__,'source_files_verified':len(expected),'hdf5_mpi':h5py.get_config().mpi,'scientific_execution':False}))
'''.replace('HASHFILE',repr(str(TOOLS/'_icepack_source_hashes.json')))
 with tempfile.TemporaryDirectory(prefix='icepack-import-') as cwd:
  probe=subprocess.run([str(python),'-c',code],cwd=cwd,env=env,text=True,capture_output=True,timeout=180)
  created=list(Path(cwd).iterdir())
 if probe.returncode or 'ICEPACK_NATIVE_IMPORT=' not in probe.stdout or created:raise SystemExit('Native import verification failed: '+probe.stdout+probe.stderr)
 receipt={'source_commit':PIN,'python':str(python),'native_wheels':receipts,'petsc_dir':str(petsc),'petsc_arch':arch,'returncode':probe.returncode,'stdout':probe.stdout,'stderr':probe.stderr,'scientific_execution':False}
 (source/'icepack-build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(probe.stdout)
if __name__=='__main__':main()
