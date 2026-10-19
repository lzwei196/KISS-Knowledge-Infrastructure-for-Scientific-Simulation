"""Host-authored dependency probes for an explicitly bound Ubuntu runtime.

This is capability evidence, not model readiness or an operating-system sandbox.
Only authenticated distribution packages are admitted by the first profile;
workspace dependency shims and provider-authored probe programs are not accepted.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import secrets
import sys
import uuid

from . import implementation_identity

POLICY = "ubuntu-native-dependency-capabilities-v1"
BINARY_POLICY = "ubuntu-native-dependency-binary-v1"
PROFILE = "mpi_netcdf4_fortran_v1"
PACKAGES = ("gfortran", "openmpi-bin", "libopenmpi-dev", "libnetcdff-dev",
            "netcdf-bin", "python3-netcdf4", "python3-apt")
MAX_ARTIFACT = 4 * 1024 * 1024
ARTIFACTS = ("driver.py", "request.json", "mpi.f90", "netcdf.f90", "reader.py",
             "mpi-probe", "netcdf-probe", "probe.nc") + tuple(
    name + suffix for name in ("compile-mpi", "compile-netcdf", "mpi", "netcdf", "reader", "ncdump")
    for suffix in (".stdout", ".stderr"))


class CapabilityError(ValueError):
    """No current, authenticated functional dependency evidence is available."""


_MAPS = r'''
subroutine maps(label, rank)
  implicit none
  character(*), intent(in) :: label
  integer, intent(in) :: rank
  character(4096) :: line
  character(64) :: address
  character(4) :: permissions
  integer :: unit, ios, pos
  open(newunit=unit, file='/proc/self/maps', status='old', action='read', iostat=ios)
  if (ios /= 0) stop 81
  do
    read(unit, '(A)', iostat=ios) line
    if (ios /= 0) exit
    read(line, *, iostat=ios) address, permissions
    if (ios /= 0) stop 82
    if (index(permissions, 'x') == 0) cycle
    pos = index(line, '/')
    if (pos > 0) write(*,'(A,A,A,I0,A,A)') 'GEOF_MAP|',label,'|',rank,'|',trim(line(pos:))
  end do
  close(unit)
end subroutine
'''

MPI_SOURCE = r'''
program actual_mpi
  use mpi
  implicit none
  integer :: ierr, rank, count, seed, peer, token, i
  integer :: sent(3), received(3), totals(3), gathered(3,2), status(MPI_STATUS_SIZE)
  character(32) :: arg
  call get_command_argument(1, arg)
  read(arg, *) seed
  call MPI_INIT(ierr)
  if (ierr /= MPI_SUCCESS) stop 10
  call MPI_COMM_RANK(MPI_COMM_WORLD, rank, ierr)
  call MPI_COMM_SIZE(MPI_COMM_WORLD, count, ierr)
  if (ierr /= MPI_SUCCESS .or. count /= 2) call MPI_ABORT(MPI_COMM_WORLD, 11, ierr)
  sent = (/ seed + rank*101, seed*3 + rank*7, -seed + rank*29 /)
  received = -987654321
  totals = -987654321
  peer = 1 - rank
  call MPI_SENDRECV(sent,3,MPI_INTEGER,peer,91,received,3,MPI_INTEGER,peer,91,MPI_COMM_WORLD,status,ierr)
  if (ierr /= MPI_SUCCESS) call MPI_ABORT(MPI_COMM_WORLD, 12, ierr)
  if (any(received /= (/ seed+peer*101, seed*3+peer*7, -seed+peer*29 /))) &
    call MPI_ABORT(MPI_COMM_WORLD, 13, ierr)
  call MPI_ALLREDUCE(sent,totals,3,MPI_INTEGER,MPI_SUM,MPI_COMM_WORLD,ierr)
  if (ierr /= MPI_SUCCESS .or. any(totals /= (/ 2*seed+101, 6*seed+7, -2*seed+29 /))) &
    call MPI_ABORT(MPI_COMM_WORLD, 14, ierr)
  token = 0
  if (rank == 0) token = seed*11+43
  call MPI_BCAST(token,1,MPI_INTEGER,0,MPI_COMM_WORLD,ierr)
  if (ierr /= MPI_SUCCESS .or. token /= seed*11+43) call MPI_ABORT(MPI_COMM_WORLD, 15, ierr)
  gathered = -987654321
  call MPI_GATHER(sent,3,MPI_INTEGER,gathered,3,MPI_INTEGER,0,MPI_COMM_WORLD,ierr)
  if (ierr /= MPI_SUCCESS) call MPI_ABORT(MPI_COMM_WORLD, 16, ierr)
  if (rank == 0) then
    do i=0,1
      if (any(gathered(:,i+1) /= (/ seed+i*101, seed*3+i*7, -seed+i*29 /))) &
        call MPI_ABORT(MPI_COMM_WORLD, 17, ierr)
    end do
  end if
  write(*,'(A,I0,A,I0,7(A,I0))') 'GEOF_MPI|',rank,'|',count, &
    '|',received(1),'|',received(2),'|',received(3), &
    '|',totals(1),'|',totals(2),'|',totals(3),'|',token
  call maps('MPI', rank)
  call MPI_FINALIZE(ierr)
  if (ierr /= MPI_SUCCESS) stop 18
end program
''' + _MAPS

NETCDF_SOURCE = r'''
program actual_netcdf
  use netcdf
  implicit none
  integer :: seed, ncid, varid, dims(2), values(3,4), back(3,4), i, j, fmt
  character(32) :: arg
  character(4096) :: path
  call get_command_argument(1,arg)
  read(arg,*) seed
  call get_command_argument(2,path)
  do j=1,4
    do i=1,3
      values(i,j)=seed+100*i+7*j
    end do
  end do
  call ok(nf90_create(trim(path),ior(NF90_CLOBBER,NF90_NETCDF4),ncid))
  call ok(nf90_def_dim(ncid,'station',3,dims(1)))
  call ok(nf90_def_dim(ncid,'time',4,dims(2)))
  call ok(nf90_def_var(ncid,'signal',NF90_INT,dims,varid))
  call ok(nf90_def_var_deflate(ncid,varid,1,1,1))
  call ok(nf90_put_att(ncid,NF90_GLOBAL,'challenge',seed))
  call ok(nf90_enddef(ncid))
  call ok(nf90_put_var(ncid,varid,values))
  call ok(nf90_close(ncid))
  back=-987654321
  call ok(nf90_open(trim(path),NF90_NOWRITE,ncid))
  call ok(nf90_inquire(ncid,formatNum=fmt))
  if (fmt /= NF90_FORMAT_NETCDF4) stop 31
  call ok(nf90_inq_varid(ncid,'signal',varid))
  call ok(nf90_get_var(ncid,varid,back))
  if (any(back /= values)) stop 32
  call ok(nf90_close(ncid))
  write(*,'(A,I0,A,I0,A,I0)') 'GEOF_NETCDF|',seed,'|',fmt,'|',sum(back)
  call maps('NETCDF',0)
contains
  subroutine ok(code)
    integer, intent(in) :: code
    if (code /= nf90_noerr) then
      write(*,'(A)') trim(nf90_strerror(code))
      stop 33
    end if
  end subroutine
end program
''' + _MAPS

READER_SOURCE = r'''
import json, pathlib, sys
sys.path.append('/usr/lib/python3/dist-packages')
import netCDF4
path, seed = sys.argv[1], int(sys.argv[2])
with netCDF4.Dataset(path) as data:
    assert data.data_model == 'NETCDF4'
    assert set(data.dimensions) == {'station', 'time'}
    assert len(data.dimensions['station']) == 3 and len(data.dimensions['time']) == 4
    assert set(data.variables) == {'signal'} and int(data.challenge) == seed
    var = data.variables['signal']
    assert var.dimensions == ('time', 'station') and str(var.dtype) == 'int32'
    expected = [[seed + 100*i + 7*j for i in range(1,4)] for j in range(1,5)]
    assert var[:].tolist() == expected
    filters = var.filters()
    assert filters['zlib'] is True and filters['shuffle'] is True and filters['complevel'] == 1
    print('GEOF_READER|' + json.dumps({'seed': seed, 'model': data.data_model,
          'values': expected, 'filters': filters}, sort_keys=True))
for line in pathlib.Path('/proc/self/maps').read_text().splitlines():
    parts = line.split(None, 5)
    if len(parts) == 6 and 'x' in parts[1] and parts[5].startswith('/'):
        print('GEOF_MAP|READER|0|' + parts[5])
'''

# This driver is trusted host code, staged through runtime_backend rather than
# supplied by an agent. All executable paths and the profile are fixed here.
DRIVER_SOURCE = r'''
import hashlib, json, os, pathlib, re, shlex, subprocess, sys
sys.path.append('/usr/lib/python3/dist-packages')
ROOT = pathlib.Path(__file__).resolve().parent
LIMIT = 4 * 1024 * 1024
ENV = {'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8', 'LC_ALL':'C.UTF-8',
       'HOME':str(ROOT), 'TMPDIR':str(ROOT)}
records = {}
package_records = {}
package_cache = None

def sha(path):
    h = hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def run(argv, label=None, timeout=90):
    p = subprocess.run(argv,cwd=ROOT,env=ENV,capture_output=True,timeout=timeout)
    if len(p.stdout)+len(p.stderr)>LIMIT: raise ValueError('Probe output exceeds limit')
    if label:
        (ROOT/(label+'.stdout')).write_bytes(p.stdout)
        (ROOT/(label+'.stderr')).write_bytes(p.stderr)
    if p.returncode: raise ValueError(str(argv[0])+' failed '+str(p.returncode)+': '+p.stderr[-1200:].decode('utf8','replace'))
    return p.stdout.decode('utf8','strict')

def package_origin_error(name, entry):
    # Diagnostics only: candidate trust never authenticates the installed version.
    def field(value, pattern, limit=96):
        return value if isinstance(value, str) and len(value) <= limit and re.fullmatch(pattern, value) else '<unknown>'
    package_name = field(name, r'[a-z0-9][a-z0-9+.:~-]*', 128)
    version_pattern = r'[0-9][A-Za-z0-9.+:~\-]*'
    installed = field(getattr(entry.installed, 'version', None), version_pattern)
    candidate = getattr(entry, 'candidate', None)
    candidate_version = field(getattr(candidate, 'version', None), version_pattern)
    trusted = []
    for origin in (getattr(candidate, 'origins', None) or ())[:32]:
        if getattr(origin, 'trusted', False) and getattr(origin, 'origin', None) == 'Ubuntu':
            archive = field(getattr(origin, 'archive', None), r'[A-Za-z0-9][A-Za-z0-9.+\-]*')
            site = field(getattr(origin, 'site', None), r'[A-Za-z0-9][A-Za-z0-9.\-]*', 128)
            if archive != '<unknown>' and site != '<unknown>':
                description = archive+' at '+site
                if description not in trusted: trusted.append(description)
                if len(trusted) == 3: break
    message = ('No trusted Ubuntu origin for installed package '+package_name+' version '+installed+
               ' in current repository metadata. Repository candidate version: '+candidate_version+'. ')
    if trusted:
        message += ('Candidate trusted Ubuntu origin: '+', '.join(trusted)+'. '
                    'Install/update the package to a trusted repository candidate through normal package '
                    'management, then re-run verification. ')
    else:
        message += ('No trusted Ubuntu candidate origin is currently identified. Check or refresh repository '
                    'metadata through normal package management; install/update from a trusted Ubuntu '
                    'repository candidate when available, then re-run verification. ')
    return message+('Other installed dependencies may require the same repository refresh/update; '
                    'updating this package alone does not establish readiness. '
                    'Candidate metadata does not authenticate the installed version; '
                    'verification remains blocked and no package was changed by this check.')

def package(name):
    global package_cache
    if name in package_records: return package_records[name]
    if package_cache is None:
        import apt
        package_cache = apt.Cache()
    if name not in package_cache or not package_cache[name].is_installed:
        raise ValueError('Required official system package missing: '+name)
    installed = package_cache[name].installed
    origins = sorted({(x.origin,x.archive,x.site) for x in installed.origins
                      if x.trusted and x.origin == 'Ubuntu' and x.archive and x.site})
    if not origins: raise ValueError(package_origin_error(name, package_cache[name]))
    status = run(['/usr/bin/dpkg-query','-W','-f=${db:Status-Abbrev}\t${Version}\t${Architecture}',name]).strip()
    if not status.startswith('ii '): raise ValueError('Package is not fully installed: '+name)
    verified = run(['/usr/bin/dpkg','--verify',name])
    if verified.strip(): raise ValueError('Installed package verification differs: '+name+' '+verified[:500])
    row = {'status':status,'origins':[list(x) for x in origins]}
    package_records[name] = row
    return row

def official(raw):
    path = pathlib.Path(raw).resolve(strict=True)
    name = str(path)
    if name in records: return records[name]
    if not path.is_file() or not any(name.startswith(p) for p in ('/usr/bin/','/usr/lib/','/usr/lib64/','/usr/libexec/','/bin/','/lib/','/lib64/')):
        raise ValueError('Dependency is not an ordinary system package file: '+name)
    spellings = [name]
    if name.startswith('/usr/'): spellings.append(name[4:])
    owners = []
    for spelling in spellings:
        p = subprocess.run(['/usr/bin/dpkg-query','-S',spelling],env=ENV,capture_output=True,timeout=30)
        if p.returncode == 0:
            for line in p.stdout.decode('utf8','strict').splitlines():
                if ': ' in line:
                    owner, owned = line.rsplit(': ',1)
                    if pathlib.Path(owned).resolve() == path: owners.extend(owner.split(', '))
        if owners: break
    owners = sorted(set(owners))
    if len(owners) != 1: raise ValueError('No unique package owner for '+name)
    package(owners[0])
    records[name]={'path':name,'sha256':sha(path),'bytes':path.stat().st_size,'package':owners[0]}
    return records[name]

def linkage(binary):
    output = run(['/usr/bin/ldd',str(binary)])
    if 'not found' in output: raise ValueError('Unresolved native library')
    result = []
    for line in output.splitlines():
        hit = re.search(r'(?:=>\s+)?(/[^\s]+)\s+\(',line)
        if hit: result.append(official(hit.group(1))['path'])
    if not result: raise ValueError('No dynamic native dependency evidence')
    return sorted(set(result))

def artifact(path):
    path = pathlib.Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError('Probe artifact missing, linked or too large: '+str(path))
    return {'sha256':sha(path),'bytes':path.stat().st_size}

def maps(output, label, binary=None):
    prefix='GEOF_MAP|'+label+'|'
    found=set()
    for line in output.splitlines():
        if line.startswith(prefix):
            raw=line.split('|',3)[3]
            if raw.endswith(' (deleted)'): raise ValueError('Loaded dependency deleted')
            path=pathlib.Path(raw).resolve(strict=True)
            if binary is not None and path == binary.resolve(): continue
            found.add(official(path)['path'])
    if not found: raise ValueError('Actual loaded-library evidence missing for '+label)
    return sorted(found)

def system_tools():
    for name in ('python3','mpifort','mpiexec','gfortran','nf-config','ncdump','ldd'):
        official('/usr/bin/'+name)
    for name in ('f951','collect2','as','ld'):
        path=run(['/usr/bin/gfortran','-print-prog-name='+name]).strip()
        if not path.startswith('/'): path='/usr/bin/'+path
        official(path)

def current(request):
    expected=request['expected']
    for name in expected['packages']: package(name)
    for path in expected['system_files']: official(path)
    if records != expected['system_files'] or package_records != expected['packages']:
        raise ValueError('System dependency identity changed')
    work=pathlib.Path(expected['workspace'])
    if work.resolve() != work or not work.is_dir(): raise ValueError('Probe workspace changed')
    actual={name:artifact(work/name) for name in expected['artifacts']}
    if actual != expected['artifacts']: raise ValueError('Probe artifact bytes changed')
    linked={name:linkage(work/name) for name in expected['linkage']}
    if linked != expected['linkage'] or records != expected['system_files']:
        raise ValueError('Native dependency resolution changed')
    return {'current':True,'system_files':records,'packages':package_records,
            'artifacts':actual,'linkage':linked}

def elf_file(path):
    path=pathlib.Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256*1024*1024:
        raise ValueError('Native executable is missing, linked or too large')
    with path.open('rb') as stream: header=stream.read(20)
    if len(header)!=20 or header[:4]!=b'\x7fELF' or header[4] not in (1,2) or header[5] not in (1,2):
        raise ValueError('A real dynamically linked ELF executable is required')
    return header

def absent_official_path(raw):
    # Some distribution libraries retain an unused absolute build RUNPATH.
    # It is admissible only while the path is absent below root-owned,
    # non-writable ancestors; it is rechecked, not treated as a library root.
    path=pathlib.Path(raw)
    if not path.is_absolute() or '$' in raw or str(path)!=raw or '..' in path.parts:
        raise ValueError('Unsupported absent official loader path')
    if path.exists() or path.is_symlink(): raise ValueError('Non-system loader directory exists')
    ancestor=path.parent
    while not ancestor.exists():
        if ancestor.is_symlink(): raise ValueError('Absent loader path contains a link')
        ancestor=ancestor.parent
    for node in (ancestor,*ancestor.parents):
        info=node.lstat()
        if node.is_symlink() or not node.is_dir() or info.st_uid!=0 or info.st_mode&0o022 or os.access(node,os.W_OK):
            raise ValueError('Absent loader directory could be created by this runtime user')
    info=ancestor.stat()
    return {'absent':raw,'ancestor':str(ancestor),'device':info.st_dev,'inode':info.st_ino,
            'mode':info.st_mode,'uid':info.st_uid,'gid':info.st_gid}

def rpaths(path, official_library=False):
    output=run(['/usr/bin/readelf','--wide','--dynamic',str(path)])
    values=[]
    for line in output.splitlines():
        if any(tag in line for tag in ('(AUDIT)','(DEPAUDIT)','(FILTER)','(AUXILIARY)')):
            raise ValueError('ELF requests an unsupported loader audit/filter module')
        if '(RPATH)' not in line and '(RUNPATH)' not in line: continue
        hit=re.search(r'\[(.*)\]',line)
        if not hit: raise ValueError('Unrecognized ELF loader search path')
        for part in hit.group(1).split(':'):
            if not part: raise ValueError('ELF loader search path includes current directory')
            expanded=part.replace('${ORIGIN}',str(path.parent)).replace('$ORIGIN',str(path.parent))
            if '$' in expanded or not expanded.startswith('/'):
                raise ValueError('Unsupported dynamic loader path: '+part)
            if official_library and '$' not in part and not pathlib.Path(expanded).exists():
                values.append(absent_official_path(expanded))
                continue
            resolved=str(pathlib.Path(expanded).resolve(strict=True))
            if not any(resolved==p or resolved.startswith(p+'/') for p in ('/usr/lib','/usr/lib64','/lib','/lib64')):
                raise ValueError('ELF selects non-system libraries: '+part)
            values.append(resolved)
    return sorted(values,key=lambda value:value if isinstance(value,str) else value['absent'])

def import_contract(dyn):
    undefined={hit.group(1).split('@',1)[0].lower() for line in dyn.splitlines()
               for hit in [re.search(r'\bUND\s+(\S+)',line)] if hit}
    mpi_calls={name for name in undefined if name.startswith(('mpi_','pmpi_'))}
    nc_calls={name for name in undefined if name.startswith(('nf_','nf90_','nc_','__netcdf_MOD_'.lower()))}
    if not any('init' in n for n in mpi_calls) or not any(any(x in n for x in ('send','recv','reduce','bcast')) for n in mpi_calls):
        raise ValueError('Native executable has no real MPI initialization/communication imports')
    if not any('open' in n for n in nc_calls) or not any(any(x in n for x in ('get_var','put_var','create')) for n in nc_calls):
        raise ValueError('Native executable has no real NetCDF data-operation imports')
    return sorted(mpi_calls), sorted(nc_calls)

def binary(request):
    expected=request['expected']
    current({'expected':expected})
    path=pathlib.Path(request['executable'])
    allowed=pathlib.Path(request['runtime_workspace'])
    if not path.is_absolute() or path.resolve()!=path or not path.is_relative_to(allowed):
        raise ValueError('Native executable must be ordinary and inside the bound runtime')
    for parent in path.parents:
        if parent==allowed: break
        if parent.is_symlink(): raise ValueError('Native executable parent is linked')
    header=elf_file(path)
    initial_digest=sha(path)
    reference=elf_file(pathlib.Path(expected['workspace'])/'mpi-probe')
    if header[4:7]!=reference[4:7] or header[18:20]!=reference[18:20]:
        raise ValueError('Native executable architecture differs from the verified compiler')
    official('/usr/bin/readelf')
    program=run(['/usr/bin/readelf','--wide','--program-headers',str(path)])
    matches=re.findall(r'Requesting program interpreter:\s*([^\]]+)\]',program)
    if len(matches)!=1: raise ValueError('Static or non-executable ELF cannot prove dependency routing')
    loader=official(matches[0])['path']
    if loader not in expected['system_files'] or not re.search(r'/ld(?:-linux[^/]*|-[0-9.]+)\.so(?:\.[0-9]+)*$',loader):
        raise ValueError('ELF interpreter is not the previously verified system loader')
    routes={str(path):rpaths(path)}
    # The authenticated system loader lists dependencies without entering main
    # or running the target's constructors. Never use ldd on an unknown file.
    output=run([loader,'--list',str(path)])
    if 'not found' in output: raise ValueError('Native executable has unresolved libraries')
    libraries={}
    for line in output.splitlines():
        hit=re.search(r'(?:=>\s+)?(/[^\s]+)\s+\(',line)
        if hit:
            row=official(hit.group(1))
            libraries[row['path']]=row
    if not libraries: raise ValueError('No dynamic dependency resolution')
    required={'libmpi.so':'mpi','libnetcdff.so':'netcdf','libnetcdf.so':'netcdf','libhdf5':'netcdf'}
    for prefix,label in required.items():
        found=[p for p in libraries if '/'+prefix in p]
        if not found: raise ValueError('Native executable lacks required dependency '+prefix)
        for name in found:
            if name not in expected['loaded_libraries'][label] or libraries[name]!=expected['system_files'][name]:
                raise ValueError('Native executable resolved a different dependency: '+name)
    routes.update({name:rpaths(pathlib.Path(name),official_library=True) for name in libraries})
    dyn=run(['/usr/bin/readelf','--wide','--dyn-syms',str(path)])
    mpi_calls,nc_calls=import_contract(dyn)
    digest=sha(path)
    result={'executable':str(path),'sha256':digest,'bytes':path.stat().st_size,
            'elf_header':header.hex(),'loader':loader,'libraries':libraries,'rpaths':routes,
            'mpi_imports':sorted(mpi_calls),'netcdf_imports':sorted(nc_calls),
            'inspection_tools':{p:row for p,row in records.items() if p not in expected['system_files']}}
    if digest!=initial_digest or sha(path)!=digest: raise ValueError('Native executable changed during inspection')
    return result

def verify(request):
    seed=request['seed']
    if type(seed) is not int or not 10000 <= seed <= 999999: raise ValueError('Invalid challenge')
    for name in request['required_packages']: package(name)
    system_tools()
    # The wrapper flags are recorded; compilation uses the official wrapper.
    mpi_flags=run(['/usr/bin/mpifort','--showme'])
    nf_flags=run(['/usr/bin/nf-config','--fflags'])
    nf_libs=run(['/usr/bin/nf-config','--flibs'])
    for value in (nf_flags,nf_libs,mpi_flags):
        if str(ROOT) in value or '/usr/local/' in value:
            raise ValueError('Native wrapper selects non-system dependencies')
    run(['/usr/bin/mpifort','-O0','-fcheck=all','mpi.f90','-o','mpi-probe'],'compile-mpi',180)
    run(['/usr/bin/gfortran','-O0','-fcheck=all',*shlex.split(nf_flags),
         'netcdf.f90','-o','netcdf-probe',*shlex.split(nf_libs)],'compile-netcdf',180)
    linked={name:linkage(ROOT/name) for name in ('mpi-probe','netcdf-probe')}
    mpi=run(['/usr/bin/mpiexec','--oversubscribe','-n','2',str(ROOT/'mpi-probe'),str(seed)],'mpi',60)
    netcdf=run([str(ROOT/'netcdf-probe'),str(seed),str(ROOT/'probe.nc')],'netcdf',60)
    reader=run(['/usr/bin/python3','-I','-S',str(ROOT/'reader.py'),str(ROOT/'probe.nc'),str(seed)],'reader',60)
    kind=run(['/usr/bin/ncdump','-k',str(ROOT/'probe.nc')],'ncdump',30)
    if kind.strip() != 'netCDF-4': raise ValueError('Independent format probe is not NetCDF-4')
    if (ROOT/'probe.nc').read_bytes()[:8] != b'\x89HDF\r\n\x1a\n': raise ValueError('No HDF5 file signature')
    loaded={'mpi':maps(mpi,'MPI',ROOT/'mpi-probe'),
            'netcdf':maps(netcdf,'NETCDF',ROOT/'netcdf-probe'),
            'reader':maps(reader,'READER')}
    if not any('/libmpi.so' in p for p in loaded['mpi']): raise ValueError('Official MPI library was not loaded')
    for lib in ('libnetcdff.so','libnetcdf.so','libhdf5'):
        if not any('/'+lib in p for p in loaded['netcdf']): raise ValueError('Required native library not loaded: '+lib)
    # Recheck package bytes after the actual build and execution.
    packages_before=dict(package_records)
    package_records.clear()
    for name in packages_before: package(name)
    if packages_before != package_records: raise ValueError('Package provenance changed during probes')
    for row in records.values():
        if sha(row['path']) != row['sha256']: raise ValueError('System file changed during probes')
    names=['driver.py','request.json','mpi.f90','netcdf.f90','reader.py','mpi-probe','netcdf-probe','probe.nc']
    names += [name+suffix for name in ('compile-mpi','compile-netcdf','mpi','netcdf','reader','ncdump')
              for suffix in ('.stdout','.stderr')]
    return {'workspace':str(ROOT),'seed':seed,'system_files':records,'packages':package_records,
            'loaded_libraries':loaded,'linkage':linked,'artifacts':{name:artifact(ROOT/name) for name in names},
            'wrapper_flags':{'mpi':mpi_flags,'netcdf_compile':nf_flags,'netcdf_link':nf_libs}}

try:
    request=json.loads((ROOT/'request.json').read_text())
    mode=request.get('mode')
    result=current(request) if mode=='current' else binary(request) if mode=='binary' else verify(request)
    (ROOT/'result.json').write_text(json.dumps(result,sort_keys=True))
    print('GEOF_CAPABILITIES_OK')
except Exception as error:
    (ROOT/'failure.json').write_text(json.dumps({'error':str(error)}))
    print('GEOF_CAPABILITIES_FAILED: '+str(error),file=sys.stderr)
    raise SystemExit(2)
'''


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _implementation():
    return implementation_identity.module_digest(sys.modules[__name__])


def _backend(value):
    if value is not None:
        return value
    from . import runtime_backend
    return runtime_backend


def _identity(backend, binding):
    value = backend.inspect(binding)
    identity = value.get("identity_sha256") if isinstance(value, dict) else None
    if not isinstance(identity, str) or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise CapabilityError("Backend inspection did not return an identity")
    return identity


def profiles_for_manifest(manifest) -> tuple[str, ...]:
    """Derive the profile from declared native requirements, never an agent flag."""
    def get(obj, key, default=None):
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
    names = set(get(manifest, "system_deps", []) or [])
    names.update(get(get(manifest, "acquire"), "system_deps", []) or [])
    mpi = {"mpicc", "mpicxx", "mpif90", "mpifort", "mpirun", "mpiexec"}
    return (PROFILE,) if names.intersection(mpi) and "nf-config" in names else ()


def _binding(binding):
    if not is_dataclass(binding):
        raise CapabilityError("Dependency verification requires a host runtime binding")
    value = asdict(binding)
    if value.get("python") != "/usr/bin/python3":
        raise CapabilityError("This official-package profile requires /usr/bin/python3")
    return value


def _read(backend, binding, paths):
    rows = backend.read_files(binding, paths)
    result = {}
    for path in paths:
        row = rows.get(path)
        data = row.get("data") if isinstance(row, dict) else None
        if (not isinstance(data, bytes) or len(data) > MAX_ARTIFACT or
                row.get("sha256") != _hash(data) or row.get("bytes") != len(data)):
            raise CapabilityError("Backend did not return exact bounded artifact bytes: " + path)
        result[path] = data
    return result


def _validate_outputs(seed, outputs):
    """Independent host checks: an exit code or a printed pass flag is insufficient."""
    rows = [line.split("|")[1:] for line in outputs["mpi.stdout"].decode().splitlines()
            if line.startswith("GEOF_MPI|")]
    expected = []
    for rank in (0, 1):
        peer = 1 - rank
        expected.append([str(x) for x in (rank, 2, seed+peer*101, seed*3+peer*7,
            -seed+peer*29, 2*seed+101, 6*seed+7, -2*seed+29, seed*11+43)])
    if sorted(rows) != expected:
        raise CapabilityError("MPI ranks did not demonstrate exact communication and collective results")
    rows = [line for line in outputs["netcdf.stdout"].decode().splitlines()
            if line.startswith("GEOF_NETCDF|")]
    if rows != [f"GEOF_NETCDF|{seed}|3|{12*seed+2610}"]:
        raise CapabilityError("Fortran NetCDF-4 write/reopen did not verify challenge values")
    rows = [line[len("GEOF_READER|"):] for line in outputs["reader.stdout"].decode().splitlines()
            if line.startswith("GEOF_READER|")]
    if len(rows) != 1:
        raise CapabilityError("Independent NetCDF reader result missing")
    reader = json.loads(rows[0])
    expected_values = [[seed+100*i+7*j for i in range(1, 4)] for j in range(1, 5)]
    if (reader.get("seed") != seed or reader.get("model") != "NETCDF4" or
            reader.get("values") != expected_values or
            reader.get("filters", {}).get("zlib") is not True or
            reader.get("filters", {}).get("shuffle") is not True or
            reader.get("filters", {}).get("complevel") != 1):
        raise CapabilityError("Independent NetCDF-4 data/compression crosscheck failed")
    if outputs["ncdump.stdout"].strip() != b"netCDF-4" or not outputs["probe.nc"].startswith(b"\x89HDF\r\n\x1a\n"):
        raise CapabilityError("Output is not an independently identified HDF5/NetCDF-4 file")


def _execute(binding, backend, relative, request, *, stop=None):
    files = {relative + "/driver.py": DRIVER_SOURCE.encode(),
             relative + "/request.json": _json(request)}
    if request["mode"] == "verify":
        files.update({relative + "/mpi.f90": MPI_SOURCE.encode(),
                      relative + "/netcdf.f90": NETCDF_SOURCE.encode(),
                      relative + "/reader.py": READER_SOURCE.encode()})
    backend.write_files(binding, files)
    staged = _read(backend, binding, list(files))
    if staged != files:
        raise CapabilityError("Host-authored probe source changed before execution")
    cwd = str(PurePosixPath(binding.workspace) / relative)
    result = backend.run(binding, ["/usr/bin/python3", "-I", "-S", cwd + "/driver.py"],
                         cwd=cwd, timeout=600, stop=stop)
    if result.returncode != 0 or result.status != "finished":
        raise CapabilityError("Dependency capability probe failed: " +
                              str(result.detail or result.stderr or result.stdout)[-2500:])
    path = relative + "/result.json"
    raw = _read(backend, binding, [path])[path]
    try:
        return json.loads(raw), files
    except (ValueError, TypeError) as error:
        raise CapabilityError("Invalid dependency probe report") from error


def verify(binding, *, authority: Path, backend=None, profile=PROFILE, stop=None):
    """Run the fixed functional profile; sign evidence without granting readiness."""
    if profile != PROFILE:
        raise CapabilityError("Unsupported dependency capability profile")
    backend = _backend(backend)
    bound = _binding(binding)
    initial = _identity(backend, binding)
    seed = 10000 + secrets.randbelow(990000)
    relative = ".geoforge/capability-probes/" + uuid.uuid4().hex
    evidence, files = _execute(binding, backend, relative, {
        "mode": "verify", "seed": seed, "required_packages": list(PACKAGES)}, stop=stop)
    artifacts = evidence.get("artifacts")
    if (not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACTS)
            or evidence.get("seed") != seed
            or evidence.get("workspace") != str(PurePosixPath(binding.workspace) / relative)):
        raise CapabilityError("Probe evidence is incomplete or belongs to another challenge")
    paths = [relative + "/" + name for name in artifacts]
    outputs = _read(backend, binding, paths)
    for name, row in artifacts.items():
        raw = outputs[relative + "/" + name]
        if row != {"sha256": _hash(raw), "bytes": len(raw)}:
            raise CapabilityError("Probe artifact changed after verification: " + name)
    for name, raw in files.items():
        if outputs.get(name) != raw:
            raise CapabilityError("Executed probe source differs from host source")
    _validate_outputs(seed, {name: outputs[relative + "/" + name] for name in artifacts})
    _validate_provenance(evidence)
    if _identity(backend, binding) != initial:
        raise CapabilityError("Bound Linux runtime changed during verification")
    report = {"policy": POLICY, "profile": PROFILE, "implementation": _implementation(),
              "binding": bound, "backend_identity": initial, "relative": relative,
              "evidence": evidence, "model_readiness": False}
    from . import flowgate
    return flowgate.load().receipts.sign(Path(authority), report)


def require_current(report, binding, *, authority: Path, backend=None, stop=None):
    """Authenticate and rehash evidence; never silently rerun or repair a probe."""
    from . import flowgate
    if (not isinstance(report, dict) or not flowgate.load().receipts.verify(Path(authority), report)
            or report.get("policy") != POLICY or report.get("profile") != PROFILE
            or report.get("implementation") != _implementation()
            or report.get("binding") != _binding(binding) or report.get("model_readiness") is not False):
        raise CapabilityError("Dependency capability evidence is unauthenticated or stale")
    backend = _backend(backend)
    identity = _identity(backend, binding)
    if identity != report.get("backend_identity"):
        raise CapabilityError("Dependency evidence belongs to a different Linux runtime")
    evidence = report["evidence"]
    current, _ = _execute(binding, backend, ".geoforge/capability-current/" + uuid.uuid4().hex,
                          {"mode": "current", "expected": evidence}, stop=stop)
    if (current.get("current") is not True
            or any(current.get(key) != evidence[key] for key in
                   ("system_files", "packages", "artifacts", "linkage"))
            or _identity(backend, binding) != identity):
        raise CapabilityError("Dependency capability artifacts are no longer current")
    return report


def _validate_provenance(evidence):
    packages, files = evidence.get("packages"), evidence.get("system_files")
    if not isinstance(packages, dict) or not set(PACKAGES).issubset(packages) or not isinstance(files, dict) or not files:
        raise CapabilityError("Official system dependency provenance is missing")
    for row in packages.values():
        if (not isinstance(row, dict) or not str(row.get("status", "")).startswith("ii ")
                or not isinstance(row.get("origins"), list) or not row["origins"]
                or any(not isinstance(x, list) or len(x) != 3 or x[0] != "Ubuntu"
                       or not x[1] or not x[2] for x in row["origins"])):
            raise CapabilityError("Dependency is not bound to a verified Ubuntu package")
    for name, row in files.items():
        if (not isinstance(row, dict) or row.get("path") != name
                or not name.startswith(("/usr/bin/", "/usr/lib/", "/usr/lib64/", "/usr/libexec/", "/bin/", "/lib/", "/lib64/"))
                or row.get("package") not in packages or type(row.get("bytes")) is not int or row["bytes"] <= 0
                or not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64):
            raise CapabilityError("Loaded dependency file lacks exact system-package provenance")
    loaded = evidence.get("loaded_libraries")
    if (not isinstance(loaded, dict) or set(loaded) != {"mpi", "netcdf", "reader"}
            or any(not isinstance(value, list) or not value or any(path not in files for path in value)
                   for value in loaded.values())):
        raise CapabilityError("Actual loaded library provenance is incomplete")
    for label, names in (("mpi", ("libmpi.so",)), ("netcdf", ("libnetcdff.so", "libnetcdf.so", "libhdf5"))):
        if any(not any("/" + name in path for path in loaded[label]) for name in names):
            raise CapabilityError("Required dependency was not observed in the running probe")


def validate_loader_environment(report, env) -> None:
    """Check declared launch variables after authenticating the capability report.

    An arbitrary child program can construct its own environment; this function
    does not make Python or model code a sandbox. The launch boundary must use
    the validated environment and retained, trusted KI instructions.
    """
    if not isinstance(env, dict):
        raise CapabilityError("Native launch requires an explicit environment mapping")
    files = report.get("evidence", {}).get("system_files", {})
    allowed = {str(PurePosixPath(path).parent) for path in files}
    for name, value in env.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise CapabilityError("Native environment keys and values must be strings")
        if not value:
            continue
        if name == "LD_LIBRARY_PATH":
            if any(not path or path not in allowed or str(PurePosixPath(path)) != path
                   for path in value.split(":")):
                raise CapabilityError("LD_LIBRARY_PATH selects unverified library directories")
        elif name.startswith("LD_") or name in {"GLIBC_TUNABLES", "GCONV_PATH"}:
            raise CapabilityError("Unverified loader override: " + name)


def verify_binary(report, binding, executable, *, authority: Path, backend=None, stop=None):
    """Inspect actual ELF dependency routing without executing the model."""
    backend = _backend(backend)
    require_current(report, binding, authority=authority, backend=backend, stop=stop)
    if (not isinstance(executable, str) or not PurePosixPath(executable).is_absolute()
            or any(part in {"", ".", ".."} for part in executable.split("/")[1:])
            or "\\" in executable or "\0" in executable):
        raise CapabilityError("An exact absolute Linux executable is required")
    request = {"mode": "binary", "expected": report["evidence"],
               "executable": executable, "runtime_workspace": binding.workspace}
    evidence, _ = _execute(binding, backend, ".geoforge/capability-binary/" + uuid.uuid4().hex,
                           request, stop=stop)
    if (evidence.get("executable") != executable or not evidence.get("libraries")
            or not evidence.get("mpi_imports") or not evidence.get("netcdf_imports")
            or not isinstance(evidence.get("sha256"), str) or len(evidence["sha256"]) != 64
            or type(evidence.get("bytes")) is not int or evidence["bytes"] <= 0
            or _identity(backend, binding) != report["backend_identity"]):
        raise CapabilityError("Native binary dependency proof is incomplete or stale")
    doc = {"policy": BINARY_POLICY, "implementation": _implementation(),
           "capability_sha256": _hash(_json(report)), "binding": _binding(binding),
           "backend_identity": report["backend_identity"], "executable": executable,
           "evidence": evidence, "model_readiness": False}
    from . import flowgate
    return flowgate.load().receipts.sign(Path(authority), doc)


def require_binary_current(binary_report, report, binding, executable, *, authority: Path,
                           backend=None, stop=None):
    from . import flowgate
    if (not isinstance(binary_report, dict)
            or not flowgate.load().receipts.verify(Path(authority), binary_report)
            or binary_report.get("policy") != BINARY_POLICY
            or binary_report.get("implementation") != _implementation()
            or binary_report.get("capability_sha256") != _hash(_json(report))
            or binary_report.get("binding") != _binding(binding)
            or binary_report.get("executable") != executable
            or binary_report.get("model_readiness") is not False):
        raise CapabilityError("Native binary dependency evidence is unauthenticated or stale")
    fresh = verify_binary(report, binding, executable, authority=authority, backend=backend, stop=stop)
    if fresh["evidence"] != binary_report.get("evidence"):
        raise CapabilityError("Native executable, dependency resolution or library bytes changed")
    return binary_report
