#!/bin/bash

make distclean
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

#./autogen.sh
autoreconf -fiv 
./configure --without-gui --disable-shared --enable-static
bear -- make