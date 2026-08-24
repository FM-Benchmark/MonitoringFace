FROM eclipse-temurin:17-jdk AS builder

ARG GIT_BRANCH=master
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y git curl gnupg2 ca-certificates && \
    curl -sL "https://repo.scala-sbt.org/scalasbt/debian/sbt-1.9.3.deb" -o sbt.deb && \
    dpkg -i sbt.deb || apt-get install -f -y && rm sbt.deb && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git config --global http.sslVerify false
RUN git clone --branch ${GIT_BRANCH} https://git.tessla.io/tessla/tessla.git

WORKDIR /build/tessla
RUN sbt assembly

FROM eclipse-temurin:17-jre
RUN apt-get update && apt-get install -y time && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /build/tessla/target/scala-*/tessla-assembly-*.jar /app/tessla.jar
# -Xss1g: the interpreter's lazy evaluation recurses proportionally to the
# size of Set values; converted MFOTL relations overflow the default stack
# (512m still overflowed on relations of ~10k tuples; 1g completes them).
RUN echo '#!/bin/sh\n/usr/bin/time -v -o scratch/stats.txt java -Xss1g -jar /app/tessla.jar "$@"' > /usr/local/bin/tessla && chmod +x /usr/local/bin/tessla

ENTRYPOINT ["tessla"]
