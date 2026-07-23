#!/bin/bash
rm -rf build
mkdir build

export CC=afl-gcc
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

cd build
cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
      -DENABLE_GPGME=OFF \
      ..
make