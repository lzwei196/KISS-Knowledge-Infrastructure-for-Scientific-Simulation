#!/usr/bin/env python3
"""Build the genuine USGS PHREEQC batch engine with a version-only startup path."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import tarfile

URL = 'https://water.usgs.gov/water-resources/software/PHREEQC/phreeqc-3.8.6-17100.tar.gz'
ARCHIVE_SHA256 = 'b5c4a6dfea1a6bb6a3436857a50346bb943904a49582714494b4f1b1e54e64e1'
SOURCE_NAME = 'phreeqc-3.8.6-17100'
SOURCE_HASHES = {
    'CMakeLists.txt': '35da64df0056610ab50f67a82421b46a3c565a41d381a376c2475c6d3b2c9672',
    'src/class_main.cpp': '3910a5c7f6764c09cf3322b409aa243ca2b1d95cafebab1520e649f65288b28a',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', default='binaries/PHREEQC/source')
    parser.add_argument('--archive', help='Optional local official archive; same SHA256 required')
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Darwin', 'arm64'):
        raise SystemExit('This recipe targets native macOS arm64')
    workspace = Path.cwd().resolve()
    prefix = Path(args.prefix).resolve()
    if prefix == workspace or not prefix.is_relative_to(workspace):
        raise SystemExit('Build prefix must remain inside installation workspace')
    prefix.mkdir(parents=True, exist_ok=True)
    archive = Path(args.archive).resolve() if args.archive else prefix / (SOURCE_NAME + '.tar.gz')
    if not args.archive:
        if archive.is_symlink():
            raise SystemExit('Archive destination must not be a symlink')
        subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                        '--max-time', '600', URL, '-o', str(archive)], check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise SystemExit('Official USGS archive SHA256 mismatch')
    source = prefix / SOURCE_NAME
    if source.is_symlink() or not source.resolve().is_relative_to(prefix):
        raise SystemExit('Source directory must remain inside build prefix')
    source.mkdir(exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != SOURCE_NAME or '..' in parts:
                raise SystemExit('Unsafe archive path')
            relative = PurePosixPath(*parts[1:])
            if not relative.parts:
                continue
            # Database files are distributed runtime resources. No examples,
            # regression cases, or documentation PDFs are extracted.
            allowed = (relative.parts[0] in {'src', 'database', 'cmake'}
                       or len(relative.parts) == 1
                       or str(relative) in {'doc/NOTICE', 'doc/README', 'doc/RELEASE'})
            if not allowed or member.isdir():
                continue
            if not member.isfile():
                raise SystemExit('Unexpected nonregular software member')
            target = source.joinpath(*relative.parts)
            if target.is_symlink() or not target.resolve().is_relative_to(source.resolve()):
                raise SystemExit('Unsafe extraction destination')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
            target.chmod(member.mode & 0o777)
    changes = {}
    for relative, expected in SOURCE_HASHES.items():
        path = source / relative
        original = path.read_bytes()
        if hashlib.sha256(original).hexdigest() != expected:
            raise SystemExit('Unexpected source revision: ' + relative)
        backup = source / 'macos-original' / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(original)
        text = original.decode()
        if relative.endswith('class_main.cpp'):
            before = '\tPhreeqc phreeqc_instance;\n\treturn phreeqc_instance.main_method(argc, argv);'
            after = ('\tPhreeqc phreeqc_instance;\n'
                     '\t// Installation probe: original banner, before input processing.\n'
                     '\tif (argc == 2 && std::string(argv[1]) == "--version") {\n'
                     '\t\tphreeqc_instance.Get_phrq_io()->Set_error_ostream(&std::cerr);\n'
                     '\t\tphreeqc_instance.Get_phrq_io()->Set_screen_on(true);\n'
                     '\t\treturn phreeqc_instance.write_banner();\n'
                     '\t}\n'
                     '\treturn phreeqc_instance.main_method(argc, argv);')
            if text.count(before) != 1:
                raise SystemExit('Version dispatch patch context mismatch')
            text = text.replace(before, after)
        else:
            for line in ['add_subdirectory(doc)', 'add_subdirectory(examples)']:
                if text.count(line) != 1:
                    raise SystemExit('Build-only patch context mismatch')
                text = text.replace(line, '# Mac software-only build: ' + line)
        path.write_text(text)
        changes[relative] = {'before_sha256': expected,
                             'after_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    cmake = shutil.which('cmake')
    if not cmake:
        raise SystemExit('A real CMake installation is required')
    build = source / 'build'
    subprocess.run([cmake, '-S', str(source), '-B', str(build),
                    '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_TESTING=OFF',
                    '-DPHRQC_TESTING=OFF', '-DPHRQC_ENABLE_REGRESSION_TESTING=OFF',
                    '-DCMAKE_C_COMPILER=clang', '-DCMAKE_CXX_COMPILER=clang++'], check=True)
    subprocess.run([cmake, '--build', str(build), '--target', 'phreeqc', '--parallel', '1'], check=True)
    (source / 'macos-build-receipt.json').write_text(json.dumps({
        'url': URL, 'archive_sha256': ARCHIVE_SHA256, 'source_changes': changes,
        'product': str(build / 'phreeqc'), 'science_execution': False,
        'version_probe': '--version uses unmodified upstream write_banner and returns before main_method',
    }, indent=2))
    print('Built genuine PHREEQC at ' + str(build / 'phreeqc'))


if __name__ == '__main__':
    main()
