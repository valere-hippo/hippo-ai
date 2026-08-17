# Produktionsplan für `animals-ai`

## Ziel

Das Ziel ist ein produktionsreifes System, das geospatiale Beobachtungsdaten
(GeoPackage und optional Shapefile) einliest, pro Art auswertet, räumliche
Konzentrationen erkennt und daraus fachlich plausible Berichtstexte erzeugt.

Das System soll ohne manuelle Detailanalyse die erste fachliche Auswertung
erstellen. Ein Mensch bleibt für die Endfreigabe im Loop.

## Leitentscheidung

Für den Start wird **kein Modell von Grund auf trainiert**.
Stattdessen wird eine **hybride Architektur** gebaut:

1. Fachlogik in Code
2. Geodatenanalyse in Code
3. Textgenerierung mit einem vorhandenen Modell oder Template-Generator
4. Fachliche Endprüfung durch Menschen

## Lieferumfang der Produktionsversion

Am Ende der ersten produktionsreifen Version muss das System folgendes können:

1. Geodaten laden
2. Beobachtungen pro Art gruppieren
3. Häufungen und Konzentrationszonen erkennen
4. Brutverdacht / Revierverdacht nach Regeln ableiten
5. Zeitraum und artspezifische Habitatregeln berücksichtigen
6. Einen deutschsprachigen Berichtstext erzeugen
7. Statistiken und Zusammenfassungen ausgeben
8. Ergebnisse exportieren, idealerweise als `TXT`, `DOCX` oder `PDF`

## Arbeitspakete

### Paket 1: Projektgrundlage und Domänenklärung

**Ziel**
- Klären, welche Datenschemata, Arten und Berichtstypen unterstützt werden.

**Aufgaben**
- Eingabeformate definieren
- Pflichtfelder festlegen
- Artenkatalog strukturieren
- Brutzeiten und Habitatregeln je Art erfassen
- Referenzberichte als Vorlagen katalogisieren

**Ergebnis**
- saubere Fachspezifikation
- Datenvertrag für Input und Output

**DoD**
- Jede Eingabespalte ist dokumentiert
- Jede Ausgabe ist beschrieben
- Unklare Fachbegriffe sind entschieden

---

### Paket 2: Datenimport und Normalisierung

**Ziel**
- Rohdaten zuverlässig lesen und in ein internes, einheitliches Format bringen.

**Aufgaben**
- `GeoPackage` importieren
- optional `Shapefile` importieren
- Koordinatensystem prüfen
- Geometrien validieren
- Daten in ein internes Beobachtungsmodell überführen

**Ergebnis**
- ein robuster Importer
- validierte Beobachtungsobjekte

**DoD**
- fehlerhafte Dateien werden verständlich gemeldet
- leere oder kaputte Geometrien werden erkannt
- alle Daten landen in einem standardisierten Schema

---

### Paket 3: Räumliche Analyse

**Ziel**
- Konzentrationen, Cluster und mögliche Reviere identifizieren.

**Aufgaben**
- Clustering-Verfahren definieren
- Mindestanzahl von Kontakten je Art konfigurierbar machen
- Distanzschwellen je Art oder Artgruppe hinterlegen
- räumliche Schwerpunkte berechnen
- Ausreißer und Einzelpunkte getrennt behandeln

**Ergebnis**
- Analyseobjekt pro Art mit Konzentrationen und Verdachtszonen

**DoD**
- dieselben Daten liefern reproduzierbare Ergebnisse
- Parameter sind konfigurierbar und dokumentiert

---

### Paket 4: Fachlogik pro Art

**Ziel**
- Die KI darf nicht nur zählen, sie muss ökologische Plausibilität prüfen.

**Aufgaben**
- Brutzeitfenster je Art hinterlegen
- Habitattyp je Art hinterlegen
- Reproduktionsverdacht aus Zeitraum + Raum + Habitat ableiten
- Regeln für Vogelarten und Fledermäuse getrennt modellieren
- Sonderfälle wie Transitflug oder Nahrungssuche berücksichtigen

**Ergebnis**
- fachliche Entscheidungsschicht pro Art

