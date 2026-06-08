FROM rust:1.88-trixie AS builder

ARG GIGASTT_VERSION=2.0.9

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libssl-dev \
        pkg-config \
        protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

RUN cargo install gigastt --version "${GIGASTT_VERSION}" --locked

FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin gigastt

COPY --from=builder /usr/local/cargo/bin/gigastt /usr/local/bin/gigastt

USER gigastt
WORKDIR /home/gigastt

EXPOSE 9876

ENTRYPOINT ["gigastt"]
CMD ["serve", "--host", "0.0.0.0", "--port", "9876", "--metrics", "--bind-all"]
