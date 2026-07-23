#!/bin/bash

make clean
make distclean 

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

auto/configure \
    --with-cc-opt="$CFLAGS" \
    --with-ld-opt="$LDFLAGS"
bear -- make