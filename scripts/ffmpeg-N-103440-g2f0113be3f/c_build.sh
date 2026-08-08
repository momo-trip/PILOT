#!/bin/bash

make distclean
export CFLAGS="-g -O2 -fprofile-arcs -ftest-coverage -Wno-error=int-conversion"
export LDFLAGS="-lgcov --coverage"
 
./autogen.sh
./configure --disable-shared --enable-static
bear -- make -j"$(nproc)"