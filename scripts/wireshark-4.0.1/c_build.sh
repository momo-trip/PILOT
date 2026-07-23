#!/bin/bash

# mv epan/dissectors/asn1/lix2/CMakeLists.txt epan/dissectors/asn1/lix2/CMakeLists.txt.bak
# mv epan/dissectors/asn1 epan/dissectors/asn1_disabled
# sudo apt-get install libpcap-dev

rm -rf build CMakeCache.txt CMakeFiles/
#export CC=afl-gcc
export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

mkdir build
cd build
cmake \
    -DBUILD_wireshark=OFF \
    -DENABLE_TSHARK=ON \
    -DDISABLE_WERROR=ON \
    -DBUILD_SHARED_LIBS=OFF \
    -DENABLE_PLUGINS=OFF \
    ..


bear -- make -j$(nproc)