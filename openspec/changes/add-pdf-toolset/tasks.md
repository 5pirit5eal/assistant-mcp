# Tasks

Parallelisierbarkeit: Gruppe 1 ist Fundament und blockiert alle Folgenden. Danach sind die Gruppen 2 und 3 voneinander unabhängig (parallelisierbar), Gruppe 4 (Registrierung/Integration) hängt an 1-3, Gruppe 5 hängt an allen.

## 1. Toolset-Gerüst und Dependencies

- [x] 1.1 Dependencies `reportlab` und `markdown-it-py` in `pyproject.toml` aufnehmen und `uv sync` ausführen. Verifikation: `uv run python -c "import reportlab, markdown_it"` erfolgreich, `uv run pytest` bleibt grün.
- [x] 1.2 Toolset-Modul `src/assistant_mcp/toolsets/pdf.py` mit `mcp = FastMCP("pdf")` und leerem Tool anlegen (Gerüst ohne Implementierung). Verifikation: `uv run python -c "from assistant_mcp.toolsets.pdf import mcp"` erfolgreich.

## 2. Tool `generate_pdf` (Text/Markdown -> PDF)

- [x] 2.1 Fail-Tests für `generate_pdf` schreiben (Spec pdf-generation): Plain Text -> PDF-Bytes (`%PDF-`-Magic), leere Eingabe -> Fehler. Verifikation: `uv run pytest tests/test_pdf_toolset.py` schlägt fehl mit begründetem Grund (Tool existiert nicht).
- [x] 2.2 Minimal-Implementierung: `generate_pdf` rendert Plain Text (Absätze) via reportlab und gibt PDF-Bytes als strukturierte MCP-Content-Rückgabe zurück. Verifikation: neue Tests grün.
- [x] 2.3 Fail-Tests für Markdown-Rendering schreiben: Überschriften #/##/###, Listen, `**bold**`/`*italic*`, deutsche Umlaute, Mehrseiten-Umbruch. Verifikation: Tests scheitern vor Implementierung.
- [x] 2.4 markdown-it-py-Walker nach reportlab-Flowables implementieren (Paragraph, Trennung, Stile je Elementtyp). Verifikation: Markdown-Tests grün.
- [x] 2.5 Fail-Tests für Tabellen und Code-Blöcke schreiben (erkennbare Stile: Zellen-Layout, Monospace). Verifikation: Tests scheitern vor Implementierung.
- [x] 2.6 Tabellen- und Code-Block-Rendering implementieren (Table-Flowable mit Kopfzeile, Preformatted in Monospace). Verifikation: Tabellen-/Code-Tests grün, Gesamtsuite grün.

## 3. Tool `convert_to_pdf` (Office -> PDF via LibreOffice)

- [x] 3.1 Fail-Tests für `convert_to_pdf` schreiben (Spec pdf-file-conversion): ungültiges base64 -> Fehler, nicht unterstütztes Format -> Fehler mit Formatname. Verifikation: Tests scheitern vor Implementierung.
- [x] 3.2 Minimal-Implementierung mit base64-Dekodierung, Formatvalidierung und Fehlern für ungültige Eingaben. Verifikation: Fehlerfälle-Tests grün.
- [x] 3.3 Fail-Tests für erfolgreiche Konvertierung schreiben: minimale DOCX/XLSX/PPTX (per python-Bibliothek oder Fixture erzeugt) -> PDF-Bytes (`%PDF-`-Magic); Skip-Guard, falls `soffice` lokal fehlt. Verifikation: Tests scheitern vor Implementierung bzw. skippen ohne soffice.
- [x] 3.4 LibreOffice-Konvertierung implementieren: temporäres Verzeichnis (kontextverwaltet), `soffice --headless` mit isoliertem Profil, PDF-Bytes lesen, keine Rückstände. Verifikation: Konvertierungs-Tests grün; temporäres Verzeichnis nach Aufruf nicht mehr vorhanden.
- [x] 3.5 Test für korrupte Datei (gültiges base64, ungültiger Dateiinhalt) schreiben und Fehlerbehandlung implementieren, ohne Server-Absturz. Verifikation: Test grün, Suite insgesamt grün.

## 4. Registrierung und Integration

- [x] 4.1 Toolset in `toolsets/__init__.py` registrieren (`"pdf": pdf.mcp`) und Toolset-Mount-Test ergänzen (Client-Aufruf über `TOOLSETS["pdf"]`). Verifikation: `uv run pytest` grün, inkl. bestehender Tests.
- [x] 4.2 `uv run ruff check .` und `uv run mypy src` ausführen und Mängel beheben. Verifikation: beide Checks grün.

## 5. Deployment (Docker mit LibreOffice)

- [ ] 5.1 Dockerfile um LibreOffice (core/writer/calc/impress) erweitern. Verifikation: `docker build` erfolgreich; `soffice --version` im Container lauffähig.
- [ ] 5.2 Smoke-Test im Container: DOCX-XLSX-Konvertierung über MCP-Interface im gebauten Image ausführen. Verifikation: PDF-Ausgabe im Container erfolgreich.
