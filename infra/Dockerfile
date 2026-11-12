FROM timescale/timescaledb:latest-pg17

# Pinned so every machine builds the same thing.
ARG PGVECTOR_VERSION=0.8.0

# OPTFLAGS="" avoids -march=native, which breaks when the image runs on a different CPU.
# with_llvm=no skips JIT bitcode, so we do not need clang. It does not affect search results.
RUN apk add --no-cache --virtual .build-deps build-base git \
 && git clone --branch "v${PGVECTOR_VERSION}" --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
 && cd /tmp/pgvector \
 && make OPTFLAGS="" with_llvm=no \
 && make OPTFLAGS="" with_llvm=no install \
 && cd / && rm -rf /tmp/pgvector \
 && apk del .build-deps