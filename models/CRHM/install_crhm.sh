#!/bin/bash
# ============================================================================
# CRHM Installation Script
# ============================================================================
# Clones, builds, and validates CRHM (Cold Regions Hydrological Model)
# from the srlabUsask/crhmcode repository.
#
# Prerequisites: cmake, gcc/g++ (C++14), git
# Boost 1.75.0 is downloaded automatically if not found locally.
#
# Usage:
#   chmod +x install_crhm.sh
#   ./install_crhm.sh
#
# Output:
#   KISSPATH_BINARIES/crhmcode/crhmcode/build/crhm
# ============================================================================

set -euo pipefail

MODEL_DIR="KISSPATH_BINARIES"
CRHM_DIR="${MODEL_DIR}/crhmcode"
SRC_DIR="${CRHM_DIR}/crhmcode/src"
BUILD_DIR="${CRHM_DIR}/crhmcode/build"
BOOST_VERSION="1_75_0"
# The crhmcode commit every machine builds. Upstream has no release tags, and a
# bare `git clone --depth 1` takes whatever the default branch holds that day,
# so two machines could build different sources under the same "4.7_16" banner.
# This is the commit the server binary was built from (2026-03-13) and the one
# the KI's source line references (ClassSnobalCRHM.cpp:170, NewModules.cpp:278,
# ...) were read against. Override with CRHM_COMMIT=<sha> only on purpose.
CRHM_COMMIT="${CRHM_COMMIT:-b6f7e707e855980a3d050c6654c1b8674af9cf00}"
CRHM_REPO_URL="https://github.com/srlabUsask/crhmcode.git"
BOOST_URL="https://archives.boost.io/release/1.75.0/source/boost_${BOOST_VERSION}.tar.gz"

echo "=== CRHM Installation Script ==="
echo ""

# Step 1: Check prerequisites
echo "[1/6] Checking prerequisites..."
for cmd in cmake g++ git; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: $cmd not found. Install a C++ toolchain, CMake, and Git with your system package manager."
        exit 1
    fi
done
echo "  cmake: $(cmake --version | head -1)"
echo "  g++:   $(g++ --version | head -1)"
echo "  git:   $(git --version)"

# Step 2: Clone repository
echo ""
echo "[2/6] Cloning crhmcode repository..."
if [ -d "${CRHM_DIR}/.git" ]; then
    echo "  Repository already exists at ${CRHM_DIR}, skipping clone."
else
    mkdir -p "${CRHM_DIR}"
    cd "${CRHM_DIR}"
    git init -q
    git remote add origin "${CRHM_REPO_URL}"
    # fetch exactly the pinned commit (GitHub serves a commit by its full sha)
    git fetch --depth 1 origin "${CRHM_COMMIT}"
    git checkout -q FETCH_HEAD
fi
HAVE_COMMIT="$(git -C "${CRHM_DIR}" rev-parse HEAD)"
if [ "${HAVE_COMMIT}" != "${CRHM_COMMIT}" ]; then
    echo "ERROR: ${CRHM_DIR} is at ${HAVE_COMMIT}, but the KI is pinned to ${CRHM_COMMIT}."
    echo "  Check out the pinned commit, or set CRHM_COMMIT=${HAVE_COMMIT} to build this one on purpose."
    exit 1
fi
echo "  crhmcode commit: ${HAVE_COMMIT} ($(git -C "${CRHM_DIR}" log -1 --format=%ci))"

# Step 3: Download Boost 1.75.0 (if not present)
echo ""
echo "[3/6] Checking Boost ${BOOST_VERSION}..."
BOOST_DIR="${SRC_DIR}/libs/boost_${BOOST_VERSION}"
if [ -d "${BOOST_DIR}" ]; then
    echo "  Boost already present at ${BOOST_DIR}"
else
    echo "  Downloading Boost ${BOOST_VERSION} (~120 MB)..."
    mkdir -p "${SRC_DIR}/libs"
    cd "${SRC_DIR}/libs"
    ARCHIVE="boost_${BOOST_VERSION}.tar.gz"
    if command -v curl &>/dev/null; then
        curl -fL --retry 3 --progress-bar "${BOOST_URL}" -o "${ARCHIVE}"
    elif command -v wget &>/dev/null; then
        wget -q --show-progress "${BOOST_URL}" -O "${ARCHIVE}"
    else
        echo "ERROR: curl or wget is required to download Boost."
        exit 1
    fi
    echo "  Extracting..."
    tar -xzf "${ARCHIVE}"
    rm "${ARCHIVE}"
    echo "  Boost extracted to ${BOOST_DIR}"
fi

# Step 4: Initialize submodules (spdlog)
echo ""
echo "[4/6] Initializing git submodules (spdlog)..."
cd "${CRHM_DIR}"
git submodule update --init --recursive 2>/dev/null || {
    echo "  WARNING: Submodule init failed. spdlog may need manual setup."
    echo "  If build fails with 'spdlog not found', clone spdlog manually:"
    echo "    cd ${SRC_DIR}/libs && git clone --depth 1 https://github.com/gabime/spdlog.git"
}

# Step 5: Build with CMake
echo ""
echo "[5/6] Building CRHM..."
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"
cmake ../src -DCMAKE_BUILD_TYPE=Release 2>&1
if command -v nproc &>/dev/null; then
    JOBS="$(nproc)"
elif command -v sysctl &>/dev/null; then
    JOBS="$(sysctl -n hw.ncpu 2>/dev/null || echo 2)"
else
    JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
fi
cmake --build . -j"${JOBS}" 2>&1

# Step 6: Validate
echo ""
echo "[6/6] Validating build..."
if [ -f "${BUILD_DIR}/crhm" ]; then
    echo "  SUCCESS: CRHM executable built at ${BUILD_DIR}/crhm"
    echo ""
    echo "  Testing --help:"
    "${BUILD_DIR}/crhm" --help 2>&1 || true
    echo ""
    echo "  File size: $(ls -lh ${BUILD_DIR}/crhm | awk '{print $5}')"
    echo ""
    echo "=== Installation complete ==="
    echo "Executable: ${BUILD_DIR}/crhm"
    echo "Built from crhmcode commit: ${HAVE_COMMIT}"
    echo "${HAVE_COMMIT}" > "${BUILD_DIR}/CRHM_COMMIT.txt"
    echo ""
    echo "Quick test:"
    echo "  badlake.prj is part of the crhmcode SOURCE tree (${CRHM_DIR}/crhmcode/prj/), not of"
    echo "  the KI. Its Observations line is a Windows path from the authors' machine; copy the"
    echo "  file and point that line at ${CRHM_DIR}/crhmcode/obs/Badlake73_76.obs first, then:"
    echo "  ${BUILD_DIR}/crhm -p 100 <your copy of badlake.prj> -o /tmp/crhm_test.txt"
else
    echo "  FAILED: crhm executable not found in ${BUILD_DIR}"
    echo "  Check build output above for errors."
    exit 1
fi
