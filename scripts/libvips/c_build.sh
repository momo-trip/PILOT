#!/bin/bash

# makeのdistcleanは無視（エラーでも続行）
make distclean 2>/dev/null || true

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

# クリーンアップ
rm -rf build_output

# meson setup
meson setup build_output

# ビルドディレクトリに移動してからビルド
#cd build_output
#bear -- meson compile
bear -- meson compile -C build_output
