# StaticMon: an MFOTL monitor that compiles an optimized binary per formula
# (C++ template metaprogramming), so -- like DejaVu -- monitoring is a two-step
# compile/run affair. Adapted from the Dockerfile on the tool's master branch:
# the image is self-contained, carrying the repository configured and compiled
# once (Clang 19 + lld + Ninja, deps via Conan 2, Release + LTO + jemalloc), so
# a per-formula compile only rebuilds a single translation unit and relinks.
#
# The dispatcher `staticmon` (scripts/staticmon-impl) is on the PATH; the
# harness mounts the experiment folder at /data (the working directory) and
# invokes
#   staticmon compile -sig S -formula F -keep BIN    # compile step
#   staticmon run -monitor BIN -log TRACE            # run step
# Signature, formula, trace and verdicts are all MonPoly-compatible. The
# in-image binary cache lives at /cache and is ephemeral per container run, so
# every `staticmon compile` performs (and times) a real compile; `-keep` copies
# the binary into the mounted folder for the subsequent `staticmon run`.

FROM ubuntu:24.04

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install \
      --no-install-recommends -y \
      ca-certificates git clang-19 lld-19 libstdc++-14-dev llvm-19 \
      ninja-build cmake make python3 python3-pip libgmp10 time \
    && rm -rf /var/lib/apt/lists/*
# ubuntu 24.04's pip is PEP-668 externally-managed; allow the system install.
RUN pip3 install --no-cache-dir --break-system-packages conan
# Expose the versioned lld as the default `ld` (Clang LTO objects link via lld).
RUN lld_bin="$(ls /usr/bin/ld.lld-* /usr/bin/ld.lld 2>/dev/null | sort -V | tail -1)" && \
    ln -sf "$lld_bin" /usr/local/bin/ld && ln -sf "$lld_bin" /usr/bin/ld.lld
ENV CC=clang-19
ENV CXX=clang++-19

ARG GIT_BRANCH=master
ARG GIT_COMMIT=""
RUN git clone --branch "$GIT_BRANCH" https://github.com/krledmno1/staticmon.git /opt/staticmon \
    && if [ -n "$GIT_COMMIT" ]; then cd /opt/staticmon && git checkout "$GIT_COMMIT"; fi

WORKDIR /opt/staticmon

# Conan 2 profile (Clang 19 / release). arch tracks the build platform.
RUN case "$(dpkg --print-architecture)" in \
      amd64) CONAN_ARCH=x86_64 ;; \
      arm64) CONAN_ARCH=armv8 ;; \
      *) echo "unsupported build arch: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac && \
    printf '%s\n' \
      '[settings]' 'os=Linux' "arch=$CONAN_ARCH" 'compiler=clang' \
      'compiler.libcxx=libstdc++11' 'compiler.cppstd=20' 'compiler.version=19' \
      'build_type=Release' \
      > profile
# conan resolves boost/abseil/fmt/jemalloc from conancenter and cmake fetches
# lexy via FetchContent: this step needs network access at image build time.
# Host-native codegen flag is x86-64 vs aarch64 specific.
RUN case "$(dpkg --print-architecture)" in \
      amd64) ARCH_FLAG='-march=native' ;; \
      arm64) ARCH_FLAG='-mcpu=native' ;; \
      *) ARCH_FLAG='' ;; \
    esac && \
    conan install . --output-folder=builddir --build=missing -pr:h=profile -pr:b=profile && \
    cmake -G Ninja -DUSE_JEMALLOC=ON -DENABLE_IPO=ON \
      -DCMAKE_TOOLCHAIN_FILE="$PWD/builddir/conan_toolchain.cmake" \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="$ARCH_FLAG" \
      -S . -B builddir

# Build the header generator (a dependency-free translation unit that does not
# include the formula headers), prime the template monitor with a trivial
# formula (the repo ships only input_formula/formula.h, which #includes the two
# generated headers), then a per-formula rebuild only recompiles staticmon.cpp.
RUN ninja -C builddir bin/staticmon-headers && \
    mkdir -p src/staticmon/input_formula && \
    echo 'p(int)' > /tmp/smoke.sig && echo 'ONCE[0,10] p(x)' > /tmp/smoke.mfotl && \
    ./builddir/bin/staticmon-headers -sig /tmp/smoke.sig -formula /tmp/smoke.mfotl \
      -prefix "$PWD/src/staticmon/input_formula" && \
    ninja -C builddir && test -x builddir/bin/staticmon

ENV STATICMON_HOME=/opt/staticmon
ENV STATICMON_CACHE=/cache
RUN mkdir -p /cache && \
    ln -s /opt/staticmon/scripts/staticmon-impl /usr/local/bin/staticmon

# No ENTRYPOINT: the harness composes the command itself (`staticmon compile
# ...` / `staticmon run ...`, optionally wrapped in `/usr/bin/time -v`).
WORKDIR /data
CMD ["staticmon"]
