#!/bin/bash

make distclean 

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"
autoreconf -vfi

# configure実行
echo "4. configure実行..."
./configure 

# ビルド実行
echo "5. ビルド実行..."
bear -- make