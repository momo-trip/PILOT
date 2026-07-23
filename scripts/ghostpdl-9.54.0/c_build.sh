#!/bin/bash

make distclean
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage -ldeflate"

./autogen.sh
./configure --disable-libdeflate #--disable-shared --enable-static
bear -- make