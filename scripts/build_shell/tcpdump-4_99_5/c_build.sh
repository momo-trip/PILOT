#!/bin/bash

make distclean 

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

autoreconf -vif

# ビルド設定
./configure

# ビルドとインストール
bear -- make