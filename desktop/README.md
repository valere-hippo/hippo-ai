# hippo-ai Desktop

Windows-App auf Basis von Tauri.

## Zweck

- Projekte anlegen und Ordner anhängen
- Projektinhalt mit Metadaten scannen
- GeoPackage auswählen
- Analyse über Backend/GPU-Hub anstoßen
- Ergebnis direkt im Fenster anzeigen
- optional als TXT, DOCX oder PDF exportieren
- GeoJSON-Dateien werden ebenfalls akzeptiert
- zwei Testdateien liegen unter `tests/fixtures/`

## Voraussetzungen auf Windows

- Python 3.11+
- Node.js
- Rust/Cargo
- Microsoft C++ Build Tools
- Microsoft Edge WebView2

Wenn `cargo` nicht gefunden wird, ist Rust nicht installiert oder nicht im PATH.
Installiere Rust unter Windows am einfachsten mit:

```powershell
winget install --id Rustlang.Rustup
```

Danach das Terminal neu öffnen und prüfen:

```powershell
cargo --version
rustc --version
```

## Lokale Entwicklung

Im Root des Repos:

```bash
cd desktop
npm install
npm run tauri dev
```

### Windows-Build

Für ein lokales Windows-Paket:

```bash
npm run tauri build
```

Das Ergebnis liegt danach im Tauri-Build-Ordner und erzeugt einen Windows-Installer (`.exe`/NSIS), sobald Rust, WebView2 und die C++ Build Tools installiert sind.

Das Fenster dient als Arbeitsoberfläche. Die eigentliche Analyse soll über das
Backend und die GPU-Hub-Modelle laufen.

## Aktueller Stand

- Desktop-UI ist angelegt
- Rust-Command startet die Desktop-Orchestrierung
- Windows-only als erster Zielpfad
- Bundling ist noch deaktiviert
- Die letzte Formularbelegung wird lokal im Webview gespeichert und beim nächsten Start wiederhergestellt
- Ein animierter Fortschrittsbalken zeigt den aktuellen Analysezustand
- Die letzten Läufe werden lokal als Verlauf gespeichert
- Die App kann direkt TXT, DOCX und PDF exportieren, ohne Terminal
- Die App kann Projekte anlegen, Ordner anhängen und den Inhalt des Projekts auflisten
- GeoJSON kann direkt mit importiert werden
- Alle `species_rules*.json` im Projekt werden beim Start automatisch zusammengeführt; ein `Analyse-Config`-Feld ist daher meist nicht nötig
- Als Eingabe bitte `.gpkg`, `.shp` oder `.geojson` wählen; `.cpg` ist nur eine Begleitdatei und keine Analyse-Eingabe
- Bei Shapefiles müssen `.shp`, `.dbf` und `.shx` im selben Ordner liegen; fehlt `.shx`, versucht die App die Datei zu restaurieren
