#!/bin/bash
make clean

./Configure -n linux

# Configure実行後にMakefileを書き換える
cp Makefile Makefile.backup

# CFLAGSにカバレッジフラグを追加
sed -i 's/^CFLAGS=\t-Wall/CFLAGS=\t-Wall -fprofile-arcs -ftest-coverage -g -O0/' Makefile

# LDFLAGSにカバレッジライブラリを追加
sed -i 's/-ltirpc -lselinux/-lgcov --coverage -ltirpc -lselinux/' Makefile

# 変更確認
echo "=== Modified CFLAGS ==="
grep "^CFLAGS=" Makefile

bear -- make