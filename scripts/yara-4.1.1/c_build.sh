#!/bin/bash

make distclean
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

./bootstrap.sh
./configure
bear -- make -j"$(nproc)"