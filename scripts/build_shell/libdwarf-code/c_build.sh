#!/bin/bash

make distclean
#export CC=afl-gcc
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"
 
autoreconf -fiv
./configure
bear -- make