# hippo-ai

Dieses Repository enthält die Arbeitsbasis für `hippo-ai`, eine Plattform für
projektbezogene Geo-KI, Berichte und Dokumentenarbeit.

Siehe:
- [Phase 0](docs/PHASE-0.md)
- [Phase 1](docs/PHASE-1.md)
- [Produktionsplan](docs/PRODUKTIONSPLAN.md)
- [Datenformat](docs/DATENFORMAT.md)
- [GPU Hub Setup](docs/GPU-HUB.md)

## Erste Nutzung

### Entwicklung vor Ort

Für Entwicklung und Tests kann das Projekt direkt mit Python laufen. Der
produktive Modellbetrieb soll jedoch in GPU Hub stattfinden:

- Chat-LLM: remote
- Embeddings: remote
- Reranker: remote
- Qdrant: zentral

Das Projekt läuft direkt mit Python, ohne extra Build-Schritt:

```bash
hippo-ai path/zur/datei.gpkg
```

Falls das Paket noch nicht installiert ist:

```bash
PYTHONPATH=src python3 -m tier_ai path/zur/datei.gpkg
```

Mit Ausgabe in eine Datei:

```bash
hippo-ai path/zur/datei.gpkg -o bericht.txt
```

Ou en `DOCX`:

```bash
hippo-ai path/zur/datei.gpkg -o bericht.docx
```

Ein eigenes DOCX-Template-Verzeichnis kann zusätzlich übergeben werden:

```bash
hippo-ai path/zur/datei.gpkg -o bericht.docx --docx-template-dir /pfad/zu/template
```

Ou en `PDF`:

```bash
hippo-ai path/zur/datei.gpkg -o bericht.pdf
```

Wenn die Spaltennamen abweichen:

```bash
hippo-ai path/zur/datei.gpkg --species-column art --date-column datum
```

Analyseparameter laden:

```bash
hippo-ai path/zur/datei.gpkg --analysis-config-file /pfad/zu/analyse.json
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
hippo-ai path/zur/datei.gpkg --rules-file /pfad/zu/eigenen_regeln.json
```

In den Regeln können auch Prioritäten je Art definiert werden, z. B. für Brutverdacht,
Transit oder Konzentrationsbereiche.

## Plattform-Basis

Die aktuelle Codebasis ist als Monorepo aufgebaut. Phase 0 umfasst:

- einfache Authentifizierung
- Projektordner mit Logs, Audit und Backups
- Docker Compose für Backend und spätere Services
- klare Namenskonventionen
- lokale und Windows-UI-Nutzung

### GPU Hub-Betrieb

Für den produktiven Betrieb setze diese Umgebungsvariablen:

- `HIPPO_AI_EMBEDDING_URL`
- `HIPPO_AI_EMBEDDING_MODEL`
- `HIPPO_AI_RERANKER_URL`
- `HIPPO_AI_RERANKER_MODEL`
- `HIPPO_AI_LLM_URL`
- `HIPPO_AI_LLM_MODEL`
- `HIPPO_AI_MODEL_MODE=remote`

Dann ruft `hippo-ai` Embeddings, Re-Ranking und Chat über HTTP im GPU Hub ab.

### Backend

Das Backend liegt unter [backend](backend/README.md).

## Windows-App

Für eine Windows-Oberfläche ohne Terminal gibt es jetzt einen Tauri-Prototyp unter
[desktop/](desktop/README.md).

Der Prototyp dient als Arbeitsoberfläche, während die eigentliche KI-Verarbeitung
über GPU Hub erfolgen soll. Außerdem kann er Projekte anlegen, Ordner anhängen
und den Projektinhalt scannen.

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
