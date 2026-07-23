#!/bin/bash

# Build script created 
# export CFLAGS="-fprofile-arcs -ftest-coverage"
# export LDFLAGS="-lgcov --coverage"

# makeコマンドに直接渡す
#!/bin/bash
rm -f *.gcda *.gcno *.gcov

make clean
bear -- make CC="gcc -fprofile-arcs -ftest-coverage" EXTRAFLAGS="-fstack-protector-strong -lgcov --coverage"