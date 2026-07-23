#!/bin/bash

make distclean
#export CC=afl-gcc
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"
 
./configure --without-gui
bear -- make