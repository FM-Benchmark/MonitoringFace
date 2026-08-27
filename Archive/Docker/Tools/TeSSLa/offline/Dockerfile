FROM eclipse-temurin:17-jdk AS builder

ARG GIT_BRANCH=master
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y git curl gnupg2 ca-certificates && \
    curl -sL "https://repo.scala-sbt.org/scalasbt/debian/sbt-1.9.3.deb" -o sbt.deb && \
    dpkg -i sbt.deb || apt-get install -f -y && rm sbt.deb && rm -rf /var/lib/apt/lists/*

ARG GIT_COMMIT=""
WORKDIR /build
RUN git config --global http.sslVerify false
# Honor a pinned commit: the image name carries it, so the build must too
# (the old clone silently built the branch HEAD regardless of GIT_COMMIT).
RUN git clone https://git.tessla.io/tessla/tessla.git && cd tessla && \
    if [ -n "${GIT_COMMIT}" ]; then git checkout "${GIT_COMMIT}"; else git checkout "${GIT_BRANCH}"; fi

WORKDIR /build/tessla
RUN sbt assembly

FROM eclipse-temurin:17-jre
# cargo: the compile-rust backend shells out to it (rust monitor lane).
RUN apt-get update && apt-get install -y time cargo && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /build/tessla/target/scala-*/tessla-assembly-*.jar /app/tessla.jar
# -Xss1g: the interpreter's lazy evaluation recurses proportionally to the
# size of Set values; converted MFOTL relations overflow the default stack
# (512m still overflowed on relations of ~10k tuples; 1g completes them).
# CMD contract (framework overrides the command; measurement wrapping works):
# no ENTRYPOINT, no internal time wrapper; the wrapper passes name="tessla".
RUN printf '#!/bin/sh\nexec java -Xss1g -jar /app/tessla.jar "$@"\n' > /usr/local/bin/tessla && chmod +x /usr/local/bin/tessla
# Pre-warm the cargo registry so compile-rust needs no crate downloads at
# run time (it builds a fresh workspace depending on the im crate).
RUN mkdir -p /tmp/warm && printf 'in x: Events[Int]\nout x\n' > /tmp/warm/w.tessla && \
    tessla compile-rust -b /tmp/warm/m /tmp/warm/w.tessla && rm -rf /tmp/warm

CMD ["tessla"]
