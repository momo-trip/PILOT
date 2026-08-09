#!/bin/bash

make distclean
# export CC=clang
# export CXX=clang++
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage -ldeflate" # -Wl,--no-as-needed 

./autogen.sh
./configure --disable-libdeflate #--disable-shared --enable-static
bear -- make -j"$(nproc)"