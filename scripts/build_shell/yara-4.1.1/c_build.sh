#!/bin/bash

make distclean
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

./build.sh
bear -- make