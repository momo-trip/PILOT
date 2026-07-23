#!/bin/bash

make clean
make distclean

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

make configure
./configure 

bear -- make
