#!/bin/bash

## Libav
git clone https://github.com/libav/libav libav-git-c464278
cd libav-git-c464278
git reset --hard c464278
cd ..

## Bison
wget -O- https://ftp.gnu.org/gnu/bison/bison-3.7.6.tar.gz|tar zxv
cd bison-3.7.6
cd ..

## Cflow
wget -O- https://ftp.gnu.org/gnu/cflow/cflow-1.6.tar.gz|tar zxv
cd cflow-1.6
cd ..

## Libjpeg-turbo-2.1.0
wget -O- https://github.com/libjpeg-turbo/libjpeg-turbo/archive/refs/tags/2.1.0.tar.gz |tar zxv
cd libjpeg-turbo-2.1.0
cd ..

## Libdwarf
wget -O- https://www.prevanders.net/libdwarf-20210528.tar.gz |tar zxv
cd libdwarf-20210528
cd ..

## Ffmpeg
git clone https://git.ffmpeg.org/ffmpeg.git ffmpeg-N-103440-g2f0113be3f
cd ffmpeg-N-103440-g2f0113be3f
git reset --hard 2f0113be3f
cd ..

## Graphicsmagick
wget -O- https://sourceforge.net/projects/graphicsmagick/files/graphicsmagick/1.3.36/GraphicsMagick-1.3.36.tar.gz/download |tar zxv
cd GraphicsMagick-1.3.36
cd ..

## Ghostpdl
wget -O- https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs9540/ghostpdl-9.54.0.tar.gz |tar zxv
cd ghostpdl-9.54.0
cd ..

## Jasper
wget -O- https://github.com/jasper-software/jasper/releases/download/version-2.0.32/jasper.tar.gz|tar zxv
cd jasper-2.0.32
cd ..

## Mpg123
wget -O- https://sourceforge.net/projects/mpg123/files/mpg123/1.28.2/mpg123-1.28.2.tar.bz2/download |tar xvj
cd mpg123-1.28.2
cd ..

## Nasm
wget -O- https://www.nasm.us/pub/nasm/releasebuilds/2.15.05/nasm-2.15.05.tar.gz|tar zxv
cd nasm-2.15.05
cd ..

## Pspp
wget -O- https://ftp.gnu.org/gnu/pspp/pspp-1.4.1.tar.gz |tar zxv
cd pspp-1.4.1
cd ..

## Binutils
wget -O- https://ftp.gnu.org/gnu/binutils/binutils-2.36.1.tar.gz| tar zxv
cd binutils-2.36.1/
cd ..

## Libtiff
wget -O- https://download.osgeo.org/libtiff/tiff-4.3.0.tar.gz|tar zxv
cd tiff-4.3.0
cd ..

## Libxml
# wget -O- http://xmlsoft.org/download/libxml2-2.9.12.tar.gz|tar zxv
wget -O- https://download.gnome.org/sources/libxml2/2.9/libxml2-2.9.12.tar.xz | tar Jxv
cd libxml2-2.9.12
cd ..

## Libexpat
wget -O- https://github.com/libexpat/libexpat/releases/download/R_2_4_1/expat-2.4.1.tar.gz |tar zxv
cd expat-2.4.1
cd ..

## Yara
wget -O- https://github.com/VirusTotal/yara/archive/refs/tags/v4.1.1.tar.gz|tar zxv
cd yara-4.1.1
cd ..

## Vim
git clone https://github.com/vim/vim.git vim-8.2.3113
cd vim-8.2.3113
git checkout v8.2.3113
cd ..





## Cmark
git clone https://github.com/commonmark/cmark cmark-git-9c8e8
cd cmark-git-9c8e8
git reset --hard 9c8e8341361fddc94322f9e0d7e9439e50d16138
cd ..

## Wireshark
wget -O- https://2.na.dl.wireshark.org/src/all-versions/wireshark-4.0.1.tar.xz | tar xJ 
cd wireshark-4.0.1/
cd ..

## Elfutil
wget -O- https://sourceware.org/elfutils/ftp/0.188/elfutils-0.188.tar.bz2 | tar xvj 
cd elfutils-0.188
cd ..

## Libsixel
git clone https://github.com/saitoha/libsixel libsixel-git-6a5be
cd libsixel-git-6a5be
git reset --hard 6a5be8b72d84037b83a5ea838e17bcf372ab1d5f  
cd ..

## Jpegoptim
wget -O- https://github.com/tjko/jpegoptim/archive/refs/tags/v1.5.0.tar.gz | tar zxv
cd jpegoptim-1.5.0
cd ..

## Libjpeg-turbo
wget -O- https://github.com/libjpeg-turbo/libjpeg-turbo/archive/refs/tags/2.1.4.tar.gz | tar zxv 
cd libjpeg-turbo-2.1.4
cd ..

## Jq
wget -O- https://github.com/stedolan/jq/releases/download/jq-1.6/jq-1.6.tar.gz | tar zxv 
cd jq-1.6
cd ..


## Vorbis-tools
wget -O- https://github.com/xiph/vorbis-tools/archive/refs/tags/v1.4.2.tar.gz | tar zxv
cd vorbis-tools-1.4.2/
cd ..

## Lrzip
wget -O- https://github.com/ckolivas/lrzip/archive/refs/tags/v0.651.tar.gz | tar zxv
cd lrzip-0.651
cd ..

## OpenSSL
git clone https://github.com/openssl/openssl openssl-git-31ff3
cd openssl-git-31ff3
git reset --hard 31ff3635371b51c8180838ec228c164aec3774b6
cd ..

## Speex
wget -O- https://github.com/xiph/speex/archive/refs/tags/Speex-1.2.1.tar.gz | tar zxv
cd speex-Speex-1.2.1
cd ..


## Tcpreplay
wget -O- https://github.com/appneta/tcpreplay/releases/download/v4.4.2/tcpreplay-4.4.2.tar.xz | tar xJ 
cd tcpreplay-4.4.2
cd ..

# ## Libtiff
git clone https://gitlab.com/libtiff/libtiff libtiff-git-b51bb
cd libtiff-git-b51bb
git reset --hard b51bb157123264e26d34c09cc673d213aea61fc7
cd ..
