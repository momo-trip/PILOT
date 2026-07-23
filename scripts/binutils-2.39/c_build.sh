#!/bin/bash

make distclean

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"
 

./configure --disable-shared --enable-static

# export TARGET_PROGRAM="dummy_cmd"
# export INPUT_PATH="dummy_path"

make #objdump