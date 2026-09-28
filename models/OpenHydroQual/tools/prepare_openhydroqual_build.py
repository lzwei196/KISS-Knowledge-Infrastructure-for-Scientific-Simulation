#!/usr/bin/env python3
"""Hash-guarded macOS build/CLI integration for official OpenHydroQual v2.0.7."""
import hashlib
from pathlib import Path
import platform
import subprocess
import sys

PIN = 'e24ea5eebcc0d2894b779adfdfc7ea78bd9a4ce2'
HASHES = {
 'OHQLib/CMakeLists.txt': 'c72a1587f1d05dc7b46db4d14dd78560077176c8becf0060206590bc82e74d3b',
 'OHQLibTest/CMakeLists.txt': 'c0663f9762e2c990bdfa00d171a3b692af9403b24f0a7427a08654f92030ba11',
 'OHQLibTest/main.cpp': '9415dc87cdb561a350cc169645fe20949f4dfc523347a00b6b7cb56269f823c5',
}

def transform(name, s):
    if name == 'OHQLib/CMakeLists.txt':
        s = s.replace('/usr/local/lib/libomp.dylib', '/opt/homebrew/opt/libomp/lib/libomp.dylib')
        s = s.replace('    target_link_libraries(OHQLib PRIVATE ${ARMADILLO_LIBRARIES})', '    target_compile_definitions(OHQLib PUBLIC ARMA_DONT_USE_WRAPPER)')
        return s
    if name == 'OHQLibTest/CMakeLists.txt':
        start = s.index('set_target_properties(OHQLib PROPERTIES')
        end = s.index('target_link_libraries(OHQLib INTERFACE', start)
        s = s[:start] + 'set_target_properties(OHQLib PROPERTIES\n    IMPORTED_LOCATION "${OHQLIB_BUILD_DIR}/libOHQLib.dylib")\n' + s[end:]
        s = s.replace('    windows_version', '    mac_version\n    ARMA_DONT_USE_WRAPPER')
        s = s.replace('find_package(Qt6 REQUIRED COMPONENTS Core)', 'find_package(Qt6 REQUIRED COMPONENTS Core)\nfind_package(OpenMP REQUIRED)')
        s = s.replace('    OHQLib\n    Qt6::Core', '    OHQLib\n    Qt6::Core\n    OpenMP::OpenMP_CXX')
        s = s.replace('"${OHQLIB_DIR}/build"', '"${OHQLIB_DIR}/../build-lib"')
        s = s.replace('"${OHQLIB_DIR}/../include"\n    CACHE PATH "Path to Armadillo headers"', '"/opt/homebrew/include"\n    CACHE PATH "Path to Armadillo headers"')
        return s.replace('"C:/Projects/vcpkg/installed/x64-windows/include"', '"/opt/homebrew/include"')
    s = s.replace('/../../../resources/', '/../resources/')
    needle = '    QCoreApplication a(argc, argv);'
    return s.replace(needle, needle + '''
    if (argc == 2 && QString::fromLocal8Bit(argv[1]) == "--help") {
        cout << "Usage: OHQLibTest <input_file>" << endl;
        return 0;
    }
    if (argc == 2 && QString::fromLocal8Bit(argv[1]) == "--version") {
        cout << "OpenHydroQual OHQLibTest 2.0.7 (macOS build)" << endl;
        return 0;
    }
''')

def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('Audited patch is only for Darwin arm64')
    root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
    if not root.is_relative_to(Path.cwd().resolve()):
        raise SystemExit('Source must be in the current workspace')
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if head != PIN:
        raise SystemExit('Unexpected OpenHydroQual commit')
    pending = []
    for name, expected in HASHES.items():
        original = subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:' + name])
        if hashlib.sha256(original).hexdigest() != expected:
            raise SystemExit('Unexpected original source hash: ' + name)
        new = transform(name, original.decode()).encode()
        target = root / name
        if target.read_bytes() == new:
            continue
        if target.read_bytes() != original:
            raise SystemExit('Refusing to overwrite independently modified source: ' + name)
        pending.append((target, new))
    for target, data in pending:
        target.write_bytes(data)
    print('Applied/verified OpenHydroQual macOS CMake and bounded CLI patch; no simulation invoked.')

if __name__ == '__main__':
    main()
