# assistant-mcp

Modularer MCP-Server auf Basis von [FastMCP](https://gofastmcp.com/), deploybar auf Google Cloud Run
(Target-Projekt: `rubenschulze-sandbox`).

## Struktur

```
src/assistant_mcp/
├── server.py        # Einstiegspunkt: FastMCP-Server, mountet alle Toolsets
├── toolsets/
│   ├── __init__.py  # Toolset-Registry
│   └── pdf.py       # PDF-Toolset: Markdown-to-PDF und Office-to-PDF
└── ...
```

Jedes Toolset ist ein eigenes Modul mit einer FastMCP-Instanz; neue Toolsets werden in
`toolsets/__init__.py` registriert und automatisch vom Server gemountet. Das PDF-Toolset
dient dabei als Referenzimplementierung.

## Lokale Entwicklung

```bash
uv sync
uv run assistant-mcp           # stdio-Transport (z. B. für lokale MCP-Clients)
uv run pytest                  # Tests
uv run ruff check .            # Lint
```

## Deployment auf Cloud Run

```bash
gcloud builds submit --project rubenschulze-sandbox --tag gcr.io/rubenschulze-sandbox/assistant-mcp

gcloud run deploy assistant-mcp \
  --project rubenschulze-sandbox \
  --image gcr.io/rubenschulze-sandbox/assistant-mcp \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars MCP_TRANSPORT=http
```

Der Server lauscht auf `$PORT` (Cloud Run Standard) und nutzt standardmäßig den
Streamable-HTTP-Transport von FastMCP unter `/mcp`.
