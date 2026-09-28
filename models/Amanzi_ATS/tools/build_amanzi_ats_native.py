#!/usr/bin/env python3
"""Pinned software-only ATS native preparation and installation.

Recipe validated by native source/build audit; each fresh installation must pass the recorded probes.
"""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,tempfile,time,signal,shutil
AMANZI_COMMIT='f8b03562ec6dea6257baf1250bddf889caef8ffb'
ATS_COMMIT='e23c8eef6773e1a055cbda74f1c7c4a553c7d6c5'
HERE=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def capture(args,cwd=None,env=None):
 return subprocess.check_output([str(x) for x in args],cwd=cwd,env=env,text=True,stderr=subprocess.STDOUT)
def run(args,cwd=None,env=None,log=None,input=None):
 if log:
  with Path(log).open('w') as out:subprocess.run([str(x) for x in args],cwd=cwd,env=env,input=input,text=True,stdout=out,stderr=subprocess.STDOUT,check=True)
 else:subprocess.run([str(x) for x in args],cwd=cwd,env=env,input=input,text=True,check=True)
def guarded_native_build(args,cwd,env,log):
 minimum=16*1024**3;started=time.monotonic();reason=None
 if shutil.disk_usage(cwd).free<minimum:raise SystemExit('Native build disk guard: less than16GiB free before start')
 with Path(log).open('w') as out:
  process=subprocess.Popen([str(x) for x in args],cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
  try:
   while process.poll() is None:
    if shutil.disk_usage(cwd).free<minimum:reason='disk guard: less than16GiB free';break
    if time.monotonic()-started>3600:reason='native build exceeded3600seconds';break
    time.sleep(2)
  finally:
   if process.poll() is None:
    os.killpg(process.pid,signal.SIGTERM)
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:
     os.killpg(process.pid,signal.SIGKILL);process.wait()
  record={'returncode':process.returncode,'reason':reason,'seconds':time.monotonic()-started,'free_bytes':shutil.disk_usage(cwd).free,'minimum_free_bytes':minimum,'log':str(log),'process_group':process.pid}
  (Path(cwd)/'ki-native-build-status.json').write_text(json.dumps(record,indent=2)+'\n')
  if reason or process.returncode:raise SystemExit('Native build failed; inspect preserved ki-build.log and ki-native-build-status.json')

def git(root,*args):return capture(['git','-C',root,*args])

def prepare_checkout(root,url,commit,patterns):
 root.mkdir(parents=True,exist_ok=True)
 if not (root/'.git').exists():
  if any(root.iterdir()):raise SystemExit('Refusing to clone over nonempty source directory')
  # No initial full checkout: fetched blobs follow the exact software-only patterns.
  run(['git','clone','--filter=blob:none','--no-checkout',url,root])
 elif git(root,'rev-parse','HEAD').strip()!=commit:
  raise SystemExit('Existing source is not the pinned commit; use a fresh source directory')
 run(['git','-C',root,'sparse-checkout','init','--no-cone'])
 run(['git','-C',root,'sparse-checkout','set','--no-cone','--stdin'],input=patterns)
 run(['git','-C',root,'checkout','--detach',commit])
 if git(root,'rev-parse','HEAD').strip()!=commit:raise SystemExit('Source pin mismatch')

def apply_proven_cmake_repairs(root):
 repairs=json.loads((HERE/'source-compatibility-patches.json').read_text())
 for repair in repairs:
  path=root/repair['path'];before=digest(path)
  if before==repair['after_sha256']:continue
  if before!=repair['before_sha256']:raise SystemExit('Unexpected source hash: '+repair['path'])
  source=path.read_text()
  if source.count(repair['old'])!=1:raise SystemExit('Patch anchor mismatch: '+repair['path'])
  changed=source.replace(repair['old'],repair['new'])
  if hashlib.sha256(changed.encode()).hexdigest()!=repair['after_sha256']:raise SystemExit('Patch output mismatch: '+repair['path'])
  path.write_text(changed)
 return repairs

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('source',help='Workspace-contained Amanzi source/install directory')
 parser.add_argument('--prepare-only',action='store_true',help='Only clone pinned software sources, no native model or dependencies')
 args=parser.parse_args();workspace=Path.cwd().resolve();root=Path(args.source).resolve()
 if root!=workspace and workspace not in root.parents:raise SystemExit('Source must be inside working directory')
 prepare_checkout(root,'https://github.com/amanzi/amanzi.git',AMANZI_COMMIT,(HERE/'amanzi-sparse-patterns.txt').read_text())
 ats=root/'src/physics/ats'
 prepare_checkout(ats,'https://github.com/amanzi/ats.git',ATS_COMMIT,(HERE/'ats-sparse-patterns.txt').read_text())
 # Version generation requires genuine upstream tags, while HEAD remains pinned.
 run(['git','-C',ats,'fetch','--filter=blob:none','--tags','https://github.com/amanzi/ats.git'])
 if git(ats,'rev-parse','HEAD').strip()!=ATS_COMMIT:raise SystemExit('ATS pin changed during tag fetch')
 provenance={'status':'source prepared; native model not yet verified','amanzi_commit':AMANZI_COMMIT,'ats_commit':ATS_COMMIT,'software_only_patterns':{x:digest(HERE/x) for x in ['amanzi-sparse-patterns.txt','ats-sparse-patterns.txt']},'scientific_execution':False,'nested_demo_submodules':False,'source_tree_ids':{'amanzi':git(root,'rev-parse','HEAD^{tree}').strip(),'ats':git(ats,'rev-parse','HEAD^{tree}').strip()},'entry_source_sha256':{'ats_main':digest(ats/'src/executables/main.cc'),'amanzi_main':digest(root/'src/common/standalone_simulation_coordinator/Main.cc')}}
 provenance['source_preparation_metadata']={'amanzi_tools_py_lib_cmake_sha256':digest(root/'tools/py_lib/CMakeLists.txt'),'ats_testing_cmake_sha256':digest(ats/'testing/CMakeLists.txt'),'amanzi_software_schema_sha256':digest(root/'doc/input_spec/schema/amanzi.xsd'),'amanzi_update_spec_software_sha256':digest(root/'tools/input/UpdateSpec_210to211.py'),'ats_upstream_tags':git(ats,'for-each-ref','--format=%(refname) %(objectname)','refs/tags/').splitlines()}
 (root/'ki-native-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
 if args.prepare_only:return
 config=None
 for parent in [workspace,*workspace.parents]:
  candidate=parent/'amanzi-ats-build-config.json'
  if candidate.is_file():config=json.loads(candidate.read_text());break
 if config is None:raise SystemExit('Provide same-host genuine dependencies in workspace amanzi-ats-build-config.json; read MACOS_INSTALL.md')
 for key in ['tpl_prefix','cmake','build_python','mpi_prefix']:
  if not Path(config[key]).is_absolute():raise SystemExit('Provider path must be absolute: '+key)
 tpl=Path(config['tpl_prefix']).resolve();cmake=Path(config['cmake']).absolute();python=Path(config['build_python']).absolute();mpi=Path(config['mpi_prefix']).resolve();cache=tpl/'share/cmake/amanzi-tpl-config.cmake'
 for path in [cache,cmake,python,mpi/'bin/mpicc',mpi/'bin/mpicxx',mpi/'bin/mpif90',mpi/'include/mpi.h']:
  if not path.is_file():raise SystemExit('Missing genuine provider: '+str(path))
 cmake_version=capture([cmake,'--version']);python_version=capture([python,'--version']);mpi_version=capture([mpi/'bin/mpichversion'])
 if not cmake_version.startswith('cmake version 3.31.10'):raise SystemExit('Expected validated CMake3.31.10 provider')
 if not python_version.startswith('Python 3.11.'):raise SystemExit('Expected genuine Python3.11 build environment')
 if '4.3.1' not in mpi_version:raise SystemExit('Expected validated MPICH4.3.1 ABI provider')
 # Proven build-system repairs only; scientific model source is unchanged.
 provenance['compatibility_repairs']=apply_proven_cmake_repairs(root)
 build=root/'ki-build';install=root/'install';env=os.environ.copy();env.update(FI_PROVIDER='tcp',FI_TCP_IFACE='en0',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',CMAKE_BUILD_PARALLEL_LEVEL='2')
 options=json.loads((HERE/'ats-configure-options.json').read_text())
 command=[cmake,'-S',root,'-B',build,'-C'+str(cache),*options,'-DCMAKE_INSTALL_PREFIX:STRING='+str(install),'-DPYTHON_EXECUTABLE:STRING='+str(python)]
 run(command,cwd=root,env=env,log=root/'ki-configure.log')
 guarded_native_build([cmake,'--build',build,'--parallel','2'],cwd=root,env=env,log=root/'ki-build.log')
 run([cmake,'--install',build],cwd=root,env=env,log=root/'ki-install.log')
 binary=install/'bin/ats'
 shape=capture(['file',binary])
 if 'Mach-O 64-bit executable arm64' not in shape:raise SystemExit('Expected genuine native arm64 ATS executable')
 probes=[]
 for flag in ['--version','--print_version','--help']:
  with tempfile.TemporaryDirectory(dir=root,prefix='ki-probe-') as empty:
   started=time.monotonic()
   p=subprocess.run([str(binary),flag],cwd=empty,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=60)
   created=[x.name for x in Path(empty).iterdir()]
   if p.returncode!=0 or created:raise SystemExit('Native installation probe failed: '+flag)
   output=p.stdout+'\n'+p.stderr
   expected=['ATS version','1.6.0_e23c8eef'] if flag!='--help' else ['Run ATS simulations for ecosystem hydrology.']
   if flag=='--print_version':expected += ['Amanzi version','1.7-dev_f8b03562e',AMANZI_COMMIT[:9],ATS_COMMIT[:8]]
   if not all(text in output for text in expected):raise SystemExit('Missing native provenance/banner: '+flag)
   probes.append({'flag':flag,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'created_files':created,'seconds':time.monotonic()-started,'timeout_seconds':60})
 model_libraries=[]
 for library in sorted({x.resolve() for x in (install/'lib').rglob('*.dylib')}):
  if install.resolve() in library.parents:
   model_libraries.append({'path':str(library),'size':library.stat().st_size,'sha256':digest(library)})
 provenance['installed_native_libraries']=model_libraries
 manifest=build/'install_manifest.txt'
 if not manifest.is_file():raise SystemExit('Missing successful native install manifest')
 installed_paths=[Path(x) for x in manifest.read_text().splitlines()]
 if any(not x.is_file() for x in installed_paths):raise SystemExit('Native install manifest contains missing files')
 provenance['install_manifest']={'sha256':digest(manifest),'files':[{'path':str(x),'size':x.stat().st_size,'sha256':digest(x)} for x in sorted(set(installed_paths))]}
 provenance['generated_version_headers']={str(x.relative_to(build)):digest(x) for x in [build/'amanzi_version.hh',build/'src/physics/ats/ats_version.hh'] if x.is_file()}
 provenance.update(status='native installation probes passed; not scientific validation',binary={'path':str(binary),'sha256':digest(binary),'size':binary.stat().st_size,'shape':shape,'otool':capture(['otool','-L',binary])},provider_cache_sha256=digest(cache),provider_versions={'cmake':cmake_version,'python':python_version,'mpich':mpi_version},configure= [str(x) for x in command],source_changes={'amanzi':git(root,'diff','--stat'),'ats':git(ats,'diff','--stat')},probes=probes)
 (root/'ki-native-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')

if __name__=='__main__':main()
