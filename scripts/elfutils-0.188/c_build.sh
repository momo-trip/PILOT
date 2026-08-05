#!/bin/bash

make clean

export CFLAGS="-fprofile-arcs -ftest-coverage -Wno-error=maybe-uninitialized -Wno-error -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=1"
export CXXFLAGS="-fprofile-arcs -ftest-coverage -Wno-error=maybe-uninitialized -Wno-error -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=1"
export LDFLAGS="-lgcov --coverage"

export ACLOCAL_PATH=/usr/share/aclocal
autoreconf -i -f
./configure --enable-maintainer-mode --disable-werror
bear -- make


# make clean
# #export CC=afl-gcc
# export CFLAGS="-fprofile-arcs -ftest-coverage -Wno-error=maybe-uninitialized -Wno-error"
# export LDFLAGS="-lgcov --coverage"

# autoreconf -i -f
# ./configure --enable-maintainer-mode
# bear -- make 