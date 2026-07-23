
#!/bin/bash

# ./Configure
# bear -- make

make clean
make distclean

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

./autogen.sh
./configure
bear -- make