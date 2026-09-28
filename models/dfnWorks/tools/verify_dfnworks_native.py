#!/usr/bin/env python3
"""Fixed installation-only native/package dependency checks; no model construction."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

PFLOTRAN_SHA256='f39ab9ddc7deb81a8ae42dcf01e75aa2d9348c4e036fd043f20f2c09f6dbe629'
PFLOTRAN_PIN='fab315dc6559306f2f93b27571bf5add812dd820'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='.')
    parser.add_argument('--prefix',default='binaries/dfnWorks')
    parser.add_argument('--python',default='venv/bin/python')
    args=parser.parse_args();root=Path(args.root).resolve();prefix=(root/args.prefix).resolve()
    if not prefix.is_relative_to(root):raise SystemExit('Native prefix must be inside root')
    for name,pin in [('upstream','1c102b068097a9b9d8bfa9182dd6d2d2d41cf6c8'),('lagrit-upstream','35f2fc81ae0b42a00f05e332db9f762516dc51fd')]:
        checkout=prefix/'source'/name
        if subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()!=pin:
            raise SystemExit('Native source pin differs: '+name)
        if subprocess.check_output(['git','-C',str(checkout),'status','--porcelain','--untracked-files=no'],text=True).strip():
            raise SystemExit('Modified original native source: '+name)
    hashes=json.loads(Path(__file__).with_name('native-source-hashes.json').read_text())
    for name,digest in hashes.items():
        source=(prefix/'source/lagrit-upstream'/name.removeprefix('lagrit/')) if name.startswith('lagrit/') else (prefix/'source/upstream'/name)
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise SystemExit('Source patch identity mismatch')
    for sub in ['DFNTrans','CPP_correct_volumes','DFN_Mesh_Connectivity_Test']:
        for source in (prefix/'source/upstream'/sub).iterdir():
            if source.suffix in ['.c','.cpp','.h'] or source.name=='makefile':
                if source.read_bytes()!=(prefix/'source/repo'/sub/source.name).read_bytes():
                    raise SystemExit('Unexpected native utility source change: '+str(source))
    python=root/args.python
    if not python.parent.resolve().is_relative_to(root):raise SystemExit('Venv launcher must be inside root')
    config=json.loads((root/'dfnworks-build-config.json').read_text())
    pflotran=Path(config['pflotran_exe']).resolve();petsc=Path(config['petsc_dir']).resolve();arch=config['petsc_arch']
    if hashlib.sha256(pflotran.read_bytes()).hexdigest()!=PFLOTRAN_SHA256:raise SystemExit('Unverified shared PFLOTRAN executable')
    if subprocess.check_output(['git','-C',str(pflotran.parent.parent.parent),'rev-parse','HEAD'],text=True).strip()!=PFLOTRAN_PIN:raise SystemExit('PFLOTRAN source pin differs')
    env=dict(os.environ,FI_PROVIDER='tcp',FI_TCP_IFACE='en0',MPLBACKEND='Agg',MPLCONFIGDIR=str(prefix/'mplcache'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    products=[
      ('DFNGen',prefix/'source/repo/DFNGen/DFNGen',['--version'],0,'dfnWorks 2.10.0 DFNGen 2.3',{'dfngen_logfile.txt'}),
      ('DFNTrans',prefix/'source/repo/DFNTrans/DFNTrans',[],1,'Provide the name of Input Control File',set()),
      ('correct_volume',prefix/'source/repo/CPP_correct_volumes/correct_volume',[],1,'Error: <mode> [parameter file...]',{'correct_volumes_logfile.log'}),
      ('ConnectivityTest',prefix/'source/repo/DFN_Mesh_Connectivity_Test/ConnectivityTest',[],1,'Must inlude cmd line arguments:',set()),
      ('LaGriT',prefix/'lagrit-build/lagrit',['--version'],0,'LaGriT 3.3.3',set()),
      ('PFLOTRAN',pflotran,['-help','intro'],0,'Petsc Release Version 3.21.4',set())]
    receipts=[]
    for name,binary,argv,code,identity,allowed in products:
        if name!='PFLOTRAN' and not binary.resolve().is_relative_to(root):raise SystemExit('Native binary escapes root')
        shape=subprocess.check_output(['file',str(binary)],text=True)
        if 'Mach-O 64-bit executable arm64' not in shape:raise SystemExit('Not native arm64: '+name)
        links=subprocess.check_output(['otool','-L',str(binary)],text=True)
        for line in links.splitlines()[1:]:
            dep=line.strip().split(' (',1)[0]
            if dep.startswith('/') and not dep.startswith(('/usr/lib/','/System/')) and not Path(dep).is_file():raise SystemExit('Missing native dependency '+dep)
        if name=='PFLOTRAN' and str(petsc/arch/'lib') not in links:raise SystemExit('Wrong PETSc dependency prefix')
        with tempfile.TemporaryDirectory(prefix='native-install-',dir=root) as temp:
            result=subprocess.run([str(binary),*argv],cwd=temp,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,errors='replace',timeout=30)
            created={p.name for p in Path(temp).iterdir()}
            if result.returncode!=code or identity not in result.stdout or result.stderr.strip() or not created.issubset(allowed):
                raise SystemExit('Native probe mismatch '+name+': '+repr((result.returncode,result.stdout,result.stderr,created)))
            if name in ('DFNGen','LaGriT') and result.stdout.strip()!=identity:raise SystemExit('Version identity mismatch')
            receipts.append(dict(product=name,path=str(binary),sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),file=shape,linked_libraries=links,argv=argv,returncode=code,stdout=result.stdout,stderr=result.stderr,created_files=sorted(created)))
    code="""import json, pathlib, sys, importlib.metadata
import pydfnworks
assert pydfnworks.__version__ == '2.10.0'
assert importlib.metadata.version('pydfnworks') == '2.10.0'
assert pathlib.Path(pydfnworks.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve())
assert pydfnworks.DFNWORKS.__module__ == 'pydfnworks.general.dfnworks'
print(json.dumps({'version':pydfnworks.__version__,'file':pydfnworks.__file__,'class':str(pydfnworks.DFNWORKS),'prefix':sys.prefix}))
"""
    result=subprocess.run([str(python),'-c',code],cwd=root,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=180)
    if result.returncode:raise SystemExit('Actual package load failed: '+result.stderr)
    receipts.append(dict(product='pydfnworks',returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
    report=dict(installation_only=True,scope='DFN native stack plus Python; external verified PFLOTRAN; Exodus/DFM and FEHM excluded',products=receipts)
    (root/'dfnworks-native-dependencies.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'ready':True,'native_products':6,'python_package':'pydfnworks2.10.0','receipt':str(root/'dfnworks-native-dependencies.json')}))

if __name__=='__main__':main()
