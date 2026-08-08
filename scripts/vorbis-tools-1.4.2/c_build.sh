
#!/bin/bash

# ./Configure
# bear -- make

make clean
make distclean

export CFLAGS="-fprofile-arcs -ftest-coverage -Wno-error=implicit-function-declaration -Wno-implicit-function-declaration"
export LDFLAGS="-lgcov --coverage"

./autogen.sh
./configure
bear -- make -j"$(nproc)"