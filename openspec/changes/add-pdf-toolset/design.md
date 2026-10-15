# Design

## Context

Der Server ist ein modularer FastMCP-Server (Namespace-Mounting über `TOOLSETS` in `src/assistant_mcp/toolsets/__init__.py`), deployt auf Cloud Run, primär für die Anbindung an Mistral im Remote-Betrieb. Es existieren zwei kleine Referenz-Toolsets (`echo`, `time`), die als Muster dienen. Das Dockerfile ist aktuell ein schlankes reines Python-Image ohne System-Binaries. Der remote Betrieb bedeutet: kein gemeinsames Dateisystem mit dem Client, daher base64-Eingabe für Dateien und strukturierte Byte-Rückgabe statt Pfad-Übergabe.

## Goals / Non-Goals

**Goals:**

- `generate_pdf`: vollständige Markdown-Teilmenge (Überschriften, Absätze, Listen, Tabellen, Code-Blöcke, Links, bold/italic) mit gepflegtem, einheitlichem reportlab-Layout
- `convert_to_pdf`: DOCX/XLSX/PPTX über base64 via LibreOffice headless, mit robuster Fehlerbehandlung und ohne temporäre Rückstände
- Beide Tools geben PDF-Bytes als strukturierte MCP-Content-Rückgabe (FastMCP-Byte-Result) zurück
- Deploy-fähiges Docker-Image inkl. LibreOffice

**Non-Goals:**

- Offene Formate (ODT/ODP), Google Docs/Sheets, Mermaid/Vega-Lite (eigene Folgeschritte)
- Konvertierung über Dateipfade (Remoting unsupported; known limit)
- Streaming oder sehr große Dateien (>Cloud-Run-Request-Limits)

## Decisions

### D1: reportlab für `generate_pdf`, LibreOffice nur für `convert_to_pdf`

`generate_pdf` bleibt ein reiner, deterministischer Python-Pfad – gut TDD-fähig ohne Subprocess-Mocks. LibreOffice bleibt auf das beschränkt, wofür es unersetzlich ist (Office-Formate). Alternative (LibreOffice für alles via HTML-Zwischenschritt) verworfen: langsamer, schwerer testbar, Markdown-Rendering hinge am HTML-Interpreter von LibreOffice.

### D2: Markdown-Parser `markdown-it-py` -> eigener AST-Kind-Walker -> reportlab-Flowables

Ein etablierter Parser erzeugt den Token-/AST-Baum; ein eigener Walker übersetzt die Knoten in reportlab-Flowables (Paragraph, Table, Preformatted, Spacer). Dadurch vollständige Layout-Kontrolle (Stile, Zebra-Streifen, Monospace) ohne HTML-Umweg. Alternative: Handgeparste Teilmenge – verworfen, da vollständiger Markdown-Support gefordert ist.

### D3: PDF-Rückgabe als FastMCP-Byte-Content

FastMCP kann Bytes als strukturierten Content-Block zurückgeben (Image/File-Result-Muster). Damit flutet kein base64 den Text-Kontext des Modells und Mistral erhält die PDF-Bytes strukturiert. Alternative (base64 im dict) nur als Fallback, falls Client-Inkompatibilitäten auftauchen.

### D4: `convert_to_pdf` via `soffice --headless --convert-to pdf` in temporärem Verzeichnis

Eingabe: base64 + erwartet Format; Dekodierung -> temporäre Datei mit korrekter Endung in `tempfile.TemporaryDirectory` -> `soffice --headless --convert-to pdf --outdir <tmpdir>` -> PDF-Bytes lesen -> Verzeichnis verwerfen (kontextverwaltet, garantiert keine Rückstände). LibreOffice-Profil wird pro Aufruf isoliert (`-env:UserInstallation=file://<tmp>/lo-profile`), um Race-Conditions bei parallelen Aufrufen zu vermeiden.

### D5: Dockerfile um LibreOffice erweitern

Installation von `libreoffice-core`, `libreoffice-writer`, `libreoffice-calc`, `libreoffice-impress` (ohne `--no-install-recommends`-Fallback, mit `--without-recommends` wo möglich), um die Image-Größe (~500-700 MB Zuwachs) zu begrenzen. Rollback: vorheriges Image bleibt deploybar; der Code wirft einen sauberen Tool-Fehler, falls `soffice` fehlt.

## Risks / Trade-offs

- [Image-Größe/Cold Starts steigen durch LibreOffice] -> bewusst akzeptiert (Entscheidung Q8a); Größenwachstum im Deployment dokumentiert
- [base64-Payloads begrenzt durch Cloud-Run-Request-Limits (~32 MB Request] -> Grenze im Tool-Docstring dokumentieren; große Dateien als späterer Schritt (Chunking/Upload) außerhalb des Scope
- [LibreOffice-Race-Conditions bei parallelen Aufrufen] -> isoliertes Profil pro Aufruf (D4); sequentialisiertes Fallback, falls nötig
- [markdown-it-py-AST-Elemente, die der Walker nicht kennt (z. B. Fußnoten)] -> bewusstes Fallback auf Fließtext statt Absturz; Markdown-Erweiterungen als eigene Szenarien nachziehen
- [Fehlendes `soffice` in lokalen Test-Umgebungen] -> Konvertierungs-Tests mit `pytest.importorskip`-ähnlicher Skip-Logik bzw. Installationscheck im Test; Spec-Anforderungen bleiben für CI mit Docker gültig

## Migration Plan

1. Dependencies ergänzen (`reportlab`, `markdown-it-py`), `uv.lock` aktualisieren
2. Toolset `pdf.py` implementieren (TDD), registrieren
3. Dockerfile erweitern, Image bauen und Conversion-Smoke-Test im Container
4. Deployment wie gehabt; Rollback über vorheriges Image-Tag
