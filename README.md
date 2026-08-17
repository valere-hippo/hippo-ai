# animals-ai

Dieses Repository enthält die professionelle Arbeitsaufteilung für das KI-Projekt
zur Auswertung von GeoPackage-/Shape-Daten und zur automatischen Erstellung
fachlicher Texte für Berichte.

Siehe:
- [Produktionsplan](docs/PRODUKTIONSPLAN.md)
- [Datenformat](docs/DATENFORMAT.md)

## Erste Nutzung

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg -o bericht.txt
```

Wenn die Spaltennamen abweichen:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg --species-column art --date-column datum
```
