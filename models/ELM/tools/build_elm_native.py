#!/usr/bin/env python3
"""Pinned E3SM v3 ELM build-only driver; never generate run namelists or run cases."""
import argparse, json, os, shlex, subprocess, sys
from pathlib import Path
import xml.etree.ElementTree as ET
PIN='399d4301138617088dd93214123d6c025e061302'
MODULES={'cime':'ESMCI/cime','externals/mct':'MCSclimate/MCT','externals/scorpio':'E3SM-Project/scorpio','externals/ekat':'E3SM-Project/EKAT','components/elm/src/external_models/fates':'NGEET/fates','components/elm/src/external_models/mpp':'MPP-LSM/MPP','components/elm/src/external_models/sbetr':'BeTR-biogeochemistry-modeling/sbetr'}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',nargs='?',default='.');p.add_argument('--runtime');p.add_argument('--python');p.add_argument('--configure-only',action='store_true');p.add_argument('--native-stage',action='store_true');p.add_argument('--model-only',action='store_true');a=p.parse_args()
 source=Path(a.source).resolve()
 if not source.is_relative_to(Path.cwd().resolve()):raise SystemExit('Source must be within current workspace')
 if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()!=PIN:raise SystemExit('Unexpected E3SM source commit')
 cfg={}
 for path in (source.parent.parent/'elm-build-config.json',source/'elm-build-config.json'):
  if path.is_file():cfg.update(json.loads(path.read_text()))
 runtime=Path(a.runtime or cfg.get('native_runtime') or os.environ.get('ELM_NATIVE_RUNTIME','')).resolve()
 python=Path(a.python or cfg.get('build_python') or sys.executable).absolute()
 for name in ['include/netcdf.mod','bin/mpifort','lib/libnetcdff.dylib']:
  if not(runtime/name).is_file():raise SystemExit('Missing native dependency '+str(runtime/name))
 (source/'elm-build-config.json').write_text(json.dumps({'native_runtime':str(runtime),'build_python':str(python)},indent=2)+'\n')
 env=os.environ.copy();env.update(PATH=str(python.parent)+':'+str(runtime/'bin')+':/opt/homebrew/bin:'+env.get('PATH',''),MPICH_FC='/opt/homebrew/bin/gfortran -I'+str(source/'ki-build/gnu/mpich/nodebug/nothreads/mct/include'),MPICH_CC='/usr/bin/clang -I'+str(source/'externals/scorpio/src/clib'),MPICH_CXX='/usr/bin/clang++ -I'+str(source/'externals/scorpio/src/clib'),NETCDF_PATH=str(runtime),NETCDF_C_PATH=str(runtime),NETCDF_FORTRAN_PATH=str(runtime),PNETCDF_PATH=str(runtime),CMAKE_PREFIX_PATH=str(runtime))
 def run(cmd,cwd=source):
  print('+',' '.join(map(str,cmd)),flush=True);subprocess.run(list(map(str,cmd)),cwd=cwd,env=env,check=True)
 if a.native_stage:
  os.environ.update(env);os.environ['CIMEROOT']=str(source/'cime');sys.path.insert(0,str(source/'cime'))
  from CIME.config import Config
  Config.load(str(source/'cime_config/customize'))
  Config.instance().case_setup_generate_namelist=False
  from CIME.case import Case
  from CIME.build import case_build
  import logging
  logging.basicConfig(level=logging.INFO)
  casepath=source/'ki-case'
  with Case(str(casepath),read_only=False,record=True) as case:
   Config.instance().case_setup_generate_namelist=False
   case.case_setup()
   if case.get_value('MASK_GRID')=='reg':raise SystemExit('This audited build route requires a global grid')
   for component in ['cpl','mosart']:(casepath/'Buildconf'/(component+'conf')).mkdir(parents=True,exist_ok=True)
   elmconf=casepath/'Buildconf/elmconf';elmconf.mkdir(parents=True,exist_ok=True)
   run([source/'components/elm/bld/configure','-comp_intf','mct',*shlex.split(case.get_value('ELM_CONFIG_OPTS') or ''),'-usr_src',casepath/'SourceMods/src.elm'],elmconf)
   if not a.configure_only:
    if not a.model_only and not case_build(str(casepath),case,sharedlib_only=True,buildlist=['gptl','mct','spio','csm_share']):raise SystemExit('ELM native support build failed')
    if not case_build(str(casepath),case,model_only=True):raise SystemExit('ELM native model build/link failed')
  return
 for path,repo in MODULES.items():
  run(['git','submodule','init',path])
  entries=subprocess.check_output(['git','config','-f','.gitmodules','--get-regexp','submodule.*.path'],cwd=source,text=True).splitlines()
  key=next(x.split()[0].removesuffix('.path')+'.url' for x in entries if x.split()[1]==path)
  run(['git','config',key,'https://github.com/'+repo+'.git'])
 run(['git','submodule','update','--init','--depth','1',*MODULES])
 machinefile=source/'cime_config/machines/config_machines.xml';tree=ET.parse(machinefile);machine=next(n for n in tree.getroot() if n.attrib.get('MACH')=='mac')
 for key,leaf in {'CIME_OUTPUT_ROOT':'ki-output','DIN_LOC_ROOT':'ki-inputdata','DIN_LOC_ROOT_CLMFORC':'ki-inputdata','DOUT_S_ROOT':'ki-archive','BASELINE_ROOT':'ki-baselines','RUNDIR':'ki-run','EXEROOT':'ki-build'}.items():
  machine.find(key).text=str(source/leaf)
 variables=machine.find('environment_variables')
 if variables is None:variables=ET.SubElement(machine,'environment_variables')
 for key in ['NETCDF_PATH','NETCDF_C_PATH','NETCDF_FORTRAN_PATH','PNETCDF_PATH']:
  node=next((n for n in variables if n.attrib.get('name')==key),None)
  if node is None:node=ET.SubElement(variables,'env',{'name':key})
  node.text=env[key]
 tree.write(machinefile,encoding='unicode')
 macro=source/'cime_config/machines/cmake_macros/gnu_mac.cmake'
 macro.write_text('string(APPEND CMAKE_C_FLAGS " -DNETCDF_ENABLE_LEGACY_MACROS")\nset(SPIO_CMAKE_OPTS "-DCMAKE_POLICY_VERSION_MINIMUM=3.5")\nset(SCC "/usr/bin/clang")\nset(SCXX "/usr/bin/clang++")\nset(SFC "/opt/homebrew/bin/gfortran")\n'+''.join('set('+key+' "'+env[key]+'")\n' for key in ['NETCDF_PATH','NETCDF_C_PATH','NETCDF_FORTRAN_PATH','PNETCDF_PATH'])+'string(REGEX REPLACE "-mcmodel=(large|medium)" "-mcmodel=small" CMAKE_C_FLAGS "${CMAKE_C_FLAGS}")\nstring(REGEX REPLACE "-mcmodel=(large|medium)" "-mcmodel=small" CMAKE_Fortran_FLAGS "${CMAKE_Fortran_FLAGS}")\n')
 case=source/'ki-case'
 if not case.exists():run([python,source/'cime/scripts/create_newcase','--case',case,'--compset','I1850ELM','--res','f19_g16','--machine','mac','--compiler','gnu','--mpilib','mpich','--pecount','1'])
 run([python,case/'xmlchange',','.join(['EXEROOT='+str(source/'ki-build'),'RUNDIR='+str(source/'ki-run'),'DIN_LOC_ROOT='+str(source/'ki-inputdata'),'GET_REFCASE=FALSE','GMAKE_J=2','GMAKE=/usr/bin/make'])],case)
 cmd=[python,Path(__file__).resolve(),source,'--runtime',runtime,'--python',python,'--native-stage']
 if a.configure_only:cmd.append('--configure-only')
 run(cmd)
 if not a.configure_only and not(source/'ki-build/e3sm.exe').is_file():raise SystemExit('Native e3sm.exe missing after compile')
if __name__=='__main__':main()
