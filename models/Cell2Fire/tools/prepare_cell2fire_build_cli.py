"""Add a data-free CLI exit to audited official Cell2Fire; numerical code is unchanged."""
from pathlib import Path
import hashlib
import sys
root = Path(sys.argv[1]).resolve()
workspace = Path.cwd().resolve()
if root != workspace and workspace not in root.parents:
    raise SystemExit("Source must be inside the working installation directory")
path = root / "Cell2Fire" / "Cell2Fire.cpp"
raw = path.read_bytes()
digest = hashlib.sha256(raw).hexdigest()
EXPECTED = '8efd45ea6fe66328881629d1bf4b45481d298dceb2c5458455c5e5cdc540edb6'
PATCHED = '6a2da20ecec505899c97019d08096778a7155a7cb1a413600fa2bb5e6c274154'
if digest == PATCHED:
    print("Cell2Fire CLI repair already applied")
elif digest != EXPECTED:
    raise SystemExit("Refusing unexpected Cell2Fire source")
else:
    old = '    printf("version: %s\\n", C2FW_VERSION.c_str());\n    // Read Arguments'
    new = '    printf("version: %s\\n", C2FW_VERSION.c_str());\n    // GeoForge CLI-only repair: exit before reading any simulation inputs.\n    if (argc == 2 && std::string(argv[1]) == "--version")\n        return 0;\n    if (argc == 2 && (std::string(argv[1]) == "--help" || std::string(argv[1]) == "-h"))\n    {\n        std::cout << "Cell2Fire (C2F-W)\\n"\n                  << "Usage: Cell2Fire --input-instance-folder PATH --output-folder PATH [options]\\n"\n                  << "Options: --sim MODEL --nsims N --nthreads N --seed N\\n"\n                  << "         --help, -h   Show this help without loading input data\\n"\n                  << "         --version    Show the embedded upstream version\\n";\n        return 0;\n    }\n    // Read Arguments'
    text = raw.decode()
    if text.count(old) != 1:
        raise SystemExit("Unexpected CLI source anchor")
    path.write_text(text.replace(old, new))
    print("Applied CLI-only help/version exits before simulation data loading")
