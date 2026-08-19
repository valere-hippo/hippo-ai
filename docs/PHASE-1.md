# Phase 1 - Projekte und Dateien

## Ziel

Die Plattform kann Projekte anlegen, einen lokalen oder gemeinsamen Ordner anhängen,
Dateien automatisch erkennen, Metadaten indexieren und den Projektinhalt anzeigen.

## Kernfunktionen

- Projekt erstellen
- Ordner anhängen oder importieren
- Inhalte automatisch scannen
- Dateitypen und Metadaten indizieren
- Projektinhalt im Desktop-UI anzeigen

## Datenmodell

Jedes Projekt enthält:

- `id`
- `slug`
- `name`
- `description`
- `client`
- `tags`
- `root_path`
- `metadata`
- `directories`

## Projektinventar

Beim Scannen werden pro Datei erfasst:

- relativer Pfad
- absoluter Pfad
- Dateiname
- Endung
- Kategorie
- Größe
- Änderungszeitpunkt

Zusätzlich werden Summen gebildet für:

- Geodaten
- Dokumente
- Bilder
- QGIS-Dateien
- Sonstiges

## Benutzerfluss

1. Projekt anlegen.
2. Quellordner oder Netzwerkpfad anhängen.
3. Scan ausführen.
4. Dateiliste und Metadaten prüfen.
5. Danach Analyse und Bericht auf diesem Projekt aufbauen.

## Hinweise

- Shapefiles werden als Datei-Paare bzw. -Sets behandelt.
- GeoPackage, GeoJSON und QGIS-Projekte werden automatisch erkannt.
- Die Projektmetadaten werden in `workspace/state/projects.json` gespeichert.
