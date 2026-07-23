#!/bin/bash

# sudo apt install liblzo2-dev
make clean

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

./autogen.sh
./configure
bear -- make