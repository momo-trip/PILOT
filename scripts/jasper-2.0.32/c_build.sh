#!/bin/bash

# JasPer v4.1.1 Build Script
set -e

SOURCE_DIR=$(pwd)
BUILD_DIR="build_out"
INSTALL_DIR="/usr/local"


rm -rf $BUILD_DIR

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"
echo "Building JasPer..."

# Step 1: Create build directory
mkdir -p $BUILD_DIR

# Step 2: Configure with CMake (allow in-source build)
cmake -H$SOURCE_DIR -B$BUILD_DIR -DCMAKE_INSTALL_PREFIX=$INSTALL_DIR -DALLOW_IN_SOURCE_BUILD=ON -DBUILD_SHARED_LIBS=OFF #-DCMAKE_EXPORT_COMPILE_COMMANDS=ON

# Step 3: Build
cmake --build $BUILD_DIR

# Step 4: Run tests
cd $BUILD_DIR
ctest --output-on-failure

echo "Build complete!"
echo "Executables are in $BUILD_DIR/src/app"
echo "To install: cmake --build $BUILD_DIR --target install"