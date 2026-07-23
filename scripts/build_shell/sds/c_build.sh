#!/bin/bash

# Build script created automatically
make clean

find . -name "*.gcda" -delete
find . -name "*.gcno" -delete  
find . -name "*.gcov" -delete
find . -name "*.info" -delete


export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

bear -- make CC="gcc -fprofile-arcs -ftest-coverage -lgcov --coverage"