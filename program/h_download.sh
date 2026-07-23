#!/bin/bash

# chmod +x download.sh

# Prepare Programs for RQ1-4
mkdir -p /root/programs
cd /root/programs

## Cmark
git clone https://github.com/commonmark/cmark cmark-git-9c8e8
cd cmark-git-9c8e8
git reset --hard 9c8e8341361fddc94322f9e0d7e9439e50d16138
mkdir build
cd build
all_cmake
cd ..
mkdir input
cp test/afl_test_cases/test.md input/
cd ..

## Libsixel
git clone https://github.com/saitoha/libsixel libsixel-git-6a5be
cd libsixel-git-6a5be
git reset --hard 6a5be8b72d84037b83a5ea838e17bcf372ab1d5f  # ここまで
all_configure
mkdir input
cp /root/fuzzer/afl++/testcases/images/jpeg/not_kitty.jpg input/
cd ..

## Libtiff
git clone https://gitlab.com/libtiff/libtiff libtiff-git-b51bb
cd libtiff-git-b51bb
git reset --hard b51bb157123264e26d34c09cc673d213aea61fc7
bash ./autogen.sh  # ここまで
all_configure
mkdir input
cp /root/fuzzer/afl++/testcases/images/tiff/not_kitty.tiff input/
cd ..

## OpenSSL
git clone https://github.com/openssl/openssl openssl-git-31ff3
cd openssl-git-31ff3
git reset --hard 31ff3635371b51c8180838ec228c164aec3774b6

### We modified the ui_openssl.c to avoid waiting for user input
sed -i '339s/.*/    p = "123456\\n";\n    strcpy(result, p);/' crypto/ui/ui_openssl.c # ここまで
CFLAGS="-g -O0" ./config --prefix=$PWD/build_orig no-shared no-module -DPEDANTIC enable-tls1_3 enable-weak-ssl-ciphers enable-rc5 enable-md2 enable-ssl3 enable-ssl3-method enable-nextprotoneg enable-ec_nistp_64_gcc_128 -fno-sanitize=alignment --debug
make -j
make install
make clean

CFLAGS="-g -fsanitize=address -fno-omit-frame-pointer" ./config --prefix=$PWD/build_asan no-shared enable-asan no-module -DPEDANTIC enable-tls1_3 enable-weak-ssl-ciphers enable-rc5 enable-md2 enable-ssl3 enable-ssl3-method enable-nextprotoneg enable-ec_nistp_64_gcc_128 -fno-sanitize=alignment --debug
make -j
make install
make clean

for fuzzer in afl aflfast mopt afl++; do
  CC=/root/fuzzer/${fuzzer}/afl-clang-fast ./config --prefix=$PWD/build_${fuzzer} enable-fuzz-afl no-shared no-module -DPEDANTIC enable-tls1_3 enable-weak-ssl-ciphers enable-rc5 enable-md2 enable-ssl3 enable-ssl3-method enable-nextprotoneg enable-ec_nistp_64_gcc_128 -fno-sanitize=alignment --debug
  make -j
  make install
  make clean
done

CC=/root/fuzzer/CarpetFuzz/fuzzer_afl/afl-clang-fast ./config --prefix=$PWD/build_carpetfuzz enable-fuzz-afl no-shared no-module -DPEDANTIC enable-tls1_3 enable-weak-ssl-ciphers enable-rc5 enable-md2 enable-ssl3 enable-ssl3-method enable-nextprotoneg enable-ec_nistp_64_gcc_128 -fno-sanitize=alignment --debug
make -j
make install
make clean

mkdir input
mkdir input/ec
mkdir input/rsa
mkdir input/asn1parse
cp test/testecpub-p256.pem input/ec/
cp test/testrsapub.pem input/rsa/
cp test/testx509.pem input/asn1parse/
cd ..

## Xpdf
wget -O- https://dl.xpdfreader.com/old/xpdf-4.03.tar.gz | tar zxv
cd xpdf-4.03 # ここまで
mkdir build
cd build
all_cmake
cd ..
mkdir input
cp /root/fuzzer/afl++/testcases/others/pdf/small.pdf input/
cd ..

## Vorbis-tools
wget -O- https://github.com/xiph/vorbis-tools/archive/refs/tags/v1.4.2.tar.gz | tar zxv
cd vorbis-tools-1.4.2/
./autogen.sh # ここまで
all_configure
mkdir input
cp /root/fuzzer/fuzzdata/samples/ogg/audio.ogg input/
cd ..

## Podofo
wget -O- http://sourceforge.net/projects/podofo/files/podofo/0.9.8/podofo-0.9.8.tar.gz/download | tar zxv # ここまで
cd podofo-0.9.8
mkdir build
cd build
all_cmake
cd ..
mkdir input
cp /root/fuzzer/afl++/testcases/others/pdf/small.pdf input/
cd ..

