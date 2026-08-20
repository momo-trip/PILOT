#!/bin/bash

make distclean
# export CC=clang
# export CXX=clang++
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="--coverage" 

./autogen.sh
./configure #--disable-shared --enable-static
bear -- make -j"$(nproc)" EXTRALIBS='$(XTRALIBS) -lm -ldl -rdynamic -lfontconfig -lfreetype -ldeflate'
