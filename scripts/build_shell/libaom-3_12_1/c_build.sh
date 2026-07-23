#!/bin/bash
# クリーンアップ
make distclean 2>/dev/null || true

# 新しいビルドディレクトリを作成（buildディレクトリは残す）
rm -rf build_output
mkdir build_output
cd build_output

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

# CMakeでcompile_commands.jsonを生成
cmake .. -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

# ビルド実行
make -j$(nproc)