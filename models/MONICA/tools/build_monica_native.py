"""Build official MONICA 3.6.56 with genuine pinned native dependencies."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
SOURCE='84f97cb37ff5dcd6a210d40f346de7130822cad7'
VCPKG='74e6536215718009aae747d86d84b78376bf9e09'
root=Path(sys.argv[1]).resolve();workspace=Path.cwd().resolve()
if root!=workspace and workspace not in root.parents:raise SystemExit('Source must be in working directory')
def run(args,cwd=root,env=None):subprocess.run([str(x) for x in args],cwd=cwd,env=env,check=True)
def head(path):return subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
if head(root)!=SOURCE:raise SystemExit('Unexpected MONICA source commit')
run(['git','submodule','update','--init','--recursive'])
p=root/'mas_cpp_misc/json11/json11-helper.h';digest=hashlib.sha256(p.read_bytes()).hexdigest()
if digest=='0488a27d275ce0b4caf04ed467a9e17bdbb1d7dad0b18bea6aa5fada5a6cc21c':
 s=p.read_text();old='  for (auto v: col)\n    js.push_back(v);';new='  for (typename Collection::value_type v: col)\n    js.push_back(v);'
 if s.count(old)!=1:raise SystemExit('Compatibility patch context changed')
 p.write_text(s.replace(old,new))
elif digest!='bf328e4cc87ad1dd475ab66825acdbc55db9c7bd385b6da9069d077dbefc2dbf':raise SystemExit('Unexpected JSON helper source hash')
# Optional genuine prebuilt build-dependency checkout; resulting executable links only macOS system libraries.
config={}
for parent in [root, root.parent.parent]:
 candidate=parent/'monica-build-config.json'
 if candidate.is_file():config=json.loads(candidate.read_text());break
vcpkg=Path(config['vcpkg_root']).resolve() if config.get('vcpkg_root') else root/'.ki-vcpkg'
if not vcpkg.exists():
 run(['git','clone','--depth','1','--branch','2025.10.17','https://github.com/microsoft/vcpkg.git',vcpkg])
if head(vcpkg)!=VCPKG:raise SystemExit('Unexpected vcpkg revision')
env=os.environ.copy();env.update(VCPKG_MAX_CONCURRENCY='2',VCPKG_DISABLE_METRICS='1')
if not (vcpkg/'vcpkg').is_file():run([vcpkg/'bootstrap-vcpkg.sh','-disableMetrics'],cwd=vcpkg,env=env)
run([vcpkg/'vcpkg','install','capnproto','libsodium','zeromq','--triplet','arm64-osx','--disable-metrics'],cwd=vcpkg,env=env)
run(['cmake','-S',root,'-B',root/'ki-build','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64','-DCMAKE_C_COMPILER=/usr/bin/clang','-DCMAKE_CXX_COMPILER=/usr/bin/clang++',f'-DCMAKE_TOOLCHAIN_FILE={vcpkg}/scripts/buildsystems/vcpkg.cmake','-DVCPKG_TARGET_TRIPLET=arm64-osx'])
run(['cmake','--build',root/'ki-build','--target','monica-run','-j2'])
if not (root/'ki-build/monica-run').is_file():raise SystemExit('Native MONICA product missing')
