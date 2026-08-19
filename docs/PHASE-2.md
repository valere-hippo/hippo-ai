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
- Externe Modell-Endpunkte im GPU-Hub über OpenAI-kompatible HTTP-APIs anbinden
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
8. Wenn externe Modell-URLs gesetzt sind, werden Embeddings und Re-Ranking
   nicht lokal gerechnet, sondern über HTTP im GPU-Hub angefragt.

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
- `HIPPO_AI_EMBEDDING_URL`
- `HIPPO_AI_EMBEDDING_MODEL`
- `HIPPO_AI_RERANKER_URL`
- `HIPPO_AI_RERANKER_MODEL`
- `HIPPO_AI_LLM_URL`
- `HIPPO_AI_LLM_MODEL`
- `HIPPO_AI_REMOTE_TIMEOUT_SECONDS`

## DoD

- Ein Projekt kann indexiert werden.
- Eine Suche liefert Treffer mit Metadaten.
- Qdrant ist optional, aber aktiv nutzbar.
- Der lokale Fallback bleibt funktionsfähig.
- Der GPU-Hub kann Embeddings und Re-Ranking extern liefern.
