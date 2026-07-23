#!/bin/bash

make distclean

# sudo apt install libsdl2-dev

# # 追加で必要になる可能性のあるパッケージ
# sudo apt install libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

# 3. configure実行
./configure

# 4. ビルド
bear -- make -j$(nproc)