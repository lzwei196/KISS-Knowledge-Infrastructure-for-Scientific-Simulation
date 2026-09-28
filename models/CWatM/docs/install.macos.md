# CWatM: native Mac installation guidance

Learned from the real Mac DeepSeek installation on 2026-09-08. The official IIASA source imported successfully after dependency and native-library repairs. The checkout was cloned from main; the static git metadata in cwatm/version.py does not prove its actual commit. Record git rev-parse HEAD before claiming a source pin.

- Use https://github.com/iiasa/CWatM.git. The inferred pip distribution cwatm was unavailable in this run; the source tree had no setup.py or pyproject.toml. Keep its official source in the installation workspace and register that directory in the workspace environment using a normal .pth source-path entry if no packaging metadata exists. Never substitute model modules.
- Match Python GDAL bindings to the real native GDAL SDK. On the tested host libgdal was 3.12.3, so gdal==3.12.3 built successfully; 3.13.3 did not match that SDK. Query the installed SDK for other hosts instead of assuming this version.
- The source carried an x86_64 t5_mac.so. For Apple Silicon compile the original t5.cpp into the same native library path with clang++ -shared -fPIC -O2 -o t5_mac.so t5.cpp. Preserve the scientific C++ source; do not replace the routing library with a stub.
- Verify imports of cwatm.management_modules.globals and cwatm.run_cwatm, not just the shallow cwatm namespace. These exercise the native routing library and GDAL bindings. Also verify every declared KI dependency in the same environment.
- Preserve the workspace venv/bin/python launcher in kiss.toml. An environment-path registration is not a substitute for installing real runtime dependencies.

Do not run hydrological simulations or fetch project inputs during the installation-only test. A successful base-model installation does not establish optional MODFLOW coupling readiness.
