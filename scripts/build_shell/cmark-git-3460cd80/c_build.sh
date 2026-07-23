#!/bin/bash

rm -rf build

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"
 
#export CC=afl-gcc-fast

mkdir build
cd build
cmake ..
make 