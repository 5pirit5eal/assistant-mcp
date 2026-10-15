# Proposal

## Why

Der MCP-Server soll primär an Mistral angebunden und remote betrieben werden; bisher fehlt jede Möglichkeit, PDF-Dokumente zu erzeugen. Assistenten sollen strukturierte Inhalte (Text, Markdown) und Office-Dokumente als PDF ausgeben können.

## What Changes

- Neues Toolset `pdf` mit zwei Tools:
  - `generate_pdf`: erzeugt ein PDF aus Text oder Markdown (vollständige Markdown-Teilmenge: Überschriften, Absätze, Listen, Tabellen, Code-Blöcke, Links, **bold**/*italic*) via Markdown-Parser und reportlab.
  - `convert_to_pdf`: wandelt DOCX-, XLSX- und PPTX-Dateien (Eingabe als base64) via LibreOffice headless in PDF um.
- Beide Tools geben die PDF-Bytes als strukturierte MCP-Content-Rückgabe zurück (kein Dateipfad, kein base64 im Textkontext).
- Das Docker-Image wird um LibreOffice erweitert, damit `convert_to_pdf` deploy-fähig ist.
- Registrierung des Toolsets in `toolsets/__init__.py` mit Namespace-Prefix `pdf`.

Nicht im Scope (spätere Changes): offene Formate (ODT/ODP), Google Docs/Sheets, Mermaid- und Vega-Lite-Diagramme.

## Capabilities

### New Capabilities

- `pdf-generation`: PDF-Erzeugung aus strukturiertem Text (Markdown/Plain Text) mit gepflegtem Dokumentlayout inklusive korrektem Unicode-Rendering (deutsche Umlaute).
- `pdf-file-conversion`: Konvertierung von Microsoft-Office-Formaten (DOCX, XLSX, PPTX) nach PDF über base64-Eingabe und LibreOffice headless.

### Modified Capabilities

- keine

## Impact

- Code: neues Modul `src/assistant_mcp/toolsets/pdf.py`, Anpassung `src/assistant_mcp/toolsets/__init__.py`, neues Testmodul `tests/test_pdf_toolset.py`.
- Abhängigkeiten: `reportlab` und ein Markdown-Parser (z. B. `markdown-it-py`) als Runtime-Dependencies; `soffice` als System-Abhängigkeit im Dockerfile.
- Deployment: Docker-Image wächst um LibreOffice (~500-700 MB); Cloud Run Cold Starts werden entsprechend länger.
- Dockerfile: Installation von LibreOffice im Image.
