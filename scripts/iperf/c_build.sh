#!/bin/bash

make distclean
make clean

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

./bootstrap.sh
./configure
bear -- make