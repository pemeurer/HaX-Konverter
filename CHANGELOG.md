# Changelog

Alle nennenswerten Änderungen am HaX-Konverter. Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionsnummern folgen [Semantic Versioning](https://semver.org/lang/de/).

## [1.2.0] – 2026-10-28

### Sicherheit der Daten
- Namenskonflikte werden erkannt: `Messung.csv`, `Messung(1).csv` und `Messung(2).csv` überschreiben sich nicht mehr gegenseitig. Kopien werden nummeriert (`Messung_1_QGIS.csv`).
- Quelldateien werden nie überschrieben, auch nicht bei leerem Suffix oder über Netzlaufwerk, SUBST oder Junction.
- Fremde Dateien gleichen Namens werden nie ersetzt, auch keine fremden `.csvt`-, `.vrt`- oder Sammel-Layer-Dateien. Das Ziel wird dann nummeriert. Eigene frühere Ausgaben werden nur nach Rückfrage ersetzt (ersetzen, überspringen oder abbrechen).
- Dateien werden zuerst vollständig in eine Temp-Datei geschrieben. Ist die Ausgabe in QGIS geöffnet, wird sie direkt überschrieben, erneutes Konvertieren klappt also trotzdem.
- Ein Zielordner ohne Schreibrecht führt sofort zu einer verständlichen Fehlermeldung.
- Der Ordner-Scan überspringt versteckte Dateien, Excel-Sperrdateien (`~$…`) und frühere Ausgaben, erkennbar an Suffix, eigener `.csvt` oder Kopfzeile im Zielformat.
- Mit festem Ausgabeordner wird die Unterordner-Struktur übernommen, gleichnamige Dateien aus verschiedenen Ordnern bleiben getrennt.
- Suffix, Kopfzeile und Ausgabeordner werden geprüft. Ein leeres Suffix ist nur mit festem Ausgabeordner erlaubt.

### Einlesen
- Trennzeichen (Semikolon, Tabulator, Komma, Leerzeichen) werden einmal pro Datei erkannt statt pro Zeile, auch hinter einem langen Vorspann.
- Leerzeichen-getrennte `.txt`/`.asc`-Exporte werden unterstützt, `.asc` auch beim Ordner-Scan.
- Höhenraster (ESRI-ASCII) und x-y-z-Geländemodelle werden erkannt und nicht zu Schein-Punkten verarbeitet.
- Punkte ohne Höhe (2D) gehen nicht mehr verloren. Ob die 4. Spalte eine Höhe oder der Punktcode ist, wird je Datei erkannt, am Spaltennamen der Kopfzeile oder an der Mehrheit der Werte, auch bei leeren Endspalten (`ID;x;y;Code;;`).
- Platzhalter für fehlende Höhen (`-`, `n.v.`, `nan`, `NA` …) ergeben eine leere Höhe, der Punktcode bleibt erhalten. Höhen mit Einheit `m` werden gelesen.
- Kodierung: UTF-16 (mit und ohne BOM) und DOS-Codepage 850 werden erkannt.
- Ein führender Tabulator (leere Punktnummer) verschiebt die Spalten nicht mehr.
- Fehlerhafte Datenzeilen werden mit Zeilennummer gemeldet, auch die erste Datenzeile, wenn x und y Zahlen enthalten. Kopf-, Text- und Kommentarzeilen werden mit Zeilennummer aufgeführt.
- Zeilen mit abweichendem Trennzeichen (z. B. in zusammengefügten Exporten) werden gemeldet statt still verworfen.
- Ausreißer (mehr als 10 km vom Großteil der Punkte) werden gemeldet, z. B. versehentlich übernommene Metazeilen. Liegen die Punkte in mehreren weit entfernten Gebieten, gibt es stattdessen einen Hinweis.
- Kommentarzeilen (`#`, `//`) werden übersprungen. `NaN`/`inf` gelten nicht mehr als Koordinaten. Es gibt keine negative Null `-0.00` mehr.

### Ausgabe & QGIS
- Die `.csvt`-Typdatei ist standardmäßig aktiv, damit IDs wie `3.10` oder `0010` in QGIS Text bleiben.
- Neu: `.vrt`-Layerdatei mit Koordinatensystem (UTM 32/33, mit Zonenkennung, Gauß-Krüger 2–5, ohne KBS oder frei wählbarer EPSG-Code) und Plausibilitätsprüfung der Koordinaten.
- Neu: optionaler Sammel-Layer über alle Dateien eines Laufs, mit Herkunftsspalte `Quelle`.
- Verworfene Zeilen werden mit Grund und Zeilennummer gemeldet. Dateien ohne Messpunkte erzeugen keine Ausgabe mehr und gelten nicht als Erfolg.
- Wird die `.csvt` abgeschaltet, entfernt das Programm eine eigene veraltete `.csvt`. Auf eine liegen gebliebene `.vrt` weist es hin.
- Der Sammel-Layer wird bei jedem Lauf aktualisiert und enthält auch die vorhandenen Ausgaben übersprungener Dateien. Seine Herkunftsspalte kollidiert nicht mit eigenen Spaltennamen.

### Oberfläche
- Das Protokoll wird fortlaufend geführt und hat eine Scrollbar. Fehler werden zusätzlich als Dialog gemeldet, ein Doppelklick auf eine Zeile zeigt Details.
- Die Konvertierung läuft im Hintergrund, mit Fortschrittsbalken und Abbrechen-Knopf. Die Optionen sind währenddessen gesperrt, und ein Doppelklick auf „Konvertieren“ bricht den Lauf nicht versehentlich ab.
- Scharfe Darstellung bei Windows-Skalierung. Die Fenstergröße richtet sich nach Bildschirm und Inhalt.
- Entfernte Dateien tauchen beim erneuten Einlesen nicht wieder auf.
- Dark Mode überarbeitet: lesbare Hover-Zustände, Scrollbars, Auswahlliste und eine dunkle Titelleiste.
- Tastenkürzel (`Strg+O`, `F5`, `Entf`, `Strg+A`, `Strg+Enter`). Einstellungen werden gespeichert.
- Drag & Drop über `windnd` funktioniert mit Umlauten im Pfad. Fehlt die tkdnd-Bibliothek, startet das Programm trotzdem.

### Projekt
- Neuer Name „HaX-Konverter – CSV-Batch-Konverter für den QGIS-Import“ mit Markenhinweis zu QGIS.
- Lizenz klargestellt: `GPL-3.0-or-later`, mit vollständiger `LICENSE`-Datei.
- README vervollständigt. Neu sind Tests, synthetische Beispiele, `requirements.txt` und ein Starter ohne Konsolenfenster (`HaX-Konverter.pyw`).

## [1.1.0]

- Ausgangsstand: Batch-Konvertierung von Vermessungs-CSV nach `ID,x,y,z,Punktcode` mit Drag & Drop, Dateinamen-Bereinigung, optionaler `.csvt` sowie Dark/Light Mode.
