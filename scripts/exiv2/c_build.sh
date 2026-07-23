#!/bin/bash

# sudo apt-get install -y libbrotli-dev
# sudo apt install libinih-dev
# sudo apt install libfmt-dev

make distclean

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

rm -rf build
mkdir build
cd build

# CMake設定
cmake .. -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

bear -- make -j$(nproc)
