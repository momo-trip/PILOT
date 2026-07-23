#!/bin/bash

make distclean

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

# 3. configure実行
./configure

# 4. ビルド
bear -- make -j$(nproc)