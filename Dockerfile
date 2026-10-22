# syntax=docker/dockerfile:1
FROM curlimages/curl:8.16.0 AS pandoc-fetch
# Pinned official pandoc release binary (>= 3.2 required for conventional
# Word list styles; Debian trixie apt only ships 3.1.11.1). The sha256 of
# the downloaded .deb is verified per target architecture.
ARG PANDOC_VERSION=3.12.1
ARG TARGETARCH
RUN curl -fsSL -o /tmp/pandoc.deb \
    https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${TARGETARCH}.deb \
    && case "${TARGETARCH}" in \
         amd64) echo "b4217ac7c54067c442f9d4cd38bcd0c184a43f3e7053431a12263a6f92a33ba2  /tmp/pandoc.deb" | sha256sum -c - ;; \
         arm64) echo "38f44718c0cb15cb81fc31026bd68c33e8628ca5f7ab15ca86494a7f24f7b8e4  /tmp/pandoc.deb" | sha256sum -c - ;; \
         *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
       esac

FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-core \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-impress \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=pandoc-fetch /tmp/pandoc.deb /tmp/pandoc.deb
RUN apt-get update \
    && apt-get install -y --no-install-recommends /tmp/pandoc.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/pandoc.deb

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-install-project && uv sync --frozen --no-dev

ENV MCP_TRANSPORT=http
EXPOSE 8080

CMD ["uv", "run", "assistant-mcp"]
