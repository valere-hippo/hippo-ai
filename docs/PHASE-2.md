# Phase 2 - Retrieval pro Projekt

## Ziel

Jedes Projekt bekommt eine dokumentenbasierte Suche. Die Plattform kann
Projektinhalte semantisch durchsuchen und Treffer mit Metadaten anzeigen.

## Kernfunktionen

- Projektbezogene Dokumente indexieren
- GeoPackage, Shape, GeoJSON, QGIS und klassische Dokumente erfassen
- Embeddings mit `BGE-M3`
- Re-Ranking mit `bge-reranker-v2-m3`
- Qdrant als Vektor-Store nutzen, falls verfügbar
- Lokalen Fallback-Index verwenden, falls Qdrant nicht läuft
- Suche nach:
  - Art
  - Datum
  - Dateityp
  - Kategorie
  - Zone / Gebiet
  - Freitext

## Datenfluss

1. Projektordner wird gescannt.
2. Dateien werden klassifiziert.
3. Text und Metadaten werden extrahiert.
4. Embeddings werden erzeugt.
5. Dokumente werden lokal und optional in Qdrant gespeichert.
6. Die Suche filtert zuerst nach Projekt und Metadaten.
7. Relevante Treffer werden mit Re-Ranker sortiert.

## Suchlogik

- Wenn Qdrant verfügbar ist, wird der Projektindex dort gespeichert.
- Wenn Qdrant nicht verfügbar ist, wird der lokale JSON-Index verwendet.
- Artfilter werden tolerant auf Alias, deutsche Namen und wissenschaftliche Namen gemappt.
- Leere Suchanfragen mit Filtern sind erlaubt.

## API

Backend-Endpunkte:

- `POST /projects/{project_id}/retrieval/index`
- `POST /projects/{project_id}/retrieval/search`

## Umgebung

Wichtige Umgebungsvariablen:

- `HIPPO_AI_QDRANT_URL`
- `HIPPO_AI_QDRANT_PATH`

## DoD

- Ein Projekt kann indexiert werden.
- Eine Suche liefert Treffer mit Metadaten.
- Qdrant ist optional, aber aktiv nutzbar.
- Der lokale Fallback bleibt funktionsfähig.
