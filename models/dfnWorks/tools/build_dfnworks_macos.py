#!/usr/bin/env python3
"""Build genuine dfnWorks2.10/LaGriT3.3.3. No model objects, meshes or simulations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

DFN_PIN='1c102b068097a9b9d8bfa9182dd6d2d2d41cf6c8'
LAGRIT_PIN='35f2fc81ae0b42a00f05e332db9f762516dc51fd'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',default='binaries/dfnWorks')
    parser.add_argument('--runtime-config',default='dfnworks-build-config.json')
    args=parser.parse_args()
    root=Path.cwd().resolve();prefix=Path(args.prefix).resolve()
    if (platform.system(),platform.machine())!=('Darwin','arm64'):raise SystemExit('Native macOS arm64 required')
    if prefix==root or not prefix.is_relative_to(root):raise SystemExit('Workspace-contained prefix required')
    if sys.prefix==sys.base_prefix:raise SystemExit('Use the genuine workspace venv Python')
    if sys.version_info[:2]!=(3,13):raise SystemExit('Audited Python version is3.13')
    prefix.mkdir(parents=True,exist_ok=True);records=[]
    env=dict(os.environ,MAKEFLAGS='-j2',MPLBACKEND='Agg',MPLCONFIGDIR=str(prefix/'mplcache'))
    cert=Path('/opt/homebrew/etc/openssl@3/cert.pem')
    if cert.is_file():
        env.setdefault('SSL_CERT_FILE',str(cert))
        env.setdefault('PIP_CERT',str(cert))
    def run(stage,command,cwd=None):
        start=time.monotonic()
        with (prefix/(stage+'.log')).open('w') as log:
            result=subprocess.run(command,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
        records.append(dict(stage=stage,argv=command,returncode=result.returncode,seconds=round(time.monotonic()-start,3)))
        (prefix/'build-receipt.json').write_text(json.dumps(records,indent=2)+'\n')
        if result.returncode:raise SystemExit('Failed stage '+stage+'; see its log')
    def checkout(name,url,pin,patterns):
        source=prefix/'source'/name
        if not (source/'.git').is_dir():
            source.parent.mkdir(parents=True,exist_ok=True)
            run(name+'-clone',['git','clone','--filter=blob:none','--no-checkout','--depth','1',url,str(source)])
            run(name+'-sparse-init',['git','-C',str(source),'sparse-checkout','init','--no-cone'])
            run(name+'-sparse-set',['git','-C',str(source),'sparse-checkout','set',*patterns])
            run(name+'-fetch',['git','-C',str(source),'fetch','--filter=blob:none','--depth','1','origin',pin])
            run(name+'-checkout',['git','-C',str(source),'checkout',pin])
        actual=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
        if actual!=pin:raise SystemExit('Wrong pinned source: '+name)
        if subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],text=True).strip():raise SystemExit('Modified tracked source: '+name)
        return source
    source=checkout('upstream','https://github.com/lanl/dfnWorks.git',DFN_PIN,
        ['/DFNGen/*.cpp','/DFNGen/*.h','/DFNGen/makefile','/DFNTrans/*.c','/DFNTrans/*.h','/DFNTrans/makefile','/CPP_correct_volumes/','/DFN_Mesh_Connectivity_Test/','/pydfnworks/','!/pydfnworks/**/examples/','!/pydfnworks/**/tests/','/LICENSE.md','/README.md'])
    lagrit=checkout('lagrit-upstream','https://github.com/lanl/LaGriT.git',LAGRIT_PIN,
        ['/src/','/lg_util/','/cmake/','/CMakeLists.txt','/README.md','/LICENSE.md'])
    hashes=json.loads(Path(__file__).with_name('native-source-hashes.json').read_text())
    for name,digest in hashes.items():
        file=lagrit/name.removeprefix('lagrit/') if name.startswith('lagrit/') else source/name
        if hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise SystemExit('Patch source hash mismatch: '+name)
    adapted=prefix/'source/repo';adapted.mkdir(parents=True,exist_ok=True)
    for sub in ['DFNGen','DFNTrans','CPP_correct_volumes','DFN_Mesh_Connectivity_Test']:
        target=adapted/sub;target.mkdir(exist_ok=True)
        for file in (source/sub).iterdir():
            if file.suffix in ['.cpp','.c','.h'] or file.name=='makefile':shutil.copy2(file,target/file.name)
    driver=adapted/'DFNGen/DFNmain.cpp';text=driver.read_text();needle='int main (int argc, char **argv) {'
    if text.count(needle)!=1:raise SystemExit('Unexpected DFNGen main')
    text=text.replace(needle,needle+'\n    if (argc == 2 && std::string(argv[1]) == "--version") {\n        std::cout << "dfnWorks " << KI_DFNWORKS_VERSION << " DFNGen " << KI_DFNGEN_VERSION << std::endl;\n        return 0;\n    }')
    driver.write_text('#include "ki_version.h"\n'+text)
    version=re.search(r'__version__ = "([^"]+)"',(source/'pydfnworks/pydfnworks/__init__.py').read_text()).group(1)
    generator=re.search(r'DFNGEN_VERSION = ([^\n]+)',(source/'DFNGen/makefile').read_text()).group(1).strip()
    (adapted/'DFNGen/ki_version.h').write_text(f'#define KI_DFNWORKS_VERSION "{version}"\n#define KI_DFNGEN_VERSION "{generator}"\n')
    run('dfngen-build',['make','-j2','DFNGen','CXX=/usr/bin/clang++'],adapted/'DFNGen')
    run('dfntrans-build',['make','-j2','DFNTrans','CC=/usr/bin/clang','CFLAGS=-lm -Wall -g -O3 -include sys/stat.h -Wno-error=return-mismatch'],adapted/'DFNTrans')
    run('volume-build',['make','-j2','CC=/usr/bin/clang++ -std=c++17'],adapted/'CPP_correct_volumes')
    run('connectivity-build',['make','-j2','main','CXX=/usr/bin/clang++'],adapted/'DFN_Mesh_Connectivity_Test')
    lagrit_adapted=prefix/'source/lagrit'
    for sub in ['src','lg_util','cmake']:shutil.copytree(lagrit/sub,lagrit_adapted/sub,dirs_exist_ok=True)
    shutil.copy2(lagrit/'CMakeLists.txt',lagrit_adapted/'CMakeLists.txt')
    driver=lagrit_adapted/'src/lagrit_main.f';text=driver.read_text();needle="      mode = 'noisy'"
    if text.count(needle)!=1:raise SystemExit('Unexpected LaGriT main')
    text=text.replace(needle,"      include 'lagrit.h'\n\n      call get_command_argument(1,arg)\n      if (trim(arg).eq.'--version') then\n         write(*,'(a,i0,a,i0,a,i0)') 'LaGriT ',v_major,'.',\n     &        v_minor,'.',v_patch\n         stop\n      endif\n\n"+needle);driver.write_text(text)
    build=prefix/'lagrit-build'
    run('lagrit-configure',['cmake','-S',str(lagrit_adapted),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER=/usr/bin/clang','-DCMAKE_CXX_COMPILER=/usr/bin/clang++','-DCMAKE_Fortran_COMPILER=/opt/homebrew/bin/gfortran','-DCMAKE_Fortran_FLAGS=-fallow-argument-mismatch','-DCMAKE_C_FLAGS=-Wno-error=implicit-int -Wno-error=implicit-function-declaration','-DLAGRIT_BUILD_EXODUS=OFF'])
    run('lagrit-build',['cmake','--build',str(build),'--parallel','2'])
    run('python-install',[sys.executable,'-m','pip','install',str(source/'pydfnworks')])
    config=json.loads(Path(args.runtime_config).read_text())
    runtime=dict(dfnworks_PATH=str(adapted)+'/',PETSC_DIR=config['petsc_dir'],
                 PETSC_ARCH=config['petsc_arch'],PFLOTRAN_EXE=config['pflotran_exe'],
                 LAGRIT_EXE=str(build/'lagrit'),FEHM_EXE=None)
    (prefix/'runtime-paths.json').write_text(json.dumps(runtime,indent=2)+'\n')
    print('Native builds and genuine Python installation completed. Run separate fixed installation verification.')
    print('Exodus-dependent DFM and FEHM are not provisioned; no simulation was run.')

if __name__=='__main__':main()
