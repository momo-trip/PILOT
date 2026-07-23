#!/bin/bash

## Cmark
git clone https://github.com/commonmark/cmark cmark-git-9c8e8
cd cmark-git-9c8e8
git reset --hard 9c8e8341361fddc94322f9e0d7e9439e50d16138
cd ..

## Libsixel
git clone https://github.com/saitoha/libsixel libsixel-git-6a5be
cd libsixel-git-6a5be
git reset --hard 6a5be8b72d84037b83a5ea838e17bcf372ab1d5f  
cd ..

# ## Libtiff
# git clone https://gitlab.com/libtiff/libtiff libtiff-git-b51bb
# cd libtiff-git-b51bb
# git reset --hard b51bb157123264e26d34c09cc673d213aea61fc7
# cd ..

## OpenSSL
git clone https://github.com/openssl/openssl openssl-git-31ff3
cd openssl-git-31ff3
git reset --hard 31ff3635371b51c8180838ec228c164aec3774b6
cd ..


## Vorbis-tools
wget -O- https://github.com/xiph/vorbis-tools/archive/refs/tags/v1.4.2.tar.gz | tar zxv
cd vorbis-tools-1.4.2/
cd ..


## Lrzip
wget -O- https://github.com/ckolivas/lrzip/archive/refs/tags/v0.651.tar.gz | tar zxv
cd lrzip-0.651
cd ..

## Speex
wget -O- https://github.com/xiph/speex/archive/refs/tags/Speex-1.2.1.tar.gz | tar zxv
cd speex-Speex-1.2.1
cd ..

## Jpegoptim
wget -O- https://github.com/tjko/jpegoptim/archive/refs/tags/v1.5.0.tar.gz | tar zxv
cd jpegoptim-1.5.0
cd ..

## Jq
wget -O- https://github.com/stedolan/jq/releases/download/jq-1.6/jq-1.6.tar.gz | tar zxv 
cd jq-1.6
cd ..

## Libjpeg-turbo
wget -O- https://github.com/libjpeg-turbo/libjpeg-turbo/archive/refs/tags/2.1.4.tar.gz | tar zxv 
cd libjpeg-turbo-2.1.4
cd ..

## Tcpreplay
wget -O- https://github.com/appneta/tcpreplay/releases/download/v4.4.2/tcpreplay-4.4.2.tar.xz | tar xJ 
cd tcpreplay-4.4.2
cd ..

## Elfutil
wget -O- https://sourceware.org/elfutils/ftp/0.188/elfutils-0.188.tar.bz2 | tar xvj 
cd elfutils-0.188
cd ..


## Wireshark
wget -O- https://2.na.dl.wireshark.org/src/all-versions/wireshark-4.0.1.tar.xz | tar xJ 
cd wireshark-4.0.1/
cd ..