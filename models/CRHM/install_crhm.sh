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
#   /mnt/disk1/Hydrocraft_server/model/crhmcode/crhmcode/build/crhm
# ============================================================================

set -euo pipefail

MODEL_DIR="/mnt/disk1/Hydrocraft_server/model"
CRHM_DIR="${MODEL_DIR}/crhmcode"
SRC_DIR="${CRHM_DIR}/crhmcode/src"
BUILD_DIR="${CRHM_DIR}/crhmcode/build"
BOOST_VERSION="1_75_0"
BOOST_URL="https://boostorg.jfrog.io/artifactory/main/release/1.75.0/source/boost_${BOOST_VERSION}.tar.gz"

echo "=== CRHM Installation Script ==="
echo ""

# Step 1: Check prerequisites
echo "[1/6] Checking prerequisites..."
for cmd in cmake g++ git; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: $cmd not found. Install with: sudo apt install build-essential cmake git"
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
    cd "${MODEL_DIR}"
    git clone --depth 1 https://github.com/srlabUsask/crhmcode.git
fi

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
    wget -q --show-progress "${BOOST_URL}" -O "boost_${BOOST_VERSION}.tar.gz"
    echo "  Extracting..."
    tar -xzf "boost_${BOOST_VERSION}.tar.gz"
    rm "boost_${BOOST_VERSION}.tar.gz"
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
cmake --build . -j$(nproc) 2>&1

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
    echo ""
    echo "Quick test:"
    echo "  ${BUILD_DIR}/crhm -p 100 ${CRHM_DIR}/crhmcode/prj/badlake.prj -o /tmp/crhm_test.txt"
else
    echo "  FAILED: crhm executable not found in ${BUILD_DIR}"
    echo "  Check build output above for errors."
    exit 1
fi
