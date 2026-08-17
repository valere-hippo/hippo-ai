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

Ou en `DOCX`:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg -o bericht.docx
```

Wenn die Spaltennamen abweichen:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg --species-column art --date-column datum
```

Analyseparameter laden:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg --analysis-config-file /pfad/zu/analyse.json
```

Beispiel für `analyse.json`:

```json
{
  "distance_threshold_m": 75,
  "min_cluster_size": 2,
  "distance_threshold_by_group": {
    "bat": 50,
    "bird": 75
  },
  "min_cluster_size_by_group": {
    "bat": 3,
    "bird": 2
  },
  "distance_threshold_by_species": {
    "amsel": 30
  },
  "min_cluster_size_by_species": {
    "amsel": 3
  }
}
```

Eigene Artenregeln laden:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg --rules-file /pfad/zu/eigenen_regeln.json
```

In den Regeln können auch Prioritäten je Art definiert werden, z. B. für Brutverdacht,
Transit oder Konzentrationsbereiche.
