"""Build official ISSM tag2026.2 headless native executable with genuine dependencies."""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys
root=Path(sys.argv[1]).resolve();cwd=Path.cwd().resolve()
if root!=cwd and cwd not in root.parents:raise SystemExit('Source outside working directory')
head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
if head!='fe0867872156f8f77bdf7c6ce50cde301abe768e':raise SystemExit('Unexpected official source commit')
p=root/'src/c/Makefile.am';h=hashlib.sha256(p.read_bytes()).hexdigest()
if h=='551686d0341da52357a4821f1e0b4377d94ff5aaad2300046875822e26ec5d6d':
 s,n=re.subn(r'^(\w+_DEPENDENCIES) = libISSMCore.la libISSMModules.la$',lambda m:m[1]+' = libISSMCore.la\nif WRAPPERS\n'+m[1]+' += libISSMModules.la\nendif',p.read_text(),flags=re.M)
 if n!=6:raise SystemExit('Unexpected headless build patch context')
 p.write_text(s)
elif h!='497289159a0dcc7112fe49c1463da00a5a235dc7cb5dc99667eb65d8f26ba70f':raise SystemExit('Unexpected build source hash')
config={}
for parent in [cwd,*cwd.parents]:
 q=parent/'issm-build-config.json'
 if q.is_file():config=json.loads(q.read_text());break
if not config:raise SystemExit('Provide genuine PETSc3.23.6, Triangle and static M1QN3 build prefixes in workspace issm-build-config.json; read MACOS_INSTALL.md')
petsc=Path(config['petsc_prefix']).resolve();tri=Path(config['triangle_prefix']).resolve();m1=Path(config['m1qn3_prefix']).resolve()
for q in [petsc/'include/petscversion.h',petsc/'lib/libpetsc.dylib',petsc/'lib/libscalapack.dylib',petsc/'lib/libmetis.dylib',petsc/'lib/libparmetis.dylib',tri/'lib/libtriangle.dylib',m1/'libm1qn3.a',m1/'libddot.a']:
 if not q.is_file():raise SystemExit('Missing genuine build dependency: '+str(q))
s=(petsc/'include/petscversion.h').read_text()
for k,v in [('MAJOR',3),('MINOR',23),('SUBMINOR',6)]:
 if not re.search(r'#define\s+PETSC_VERSION_'+k+r'\s+'+str(v)+r'\b',s):raise SystemExit('Expected PETSc3.23.6')
env=os.environ.copy();env.update(ISSM_DIR=str(root),FI_PROVIDER='tcp',FI_TCP_IFACE='en0',MAKEFLAGS='-j2')
def run(args,name):
 with (root/name).open('w') as log:subprocess.run([str(x) for x in args],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
run([root/'scripts/automakererun.sh'],'ki-autoreconf.log')
run([root/'configure',f'--prefix={root}','--without-wrappers','--disable-static','--with-numthreads=2','--with-fortran-lib=-L/opt/homebrew/lib/gcc/current -lgfortran','--with-mpi-include=/opt/homebrew/opt/mpich/include','--with-mpi-libflags=-L/opt/homebrew/opt/mpich/lib -lmpi -lmpicxx -lmpifort',f'--with-blas-lapack-dir={petsc}',f'--with-metis-dir={petsc}',f'--with-parmetis-dir={petsc}',f'--with-scalapack-dir={petsc}',f'--with-mumps-dir={petsc}',f'--with-petsc-dir={petsc}',f'--with-triangle-dir={tri}',f'--with-m1qn3-dir={m1}'],'ki-configure.log')
run(['make','-j2'],'ki-build.log');run(['make','install'],'ki-install.log')
if not (root/'bin/issm.exe').is_file():raise SystemExit('Native ISSM product missing')
