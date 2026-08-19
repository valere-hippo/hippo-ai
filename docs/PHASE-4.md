# Phase 4 - Chat-first Projektarbeit

## Ziel

Die App soll wie ein Projekt-Arbeitsraum funktionieren:

- der Chat ist die Hauptoberfläche
- jedes Projekt besitzt einen eigenen Chatverlauf
- ein allgemeiner Chat ist ohne Projekt möglich
- Antworten, Quellen und Aktionen bleiben im Projekt nachvollziehbar

## Was jetzt funktioniert

- Projektwechsel lädt den passenden Chatverlauf
- der Verlauf wird als Datei gespeichert
- allgemeiner Chat und Projekt-Chat sind getrennt
- Chatantworten können direkt Berichte, Exporte und Analysen auslösen
- Quellen werden mitgeführt

## Speicherorte

- Projekt-Chat: `chat/history.json` im jeweiligen Projektordner
- Allgemeiner Chat: `workspace/state/chat/general.json`

## Nutzungslogik

1. Benutzer meldet sich an
2. Benutzer sieht nur seine Projekte
3. Benutzer wählt ein Projekt oder startet einen allgemeinen Chat
4. Benutzer stellt eine Frage im Chat
5. Die KI nutzt das Projekt, die Dateien und den Retrieval-Index
6. Das Ergebnis bleibt als Chatverlauf im Projekt gespeichert

## Wichtige Befehle

- `chat_project`
- `chat_project_stream`
- `chat_general`
- `chat_general_stream`

## Nächster Schritt

Die nächste Phase ist die vollständige Projekt- und Rechteverwaltung:

- Projekt teilen
- Rollen
- Sichtbarkeit
- Audit
- Team-Zugriffe

