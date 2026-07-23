#!/bin/bash

make distclean
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"
 
rm -f aclocal.m4
rm -rf autom4te.cache

autoreconf -fiv

./configure --disable-shared --enable-static
bear -- make