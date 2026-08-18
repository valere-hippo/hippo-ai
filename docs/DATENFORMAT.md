# Datenformat für `tier-ai`

## Ziel

Dieses Dokument definiert das erwartete Eingabeformat für die erste Version.
Das System soll auch mit leicht abweichenden Spaltennamen arbeiten, solange die
fachlich nötigen Informationen vorhanden sind.

## Pflichtfelder

Jeder Datensatz muss mindestens diese Informationen enthalten:

1. Art
2. Geometrie
3. Datum oder Beobachtungszeitpunkt

## Empfohlene Spalten

| Fachliche Bedeutung | Empfohlener Spaltenname |
|---|---|
| Art | `species` |
| Datum | `observed_at` |
| Geometrie | Geometrie-Spalte des Layers |
| Beobachtungs-ID | `id` |
| Notiz | `note` |

## Erlaubte Aliasnamen

Für den Import akzeptiert das System zunächst folgende Alternativen:

- Art: `species`, `art`, `artname`, `taxon`
- Datum: `date`, `datum`, `observed_at`, `beobachtet_am`

Wenn keine explizite Art-Spalte vorhanden ist, versucht das System zusätzlich:

1. den Dateinamen zu interpretieren,
2. Textspalten auf bekannte Arten oder Aliasnamen zu prüfen,
3. englische, deutsche oder wissenschaftliche Bezeichnungen zuzuordnen,
4. zusammengesetzte Namen wie `LazuliBunting` oder `Lazuli Bunting` zu erkennen.

Das ist absichtlich tolerant, damit auch Shape- oder GeoPackage-Dateien aus Fremdquellen
sauber ausgewertet werden können. Wenn mehrere Arten ohne klare Artspalte vorkommen,
wird im Bericht eine fachliche Nachprüfung empfohlen.

## Geometrietypen

Für Version 1 werden diese Geometrietypen akzeptiert:

- Punkt
- Linie
- Polygon

Für die Analyse werden die Geometrien intern auf ihren Schwerpunkt reduziert,
wenn nötig.

## Erwartung an die Koordinaten

Die erste Implementierung arbeitet am besten mit projizierten Koordinaten.
Wenn das Koordinatensystem unbekannt oder ungeeignet ist, wird das später als
Validierungsregel ergänzt.

## Ausgabeschema

Die Analyse erzeugt pro Art:

- Anzahl Nachweise
- erkannte Konzentrationsbereiche
- vorläufige fachliche Bewertung
- Textzusammenfassung
