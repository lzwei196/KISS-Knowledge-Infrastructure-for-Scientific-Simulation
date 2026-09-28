#!/usr/bin/env python3
"""Build exact GIFMod0.1.26 with genuine Qt5; never open GUI or run model cases."""
import argparse,hashlib,json,subprocess,shutil,sys
from pathlib import Path
PIN='2a314750418099ca51a100d824381924ba982c91'
HASHES = {'GIFMod.pro': ['006bef064968364fb1e52634cbc644cc4761e0343b590da4c999b7ab95d8148d', '3519512536f76be53e6c51151a70987accc0c1e1783f47e2b18856630cfd38ea'], 'src/GUI/main.cpp': ['d55e4ce237ace0fe1d4aa43eb091869388e0414282628e11c25f4a72d507435c', '6199333019b179421f77c268b0b6689629dafe640b7a953eeb7bae965a088d1e'], 'src/GUI/qcustomplot.h': ['99d08cd0d8cc252a93b1f38903ba7f9f45c3ef84daeb582b98e82eee3a738b4a', '2fabed3eddf7f67a20f8005e322dc2a55ee36d057d16c0c9d52c62473a863259'], 'src/GUI/tth_source.c': ['b8c93cc1f32623b086053f48b3b86646ae0cfc12f7db7c142ae250fc69b0968f', '695ad4d2400751e86cf79dd7173bbb67bcf86d97a375c13007a51454fba367d4']}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',nargs='?',default='.');p.add_argument('--qt-runtime');p.add_argument('--patch-only',action='store_true');a=p.parse_args();source=Path(a.source).resolve();config={}
 if not source.is_relative_to(Path.cwd().resolve()):raise SystemExit('Source must remain inside current workspace')
 for c in [source.parent.parent/'gifmod-build-config.json',source/'gifmod-build-config.json']:
  if c.is_file():config.update(json.loads(c.read_text()))
 qt=a.qt_runtime or config.get('qt_runtime')
 if not qt:raise SystemExit('Provide --qt-runtime or gifmod-build-config.json qt_runtime with genuine Qt5 development prefix')
 qt=Path(qt).resolve();qmake=qt/'bin/qmake'
 if not qmake.is_file():raise SystemExit('Missing real Qt5 qmake: '+str(qmake))
 version=subprocess.check_output([str(qmake),'-v'],text=True)
 if 'Qt version 5.15.15' not in version:raise SystemExit('Expected audited Qt5.15.15, received: '+version)
 if subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()!=PIN:raise SystemExit('Unexpected GIFMod source pin')
 statuses=[]
 for f,(original,patched) in HASHES.items():
  digest=hashlib.sha256((source/f).read_bytes()).hexdigest()
  if digest not in [original,patched]:raise SystemExit('Unexpected source content: '+f)
  statuses.append(digest==patched)
 if any(statuses) and not all(statuses):raise SystemExit('Partially patched source; inspect before continuing')
 if not all(statuses):
  patch=Path(__file__).with_name('_gifmod_macos.patch').resolve()
  subprocess.run(['git','apply','--check',str(patch)],cwd=source,check=True)
  subprocess.run(['git','apply',str(patch)],cwd=source,check=True)
 for f,(_,patched) in HASHES.items():
  if hashlib.sha256((source/f).read_bytes()).hexdigest()!=patched:raise SystemExit('Patch verification failed: '+f)
 (source/'gifmod-build-config.json').write_text(json.dumps({'qt_runtime':str(qt)},indent=2)+'\n')
 if a.patch_only:print('Exact GIFMod source patch verified');return
 commands=[[str(qmake),'GIFMod.pro','CONFIG+=release'],['make','-j2']]
 for i,cmd in enumerate(commands,1):
  log=source/f'gifmod-build-step-{i}.log';print('Building:',cmd,'Log:',log,flush=True)
  with log.open('w') as f:r=subprocess.run(cmd,cwd=source,stdout=f,stderr=subprocess.STDOUT)
  if r.returncode:print(log.read_text(errors='replace')[-12000:]);raise SystemExit('Native build failed; retained '+str(log))
 dest=source/'builds/release'
 for f in ['GIFModGUIPropList.csv','help.txt']:shutil.copyfile(source/'src/resources'/f,dest/f)
 shutil.copytree(source/'src/GUI/Icons',dest/'Icons',dirs_exist_ok=True)
 product=dest/'GIFMod'
 if not product.is_file():raise SystemExit('Native GIFMod product missing')
 (source/'gifmod-build-receipt.json').write_text(json.dumps({'source_commit':PIN,'qt_runtime':str(qt),'native_product':str(product),'scientific_execution':False},indent=2)+'\n')
if __name__=='__main__':main()
