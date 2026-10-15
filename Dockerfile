# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-install-project && uv sync --frozen --no-dev

ENV MCP_TRANSPORT=http
EXPOSE 8080

CMD ["uv", "run", "assistant-mcp"]
