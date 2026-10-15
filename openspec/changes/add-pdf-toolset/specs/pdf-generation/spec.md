# Spec Delta

## Purpose

Fähigkeit des MCP-Servers, aus strukturiertem Text (Plain Text oder Markdown) optisch gepflegte PDF-Dokumente zu erzeugen und als strukturierte MCP-Content-Antwort zurückzugeben.

## ADDED Requirements

### Requirement: PDF-Erzeugung aus Text

Das Tool `generate_pdf` des Toolsets `pdf` MUST aus einer Texteingabe ein gültiges PDF-Dokument erzeugen und die PDF-Bytes als strukturierte MCP-Content-Rückgabe zurückgeben (nicht als base64 im Text und nicht als Dateipfad).

#### Scenario: Plain-Text-Eingabe erzeugt PDF

- **WHEN** `generate_pdf` mit einem Plain Text aufgerufen wird, der Absätze enthält (durch Leerzeilen getrennt)
- **THEN** gibt das Tool gültige PDF-Bytes als strukturierte MCP-Content-Rückgabe zurück, die mit `%PDF-` beginnen

#### Scenario: Markdown-Eingabe wird vollständig gerendert

- **WHEN** `generate_pdf` mit Markdown aufgerufen wird, das Überschriften (`#` bis `###`), Absätze, Aufzählungslisten, Tabellen, Code-Blöcke, Links sowie `**bold**`- und `*italic*`-Auszeichnungen enthält
- **THEN** rendert das erzeugte PDF alle diese Elemente als entsprechend formatierte Dokumentelemente (Überschriftenhierarchie, Tabellen mit Zellen, Code in Monospace, fette/kursive Texte)

#### Scenario: Deutsche Umlaute und Sonderzeichen

- **WHEN** `generate_pdf` mit Text aufgerufen wird, der deutsche Umlaute (ä, ö, ü, ß) sowie gängige Sonderzeichen enthält
- **THEN** enthält das erzeugte PDF diese Zeichen korrekt (kein Ersatz- oder Fehlzeichen-Rendering)

#### Scenario: Leere Eingabe

- **WHEN** `generate_pdf` mit leerer Texteingabe aufgerufen wird
- **THEN** gibt das Tool einen aussagekräftigen Fehler zurück, statt ein leeres oder ungültiges PDF zu erzeugen

### Requirement: Einheitliches Dokumentlayout

Das Tool `generate_pdf` MUST ein einheitliches, gepflegtes Dokumentlayout erzeugen: A4-Seitenformat, angemessene Seitenränder, konsistente Stile für Überschriften, Fließtext, Listen, Tabellen und Code-Blöcke, inklusive Mehrseiten-Umbruch bei langen Inhalten.

#### Scenario: Konsistente Stile

- **WHEN** `generate_pdf` mit gemischtem Markdown (Überschriften, Text, Liste, Tabelle, Code-Block) aufgerufen wird
- **THEN** unterscheiden sich die Stile der Elemente erkennbar voneinander (Größe/Gewicht der Überschriften, Monospace für Code, abgesetzte Tabellen)

#### Scenario: Mehrseiten-Dokument

- **WHEN** `generate_pdf` mit einem Text aufgerufen wird, der eine Seite deutlich übersteigt
- **THEN** besteht das erzeugte PDF aus mehreren Seiten, ohne dass Inhalt verloren geht
