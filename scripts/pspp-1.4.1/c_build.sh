#!/bin/bash

make distclean
export CFLAGS="-O0 -g -fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

# ./autogen.sh
# autoreconf -fiv 
./configure --without-gui --without-perl-module --disable-shared --enable-static
sed -i '/--language=Glade/s/^\t/\t-/' Makefile
bear -- make -j"$(nproc)"