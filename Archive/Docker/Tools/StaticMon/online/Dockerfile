# StaticMon online: the same self-contained per-formula-compiling image as the
# offline variant, with the `staticmon` dispatcher as entrypoint. StaticMon is
# an online monitor by construction: `staticmon run -monitor M` (and the
# all-in-one `staticmon -sig S -formula F`) read the event stream from stdin
# when no -log is given, so a driver can pipe events into the container;
# `-socket [PATH]` serves a Unix socket instead. Verdicts stream to stdout.
#
# Note: unlike the single-binary tools (MonPoly, TimelyMon, ...), StaticMon's
# monitor binary only exists after `staticmon compile` has seen the formula, so
# the extract-a-static-/tool-binary online pipeline does not apply; run this
# image directly and stream events on stdin.

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

# Build the header generator, prime the template monitor with a trivial formula
# (the repo ships only input_formula/formula.h, which #includes the two
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

WORKDIR /data
ENTRYPOINT ["/usr/local/bin/staticmon"]
