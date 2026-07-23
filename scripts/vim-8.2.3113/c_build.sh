#!/bin/bash

make distclean
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

./autogen.sh
./configure --disable-shared --enable-static
bear -- make