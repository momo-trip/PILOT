#!/bin/bash

make distclean
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"
 
./configure --disable-shared --enable-static
bear -- make