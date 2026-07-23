#!/bin/bash

make distclean
# export CC=afl-gcc
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

# ./autogen.sh  
# #./bootstrap   
./configure
bear -- make