**DoD**
- Amsel, Blaumeise, Buntspecht, Fledermäuse usw. können unterschiedlich bewertet werden
- gleiche Räumlichkeit kann je nach Art zu anderer Schlussfolgerung führen

---

### Paket 5: Berichtsgenerator

**Ziel**
- Aus den Analyseergebnissen lesbaren, professionellen Text erzeugen.

**Aufgaben**
- Textvorlagen aus bestehenden Berichten ableiten
- Kapitelstruktur definieren
- standardisierte Formulierungen erzeugen
- unsichere Fälle mit vorsichtiger Sprache ausgeben
- Summary pro Art und Gesamtfazit erzeugen

**Ergebnis**
- automatisch erzeugter Berichtsentwurf auf Deutsch

**DoD**
- Text ist fachlich vorsichtig und professionell
- Ausgabe klingt nach Bericht, nicht nach Chatbot
- menschliche Nachbearbeitung bleibt einfach

---

### Paket 6: Benutzeroberfläche oder CLI

**Ziel**
- Das Tool muss praktisch nutzbar sein, nicht nur technisch korrekt.

**Optionen**
- Web-UI mit Upload und Download
- CLI für Batch-Verarbeitung
- beides, falls der Aufwand vertretbar ist

**Aufgaben**
- Datei hochladen
- Analyse starten
- Status anzeigen
- Ergebnis exportieren

**Ergebnis**
- klarer Bedienpfad für den Alltag

**DoD**
- ein Nutzer kann ohne Codekenntnisse einen Report erzeugen

---

### Paket 7: Qualitätssicherung

**Ziel**
- Produktionsreife durch Tests, Metriken und Freigabekriterien.

**Aufgaben**
- Unit-Tests für Import und Regeln
- Integrationstests für ganze Analyseketten
- Goldene Testfälle aus realen Berichten
- Metriken für Genauigkeit und Vollständigkeit definieren
- fachliche Abnahmetests mit Referenzdaten

**Ergebnis**
- belastbare Qualität statt nur Demo

**DoD**
- kritische Pfade sind getestet
- Ergebnisse sind nachvollziehbar
- Regressionen werden früh entdeckt

---

### Paket 8: Betrieb und Deployment

**Ziel**
- Das System muss sicher, wartbar und ausrollbar sein.

**Aufgaben**
- Konfigurationsmanagement
- Logging
- Fehlerbehandlung
- Versionierung der Regeln
- Deployment-Strategie
- Backup- und Wiederherstellungsstrategie

**Ergebnis**
- ein Betriebskonzept für Produktion

**DoD**
- Releases sind reproduzierbar
- Konfiguration ist getrennt vom Code
- Logs helfen bei der Fehlersuche

## Empfohlene Reihenfolge

1. Fachspezifikation
2. Datenimport
3. Räumliche Analyse
4. Artlogik
5. Berichtsgenerator
6. UI oder CLI
7. Tests und Härtung
8. Deployment

## MVP und Produktionsversion

### MVP

Das MVP muss:
- GeoPackage lesen
- Arten gruppieren
- Konzentrationen erkennen
- einen kurzen Berichtstext ausgeben

### Produktionsversion

Die Produktivversion muss zusätzlich:
- artspezifische Regeln enthalten
- belastbare Fehlerbehandlung bieten
- exportierbare Berichte erzeugen
- Testabdeckung haben
- dokumentiert und wartbar sein

## Offene Entscheidungen

1. Welches interne Datenformat wird verwendet?
2. Welche Arten werden in Version 1 unterstützt?
3. Wie werden Brutzeiten gepflegt?
4. Welche Schwellenwerte pro Art gelten?
5. Wird ein lokales Modell, ein regelbasierter Generator oder beides genutzt?
6. Welche Exportformate sind verpflichtend?

## Definition of Done für das Gesamtprojekt

Das Projekt gilt als produktionsreif, wenn:

- ein gültiges GeoPackage importiert werden kann
- die Analyse pro Art reproduzierbar läuft
- der Berichtstext fachlich sinnvoll formuliert wird
- Fehlerfälle sauber behandelt werden
- Tests vorhanden sind
- der Output für fachliche Nutzer direkt verwendbar ist
