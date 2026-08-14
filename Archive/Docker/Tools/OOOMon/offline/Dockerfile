# OOOMon: the Isabelle-verified out-of-order reference monitor.
# The verified OCaml core is committed under OOOMon/generated/ (materialised by
# every `isabelle build -e` of the OOOMonitor session), so this image needs no
# Isabelle -- only an OCaml toolchain for the unverified frontend glue.
FROM ocaml/opam:debian-12-ocaml-4.14 AS builder

USER root
RUN apt-get update && apt-get install -y git libgmp-dev pkg-config && rm -rf /var/lib/apt/lists/*
USER opam

RUN opam install -y ocamlfind zarith stdlib-shims

ARG GIT_BRANCH=ooomon_rework
ARG GIT_COMMIT=""
RUN git clone --branch ${GIT_BRANCH} https://git.ku.dk/krq770/formalized_streaming_monitor.git /home/opam/ooomon \
    && cd /home/opam/ooomon && if [ -n "${GIT_COMMIT}" ]; then git checkout ${GIT_COMMIT}; fi

WORKDIR /home/opam/ooomon/frontend
RUN eval $(opam env) && ./build.sh

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y libgmp10 time && rm -rf /var/lib/apt/lists/*
COPY --from=builder /home/opam/ooomon/frontend/ooomon /usr/local/bin/ooomon
CMD ["ooomon"]
