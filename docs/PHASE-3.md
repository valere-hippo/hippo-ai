# Phase 3 - Projekt-Chat mit RAG

## Ziel

Die App soll projektbezogene Fragen beantworten können, indem sie zuerst die
relevanten Dateien und Texte des aktiven Projekts durchsucht und daraus eine
Antwort mit Quellenangaben erzeugt.

## Ergebnis

Der Projekt-Chat:

- nutzt den Projektindex als Wissensbasis
- erlaubt Fragen mit optionalen Filtern wie Art, Dateityp, Zone und Datum
- liefert eine professionelle Antwort auf Deutsch
- zeigt die verwendeten Quellen transparent an
- kann lokal oder über GPU-Hub-Modelle arbeiten

## Technische Bausteine

- Retrieval per Qdrant oder lokalem Index
- Embeddings über `BGE-M3`
- Re-Ranking über `bge-reranker-v2-m3`
- Antwortgenerierung über ein OpenAI-kompatibles Chat-Modell
- Desktop-UI mit Chat-Panel und Quellenliste

## Wichtige Endpunkte und CLI-Kommandos

- `POST /projects/{project_id}/chat`
- `python -m tier_ai.chat_cli`
- Tauri-Command `chat_project`

## Nutzungslogik

1. Projekt auswählen
2. Projektordner indizieren
3. Frage im Chat stellen
4. Antwort mit Quellen prüfen
5. Bei Bedarf Projektindex aktualisieren

## Hinweis

Wenn kein Remote-Modell konfiguriert ist, kann der Chat auf lokale Fallbacks
zurückfallen. Für die GPU-Hub-Betriebsart sollten die Umgebungsvariablen für
Chat, Embeddings, Reranking und Qdrant gesetzt sein.
