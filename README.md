# animals-ai

Dieses Repository enthält die professionelle Arbeitsaufteilung für das KI-Projekt
zur Auswertung von GeoPackage-/Shape-Daten und zur automatischen Erstellung
fachlicher Texte für Berichte.

Siehe:
- [Produktionsplan](docs/PRODUKTIONSPLAN.md)
- [Datenformat](docs/DATENFORMAT.md)

## Erste Nutzung

### Lokale Ausführung

Das Projekt läuft direkt mit Python, ohne extra Build-Schritt:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg
```

Mit Ausgabe in eine Datei:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg -o bericht.txt
```

Ou en `DOCX`:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg -o bericht.docx
```

Ein eigenes DOCX-Template-Verzeichnis kann zusätzlich übergeben werden:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg -o bericht.docx --docx-template-dir /pfad/zu/template
```

Ou en `PDF`:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg -o bericht.pdf
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

### Lokal testen

Die Tests laufen mit `unittest`:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

Optional kann man zusätzlich die Syntax prüfen:

```bash
python3 -m compileall src tests
```

### Hinweise

- Das Standard-Artenverzeichnis wird aus `species_rules.json` und `species_rules_extra.json` zusammengeführt.
- Eigene Regeln können weiterhin komplett über `--rules-file` ersetzt werden.
