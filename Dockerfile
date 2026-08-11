# syntax=docker/dockerfile:1.7
#
# PILOT — build environment
#
# Build from the PARENT directory (not from inside PILOT/):
#   docker build --platform=linux/amd64 -f PILOT/Dockerfile -t pilot:latest .
#
# The parent directory must contain all five repositories:
#   PILOT/  kiso-utils/  kiso-parser-c/  kiso-parser-macro/  kiso-llm/
#
# Requires Docker 23+ (BuildKit) so that PILOT/Dockerfile.dockerignore is honored.

FROM ubuntu:22.04

ARG UBUNTU_CODENAME=jammy
ARG LLVM_VERSION=19

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Tokyo \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ---------------------------------------------------------------------------
# 1. APT repositories (LLVM 19 + deadsnakes)
#    Registered before installing any of the packages they provide; clang-19
#    and python3.12 are not available from the stock Ubuntu 22.04 archives.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget gnupg lsb-release git \
        software-properties-common apt-transport-https \
 && wget -qO /etc/apt/trusted.gpg.d/apt.llvm.org.asc \
        https://apt.llvm.org/llvm-snapshot.gpg.key \
 && echo "deb https://apt.llvm.org/${UBUNTU_CODENAME}/ llvm-toolchain-${UBUNTU_CODENAME}-${LLVM_VERSION} main" \
        > /etc/apt/sources.list.d/llvm-${LLVM_VERSION}.list \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt-get update \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 2. Toolchain: build systems, LLVM/Clang 19, coverage tooling
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build lld ccache bear \
        lcov gcovr \
        autoconf automake libtool libtool-bin m4 pkg-config \
        autopoint gettext flex bison nasm texinfo \
        clang-${LLVM_VERSION} clang-tools-${LLVM_VERSION} \
        libclang-${LLVM_VERSION}-dev libclang-cpp${LLVM_VERSION}-dev \
        llvm-${LLVM_VERSION} llvm-${LLVM_VERSION}-dev llvm-${LLVM_VERSION}-tools \
        lld-${LLVM_VERSION} libomp-${LLVM_VERSION}-dev \
 && rm -rf /var/lib/apt/lists/*

# Expose the versioned LLVM binaries under their unversioned names, since the
# target build scripts invoke plain `clang` / `llvm-config`.
RUN update-alternatives --install /usr/bin/clang       clang       /usr/bin/clang-${LLVM_VERSION}       100 \
 && update-alternatives --install /usr/bin/clang++     clang++     /usr/bin/clang++-${LLVM_VERSION}     100 \
 && update-alternatives --install /usr/bin/llvm-config llvm-config /usr/bin/llvm-config-${LLVM_VERSION} 100 \
 && update-alternatives --install /usr/bin/llvm-cov    llvm-cov    /usr/bin/llvm-cov-${LLVM_VERSION}    100 \
 && clang --version

# ---------------------------------------------------------------------------
# 3. Build dependencies of the fuzzing targets
#    (bison, cjpeg, dwarfdump, YARA, GraphicsMagick, avconv, and others)
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        zlib1g-dev libbz2-dev liblzma-dev liblzo2-dev liblz4-dev libzstd-dev \
        libdeflate-dev libjpeg-dev libjpeg-turbo8-dev libpng-dev libtiff-dev \
        libgsl-dev libreadline-dev libncurses-dev \
        libcairo2-dev libpango1.0-dev \
        libogg-dev libvorbis-dev libflac-dev libkate-dev libspeex-dev \
        libspeexdsp-dev libao-dev \
        libonig-dev libssl-dev libjansson-dev libmagic-dev \
        protobuf-c-compiler libprotobuf-c-dev \
        libpcap-dev libcurl4-openssl-dev libmicrohttpd-dev \
        libsqlite3-dev libarchive-dev libgcrypt20-dev \
        libc-ares-dev libssh-dev libsnappy-dev libnghttp2-dev libbrotli-dev \
        libelf-dev libdw-dev \
        python3-pyparsing \
 && rm -rf /var/lib/apt/lists/*

# Point aclocal at the system m4 directory so that autoreconf-based targets
# can find the libtool macros (LT_INIT etc.).
RUN mkdir -p /usr/local/share/aclocal \
 && echo /usr/share/aclocal > /usr/local/share/aclocal/dirlist \
 && aclocal --print-ac-dir

# ---------------------------------------------------------------------------
# 4. Python 3.12 inside a virtualenv
#    The venv avoids PEP 668 (externally-managed-environment) errors and keeps
#    PILOT's dependencies isolated from the system interpreter. Because the
#    venv provides a `python3.12` entry point on PATH, existing scripts that
#    call `python3.12 -m pip ...` resolve to the venv unchanged.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
 && rm -rf /var/lib/apt/lists/*

RUN python3.12 -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN python3.12 -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Copied on its own so that edits to PILOT's source do not invalidate this
# layer; the dependency install is the slowest Python step.
COPY PILOT/requirements.txt /tmp/requirements.txt
RUN python3.12 -m pip install --no-cache-dir -r /tmp/requirements.txt

# Let the Python clang bindings locate libclang at runtime.
ENV LD_LIBRARY_PATH=/usr/lib/llvm-${LLVM_VERSION}/lib:${LD_LIBRARY_PATH} \
    LIBCLANG_PATH=/usr/lib/llvm-${LLVM_VERSION}/lib/libclang.so

# ---------------------------------------------------------------------------
# 5. Source repositories
#    Everything below is invalidated by source changes, so it is kept after
#    the system and dependency layers.
# ---------------------------------------------------------------------------
WORKDIR /root

COPY PILOT             /root/PILOT
COPY kiso-utils        /root/kiso-utils
COPY kiso-parser-c     /root/kiso-parser-c
COPY kiso-parser-macro /root/kiso-parser-macro
COPY kiso-llm          /root/kiso-llm

# Editable installs: source edits take effect without reinstalling.
RUN python3.12 -m pip install --no-cache-dir -e /root/kiso-utils \
 && python3.12 -m pip install --no-cache-dir -e /root/kiso-parser-c \
 && python3.12 -m pip install --no-cache-dir -e /root/kiso-llm

# Build the LibTooling-based parsers.
RUN cd /root/kiso-parser-macro && ./download_clang.sh && ./update.sh
RUN cd /root/kiso-parser-c     && ./download_clang.sh && ./update.sh

# # ---------------------------------------------------------------------------
# # 6. Fetch and instrument the target programs
# #    This is the longest stage, so it comes last.
# # ---------------------------------------------------------------------------
RUN cd /root/PILOT/program && ./h_download.sh
RUN cd /root/PILOT/scripts && ./h_set_build.sh

WORKDIR /root/PILOT
CMD ["/bin/bash"]