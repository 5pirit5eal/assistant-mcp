# Spec Delta

## Purpose

Fähigkeit des MCP-Servers, Microsoft-Office-Dateien (DOCX, XLSX, PPTX) über base64-Eingabe nach PDF zu konvertieren und als strukturierte MCP-Content-Antwort zurückzugeben – geeignet für den Remote-Betrieb ohne gemeinsames Dateisystem.

## ADDED Requirements

### Requirement: Konvertierung von Office-Formaten nach PDF

Das Tool `convert_to_pdf` des Toolsets `pdf` MUST eine als base64 übergebene Datei der Formate DOCX, XLSX und PPTX in ein PDF konvertieren und die PDF-Bytes als strukturierte MCP-Content-Rückgabe zurückgeben.

#### Scenario: DOCX wird konvertiert

- **WHEN** `convert_to_pdf` mit der base64-Kodierung einer gültigen DOCX-Datei aufgerufen wird
- **THEN** gibt das Tool gültige PDF-Bytes als strukturierte MCP-Content-Rückgabe zurück, die mit `%PDF-` beginnen

#### Scenario: XLSX wird konvertiert

- **WHEN** `convert_to_pdf` mit der base64-Kodierung einer gültigen XLSX-Datei aufgerufen wird
- **THEN** gibt das Tool gültige PDF-Bytes als strukturierte MCP-Content-Rückgabe zurück

#### Scenario: PPTX wird konvertiert

- **WHEN** `convert_to_pdf` mit der base64-Kodierung einer gültigen PPTX-Datei aufgerufen wird
- **THEN** gibt das Tool gültige PDF-Bytes als strukturierte MCP-Content-Rückgabe zurück

### Requirement: Fehlerbehandlung bei ungültiger Eingabe

Das Tool `convert_to_pdf` MUST ungültige Eingaben mit aussagekräftigen Fehlern beantworten, ohne den Server zum Absturz zu bringen.

#### Scenario: Nicht unterstütztes Format

- **WHEN** `convert_to_pdf` mit einer Datei aufgerufen wird, deren Format nicht DOCX, XLSX oder PPTX ist
- **THEN** gibt das Tool einen Fehler zurück, der das nicht unterstützte Format benennt

#### Scenario: Ungültige base64-Eingabe

- **WHEN** `convert_to_pdf` mit einer Zeichenkette aufgerufen wird, die keine gültige base64-Kodierung ist
- **THEN** gibt das Tool einen Fehler zurück, der die ungültige Kodierung benennt

#### Scenario: Korrupte Datei

- **WHEN** `convert_to_pdf` mit gültiger base64-Kodierung einer beschädigten DOCX/XLSX/PPTX-Datei aufgerufen wird
- **THEN** gibt das Tool einen Fehler zurück, ohne dass der Server abstürzt

### Requirement: Temporäre Dateiverarbeitung

`convert_to_pdf` MUST die Eingabedatei nur temporär verarbeiten und nach der Konvertierung keine Dateien dauerhaft auf dem Server zurücklassen.

#### Scenario: Keine Datei-Rückstände

- **WHEN** `convert_to_pdf` erfolgreich durchlaufen wurde
- **THEN** existiert keine temporäre Eingabe- oder Ausgabedatei des Aufrufs mehr im Arbeitsverzeichnis des Servers
