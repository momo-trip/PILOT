#!/bin/bash

rm -rf build
mkdir build
cd build

# カバレッジフラグの設定
export CFLAGS="-fprofile-arcs -ftest-coverage"
export CXXFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

# CMakeでビルド設定（静的ライブラリ）
cmake .. \
    -DENABLE_SHARED=OFF \
    -DENABLE_STATIC=ON \
    -DCMAKE_C_FLAGS="$CFLAGS" \
    -DCMAKE_CXX_FLAGS="$CXXFLAGS" \
    -DCMAKE_EXE_LINKER_FLAGS="$LDFLAGS"

# ビルド実行
bear -- make -j$(nproc)