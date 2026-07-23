#!/bin/bash

make distclean

# AFL用のコンパイラを使用する場合
# export CC=afl-gcc
# export CXX=afl-g++

# カバレッジとエラー回避のためのフラグ
export CFLAGS="-fprofile-arcs -ftest-coverage -Wno-error=maybe-uninitialized -Wno-error -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=1"
export CXXFLAGS="-fprofile-arcs -ftest-coverage -Wno-error=maybe-uninitialized -Wno-error -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=1"
export LDFLAGS="-lgcov --coverage"

autoreconf -i -f
./configure --enable-maintainer-mode --disable-werror --disable-shared --enable-static
bear -- make


# #!/bin/bash

# make clean
# #export CC=afl-gcc
# export CFLAGS="-fprofile-arcs -ftest-coverage -Wno-error=maybe-uninitialized -Wno-error"
# export LDFLAGS="-lgcov --coverage"

# autoreconf -i -f
# ./configure --enable-maintainer-mode
# bear -- make 