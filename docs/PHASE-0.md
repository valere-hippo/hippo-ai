# Phase 0 - Saubere Basis

## Entscheidung

Wir bauen **ein Monorepo**.

Warum:

- gemeinsame Konfiguration für KI, UI und Berichtsgenerierung
- einheitliche Versionierung
- einfacher Betrieb auf lokaler Maschine und später auf GPU-Servern
- Projektfokus statt viele getrennte Repos

## Ziel der Phase 0

Eine stabile Grundstruktur, in der:

- Projekte getrennt verwaltet werden können
- Dateien pro Projekt in einem klaren Ordnerlayout liegen
- Authentifizierung einfach, aber vorhanden ist
- Logging, Audit und Backups schon mitgedacht sind
- spätere KI- und Geo-Services sauber angebunden werden können

## Namenskonventionen

- Produktname: `hippo-ai`
- Repo: `hippo-ai`
- Python-Pakete: `snake_case`
- Ordner: `lowercase` oder `kebab-case`
- Projekt-Slugs: `kebab-case`
- API-Routen: `lowercase` mit klaren Ressourcen

## Projektstruktur

```text
hippo-ai/
  backend/
  desktop/
  docs/
  src/
  tests/
  workspace/
  docker-compose.yml
```

### Laufzeitordner

```text
workspace/
  projects/
  logs/
  audit/
  backups/
  state/
  inbox/
  cache/
```

## Simple Auth

Für Phase 0 reicht eine einfache Auth:

- Login mit Benutzername + Passwort
- Ausgabe eines Bearer Tokens
- Schutz der Projekt- und Backup-Routen

## Logging und Audit

### Logging

- lokale Logdateien in `workspace/logs/`
- zusätzlich Konsolen-Logging
- spätere Erweiterung auf JSON-Logs möglich

### Audit

- jede Projektaktion wird in `workspace/audit/` protokolliert
- Aktionen:
  - Login
  - Projekt erstellen
  - Backup erzeugen
  - Datei-Import
  - Analyse gestartet
  - Bericht exportiert

## Backups

Jedes Projekt bekommt ein eigenes Backup-Verzeichnis:

```text
workspace/backups/<projekt-slug>/
```

Ein Backup besteht vorerst aus einem ZIP-Archiv des Projektordners.

## Ergebnis der Phase 0

Nach Phase 0 soll das System:

- einen Projektordner sauber anlegen
- Projekte listen und laden
- einfache Authentifizierung haben
- Audits schreiben
- Backups erstellen
- sich mit Docker Compose starten lassen

