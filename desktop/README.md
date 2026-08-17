# Tier AI Desktop

Prototype Windows-App auf Basis von Tauri.

## Zweck

- GeoPackage auswählen
- lokale Python-Analyse starten
- Ergebnis direkt im Fenster anzeigen
- optional als TXT, DOCX oder PDF exportieren

## Voraussetzungen auf Windows

- Python 3.11+
- Node.js
- Rust/Cargo
- Microsoft C++ Build Tools
- Microsoft Edge WebView2

## Lokale Entwicklung

Im Root des Repos:

```bash
cd desktop
npm install
npm run tauri dev
```

Das Fenster spricht das Python-Backend über `python -m tier_ai` an.
Im aktuellen Prototyp wird dafür der Projekt-Root per Formularfeld übergeben.

## Aktueller Stand

- Desktop-UI ist angelegt
- Rust-Command startet die vorhandene Analyse-CLI
- Windows-only als erster Zielpfad
- Bundling ist noch deaktiviert
- Die letzte Formularbelegung wird lokal im Webview gespeichert und beim nächsten Start wiederhergestellt
- Ein animierter Fortschrittsbalken zeigt den aktuellen Analysezustand
- Die letzten Läufe werden lokal als Verlauf gespeichert