## Lrzip
wget -O- https://github.com/ckolivas/lrzip/archive/refs/tags/v0.651.tar.gz | tar zxv
cd lrzip-0.651
./autogen.sh  # ここまで
all_configure
mkdir input
cp /root/fuzzer/afl++/testcases/archives/exotic/lrzip/small_archive.lrz input
cd ..

## Speex
wget -O- https://github.com/xiph/speex/archive/refs/tags/Speex-1.2.1.tar.gz | tar zxv
cd speex-Speex-1.2.1
./autogen.sh # ここまで
all_configure
mkdir input
cp /root/fuzzer/fuzzdata/samples/speex/sample.spx input
cd ..

## Jpegoptim
wget -O- https://github.com/tjko/jpegoptim/archive/refs/tags/v1.5.0.tar.gz | tar zxv
cd jpegoptim-1.5.0
all_configure
mkdir input
cp /root/fuzzer/afl++/testcases/images/jpeg/not_kitty.jpg input/
cd ..

## Jq
wget -O- https://github.com/stedolan/jq/releases/download/jq-1.6/jq-1.6.tar.gz | tar zxv # ここまで
cd jq-1.6
all_configure
### Modify the manpage to adapt to the parsing script
sed -i "36s/.*/\.SH \"OPTIONS\"/" build_orig/share/man/man1/jq.1
mkdir input
cp tests/modules/data.json input/
cd ..

## Libjpeg-turbo
wget -O- https://github.com/libjpeg-turbo/libjpeg-turbo/archive/refs/tags/2.1.4.tar.gz | tar zxv # ここまで
cd libjpeg-turbo-2.1.4
mkdir build
cd build
all_cmake
cd ..
mkdir input
cp /root/fuzzer/afl++/testcases/images/jpeg/not_kitty.jpg input/
cd ..

## Tcpreplay
wget -O- https://github.com/appneta/tcpreplay/releases/download/v4.4.2/tcpreplay-4.4.2.tar.xz | tar xJ # ここまで
cd tcpreplay-4.4.2
all_configure --enable-debug
mkdir input
cp /root/fuzzer/afl++/testcases/others/pcap/small_capture.pcap input/
./build_orig/bin/tcpprep -a client -i input/small_capture.pcap -o small_capture.cache
cd ..

## Elfutil
wget -O- https://sourceware.org/elfutils/ftp/0.188/elfutils-0.188.tar.bz2 | tar xvj # ここまで
cd elfutils-0.188
for cmd in "orig_configure" "asan_configure"; do
  ${cmd} --enable-elf-stt-common --enable-elf-stt-common --enable-maintainer-mode --disable-debuginfod --disable-libdebuginfod --without-bzlib --without-lzma --without-zstd CFLAGS="-Wno-error $CFLAGS"
done

### Use wllvm to avoid compilation errors
LLVM_COMPILER=clang CC=wllvm CFLAGS="-Wno-error" ./configure --prefix=$PWD/build_afl --enable-elf-stt-common --enable-elf-stt-common --enable-maintainer-mode --disable-debuginfod --disable-libdebuginfod --without-bzlib --without-lzma --without-zstd
LLVM_COMPILER=clang make -j
make install
make clean


for fuzzer in aflfast mopt afl++ carpetfuzz; do
  cp -r build_afl build_${fuzzer}
done

for fuzzer in afl aflfast mopt afl++; do
  for program in `ls build_${fuzzer}/bin/`; do
    extract-bc build_${fuzzer}/bin/eu-elfclassify
    /root/fuzzer/${fuzzer}/afl-clang-fast build_${fuzzer}/bin/eu-elfclassify.bc -o build_${fuzzer}/bin/eu-elfclassify -L$PWD/build_${fuzzer}/lib -lelf -ldw -lstdc++ -lasm
  done
done

extract-bc build_carpetfuzz/bin/eu-elfclassify
/root/fuzzer/CarpetFuzz/fuzzer_afl/afl-clang-fast build_carpetfuzz/bin/eu-elfclassify.bc -o build_carpetfuzz/bin/eu-elfclassify -L$PWD/build_carpetfuzz/lib -lelf -ldw -lstdc++ -lasm

mkdir input
cp /root/fuzzer/afl++/testcases/others/elf/small_exec.elf input/
cd ..

## Wireshark
wget -O- https://2.na.dl.wireshark.org/src/all-versions/wireshark-4.0.1.tar.xz | tar xJ # ここまで
cd wireshark-4.0.1/
mkdir build
cd build
all_cmake -DBUILD_wireshark=OFF
cd ..
mkdir input
cp /root/fuzzer/afl++/testcases/others/pcap/small_capture.pcap input/
cd ..