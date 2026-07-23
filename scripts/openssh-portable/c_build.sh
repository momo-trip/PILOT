#!/bin/bash

# sudo apt-get install build-essential zlib1g-dev libssl-dev libpam0g-dev
make distclean

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

autoreconf -fiv

# 4. configure実行
./configure

# 5. ビルド
bear -- make -j$(nproc)
