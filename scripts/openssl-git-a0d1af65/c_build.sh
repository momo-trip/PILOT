
#!/bin/bash

# ./Configure
# bear -- make

make clean
make distclean

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage -static"

./config  no-shared no-module -DPEDANTIC enable-tls1_3 enable-weak-ssl-ciphers enable-rc5 enable-md2 enable-ssl3 enable-ssl3-method enable-nextprotoneg enable-ec_nistp_64_gcc_128 -fno-sanitize=alignment --debug
bear -- make