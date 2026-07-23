#!/bin/bash

export CFLAGS="-fprofile-arcs -ftest-coverage"
export LDFLAGS="-lgcov --coverage"

make distclean 

autoreconf -fi

# configure実行（OpenSSLを明示的に指定）
echo "5. configure実行..."
./configure \
    --with-openssl \
    --with-zlib \
    --disable-shared \
    --enable-static \
    --disable-ldap \
    --disable-ldaps \
    --disable-rtsp \
    --disable-dict \
    --disable-telnet \
    --disable-tftp \
    --disable-pop3 \
    --disable-imap \
    --disable-smb \
    --disable-smtp \
    --disable-gopher \
    --disable-mqtt \
    --disable-manual \
    --disable-docs \
    --without-libidn2 \
    --without-librtmp \
    --without-nghttp2

# 4. ビルド
bear -- make #make -j$(nproc)