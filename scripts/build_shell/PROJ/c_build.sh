#!/bin/bash

# sudo apt-get install -y \
#     libsqlite3-dev \
#     sqlite3 \
#     libtiff-dev \
#     libcurl4-openssl-dev \
#     pkg-config \
#     cmake \
#     build-essential

make clean
make distclean

rm -rf build

mkdir build
cd build

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

# CMake設定
cmake ..

# または最適化付き
#cmake -DCMAKE_BUILD_TYPE=Release ..
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON ..

# ビルド実行
bear -- make -j$(nproc)