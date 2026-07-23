#!/bin/bash

rm -rf build
#export CC=afl-gcc
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

mkdir build
cd build
cmake ..
bear -- make