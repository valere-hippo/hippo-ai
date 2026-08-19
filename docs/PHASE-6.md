# Phase 6 - File Connectors and Project Intelligence

## Ziel
Jedes Projekt soll nicht nur Dateien listen, sondern auch verstehen, welche
fachlichen Hinweise in den Dateien stecken.

## Was Phase 6 abdeckt

- automatische Erkennung von GeoPackage-, Shape- und QGIS-Dateien
- Prüfung von Shapefile-Bundles auf fehlende Sidecars
- Erkennung von QGIS-Projekten und einfachen Projekttiteln
- Erkennung von Artenhinweisen aus Dateinamen und Pfaden
- Speicherung von Connector-Notizen im Projektkontext
- Anzeige dieser Hinweise im Desktop-Workspace

## Warum das wichtig ist

Das Chat-Modell bekommt dadurch bessere Projektkontexte:

- welche Arten wahrscheinlich im Projekt vorkommen
- ob ein Shapefile technisch vollständig ist
- ob eine QGIS-Datei vorhanden ist
- ob ein GeoPackage als Kernquelle vorliegt

## Implementierung

- Backend-Projektinventar berechnet `species_hints`, `connector_notes` und
  `qgis_projects`
- Desktop-Projekte zeigen diese Hinweise in der Projektübersicht an
- Retrieval kann diese Metadaten später für bessere Filter und Antworten nutzen

## Bedienung

Es braucht normalerweise keine zusätzliche Aktion:

1. Projekt anlegen oder Ordner anhängen
2. Inventar wird gescannt
3. Connector-Hinweise werden automatisch erzeugt
4. Chat und Projektübersicht nutzen diese Hinweise

