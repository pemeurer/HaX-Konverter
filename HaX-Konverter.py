#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""
HaX-Konverter – CSV-Batch-Konverter für den QGIS-Import
-------------------------------------------------------
© 2026 Peter Meurer
Freie Software unter der GNU General Public License, Version 3 oder später
(GPL-3.0-or-later). Keine Gewährleistung – Nutzung auf eigene Verantwortung.

Konvertiert Vermessungsdateien (Tachymeter / GNSS, z. B. Messung(2).csv)
in ein sauberes, kommagetrenntes Format für QGIS:
- Spalten: ID,x,y,z,Punktcode (x = Rechtswert/Ost, y = Hochwert/Nord)
- Trennzeichen (; Tab , Leerzeichen) und Kodierung werden je Datei erkannt
- Punkt-IDs (z. B. 3.10 oder 0010) bleiben exakt als Text erhalten
- Z-Wert wird kaufmännisch auf 2 Dezimalstellen gerundet
- Übersprungene oder auffällige Zeilen werden gezählt und gemeldet
- Dateinamen werden von Zusätzen wie (1), (2), Leerzeichen etc. bereinigt;
  Namenskonflikte werden aufgelöst, Quelldateien werden nie überschrieben
- Optional: .csvt-Begleitdatei (Feldtypen) und .vrt-Layerdatei mit
  Koordinatensystem, auf Wunsch zusätzlich ein Sammel-Layer für alle Dateien
- Unterstützt Einzel-/Mehrfachdateien sowie Ordner (mit/ohne Unterordner)

QGIS ist eine Marke von QGIS.ORG. Dieses Programm ist kein offizielles
QGIS-Produkt und steht in keiner Verbindung zu QGIS.ORG.
"""

import csv
import errno
import io
import json
import math
import os
import queue
import re
import secrets
import stat
import sys
import threading
import time
import traceback
import webbrowser
import tkinter as tk
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont
from typing import Optional
from xml.sax.saxutils import escape, quoteattr

# Optionales Drag & Drop via tkinterdnd2 oder windnd
DND_BACKEND = None
DND_ERROR = ""  # gesetzt, wenn das Paket da ist, die native Bibliothek aber nicht lädt
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_BACKEND = "tkinterdnd2"
except ImportError:
    try:
        import windnd
        DND_BACKEND = "windnd"
    except Exception:
        DND_BACKEND = None


# =====================================================================
# KONSTANTEN: PROGRAMM, LIZENZ, PAYPAL & STANDARDWERTE
# =====================================================================

APP_NAME = "HaX-Konverter"
APP_SUBTITLE = "CSV-Batch-Konverter für den QGIS-Import"
APP_VERSION = "1.2.0"
AUTHOR = "Peter Meurer"
COPYRIGHT = f"© 2026 {AUTHOR}"
LICENSE_NAME = "GPL-3.0-or-later"
LICENSE_URL = "https://www.gnu.org/licenses/"
PAYPAL_URL = "https://paypal.me/PeMeurer"

DEFAULT_HEADER = "ID,x,y,z,Punktcode"
DEFAULT_SUFFIX = "_QGIS"
DEFAULT_CRS = "EPSG:25832"
SUPPORTED_EXTENSIONS = (".csv", ".txt", ".asc")
FIELD_TYPES = ("String", "Real", "Real", "Real", "String")
CSVT_LINE = ",".join(f'"{t}"' for t in FIELD_TYPES)
COMMENT_PREFIXES = ("#", "//")
UNION_VRT_STEM = "Sammellayer"
OUTLIER_DISTANCE = 10_000  # Meter: weiter vom Großteil der Punkte entfernt = verdächtig

CRS_NONE_LABEL = "Ohne KBS (lokales Messnetz)"
CRS_CHOICES = (
    ("EPSG:25832", "ETRS89 / UTM Zone 32N"),
    ("EPSG:25833", "ETRS89 / UTM Zone 33N"),
    ("EPSG:4647", "ETRS89 / UTM 32N, Rechtswert mit Zonenkennung 32"),
    ("EPSG:5650", "ETRS89 / UTM 33N, Rechtswert mit Zonenkennung 33"),
    ("EPSG:31466", "DHDN / Gauß-Krüger Zone 2"),
    ("EPSG:31467", "DHDN / Gauß-Krüger Zone 3"),
    ("EPSG:31468", "DHDN / Gauß-Krüger Zone 4"),
    ("EPSG:31469", "DHDN / Gauß-Krüger Zone 5"),
    ("", CRS_NONE_LABEL),
)

# Plausible Wertebereiche je KBS: (Rechtswert min, max, Hochwert min, max)
CRS_RANGES = {
    "EPSG:25832": (100_000, 900_000, 3_500_000, 8_000_000),
    "EPSG:25833": (100_000, 900_000, 3_500_000, 8_000_000),
    "EPSG:4647": (32_100_000, 32_900_000, 3_500_000, 8_000_000),
    "EPSG:5650": (33_100_000, 33_900_000, 3_500_000, 8_000_000),
    "EPSG:31466": (2_000_000, 2_999_999, 5_000_000, 6_200_000),
    "EPSG:31467": (3_000_000, 3_999_999, 5_000_000, 6_200_000),
    "EPSG:31468": (4_000_000, 4_999_999, 5_000_000, 6_200_000),
    "EPSG:31469": (5_000_000, 5_999_999, 5_000_000, 6_200_000),
}

LICENSE_TEXT = f"""{COPYRIGHT}

Freie Software unter der GNU General Public License, Version 3 oder (nach Ihrer Wahl) jeder späteren Version ({LICENSE_NAME}).

Dieses Programm ist freie Software: Sie können es unter den Bedingungen der GNU General Public License, wie von der Free Software Foundation veröffentlicht, weitergeben und/oder verändern, entweder gemäß Version 3 der Lizenz oder (nach Ihrer Wahl) jeder späteren Version.

Die Veröffentlichung dieses Programms erfolgt in der Hoffnung, dass es Ihnen von Nutzen sein wird, aber OHNE IRGENDEINE GARANTIE, sogar ohne die implizite Garantie der MARKTREIFE oder der VERWENDBARKEIT FÜR EINEN BESTIMMTEN ZWECK. Details finden Sie in der GNU General Public License.

Sie sollten eine Kopie der GNU General Public License zusammen mit diesem Programm erhalten haben (Datei LICENSE). Falls nicht, siehe {LICENSE_URL}.

Die Nutzung erfolgt auf eigene Verantwortung. Der Autor übernimmt keine Haftung für Schäden, Datenverluste oder Fehlinterpretationen der Ergebnisse.

QGIS ist eine Marke von QGIS.ORG. Dieses Programm ist kein offizielles QGIS-Produkt und steht in keiner Verbindung zu QGIS.ORG.

Tastenkürzel: Strg+O Dateien hinzufügen · F5 Ordner neu einlesen · Entf Auswahl entfernen · Strg+A alles markieren · Strg+Enter konvertieren · Doppelklick auf eine Zeile zeigt Details

Unterstützung und Weiterentwicklung sind willkommen:
{PAYPAL_URL}"""

FOOTER_TEXT = (
    f"{COPYRIGHT} · Freie Software ({LICENSE_NAME}) · Keine Gewährleistung, "
    "Nutzung auf eigene Verantwortung · Kein offizielles QGIS-Produkt"
)


# =====================================================================
# KERNLOGIK: KODIERUNG, ZAHLEN & TRENNZEICHEN
# =====================================================================

_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
DELIMITER_NAMES = {";": "Semikolon", "\t": "Tabulator", ",": "Komma", " ": "Leerzeichen"}


def parse_number(text: str) -> Optional[Decimal]:
    """Liest eine Zahl mit Dezimalpunkt oder -komma; gibt None zurück, wenn es keine ist."""
    s = text.strip()
    if s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    if not _NUMBER_RE.fullmatch(s):
        return None
    value = Decimal(s)
    # Schutz vor absurden Exponenten (z. B. 1e999999), die keine Koordinate sein können
    if abs(value.adjusted()) > 20:
        return None
    return value


def format_number(value: Decimal) -> str:
    """Gibt eine Zahl ohne Exponent und ohne negative Null aus (Nachkommastellen bleiben)."""
    if value.is_zero():
        value = value.copy_abs()
    return format(value, "f")


_HEIGHT_UNIT_RE = re.compile(r"\s*m$", re.IGNORECASE)
# Übliche Platzhalter für eine fehlende Höhe (kein Punktcode!)
MISSING_HEIGHT_MARKERS = {"-", "--", "?", "n.v.", "nv", "na", "n/a", "nan", "null", "#nv", "#n/a", "k.a."}


def is_missing_height(text: str) -> bool:
    return text.strip().casefold() in MISSING_HEIGHT_MARKERS


def format_z_value(val_str: str, round_2_dec: bool = True, fixed_2_dec: bool = True) -> Optional[str]:
    """Rundet den Z-Wert kaufmännisch auf 2 Dezimalstellen (eine Einheit „m“ ist erlaubt).

    Gibt "" für einen leeren Wert und None für einen Wert zurück, der keine Zahl ist.
    """
    if not val_str.strip():
        return ""
    value = parse_number(_HEIGHT_UNIT_RE.sub("", val_str.strip()))
    if value is None:
        return None
    if round_2_dec:
        try:
            value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return None
        if not fixed_2_dec:
            value = value.normalize()
    return format_number(value)


_CP850_UMLAUTS = b"\x81\x84\x8e\x94\x99\x9a\xe1"  # ü ä Ä ö Ö Ü ß in DOS-Codepage 850
_CP1252_UMLAUTS = b"\xc4\xd6\xdc\xdf\xe4\xf6\xfc"  # Ä Ö Ü ß ä ö ü in Windows-1252
_CP1252_TYPOGRAPHY = b"\x80\x85\x91\x92\x93\x96\x97"  # € … ‘ ’ “ – — (in deutschem cp850 kaum vorhanden)
_CP1252_UNDEFINED = b"\x81\x8d\x8f\x90\x9d"


def _count_bytes(data: bytes, values: bytes) -> int:
    return sum(data.count(bytes([b])) for b in values)


def _looks_like_cp850(data: bytes) -> bool:
    if _count_bytes(data, _CP1252_UNDEFINED):
        return True  # in Windows-1252 nicht belegte Bytes, z. B. 0x81 = ü in cp850
    dos = _count_bytes(data, _CP850_UMLAUTS)
    win = _count_bytes(data, _CP1252_UMLAUTS) + 2 * _count_bytes(data, _CP1252_TYPOGRAPHY)
    return dos > win


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Erkennt die Kodierung einer Textdatei und gibt (Text, Bezeichnung) zurück."""
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return data.decode("utf-32", errors="replace"), "UTF-32"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace"), "UTF-16"
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data[3:].decode("utf-8"), "UTF-8"
        except UnicodeDecodeError:
            data = data[3:]
    else:
        sample = data[:4096]
        if sample and sample.count(0) >= len(sample) // 4:
            # UTF-16 ohne BOM (z. B. "Unicode-Text" aus Excel)
            le = sample[1::2].count(0) >= sample[0::2].count(0)
            try:
                return data.decode("utf-16-le" if le else "utf-16-be"), "UTF-16"
            except UnicodeDecodeError:
                pass
    try:
        return data.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        pass
    if _looks_like_cp850(data):
        return data.decode("cp850"), "DOS (cp850)"
    try:
        return data.decode("cp1252"), "Windows-1252"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "ISO-8859-1"


def _strip_bom(line: str) -> str:
    if line.startswith("\ufeff"):
        return line[1:]
    if line.startswith("ï»¿"):  # UTF-8-BOM, als Windows-1252 gelesen
        return line[3:]
    return line


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith(COMMENT_PREFIXES)


def split_line(line: str, delimiter: str) -> list[str]:
    """Zerlegt eine Zeile; bei Leerzeichen-Trennung darf der Punktcode Leerzeichen enthalten."""
    if delimiter == " ":
        parts = line.split(None, 4)
    else:
        try:
            parts = next(csv.reader([line], delimiter=delimiter, skipinitialspace=True))
        except (csv.Error, StopIteration):
            parts = [line]
    return [p.strip() for p in parts]


_DIGIT_RE = re.compile(r"\d")


def _looks_like_coordinate(value: Decimal) -> bool:
    return value.as_tuple().exponent < 0 or abs(value) >= 1000


def _mostly_numeric(text: str) -> bool:
    """Mindestens die Hälfte der Zeichen sind Ziffern (z. B. '512.346,678', nicht 'X_ETRS89')."""
    compact = text.replace(" ", "")
    return bool(compact) and 2 * sum(ch.isdigit() for ch in compact) >= len(compact)


def _whitespace_point(parts: list) -> bool:
    """Leerzeichen-Zeile mit Koordinaten? Fließtext wie „Befund 12 1.5 m breit“ fällt durch."""
    if len(parts) < 3:
        return False
    x, y = parse_number(parts[1]), parse_number(parts[2])
    if x is None or y is None:
        return False
    both_like_coordinates = _looks_like_coordinate(x) and _looks_like_coordinate(y)
    return both_like_coordinates or (len(parts) > 3 and format_z_value(parts[3]) not in (None, ""))


def _score_delimiters(sample: list[str]) -> tuple[str, int]:
    best, best_score = ";", 0
    for delimiter in (";", "\t", ",", " "):
        score = 0
        for line in sample:
            parts = split_line(line, delimiter)
            if delimiter == " ":
                score += _whitespace_point(parts)
            elif len(parts) >= 3 and parse_number(parts[1]) is not None and parse_number(parts[2]) is not None:
                score += 1
        if delimiter == " " and 2 * score < len(sample):
            continue  # Leerzeichen nur, wenn die Mehrheit der Zeilen mit Ziffern Messzeilen sind
        if score > best_score:
            best, best_score = delimiter, score
    return best, best_score


def detect_delimiter(lines: list[str]) -> str:
    """Wählt das Trennzeichen, mit dem die meisten Zeilen gültige x/y-Koordinaten ergeben."""
    candidates = [line for line in lines if line.strip() and not _is_comment(line) and _DIGIT_RE.search(line)]
    best, score = _score_delimiters(candidates[:100])
    if score == 0 and len(candidates) > 100:
        best, score = _score_delimiters(candidates)  # langer Vorspann: ganze Datei prüfen
    return best


# =====================================================================
# KERNLOGIK: ROHDATEN EINLESEN
# =====================================================================

@dataclass
class ParsedFile:
    """Ergebnis des Einlesens einer Rohdatei (Zeilennummern beginnen bei 1)."""
    rows: list = field(default_factory=list)  # [ID, x, y, z, Punktcode]
    encoding: str = ""
    delimiter: str = ";"
    data_lines: int = 0
    text_lines: list = field(default_factory=list)
    comment_lines: list = field(default_factory=list)
    invalid_lines: list = field(default_factory=list)
    bad_height_lines: list = field(default_factory=list)
    no_height_lines: list = field(default_factory=list)
    empty_id_lines: list = field(default_factory=list)
    extra_column_lines: list = field(default_factory=list)
    outlier_lines: list = field(default_factory=list)
    delimiter_lines: list = field(default_factory=list)  # Zeilen mit abweichendem Trennzeichen
    multiple_areas: bool = False  # Punkte in mehreren, weit auseinanderliegenden Gebieten
    row_lines: list = field(default_factory=list)  # Zeilennummer je übernommenem Punkt
    skip_reason: str = ""  # gesetzt, wenn die Datei erkennbar keine Messpunktdatei ist


def _is_esri_grid(lines: list[str]) -> bool:
    """Erkennt den Kopf eines ESRI-ASCII-Rasters (ncols, nrows, xllcorner/xllcenter, …)."""
    keys = {line.split(None, 1)[0].lower() for line in lines[:8] if line.strip()}
    return {"ncols", "nrows"} <= keys and bool({"xllcorner", "xllcenter"} & keys)


def _looks_like_xyz_grid(rows: list) -> bool:
    """x-y-z-Dateien ohne Punktnummer (z. B. Geländemodell): Rechtswert steht in der ID-Spalte."""
    if len(rows) < 3:
        return False
    hits = 0
    for row in rows:
        ident = parse_number(row[0])
        if row[3] or row[4] or ident is None:
            continue
        x, y = float(row[1]), float(row[2])
        # „ID“ wie ein Rechtswert, „x“ wie ein Hochwert, „y“ wie eine Höhe
        if abs(ident) >= 100_000 and abs(x) >= 1_000_000 and abs(y) < 0.001 * abs(x):
            hits += 1
    return 2 * hits > len(rows)


_HEIGHT_NAMES = ("z", "h", "höhe", "hoehe", "hohe", "height", "elev", "elevation", "alt", "altitude", "nn", "nhn")
_CODE_NAMES = ("code", "punktcode", "pcode", "kennung", "beschreibung", "bemerkung", "desc", "description",
               "attribut", "objekt", "art", "typ", "info", "kommentar", "comment", "remark", "name")


def _column_kind(name: str) -> str:
    """'height' oder 'code', wenn der Spaltenname eindeutig ist, sonst ''."""
    key = re.sub(r"[^a-zäöüß]", "", name.casefold())
    if key in _HEIGHT_NAMES or key.startswith(("höhe", "hoehe", "height", "elev")):
        return "height"
    if key in _CODE_NAMES or key.startswith(("code", "punktcode", "beschr", "bemerk", "descr", "kommentar")):
        return "code"
    return ""


def _other_delimiter_point(line: str, delimiter: str) -> bool:
    """Ergibt die Zeile mit einem anderen Trennzeichen gültige x/y-Koordinaten?"""
    for other in (";", "\t", ","):
        if other == delimiter:
            continue
        parts = split_line(line, other)
        if len(parts) >= 3 and parse_number(parts[1]) is not None and parse_number(parts[2]) is not None:
            return True
    return False


def parse_survey_text(text: str, round_z: bool = True, fixed_z_decimals: bool = True) -> ParsedFile:
    """Wandelt den Inhalt einer Rohdatei in Zeilen [ID, x, y, z, Punktcode] um."""
    lines = [_strip_bom(line) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    parsed = ParsedFile(delimiter=detect_delimiter(lines))
    if _is_esri_grid(lines):
        parsed.data_lines = sum(1 for line in lines if line.strip())
        parsed.skip_reason = "ESRI-ASCII-Raster (Höhenmodell), keine Messpunktdatei"
        return parsed
    whitespace = parsed.delimiter == " "

    # 1. Durchgang: Zeilen zerlegen und in Punkt-Kandidaten und verworfene Zeilen teilen
    candidates, rejected = [], []
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parsed.data_lines += 1
        if _is_comment(line):
            parsed.comment_lines.append(lineno)
            continue
        # Nur die Felder werden getrimmt, nicht die Zeile: Ein führender Tab steht
        # für eine leere Punktnummer und darf die Spalten nicht verschieben.
        parts = split_line(line, parsed.delimiter)
        while len(parts) > 5 and not parts[-1]:
            parts.pop()
        x = parse_number(parts[1]) if len(parts) > 1 else None
        y = parse_number(parts[2]) if len(parts) > 2 else None
        if x is None or y is None or (whitespace and not _whitespace_point(parts)):
            rejected.append((lineno, line, parts, not candidates))
        else:
            candidates.append((lineno, parts, x, y))

    # Ist Spalte 4 eine Höhe oder schon der Punktcode (z. B. ID;x;y;Code;;)?
    # Zuerst entscheidet ein eindeutiger Spaltenname der Kopfzeile, sonst die Mehrheit der Werte
    # (Platzhalter wie '-' oder 'n.v.' zählen dabei nicht mit).
    header_kind = ""
    for _, _, parts, before_first_point in reversed(rejected):
        if before_first_point and len(parts) > 3:
            header_kind = _column_kind(parts[3])
            break
    fourth = [parts[3] for _, parts, _, _ in candidates
              if len(parts) > 3 and parts[3] and not is_missing_height(parts[3])]
    numeric = sum(1 for value in fourth if format_z_value(value) is not None)
    if header_kind:
        has_height_column = header_kind == "height"
    else:
        has_height_column = 2 * numeric >= len(fourth)  # ohne Werte: Höhenspalte mit fehlenden Höhen

    # 2. Durchgang: Punkte übernehmen
    for lineno, parts, x, y in candidates:
        z_raw = parts[3] if len(parts) > 3 else ""
        code = parts[4] if len(parts) > 4 else ""
        extra = len(parts) > 5
        if not has_height_column:
            # Spalte 4 ist der Punktcode – auch wenn er nur aus Ziffern besteht
            if whitespace:
                z, code = "", " ".join(parts[3:])
            else:
                extra = extra or bool(code)
                z, code = "", z_raw
        elif is_missing_height(z_raw):
            z = ""  # Platzhalter für eine fehlende Höhe, der Code steht in Spalte 5
        else:
            z = format_z_value(z_raw, round_z, fixed_z_decimals)
            if z is None:
                if whitespace or not has_height_column:
                    # ID x y Code – der Code darf Leerzeichen enthalten
                    code, z = " ".join(parts[3:]), ""
                else:
                    code, z = code or z_raw, ""  # den Text nicht verlieren
                    parsed.bad_height_lines.append(lineno)
        if not z and lineno not in parsed.bad_height_lines:
            parsed.no_height_lines.append(lineno)
        if extra:
            parsed.extra_column_lines.append(lineno)
        if not parts[0]:
            parsed.empty_id_lines.append(lineno)
        # Punkt-ID bleibt Text (wichtig für 3.10, 0010 etc.)
        parsed.rows.append([parts[0], format_number(x), format_number(y), z, code])
        parsed.row_lines.append(lineno)

    # Verworfene Zeilen: Kopf-/Textzeile, verunglückte Datenzeile oder anderes Trennzeichen?
    typical = Counter(len(parts) for _, parts, _, _ in candidates).most_common(1)[0][0] if candidates else 0
    for lineno, line, parts, before_first_point in rejected:
        if candidates and not whitespace and _other_delimiter_point(line, parsed.delimiter):
            parsed.delimiter_lines.append(lineno)
            continue
        if before_first_point:
            looks_like_data = (len(parts) == typical and bool(parts[0])
                               and all(_mostly_numeric(p) for p in parts[1:3]))
        else:
            looks_like_data = bool(parts[0]) and any(_mostly_numeric(p) for p in parts[1:])
        (parsed.invalid_lines if looks_like_data else parsed.text_lines).append(lineno)

    if _looks_like_xyz_grid(parsed.rows):
        parsed.skip_reason = "x-y-z-Datei ohne Punktnummern (z. B. Geländemodell), keine Messpunktdatei"
        parsed.rows.clear()
        parsed.row_lines.clear()
        return parsed

    # Ausreißer: Punkte weit weg vom Großteil (Tippfehler, Metazeilen wie „Datum;28;10;2026“)
    if len(parsed.rows) >= 4:
        xs = sorted(float(row[1]) for row in parsed.rows)
        ys = sorted(float(row[2]) for row in parsed.rows)
        mid_x, mid_y = xs[len(xs) // 2], ys[len(ys) // 2]
        far = [lineno for row, lineno in zip(parsed.rows, parsed.row_lines)
               if math.hypot(float(row[1]) - mid_x, float(row[2]) - mid_y) > OUTLIER_DISTANCE]
        if 4 * len(far) > len(parsed.rows):
            parsed.multiple_areas = True  # keine Ausreißer, sondern mehrere Gebiete
        else:
            parsed.outlier_lines = far
    return parsed


def read_survey_file(path, round_z: bool = True, fixed_z_decimals: bool = True) -> ParsedFile:
    """Liest eine Rohdatei von der Festplatte (Kodierung wird automatisch erkannt)."""
    text, encoding = decode_bytes(Path(path).read_bytes())
    parsed = parse_survey_text(text, round_z, fixed_z_decimals)
    parsed.encoding = encoding
    return parsed


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _line_numbers(numbers: list, limit: int = 8) -> str:
    shown = ", ".join(str(n) for n in numbers[:limit])
    more = " …" if len(numbers) > limit else ""
    return f"{'Zeile' if len(numbers) == 1 else 'Zeilen'} {shown}{more}"


def describe_parsed(parsed: ParsedFile) -> tuple[list[str], list[str]]:
    """Fasst übersprungene und auffällige Zeilen als (Warnungen, Hinweise) zusammen."""
    warnings, infos = [], []
    if parsed.invalid_lines:
        warnings.append(
            f"{_plural(len(parsed.invalid_lines), 'Zeile', 'Zeilen')} ohne gültige x/y-Koordinaten "
            f"übersprungen ({_line_numbers(parsed.invalid_lines)})"
        )
    if parsed.bad_height_lines:
        warnings.append(
            f"{_plural(len(parsed.bad_height_lines), 'ungültige Höhe', 'ungültige Höhen')} leer gelassen "
            f"({_line_numbers(parsed.bad_height_lines)})"
        )
    if parsed.empty_id_lines:
        warnings.append(
            f"{_plural(len(parsed.empty_id_lines), 'Punkt', 'Punkte')} ohne Punktnummer "
            f"({_line_numbers(parsed.empty_id_lines)})"
        )
    if parsed.delimiter_lines:
        warnings.append(
            f"{_plural(len(parsed.delimiter_lines), 'Zeile', 'Zeilen')} mit abweichendem Trennzeichen nicht "
            f"übernommen – Datei zusammengefügt? ({_line_numbers(parsed.delimiter_lines)})"
        )
    if parsed.outlier_lines:
        warnings.append(
            f"{_plural(len(parsed.outlier_lines), 'Punkt liegt', 'Punkte liegen')} mehr als "
            f"{OUTLIER_DISTANCE // 1000} km vom Großteil der Punkte entfernt – Tippfehler oder "
            f"Metazeile? ({_line_numbers(parsed.outlier_lines)})"
        )
    if parsed.multiple_areas:
        infos.append(
            f"Die Punkte liegen in mehreren, mehr als {OUTLIER_DISTANCE // 1000} km auseinanderliegenden Gebieten."
        )
    duplicates = [pid for pid, n in Counter(row[0] for row in parsed.rows if row[0]).items() if n > 1]
    if duplicates:
        infos.append(
            f"{_plural(len(duplicates), 'Punktnummer', 'Punktnummern')} mehrfach vergeben, "
            f"z. B. {', '.join(duplicates[:5])}"
        )
    if parsed.no_height_lines:
        infos.append(f"{_plural(len(parsed.no_height_lines), 'Punkt', 'Punkte')} ohne Höhe")
    if parsed.text_lines:
        infos.append(
            f"{_plural(len(parsed.text_lines), 'Kopf- oder Textzeile', 'Kopf- oder Textzeilen')} übersprungen "
            f"({_line_numbers(parsed.text_lines)})"
        )
    if parsed.comment_lines:
        infos.append(
            f"{_plural(len(parsed.comment_lines), 'Kommentarzeile', 'Kommentarzeilen')} übersprungen "
            f"({_line_numbers(parsed.comment_lines)})"
        )
    if parsed.extra_column_lines:
        infos.append(
            f"{_plural(len(parsed.extra_column_lines), 'Zeile', 'Zeilen')} mit weiteren Spalten nach dem "
            "Punktcode – diese wurden nicht übernommen"
        )
    return warnings, infos


# =====================================================================
# KERNLOGIK: KOORDINATENSYSTEM PRÜFEN
# =====================================================================

def crs_display(code: str) -> str:
    """Anzeigetext für die KBS-Auswahl."""
    for choice, label in CRS_CHOICES:
        if choice == code:
            return f"{choice} – {label}" if choice else label
    return code or CRS_NONE_LABEL


def parse_crs_choice(text: str) -> Optional[str]:
    """'EPSG:25832 – …' → 'EPSG:25832'; 'Ohne KBS …' → ''; ungültige Eingabe → None."""
    value = text.strip()
    if not value or value.lower().startswith("ohne"):
        return ""
    match = re.match(r"(?i)epsg\s*:\s*(\d{4,6})(?!\d)", value)
    return f"EPSG:{match.group(1)}" if match else None


def _de_number(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def guess_crs(x: float, y: float) -> Optional[str]:
    """Rät anhand eines typischen Punkts, welches KBS zu den Koordinaten passen könnte."""
    if 3_500_000 <= y <= 8_000_000:
        if 32_100_000 <= x <= 32_900_000:
            return "Die Rechtswerte tragen die Zonenkennung 32 – passend wäre EPSG:4647."
        if 33_100_000 <= x <= 33_900_000:
            return "Die Rechtswerte tragen die Zonenkennung 33 – passend wäre EPSG:5650."
        if 100_000 <= x <= 900_000:
            return "Die Werte sehen nach UTM ohne Zonenkennung aus (EPSG:25832 oder EPSG:25833)."
        for zone in (2, 3, 4, 5):
            if zone * 1_000_000 <= x < (zone + 1) * 1_000_000 and 5_000_000 <= y <= 6_200_000:
                return f"Die Werte sehen nach Gauß-Krüger Zone {zone} aus (EPSG:{31464 + zone})."
    if 3_500_000 <= x <= 8_000_000 and 0 <= y < 1_000_000:
        return "Möglicherweise sind Rechts- und Hochwert vertauscht."
    if abs(x) < 100_000 and abs(y) < 100_000:
        return f"Die Werte sehen nach einem lokalen Messnetz aus – dann „{CRS_NONE_LABEL}“ wählen."
    return None


def crs_plausibility(crs: str, rows: list) -> Optional[str]:
    """Warnt, wenn die Koordinaten der Datei nicht zum gewählten KBS passen.

    Geprüft wird der typische Punkt (Median); einzelne Ausreißer meldet die Ausreißerprüfung.
    """
    limits = CRS_RANGES.get(crs.upper()) if crs else None
    if not limits or not rows:
        return None
    x_min, x_max, y_min, y_max = limits
    xs = sorted(float(row[1]) for row in rows)
    ys = sorted(float(row[2]) for row in rows)
    mid_x, mid_y = xs[len(xs) // 2], ys[len(ys) // 2]
    if x_min <= mid_x <= x_max and y_min <= mid_y <= y_max:
        return None
    message = (
        f"Die Koordinaten passen nicht zu {crs} (erwartet: Rechtswert {_de_number(x_min)}–{_de_number(x_max)}, "
        f"Hochwert {_de_number(y_min)}–{_de_number(y_max)}; typischer Punkt der Datei: "
        f"{_de_number(mid_x)} / {_de_number(mid_y)}). Bitte das Koordinatensystem prüfen."
    )
    hint = guess_crs(mid_x, mid_y)
    return f"{message} {hint}" if hint else message


# =====================================================================
# KERNLOGIK: AUSGABE (CSV, CSVT, VRT)
# =====================================================================

def parse_header(text: str) -> list[str]:
    """Zerlegt den Kopfzeilentext (Trenner ',' oder ';') und prüft ihn; wirft ValueError."""
    raw = text.strip()
    separator = ";" if ";" in raw and "," not in raw else ","
    names = [name.strip() for name in raw.split(separator)]
    if len(names) != 5 or not all(names):
        raise ValueError("Die Kopfzeile braucht genau 5 Spaltennamen, z. B. ID,x,y,z,Punktcode.")
    if len({name.casefold() for name in names}) != 5:
        raise ValueError("Die Spaltennamen der Kopfzeile müssen verschieden sein.")
    if any(ch in name for name in names for ch in '"\t'):
        raise ValueError("Die Spaltennamen dürfen keine Anführungszeichen oder Tabulatoren enthalten.")
    return names


def build_csv_text(rows: list, header_cols: Optional[list] = None) -> str:
    """Erzeugt den Inhalt der QGIS-CSV (kommagetrennt, Werte bei Bedarf in Anführungszeichen)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", quoting=csv.QUOTE_MINIMAL)
    if header_cols:
        writer.writerow(header_cols)
    writer.writerows(rows)
    return buffer.getvalue()


def _error_for(exc: OSError, path: Path) -> OSError:
    """Gleiche Fehlerart, aber mit der Zieldatei statt des Temp-Namens in der Meldung."""
    return type(exc)(exc.errno, exc.strerror or str(exc), str(path))


def _remove_quietly(path: Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def write_text_atomic(path: Path, text: str) -> None:
    """Schreibt den Inhalt zuerst vollständig in eine Temp-Datei und ersetzt dann das Ziel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Eigener Temp-Name statt tempfile.mkstemp: mkstemp wiederholt unter Windows bei
    # fehlenden Schreibrechten praktisch endlos, open(..., "x") meldet den Fehler sofort.
    for _ in range(50):
        tmp = path.with_name(f".{path.stem}.{secrets.token_hex(4)}.tmp")
        try:
            handle = open(tmp, "x", encoding="utf-8", newline="")
            break
        except FileExistsError:
            continue
        except OSError as exc:
            raise _error_for(exc, path) from None
    else:
        raise FileExistsError(errno.EEXIST, "Keine freie Temp-Datei möglich", str(path))

    try:
        with handle:
            handle.write(text)
        try:
            os.replace(tmp, path)
        except PermissionError:
            # Eine in QGIS geladene Datei lässt sich unter Windows nicht ersetzen,
            # wohl aber überschreiben – der neue Inhalt liegt bereits vollständig vor.
            if not path.exists():
                raise
            with open(path, "w", encoding="utf-8", newline="") as target:
                target.write(text)
            _remove_quietly(tmp)
    except OSError as exc:
        _remove_quietly(tmp)
        raise _error_for(exc, path) from None
    except BaseException:
        _remove_quietly(tmp)
        raise


def _vrt_layer_xml(layer_name: str, csv_ref: str, header_cols: Optional[list], crs: str,
                   has_z: bool, indent: str) -> list[str]:
    names = list(header_cols) if header_cols else [f"field_{i}" for i in range(1, 6)]
    inner = indent + "  "
    lines = [
        f"{indent}<OGRVRTLayer name={quoteattr(layer_name)}>",
        f'{inner}<SrcDataSource relativeToVRT="1">{escape(csv_ref)}</SrcDataSource>',
    ]
    if not header_cols:
        lines.append(f'{inner}<OpenOptions><OOI key="HEADERS">NO</OOI></OpenOptions>')
    lines.append(f"{inner}<SrcLayer>{escape(Path(csv_ref).stem)}</SrcLayer>")
    lines.append(f"{inner}<GeometryType>{'wkbPoint25D' if has_z else 'wkbPoint'}</GeometryType>")
    if crs:
        lines.append(f"{inner}<LayerSRS>{escape(crs)}</LayerSRS>")
    z_attr = f" z={quoteattr(names[3])}" if has_z else ""
    lines.append(
        f'{inner}<GeometryField encoding="PointFromColumns" x={quoteattr(names[1])} '
        f"y={quoteattr(names[2])}{z_attr}/>"
    )
    for name, field_type in zip(names, FIELD_TYPES):
        lines.append(f'{inner}<Field name={quoteattr(name)} type="{field_type}"/>')
    lines.append(f"{indent}</OGRVRTLayer>")
    return lines


def build_vrt_text(csv_path: Path, header_cols: Optional[list], crs: str, has_z: bool = True) -> str:
    """Erzeugt eine .vrt-Datei: In QGIS hineinziehen ergibt sofort einen Punktlayer mit KBS."""
    lines = ["<OGRVRTDataSource>"]
    lines += _vrt_layer_xml(csv_path.stem, csv_path.name, header_cols, crs, has_z, "  ")
    lines += ["</OGRVRTDataSource>", ""]
    return "\n".join(lines)


def union_source_field(header_cols: Optional[list]) -> str:
    """Name der Herkunftsspalte im Sammel-Layer, der keiner eigenen Spalte gleicht."""
    taken = {name.casefold() for name in header_cols or []}
    for candidate in ("Quelle", "Quelldatei", "Herkunft"):
        if candidate.casefold() not in taken:
            return candidate
    return "Quelle_Datei"


def build_union_vrt_text(entries: list, union_path: Path, header_cols: Optional[list], crs: str) -> str:
    """Sammel-Layer über mehrere CSV-Dateien; eine Herkunftsspalte nennt die Quelle.

    entries: Liste von (csv_pfad, has_z)
    """
    any_z = any(has_z for _, has_z in entries)
    lines = [
        "<OGRVRTDataSource>",
        f"  <OGRVRTUnionLayer name={quoteattr(union_path.stem)}>",
        f"    <SourceLayerFieldName>{escape(union_source_field(header_cols))}</SourceLayerFieldName>",
        f"    <GeometryType>{'wkbPoint25D' if any_z else 'wkbPoint'}</GeometryType>",
    ]
    if crs:
        lines.append(f"    <LayerSRS>{escape(crs)}</LayerSRS>")
    used_names = set()
    for csv_path, has_z in entries:
        name = csv_path.stem
        if name.lower() in used_names:
            name = f"{csv_path.parent.name}_{csv_path.stem}"
        number = 2
        base_name = name
        while name.lower() in used_names:
            name = f"{base_name}_{number}"
            number += 1
        used_names.add(name.lower())
        reference = Path(os.path.relpath(str(csv_path), str(union_path.parent))).as_posix()
        lines += _vrt_layer_xml(name, reference, header_cols, crs, has_z, "    ")
    lines += ["  </OGRVRTUnionLayer>", "</OGRVRTDataSource>", ""]
    return "\n".join(lines)


class ConversionError(Exception):
    """Fehler mit fertiger, verständlicher Meldung."""


def friendly_error(exc: BaseException) -> str:
    """Übersetzt typische Dateifehler in verständliche Meldungen."""
    if isinstance(exc, ConversionError):
        return str(exc)
    if isinstance(exc, PermissionError):
        name = Path(exc.filename2 or exc.filename or "").name or "die Datei"
        return (
            f"Kein Schreibzugriff auf {name} – ist die Datei in einem anderen Programm (z. B. Excel) "
            "geöffnet, schreibgeschützt, oder fehlen Schreibrechte im Ordner?"
        )
    if isinstance(exc, FileNotFoundError):
        return f"Datei oder Ordner nicht gefunden: {exc.filename}"
    if isinstance(exc, OSError):
        target = f" ({exc.filename})" if exc.filename else ""
        return f"{exc.strerror or exc}{target}"
    return f"{type(exc).__name__}: {exc}"


@dataclass
class ConvertOptions:
    header_cols: Optional[list] = None  # None = keine Kopfzeile schreiben
    round_z: bool = True
    fixed_z_decimals: bool = True
    create_csvt: bool = True
    create_vrt: bool = False
    crs: str = DEFAULT_CRS


@dataclass
class ConversionResult:
    source: Path
    planned_target: Optional[Path] = None
    parsed: Optional[ParsedFile] = None
    written: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    infos: list = field(default_factory=list)
    error: str = ""
    skipped: bool = False

    @property
    def points(self) -> int:
        return len(self.parsed.rows) if self.parsed else 0

    @property
    def target(self) -> Optional[Path]:
        return self.written[0] if self.written else None

    @property
    def has_z(self) -> bool:
        return bool(self.parsed) and any(row[3] for row in self.parsed.rows)

    @property
    def level(self) -> str:
        if self.error:
            return "error"
        if self.skipped:
            return "skipped"
        if self.warnings or not self.points:
            return "warn"
        return "ok"

    def report_lines(self) -> list[str]:
        if self.error:
            return [f"Fehler: {self.error}"]
        if self.skipped:
            return ["Übersprungen: Die Zieldatei war bereits vorhanden."]
        lines = []
        if self.parsed:
            lines.append(
                f"Gelesen als {self.parsed.encoding}, Trennzeichen "
                f"{DELIMITER_NAMES.get(self.parsed.delimiter, self.parsed.delimiter)}"
            )
            lines.append(f"Übernommen: {_plural(self.points, 'Messpunkt', 'Messpunkte')}")
        lines += [f"⚠ {text}" for text in self.warnings]
        lines += [f"· {text}" for text in self.infos]
        if self.written:
            lines.append("Geschrieben: " + ", ".join(path.name for path in self.written))
        return lines


def _vrt_points_to(vrt_path: Path, csv_name: str) -> bool:
    """True, wenn die .vrt eine Layerdatei dieses Programms für die genannte CSV ist."""
    try:
        with open(vrt_path, encoding="utf-8", errors="replace") as handle:
            head = handle.read(4096)
    except OSError:
        return False
    return f">{escape(csv_name)}</SrcDataSource>" in head


def convert_file(src: Path, dst: Path, options: ConvertOptions) -> ConversionResult:
    """Konvertiert eine Rohdatei; Fehler landen im Ergebnis statt als Ausnahme."""
    result = ConversionResult(source=src, planned_target=dst)
    try:
        parsed = read_survey_file(src, options.round_z, options.fixed_z_decimals)
        result.parsed = parsed
        if parsed.skip_reason:
            result.warnings = [f"Keine Messpunkte: {parsed.skip_reason} – es wurde keine Datei geschrieben."]
            return result
        result.warnings, result.infos = describe_parsed(parsed)
        if not parsed.rows:
            result.warnings.insert(0, "Keine Messpunkte erkannt – es wurde keine Datei geschrieben.")
            return result
        # Letzte Sicherung: Über Netzlaufwerk, SUBST oder Junction kann ein anders
        # geschriebener Zielpfad auf die Quelldatei selbst zeigen.
        if dst.exists() and os.path.samefile(src, dst):
            raise ConversionError("Die Zieldatei ist die Quelldatei selbst – zum Schutz der Rohdaten abgebrochen.")

        write_text_atomic(dst, build_csv_text(parsed.rows, options.header_cols))
        result.written.append(dst)
        csvt_path = dst.with_suffix(".csvt")
        if options.create_csvt:
            # Schützt Punkt-IDs wie 3.10 oder 0010 beim Import über "Getrennte Texte"
            write_text_atomic(csvt_path, CSVT_LINE + "\n")
            result.written.append(csvt_path)
        elif _is_own_csvt(csvt_path):
            _remove_quietly(csvt_path)  # sonst erzwingt QGIS weiter die alten Feldtypen
            result.infos.append(f"Veraltete Typdatei {csvt_path.name} entfernt.")
        vrt_path = dst.with_suffix(".vrt")
        if options.create_vrt:
            write_text_atomic(vrt_path, build_vrt_text(dst, options.header_cols, options.crs, result.has_z))
            result.written.append(vrt_path)
            check = crs_plausibility(options.crs, parsed.rows)
            if check:
                result.warnings.append(check)
            if result.has_z and parsed.no_height_lines:
                result.infos.append("Im .vrt-Layer erhalten Punkte ohne Höhe den Z-Wert 0 (das Attribut z bleibt leer).")
        elif _vrt_points_to(vrt_path, dst.name):
            result.infos.append(
                f"Ältere Layerdatei {vrt_path.name} liegt noch daneben und passt evtl. nicht mehr – bei Bedarf löschen."
            )
    except Exception as exc:  # jede Datei darf einzeln scheitern, der Lauf geht weiter
        result.error = friendly_error(exc)
    return result


def output_matches_header(path: Path, header_cols: Optional[list]) -> bool:
    """Passt eine vorhandene Ausgabe-CSV zur aktuellen Kopfzeilen-Einstellung (für den Sammel-Layer)?"""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:
            first = next(csv.reader(handle), None)
    except OSError:
        return False
    if not first:
        return False
    first = [_strip_bom(value).strip() for value in first]
    if header_cols:
        return first == list(header_cols)
    # ohne Kopfzeile muss schon die erste Zeile ein Punkt sein
    return len(first) >= 3 and parse_number(first[1]) is not None and parse_number(first[2]) is not None


def csv_has_heights(path: Path, has_header: bool) -> bool:
    """Prüft, ob eine vorhandene Ausgabe-CSV mindestens eine Höhe enthält."""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            if has_header:
                next(reader, None)
            return any(len(row) > 3 and row[3].strip() for row in reader)
    except OSError:
        return True


def write_union_vrt(union_path: Path, results: list, options: ConvertOptions, existing: tuple = ()) -> None:
    """Schreibt den Sammel-Layer; 'existing' sind vorhandene Ausgaben übersprungener Dateien."""
    entries = [(result.target, result.has_z) for result in results if result.target is not None]
    entries += [(path, csv_has_heights(path, bool(options.header_cols))) for path in existing]
    write_text_atomic(union_path, build_union_vrt_text(entries, union_path, options.header_cols, options.crs))


# =====================================================================
# KERNLOGIK: DATEINAMEN, ZIELPFADE & ORDNER-SCAN
# =====================================================================

_SUFFIX_RE = re.compile(r"[\w\-]*")
_COPY_MARK_RE = re.compile(r"\s*(?:\((\d+)\)|-\s*(?:Kopie|Copy))\s*$", re.IGNORECASE)
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}


def _strip_copy_marks(stem: str) -> tuple[str, Optional[int], bool]:
    """Entfernt Kopie-Zusätze wie (2) oder '- Kopie' am Ende → (Rest, Kopienummer, war_Kopie)."""
    number, is_copy = None, False
    while True:
        match = _COPY_MARK_RE.search(stem)
        if not match or match.start() == 0:
            break
        is_copy = True
        if match.group(1) and number is None:
            number = int(match.group(1))
        stem = stem[: match.start()]
    return stem, number, is_copy


def sanitize_suffix(suffix: str) -> str:
    """Macht ein Suffix dateinamentauglich (keine Pfadtrenner, Doppelpunkte o. Ä.)."""
    return re.sub(r"[^\w\-]", "_", suffix.strip())


def clean_stem(stem: str, sanitize: bool = True) -> str:
    """Bereinigt den Dateinamen-Stamm für QGIS (entfernt (1), (2), Sonderzeichen etc.)."""
    cleaned = stem.strip()
    if sanitize:
        cleaned = _strip_copy_marks(cleaned)[0]
        # Punkte, Leerzeichen und Sonderzeichen durch Unterstrich ersetzen
        cleaned = re.sub(r"[^\w\-]", "_", cleaned)
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "messpunkte"


def build_name(base: str, suffix: str, number: Optional[int] = None) -> str:
    """Setzt den Zieldateinamen zusammen; eine Nummer steht vor dem Suffix (Name_2_QGIS.csv)."""
    if suffix and len(base) > len(suffix) and base.lower().endswith(suffix.lower()):
        base = base[: -len(suffix)]
    stem = f"{base}_{number}{suffix}" if number else f"{base}{suffix}"
    if stem.upper() in _RESERVED_NAMES:
        stem += "_"
    return f"{stem}.csv"


def clean_filename(stem: str, suffix: str = DEFAULT_SUFFIX, sanitize: bool = True) -> str:
    """Bereinigt einen Dateinamen für QGIS und hängt das Suffix an (z. B. Messung_QGIS.csv)."""
    return build_name(clean_stem(stem, sanitize), sanitize_suffix(suffix))


def _path_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _is_within(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


@dataclass
class PlannedTarget:
    source: Path
    target: Path
    renamed: bool = False  # nummeriert, weil der Name schon belegt war
    reason: str = ""  # Grund für die Nummerierung
    existing: list = field(default_factory=list)  # vorhandene eigene Dateien, die ersetzt würden


def _first_line(path: Path) -> Optional[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return _strip_bom(handle.readline(512)).strip()
    except OSError:
        return None


def looks_like_own_output(path: Path, known_outputs=frozenset(), header_lines: tuple = (DEFAULT_HEADER,)) -> bool:
    """Erkennt eine frühere Ausgabe dieses Programms (nur solche dürfen ersetzt werden)."""
    if _path_key(path) in known_outputs:
        return True
    if _is_own_csvt(path.with_suffix(".csvt")) or _vrt_points_to(path.with_suffix(".vrt"), path.name):
        return True
    return _first_line(path) in header_lines


def _real_key_function():
    """Pfadschlüssel, der Netzlaufwerk-, SUBST- und Junction-Schreibweisen gleichsetzt."""
    cache = {}

    def key(path: Path) -> str:
        folder = str(path.parent)
        real = cache.get(folder)
        if real is None:
            real = cache[folder] = os.path.realpath(folder)
        return os.path.normcase(os.path.join(real, path.name))

    return key


def _target_dir(src: Path, root: Optional[Path], out_dir: Optional[Path]) -> Path:
    if out_dir is None:
        return src.parent
    if root is not None:
        try:
            return out_dir / src.parent.relative_to(root)  # Unterordner-Struktur übernehmen
        except ValueError:
            pass
    return out_dir


def plan_targets(sources: list, roots: Optional[dict] = None, suffix: str = DEFAULT_SUFFIX,
                 sanitize: bool = True, out_dir: Optional[Path] = None,
                 companion_exts: tuple = (".csvt",), known_outputs=frozenset(),
                 header_lines: tuple = (DEFAULT_HEADER,)) -> list:
    """Berechnet eindeutige Zielpfade für alle Quellen.

    - Keine Quelldatei wird je zum Ziel – auch nicht über einen anders geschriebenen Pfad.
    - Fremde Dateien gleichen Namens (keine Ausgabe dieses Programms) werden nie ersetzt;
      das Ziel wird dann nummeriert.
    - Bilden mehrere Quellen denselben Namen, behält das Original den Namen;
      Kopien bekommen ihre Kopienummer bzw. die nächste freie Nummer.
    - 'existing' nennt vorhandene eigene Ausgaben, die beim Schreiben ersetzt würden.
    """
    roots = roots or {}
    suffix = sanitize_suffix(suffix)
    key = _real_key_function()
    source_keys = {key(src) for src in sources}
    taken = set(source_keys)
    entries = []
    for index, src in enumerate(sources):
        _, copy_number, is_copy = _strip_copy_marks(src.stem.strip())
        entries.append((is_copy, index, src, copy_number))

    def blocked(target: Path) -> str:
        target_key = key(target)
        if target_key in source_keys:
            return "Name einer Quelldatei"
        if target_key in taken:
            return "Namenskonflikt"
        if target.exists() and not looks_like_own_output(target, known_outputs, header_lines):
            return "vorhandene Datei ist nicht als eigene Ausgabe erkennbar"
        for ext in companion_exts:
            companion = target.with_suffix(ext)
            own = _is_own_csvt(companion) if ext == ".csvt" else _vrt_points_to(companion, target.name)
            if companion.exists() and not own and _path_key(companion) not in known_outputs:
                return f"fremde {ext}-Datei gleichen Namens vorhanden"
        return ""

    plans = [None] * len(sources)
    for is_copy, index, src, copy_number in sorted(entries, key=lambda e: (e[0], e[1])):
        target_dir = _target_dir(src, roots.get(src), out_dir)
        base = clean_stem(src.stem, sanitize)
        numbers = [None] + ([copy_number] if sanitize and copy_number else [])
        reason = ""
        for number in numbers:
            target = target_dir / build_name(base, suffix, number)
            problem = blocked(target)
            if not problem:
                break
            reason = reason or problem
        else:
            number = 2
            while True:
                target = target_dir / build_name(base, suffix, number)
                if not blocked(target):
                    break
                number += 1
        taken.add(key(target))
        plans[index] = PlannedTarget(
            source=src,
            target=target,
            renamed=number is not None,
            reason=reason if number is not None else "",
            # Nur die eigene CSV zählt: eigene Begleitdateien werden mit ihr ersetzt
            existing=[target] if target.exists() else [],
        )
    return plans


def _is_own_union(path: Path) -> bool:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            head = handle.read(4096)
    except OSError:
        return False
    return "<OGRVRTUnionLayer" in head and "<SourceLayerFieldName>" in head


def union_vrt_path(plans: list, out_dir: Optional[Path], suffix: str) -> Path:
    """Ort des Sammel-Layers: fester Ausgabeordner oder gemeinsamer Oberordner der Ausgaben."""
    if out_dir is not None:
        base = out_dir
    else:
        try:
            base = Path(os.path.commonpath([str(plan.target.parent) for plan in plans]))
        except ValueError as exc:
            raise ValueError("Die Ausgaben liegen auf verschiedenen Laufwerken.") from exc
    taken = {_path_key(plan.target.with_suffix(".vrt")) for plan in plans}
    suffix = sanitize_suffix(suffix)
    path = base / f"{UNION_VRT_STEM}{suffix}.vrt"
    number = 2
    # Eigene Sammel-Layer werden aktualisiert, fremde Dateien gleichen Namens nie ersetzt
    while _path_key(path) in taken or (path.exists() and not _is_own_union(path)):
        path = base / f"{UNION_VRT_STEM}_{number}{suffix}.vrt"
        number += 1
    return path


def _is_hidden_entry(entry) -> bool:
    """Versteckte, System- und Sperrdateien (z. B. Excels ~$Messung.csv) auslassen."""
    if entry.name.startswith((".", "~$")):
        return True
    try:
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))


def _is_own_csvt(path: Path) -> bool:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip() == CSVT_LINE
    except OSError:
        return False


def _is_linked_folder(entry) -> bool:
    """Symlinks und Junctions nicht durchsuchen (sonst drohen Schleifen)."""
    if entry.is_symlink():
        return True
    try:
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    mount_point = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None)
    return mount_point is not None and getattr(info, "st_reparse_tag", 0) == mount_point


def scan_folder(folder: Path, recursive: bool = True, skip_suffixes: tuple = (DEFAULT_SUFFIX,),
                header_lines: tuple = (DEFAULT_HEADER,), skipped: Optional[list] = None) -> list:
    """Sucht Rohdateien in einem Ordner; frühere Ausgaben und versteckte Dateien bleiben außen vor.

    Als frühere Ausgabe ausgelassene Dateien werden an 'skipped' angehängt (falls angegeben).
    """
    skip = tuple(s.lower() for s in skip_suffixes if s)
    found = []
    pending = [Path(folder)]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as iterator:
                entries = list(iterator)
        except OSError:
            continue
        names = {entry.name.lower() for entry in entries}
        subfolders = []
        for entry in entries:
            if _is_hidden_entry(entry):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if recursive and not _is_linked_folder(entry):
                        subfolders.append(Path(entry.path))
                    continue
            except OSError:
                continue
            path = Path(entry.path)
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            stem = path.stem.lower()
            if (skip and stem.endswith(skip)) \
                    or (f"{stem}.csvt" in names and _is_own_csvt(path.with_suffix(".csvt"))) \
                    or (path.suffix.lower() == ".csv" and _first_line(path) in header_lines):
                # Ausgabe eines früheren Laufs (Suffix, eigene .csvt oder Kopfzeile im Zielformat)
                if skipped is not None:
                    skipped.append(path)
                continue
            found.append(path)
        pending.extend(sorted(subfolders, reverse=True))
    return found


def normalize_dir_input(text: str) -> Path:
    """Prüft das Eingabefeld für den Ausgabeordner; wirft ValueError mit Hinweis."""
    value = text.strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()  # nur ein umschließendes Paar (z. B. aus „Als Pfad kopieren“)
    if not value:
        raise ValueError("Bitte einen Ausgabeordner wählen oder die Option abwählen.")
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    if not path.is_absolute():
        raise ValueError("Der Ausgabeordner muss ein vollständiger Pfad sein, z. B. D:\\Grabung\\QGIS.")
    if path.exists() and not path.is_dir():
        raise ValueError("Als Ausgabeordner ist eine Datei angegeben.")
    return path


# =====================================================================
# EINSTELLUNGEN SPEICHERN
# =====================================================================

SETTING_DEFAULTS = {
    "theme": "dark",
    "recursive": True,
    "header": True,
    "header_text": DEFAULT_HEADER,
    "round_z": True,
    "fixed_z": True,
    "clean_name": True,
    "suffix": DEFAULT_SUFFIX,
    "create_csvt": True,
    "create_vrt": True,
    "crs": DEFAULT_CRS,
    "union_vrt": False,
    "use_custom_out": False,
    "custom_out_dir": "",
}


def settings_path() -> Path:
    override = os.environ.get("HAX_KONVERTER_EINSTELLUNGEN")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / APP_NAME / "einstellungen.json"


def load_settings() -> dict:
    values = dict(SETTING_DEFAULTS)
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return values
    if isinstance(data, dict):
        for key, default in SETTING_DEFAULTS.items():
            if isinstance(data.get(key), type(default)):
                values[key] = data[key]
    return values


def save_settings(values: dict) -> None:
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# =====================================================================
# GUI-ANWENDUNG
# =====================================================================

class HaXKonverterApp:
    THEMES = {
        "dark": {
            "bg": "#1e1e2e",
            "panel": "#262639",
            "fg": "#cdd6f4",
            "muted": "#9399b2",
            "accent": "#3b82f6",
            "accent_fg": "#ffffff",
            "paypal_bg": "#f59e0b",
            "paypal_fg": "#111827",
            "success": "#10b981",
            "entry_bg": "#313244",
            "tree_bg": "#181825",
            "tree_sel": "#3b82f6",
            "drop_bg": "#232336",
            "drop_border": "#4b5563",
            "border": "#45475a",
            "ok": "#a6e3a1",
            "warn": "#f9e2af",
            "error": "#f38ba8",
        },
        "light": {
            "bg": "#f3f4f6",
            "panel": "#ffffff",
            "fg": "#1f2937",
            "muted": "#6b7280",
            "accent": "#2563eb",
            "accent_fg": "#ffffff",
            "paypal_bg": "#fbbf24",
            "paypal_fg": "#111827",
            "success": "#059669",
            "entry_bg": "#f9fafb",
            "tree_bg": "#ffffff",
            "tree_sel": "#2563eb",
            "drop_bg": "#eff6ff",
            "drop_border": "#93c5fd",
            "border": "#d1d5db",
            "ok": "#047857",
            "warn": "#b45309",
            "error": "#dc2626",
        },
    }

    CONVERT_TEXT = "🚀 Alle gelisteten Dateien konvertieren  (Strg+Enter)"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION} – {APP_SUBTITLE}")
        self.scale = self._detect_ui_scale()

        settings = load_settings()
        self.theme_mode = settings["theme"] if settings["theme"] in self.THEMES else "dark"
        self.manual_files: set = set()
        self.source_folders: set = set()
        self.excluded: set = set()
        self.file_roots: dict = {}
        self.resolved_files: list = []
        self.planned: dict = {}
        self.results: dict = {}
        self.written_outputs: set = set()
        self._after_ids: dict = {}
        self.worker: Optional[threading.Thread] = None
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False
        self.closing = False
        self.run_state: dict = {}

        # Variablen für Optionen (Startwerte aus den gespeicherten Einstellungen)
        self.var_recursive = tk.BooleanVar(value=settings["recursive"])
        self.var_header = tk.BooleanVar(value=settings["header"])
        self.var_header_text = tk.StringVar(value=settings["header_text"])
        self.var_round_z = tk.BooleanVar(value=settings["round_z"])
        self.var_fixed_z = tk.BooleanVar(value=settings["fixed_z"])
        self.var_clean_name = tk.BooleanVar(value=settings["clean_name"])
        self.var_suffix = tk.StringVar(value=settings["suffix"])
        self.var_create_csvt = tk.BooleanVar(value=settings["create_csvt"])
        self.var_create_vrt = tk.BooleanVar(value=settings["create_vrt"])
        self.var_crs = tk.StringVar(value=crs_display(settings["crs"]))
        self.var_union_vrt = tk.BooleanVar(value=settings["union_vrt"])
        self.var_use_custom_out = tk.BooleanVar(value=settings["use_custom_out"])
        self.var_custom_out_dir = tk.StringVar(value=settings["custom_out_dir"])

        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.row_height = tkfont.nametofont("TkDefaultFont").metrics("linespace") + self.px(8)

        self._build_ui()
        self._apply_theme()
        self._setup_drag_and_drop()
        self._bind_shortcuts()
        self._update_option_states()
        self._validate_options()
        self._set_initial_geometry()

        # Live-Aktualisierung (entprellt, damit Tippen flüssig bleibt)
        # Suffix und Kopfzeile bestimmen, woran frühere Ausgaben erkannt werden → neu einlesen
        for var in (self.var_suffix, self.var_header, self.var_header_text):
            var.trace_add("write", lambda *_: self._on_option_change(rescan=True))
        for var in (self.var_clean_name, self.var_use_custom_out, self.var_custom_out_dir,
                    self.var_create_csvt, self.var_create_vrt):
            var.trace_add("write", lambda *_: self._on_option_change())
        for var in (self.var_round_z, self.var_crs, self.var_union_vrt):
            var.trace_add("write", lambda *_: self._on_option_change(refresh=False))
        self.var_recursive.trace_add("write", lambda *_: self._debounce("rebuild", 50, self.rebuild_file_list))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.report_callback_exception = self._report_callback_exception
        self.root.after(50, lambda: self._set_titlebar_theme(self.root))

    # -----------------------------------------------------------------
    # HILFSFUNKTIONEN FÜR SKALIERUNG & ENTPRELLEN
    # -----------------------------------------------------------------
    def _detect_ui_scale(self) -> float:
        try:
            return max(1.0, float(self.root.tk.call("tk", "scaling")) / (96 / 72))
        except (tk.TclError, ValueError):
            return 1.0

    def px(self, value: float) -> int:
        """Rechnet Pixelangaben für hohe Bildschirmskalierung (125 %, 150 %, …) um."""
        return int(round(value * self.scale))

    def _debounce(self, key: str, delay_ms: int, func):
        after_id = self._after_ids.pop(key, None)
        if after_id:
            self.root.after_cancel(after_id)

        def run():
            self._after_ids.pop(key, None)
            func()

        self._after_ids[key] = self.root.after(delay_ms, run)

    def _set_initial_geometry(self):
        """Fenstergröße aus dem tatsächlichen Platzbedarf ableiten (Liste mind. 4 Zeilen sichtbar)."""
        self.root.update_idletasks()
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        needed_w = self.root.winfo_reqwidth()
        fixed_h = self.root.winfo_reqheight() - self.list_frame.winfo_reqheight()
        list_min = self.px(40) + 4 * self.row_height
        list_nice = self.px(40) + 12 * self.row_height
        min_w = min(needed_w, screen_w)
        min_h = min(fixed_h + list_min, int(screen_h * 0.9))
        width = min(max(needed_w, self.px(1020)), int(screen_w * 0.95))
        height = max(min(fixed_h + list_nice, int(screen_h * 0.88)), min_h)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min_w, min_h)

    # -----------------------------------------------------------------
    # UI AUFBAUEN
    # -----------------------------------------------------------------
    def _build_ui(self):
        px = self.px

        # 1. Kopfzeile mit Titel, Theme-Switch, Info/Lizenz & PayPal-Like-Button
        self.header_frame = ttk.Frame(self.root, padding=(px(14), px(10)))
        self.header_frame.pack(side=tk.TOP, fill=tk.X)

        title_box = ttk.Frame(self.header_frame)
        title_box.pack(side=tk.LEFT)
        ttk.Label(title_box, text=APP_NAME, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(title_box, text=APP_SUBTITLE, style="Muted.TLabel").pack(anchor=tk.W)

        self.btn_paypal = tk.Button(
            self.header_frame,
            text="☕ Like / PayPal",
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=px(10),
            pady=px(3),
            cursor="hand2",
            command=self.open_paypal,
        )
        self.btn_paypal.pack(side=tk.RIGHT, padx=(px(6), 0))

        self.btn_info = ttk.Button(self.header_frame, text="ℹ Info & Lizenz", command=self.show_info_dialog)
        self.btn_info.pack(side=tk.RIGHT, padx=(px(6), 0))

        self.btn_theme = ttk.Button(self.header_frame, text=self._theme_button_text(), command=self.toggle_theme)
        self.btn_theme.pack(side=tk.RIGHT)

        # 2. Drag & Drop Zone + Auswahl-Buttons
        top_frame = ttk.Frame(self.root, padding=(px(14), px(4)))
        top_frame.pack(side=tk.TOP, fill=tk.X)

        self.drop_zone = tk.Label(
            top_frame,
            text=self._drop_zone_text(bool(DND_BACKEND)),
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT,
            padx=px(12),
            pady=px(10),
            cursor="hand2",
        )
        self.drop_zone.pack(fill=tk.X, pady=(0, px(8)))
        self.drop_zone.bind("<Button-1>", lambda e: self.add_files_dialog())

        btn_bar = ttk.Frame(top_frame)
        btn_bar.pack(fill=tk.X)
        self.btn_add_files = ttk.Button(btn_bar, text="📄 Dateien wählen...", command=self.add_files_dialog)
        self.btn_add_files.pack(side=tk.LEFT, padx=(0, px(6)))
        self.btn_add_folder = ttk.Button(btn_bar, text="📁 Ordner wählen...", command=self.add_folder_dialog)
        self.btn_add_folder.pack(side=tk.LEFT, padx=(0, px(12)))
        self.chk_recursive = ttk.Checkbutton(
            btn_bar, text="Unterordner mit einbeziehen (rekursiv)", variable=self.var_recursive
        )
        self.chk_recursive.pack(side=tk.LEFT)
        self.btn_clear = ttk.Button(btn_bar, text="🧹 Liste leeren", command=self.clear_list)
        self.btn_clear.pack(side=tk.RIGHT)
        self.btn_remove = ttk.Button(btn_bar, text="➖ Auswahl entfernen", command=self.remove_selected)
        self.btn_remove.pack(side=tk.RIGHT, padx=(0, px(6)))

        # 3. Einstellungs-Panel
        self.opts_frame = ttk.LabelFrame(
            self.root, text=" Konvertierungs- & Ausgabe-Optionen ", padding=(px(12), px(8))
        )
        self.opts_frame.pack(side=tk.TOP, fill=tk.X, padx=px(14), pady=px(6))

        # Alle Options-Widgets werden während einer Konvertierung gesperrt
        self.option_widgets = []

        def option(widget):
            self.option_widgets.append(widget)
            return widget

        # Zeile 1: Kopfzeile & Z-Rundung
        row1 = ttk.Frame(self.opts_frame)
        row1.pack(fill=tk.X, pady=px(2))
        option(ttk.Checkbutton(row1, text="Kopfzeile einfügen:", variable=self.var_header)).pack(side=tk.LEFT)
        self.entry_header = option(ttk.Entry(row1, textvariable=self.var_header_text, width=24))
        self.entry_header.pack(side=tk.LEFT, padx=(px(6), px(18)))
        option(ttk.Checkbutton(row1, text="Z-Wert auf 2 Dezimalstellen runden", variable=self.var_round_z)).pack(
            side=tk.LEFT, padx=(0, px(12))
        )
        self.chk_fixed_z = option(ttk.Checkbutton(
            row1, text="Feste 2 Nachkommastellen (z. B. 34.80)", variable=self.var_fixed_z
        ))
        self.chk_fixed_z.pack(side=tk.LEFT)

        # Zeile 2: Dateinamen, Suffix & .csvt
        row2 = ttk.Frame(self.opts_frame)
        row2.pack(fill=tk.X, pady=px(4))
        option(ttk.Checkbutton(
            row2,
            text="Dateinamen säubern ((1), (2), - Kopie, Sonderzeichen)",
            variable=self.var_clean_name,
        )).pack(side=tk.LEFT, padx=(0, px(16)))
        ttk.Label(row2, text="Suffix:").pack(side=tk.LEFT)
        option(ttk.Entry(row2, textvariable=self.var_suffix, width=10)).pack(side=tk.LEFT, padx=(px(6), px(16)))
        option(ttk.Checkbutton(
            row2, text=".csvt-Typdatei (schützt IDs wie 3.10)", variable=self.var_create_csvt
        )).pack(side=tk.LEFT)

        # Zeile 3: QGIS-Layerdatei (.vrt) mit Koordinatensystem
        row3 = ttk.Frame(self.opts_frame)
        row3.pack(fill=tk.X, pady=px(2))
        option(ttk.Checkbutton(
            row3, text="QGIS-Layerdatei (.vrt) mit Koordinatensystem:", variable=self.var_create_vrt
        )).pack(side=tk.LEFT)
        self.cmb_crs = option(ttk.Combobox(
            row3, textvariable=self.var_crs, width=42, values=[crs_display(code) for code, _ in CRS_CHOICES]
        ))
        self.cmb_crs.pack(side=tk.LEFT, padx=(px(6), px(16)))
        self.chk_union = option(
            ttk.Checkbutton(row3, text="+ Sammel-Layer aller Dateien", variable=self.var_union_vrt)
        )
        self.chk_union.pack(side=tk.LEFT)

        # Zeile 4: Ausgabeordner
        row4 = ttk.Frame(self.opts_frame)
        row4.pack(fill=tk.X, pady=px(2))
        option(ttk.Checkbutton(
            row4,
            text="Fester Ausgabeordner (Unterordner werden übernommen):",
            variable=self.var_use_custom_out,
        )).pack(side=tk.LEFT)
        self.entry_out_dir = option(ttk.Entry(row4, textvariable=self.var_custom_out_dir))
        self.entry_out_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=px(6))
        option(ttk.Button(row4, text="Ordner...", command=self.select_output_dir)).pack(side=tk.LEFT)

        # Hinweis bei ungültigen Eingaben (wird nur bei Bedarf eingeblendet)
        self.lbl_validation = ttk.Label(self.opts_frame, text="", style="Error.TLabel")

        # 4. Unterer Bereich zuerst packen, damit bei kleinem Fenster die Liste schrumpft
        self.footer_frame = ttk.Frame(self.root, padding=(px(14), px(2), px(14), px(6)))
        self.footer_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.lbl_footer = ttk.Label(self.footer_frame, text=FOOTER_TEXT, style="Footer.TLabel")
        self.lbl_footer.pack(side=tk.LEFT)

        log_frame = ttk.Frame(self.root, padding=(px(14), 0))
        log_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.txt_log = tk.Text(
            log_frame, height=5, font=("Consolas", 9), relief=tk.FLAT, padx=px(8), pady=px(6), wrap=tk.WORD
        )
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_scroll.set, state=tk.DISABLED)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        action_frame = ttk.Frame(self.root, padding=(px(14), px(6)))
        action_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.btn_convert = tk.Button(
            action_frame,
            text=self.CONVERT_TEXT,
            font=("Segoe UI", 11, "bold"),
            pady=px(6),
            cursor="hand2",
            relief=tk.FLAT,
            command=self._on_convert_button,
        )
        self.btn_convert.pack(fill=tk.X)
        # Der zweite Klick eines Doppelklicks darf den gerade gestarteten Lauf nicht abbrechen
        self.btn_convert.bind("<Double-Button-1>", lambda e: "break")
        self.progress_frame = ttk.Frame(action_frame)
        self.progress_frame.pack(fill=tk.X)
        self.progress = ttk.Progressbar(self.progress_frame, mode="determinate")
        self.lbl_progress = ttk.Label(self.progress_frame, text="", style="Muted.TLabel")

        # 5. Dateiliste (Treeview) füllt den restlichen Platz
        self.list_frame = list_frame = ttk.Frame(self.root, padding=(px(14), px(4)))
        list_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        cols = ("src_name", "dst_name", "folder", "status")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", selectmode="extended", height=6)
        self.tree.heading("src_name", text="Quelldatei")
        self.tree.heading("dst_name", text="Neuer Dateiname")
        self.tree.heading("folder", text="Quellordner")
        self.tree.heading("status", text="Status")
        self.tree.column("src_name", width=px(220), anchor=tk.W)
        self.tree.column("dst_name", width=px(240), anchor=tk.W)
        self.tree.column("folder", width=px(300), anchor=tk.W)
        self.tree.column("status", width=px(160), anchor=tk.W)

        scroll_y = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll_y.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.log("Bereit. Dateien oder Ordner hineinziehen bzw. über die Buttons auswählen.")

    def _bind_shortcuts(self):
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<Control-a>", self._select_all)
        self.tree.bind("<Control-A>", self._select_all)
        self.tree.bind("<Double-1>", self._show_row_details)
        self.root.bind("<Control-o>", lambda e: self.add_files_dialog())
        self.root.bind("<Control-O>", lambda e: self.add_files_dialog())
        self.root.bind("<F5>", lambda e: self.rebuild_file_list(announce=True))
        self.root.bind("<Control-Return>", lambda e: self.run_batch_conversion())

    # -----------------------------------------------------------------
    # PAYPAL & INFO / IMPRESSUM DIALOG
    # -----------------------------------------------------------------
    def open_paypal(self):
        webbrowser.open(PAYPAL_URL)

    def show_info_dialog(self):
        t = self.THEMES[self.theme_mode]
        px = self.px
        dlg = tk.Toplevel(self.root)
        dlg.title(f"Info & Lizenz – {APP_NAME}")
        dlg.configure(bg=t["bg"])
        dlg.transient(self.root)

        frame = ttk.Frame(dlg, padding=px(16))
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=f"{APP_NAME} (v{APP_VERSION})", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text=APP_SUBTITLE, style="Muted.TLabel").pack(anchor=tk.W, pady=(0, px(8)))

        btn_row = ttk.Frame(frame)
        btn_row.pack(side=tk.BOTTOM, fill=tk.X, pady=(px(12), 0))

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(
            text_frame,
            wrap=tk.WORD,
            width=72,
            height=18,
            font=("Segoe UI", 9),
            bg=t["tree_bg"],
            fg=t["fg"],
            relief=tk.FLAT,
            padx=px(10),
            pady=px(10),
            highlightthickness=0,
        )
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        txt.insert(tk.END, LICENSE_TEXT)
        txt.configure(state=tk.DISABLED)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Button(
            btn_row,
            text="☕ Projekt auf PayPal unterstützen (paypal.me/PeMeurer)",
            font=("Segoe UI", 9, "bold"),
            bg=t["paypal_bg"],
            fg=t["paypal_fg"],
            activebackground=t["accent"],
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=px(12),
            pady=px(5),
            cursor="hand2",
            command=self.open_paypal,
        ).pack(side=tk.LEFT)
        btn_close = ttk.Button(btn_row, text="Schließen", command=dlg.destroy)
        btn_close.pack(side=tk.RIGHT)
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        # Mittig über dem Hauptfenster platzieren
        dlg.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dlg.winfo_reqwidth()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dlg.winfo_reqheight()) // 3)
        dlg.geometry(f"+{x}+{y}")
        self._set_titlebar_theme(dlg)
        btn_close.focus_set()
        # Modal machen, sobald das Fenster sichtbar ist (grab_set vorher scheitert auf manchen Systemen)
        dlg.after(50, lambda: self._grab_when_viewable(dlg))

    @staticmethod
    def _grab_when_viewable(window):
        try:
            if window.winfo_exists() and window.winfo_viewable():
                window.grab_set()
        except tk.TclError:
            pass

    # -----------------------------------------------------------------
    # DRAG & DROP EINRICHTEN
    # -----------------------------------------------------------------
    @staticmethod
    def _drop_zone_text(active: bool) -> str:
        if active:
            return "📥 Dateien oder Ordner hierher ziehen – oder hier klicken, um Dateien auszuwählen"
        if DND_BACKEND or DND_ERROR:
            # Paket installiert, aber auf diesem System nicht nutzbar
            return "📂 Hier klicken, um Dateien auszuwählen  (Drag & Drop ist hier nicht verfügbar)"
        return "📂 Hier klicken, um Dateien auszuwählen  (für Drag & Drop: py -m pip install tkinterdnd2)"

    def _setup_drag_and_drop(self):
        try:
            if DND_BACKEND == "tkinterdnd2":
                for widget in (self.root, self.drop_zone, self.tree):
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self._on_tkdnd_drop)
                return
            if DND_BACKEND == "windnd":
                # force_unicode: Pfade mit Umlauten kommen sonst als ANSI-Bytes an
                windnd.hook_dropfiles(self.root, func=self._on_windnd_drop, force_unicode=True)
                return
        except (AttributeError, tk.TclError, OSError):
            pass  # Hauptfenster ohne Drag-&-Drop-Unterstützung: Auswahl über die Buttons
        self.drop_zone.configure(text=self._drop_zone_text(False))

    def _on_tkdnd_drop(self, event):
        if event.data:
            self._process_incoming_paths([Path(p) for p in self.root.tk.splitlist(event.data)])
        return event.action

    def _on_windnd_drop(self, file_list):
        paths = []
        for item in file_list:
            if isinstance(item, bytes):
                item = item.decode("mbcs" if sys.platform == "win32" else "utf-8", errors="replace")
            paths.append(Path(item))
        self.root.after(0, lambda: self._process_incoming_paths(paths))

    # -----------------------------------------------------------------
    # DATEI- & ORDNERVERWALTUNG
    # -----------------------------------------------------------------
    def _process_incoming_paths(self, paths: list):
        if self.running:
            self.log("Während der Konvertierung können keine Dateien hinzugefügt werden.", "warn")
            return
        added, ignored = 0, []
        for p in paths:
            try:
                if p.is_dir():
                    folder = p.resolve()
                    self.source_folders.add(folder)
                    # Erneut hinzugefügter Ordner holt zuvor entfernte Dateien zurück
                    self.excluded = {path for path in self.excluded if not _is_within(path, folder)}
                    added += 1
                elif p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                    path = p.resolve()
                    self.manual_files.add(path)
                    self.excluded.discard(path)
                    added += 1
                else:
                    ignored.append(p.name)
            except OSError:
                ignored.append(p.name)

        if added:
            self.rebuild_file_list(announce=True)
        if ignored:
            names = ", ".join(ignored[:5]) + (" …" if len(ignored) > 5 else "")
            self.log(
                f"Hinweis: {len(ignored)} Element(e) ignoriert – unterstützt werden Ordner sowie "
                f"{', '.join(SUPPORTED_EXTENSIONS)}-Dateien: {names}",
                "warn",
            )

    def add_files_dialog(self):
        if self.running:
            return
        patterns = " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)
        files = filedialog.askopenfilenames(
            title="Vermessungsdateien auswählen",
            filetypes=[("CSV / Textdateien", patterns), ("Alle Dateien", "*.*")],
            parent=self.root,
        )
        if files:
            self._process_incoming_paths([Path(f) for f in files])

    def add_folder_dialog(self):
        if self.running:
            return
        folder = filedialog.askdirectory(title="Ordner mit Vermessungsdateien auswählen", parent=self.root)
        if folder:
            self._process_incoming_paths([Path(folder)])

    def select_output_dir(self):
        folder = filedialog.askdirectory(title="Zielordner für konvertierte Dateien wählen", parent=self.root)
        if folder:
            self.var_custom_out_dir.set(str(Path(folder)))
            self.var_use_custom_out.set(True)

    def rebuild_file_list(self, announce: bool = False):
        """Sammelt alle Einzeldateien und durchsucht hinzugefügte Ordner neu."""
        if self.running:
            return
        suffix = sanitize_suffix(self.var_suffix.get())
        skip = tuple({s for s in (suffix, DEFAULT_SUFFIX) if s})
        roots = {path: None for path in self.manual_files}
        skipped_outputs = []
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            # Flache Ordner zuerst, damit für jede Datei der nächstliegende Quellordner gilt
            for folder in sorted(self.source_folders, key=lambda p: len(p.parts)):
                if folder.is_dir():
                    for path in scan_folder(folder, self.var_recursive.get(), skip,
                                            (DEFAULT_HEADER,), skipped_outputs):
                        roots[path] = folder
        finally:
            self.root.configure(cursor="")
        for path in list(roots):
            if path in self.excluded or _path_key(path) in self.written_outputs:
                del roots[path]
        self.file_roots = roots
        self.resolved_files = sorted(roots, key=lambda p: (str(p.parent).lower(), p.name.lower()))
        self.refresh_file_table()
        if announce:
            message = f"{len(self.resolved_files)} Datei(en) in der Warteschlange."
            others = {p for p in skipped_outputs if p not in self.manual_files}
            if others:
                message += f" {len(others)} bereits konvertierte Datei(en) im Zielformat ausgelassen."
            self.log(message)

    def _header_lines(self) -> tuple:
        """Kopfzeilen, an denen eigene Ausgaben am Zielnamen erkannt werden.

        Eine selbst gewählte Kopfzeile zählt nur zusammen mit einem Suffix im Namen –
        sonst könnte eine Rohdatei mit zufällig gleicher Kopfzeile als eigene Ausgabe gelten.
        """
        lines = {DEFAULT_HEADER}
        if self.var_header.get() and sanitize_suffix(self.var_suffix.get()):
            try:
                lines.add(",".join(parse_header(self.var_header_text.get())))
            except ValueError:
                pass
        return tuple(lines)

    def _output_dir_or_none(self) -> Optional[Path]:
        if not self.var_use_custom_out.get():
            return None
        try:
            return normalize_dir_input(self.var_custom_out_dir.get())
        except ValueError:
            return None

    def _companion_exts(self) -> tuple:
        exts = []
        if self.var_create_csvt.get():
            exts.append(".csvt")
        if self.var_create_vrt.get():
            exts.append(".vrt")
        return tuple(exts)

    def _current_plans(self, out_dir: Optional[Path]) -> list:
        return plan_targets(
            self.resolved_files,
            self.file_roots,
            self.var_suffix.get(),
            self.var_clean_name.get(),
            out_dir,
            self._companion_exts(),
            known_outputs=frozenset(self.written_outputs),
            header_lines=self._header_lines(),
        )

    def refresh_file_table(self):
        if self.running:
            return
        out_dir = self._output_dir_or_none()
        self.planned = {plan.source: plan for plan in self._current_plans(out_dir)}
        selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for path in self.resolved_files:
            plan = self.planned.get(path)
            status, tag = self._status_for(path, plan)
            iid = str(path)
            self.tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(path.name, self._display_target(plan, out_dir), str(path.parent), status),
                tags=(tag,) if tag else (),
            )
            if iid in selection:
                self.tree.selection_add(iid)

    @staticmethod
    def _display_target(plan: Optional[PlannedTarget], out_dir: Optional[Path]) -> str:
        if plan is None:
            return "–"
        if out_dir is not None:
            try:
                return str(plan.target.relative_to(out_dir))
            except ValueError:
                pass
        return plan.target.name

    def _status_for(self, path: Path, plan: Optional[PlannedTarget]) -> tuple:
        result = self.results.get(path)
        if result is not None and plan is not None and result.planned_target is not None \
                and _path_key(result.planned_target) == _path_key(plan.target):
            return self._result_status(result)
        if plan is None:
            return "Bereit", ""
        notes = []
        if plan.renamed:
            notes.append("umbenannt")
        if plan.existing:
            notes.append("ersetzt vorh. Datei")
        return ("Bereit · " + ", ".join(notes), "note") if notes else ("Bereit", "")

    @staticmethod
    def _result_status(result: ConversionResult) -> tuple:
        if result.level == "error":
            return "❌ Fehler", "error"
        if result.level == "skipped":
            return "⏭ übersprungen", "note"
        points = f"{result.points:,}".replace(",", ".")
        if result.level == "warn":
            return f"⚠ {points} Pkt. – Details", "warn"
        return f"✅ {points} Pkt.", "ok"

    def remove_selected(self):
        if self.running:
            return
        selected = self.tree.selection()
        if not selected:
            return
        removed = {Path(iid) for iid in selected}
        for path in removed:
            self.manual_files.discard(path)
            self.excluded.add(path)  # bleibt auch nach erneutem Einlesen draußen
            self.file_roots.pop(path, None)
        self.resolved_files = [path for path in self.resolved_files if path not in removed]
        self.refresh_file_table()
        self.log(f"{len(removed)} Datei(en) entfernt – {len(self.resolved_files)} in der Warteschlange.")

    def _select_all(self, _event=None):
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def clear_list(self):
        if self.running:
            return
        self.manual_files.clear()
        self.source_folders.clear()
        self.excluded.clear()
        self.file_roots.clear()
        self.resolved_files.clear()
        self.planned.clear()
        self.results.clear()
        self.tree.delete(*self.tree.get_children())
        self.log("Liste geleert.")

    def _show_row_details(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        path = Path(iid)
        plan = self.planned.get(path)
        lines = [f"Quelle: {path}"]
        if plan is not None:
            lines.append(f"Ziel: {plan.target}")
            if plan.renamed:
                lines.append(f"Hinweis: Der Name wurde nummeriert ({plan.reason or 'Namenskonflikt'}).")
            if plan.existing:
                names = ", ".join(p.name for p in plan.existing)
                verbs = "existiert bereits und würde" if len(plan.existing) == 1 else "existieren bereits und würden"
                lines.append(f"Hinweis: {names} {verbs} ersetzt.")
        result = self.results.get(path)
        lines += result.report_lines() if result else ["Noch nicht konvertiert."]
        messagebox.showinfo(path.name, "\n".join(lines), parent=self.root)

    # -----------------------------------------------------------------
    # OPTIONEN PRÜFEN
    # -----------------------------------------------------------------
    def _on_option_change(self, refresh: bool = True, rescan: bool = False):
        self._update_option_states()
        self._validate_options()
        if rescan:
            # Der Filter für bereits konvertierte Dateien hängt am Suffix
            self._debounce("rebuild", 400, self.rebuild_file_list)
        elif refresh:
            self._debounce("refresh", 250, self.refresh_file_table)

    def _update_option_states(self):
        def enable(widget, on):
            widget.state(["!disabled"] if on else ["disabled"])

        enable(self.entry_header, self.var_header.get())
        enable(self.chk_fixed_z, self.var_round_z.get())
        enable(self.cmb_crs, self.var_create_vrt.get())
        enable(self.chk_union, self.var_create_vrt.get())
        enable(self.entry_out_dir, self.var_use_custom_out.get())

    def _validate_options(self) -> Optional[str]:
        problems = []
        if self.var_header.get():
            try:
                parse_header(self.var_header_text.get())
            except ValueError as exc:
                problems.append(str(exc))
        suffix = self.var_suffix.get().strip()
        if not _SUFFIX_RE.fullmatch(suffix):
            problems.append("Das Suffix darf nur Buchstaben, Ziffern, '_' und '-' enthalten.")
        if self.var_use_custom_out.get():
            try:
                normalize_dir_input(self.var_custom_out_dir.get())
            except ValueError as exc:
                problems.append(str(exc))
        elif not suffix:
            problems.append(
                "Ohne Suffix nur mit festem Ausgabeordner speichern – sonst könnten Originale überschrieben werden."
            )
        if self.var_create_vrt.get() and parse_crs_choice(self.var_crs.get()) is None:
            problems.append("Koordinatensystem bitte als 'EPSG:Nummer' angeben oder aus der Liste wählen.")
        if problems:
            self.lbl_validation.configure(text=f"⚠ {problems[0]}")
            if not self.lbl_validation.winfo_manager():
                self.lbl_validation.pack(fill=tk.X, pady=(self.px(2), 0))
        elif self.lbl_validation.winfo_manager():
            self.lbl_validation.pack_forget()
        return problems[0] if problems else None

    def _collect_convert_options(self) -> ConvertOptions:
        return ConvertOptions(
            header_cols=parse_header(self.var_header_text.get()) if self.var_header.get() else None,
            round_z=self.var_round_z.get(),
            fixed_z_decimals=self.var_fixed_z.get(),
            create_csvt=self.var_create_csvt.get(),
            create_vrt=self.var_create_vrt.get(),
            crs=parse_crs_choice(self.var_crs.get()) or "",
        )

    # -----------------------------------------------------------------
    # BATCH-KONVERTIERUNG (im Hintergrund-Thread, mit Fortschritt)
    # -----------------------------------------------------------------
    def _on_convert_button(self):
        if self.running:
            # Kurz nach dem Start ignorieren – sonst bricht ein versehentlicher Doppelklick sofort ab
            if time.monotonic() - self.run_state.get("started", 0) < 0.5:
                return
            self.cancel_event.set()
            self.btn_convert.configure(text="⏹ Wird abgebrochen …", state=tk.DISABLED)
        else:
            self.run_batch_conversion()

    def _flush_pending_updates(self):
        """Noch ausstehende (entprellte) Aktualisierungen sofort ausführen."""
        for key, func in (("rebuild", self.rebuild_file_list), ("refresh", self.refresh_file_table)):
            after_id = self._after_ids.pop(key, None)
            if after_id:
                self.root.after_cancel(after_id)
                func()

    def run_batch_conversion(self):
        if self.running:
            return
        self._flush_pending_updates()
        if not self.resolved_files:
            messagebox.showinfo("Keine Dateien", "Bitte zuerst Dateien oder Ordner hinzufügen.", parent=self.root)
            return
        problem = self._validate_options()
        if problem:
            messagebox.showerror("Einstellungen prüfen", problem, parent=self.root)
            return

        out_dir = None
        if self.var_use_custom_out.get():
            out_dir = normalize_dir_input(self.var_custom_out_dir.get())
            if not out_dir.is_dir():
                if not messagebox.askyesno(
                    "Ausgabeordner anlegen?",
                    f"Der Ausgabeordner existiert noch nicht:\n{out_dir}\n\nJetzt anlegen?",
                    parent=self.root,
                ):
                    return
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    messagebox.showerror("Ausgabeordner", friendly_error(exc), parent=self.root)
                    return

        options = self._collect_convert_options()
        plans = self._current_plans(out_dir)
        self.planned = {plan.source: plan for plan in plans}

        union_path = None
        if options.create_vrt and self.var_union_vrt.get():
            try:
                union_path = union_vrt_path(plans, out_dir, self.var_suffix.get())
            except ValueError as exc:
                messagebox.showwarning("Sammel-Layer", f"Kein Sammel-Layer möglich: {exc}", parent=self.root)

        existing = [plan for plan in plans if plan.existing]
        skip_existing = False
        if existing:
            names = [plan.target.name for plan in existing[:6]]
            count = len(existing)
            verb = "existiert" if count == 1 else "existieren"
            answer = messagebox.askyesnocancel(
                "Zieldateien bereits vorhanden",
                f"{count} Ausgabedatei(en) früherer Läufe {verb} bereits, z. B.:\n• " + "\n• ".join(names)
                + ("\n• …" if count > len(names) else "")
                + "\n\nJa = ersetzen\nNein = diese Dateien überspringen\nAbbrechen = nichts tun",
                parent=self.root,
            )
            if answer is None:
                return
            skip_existing = not answer

        jobs, skipped = [], []
        for plan in plans:
            (skipped if skip_existing and plan.existing else jobs).append(plan)
        # Der Sammel-Layer enthält nur Verweise und wird immer aktualisiert; vorhandene
        # Ausgaben übersprungener Dateien gehören hinein, sofern sie zur Kopfzeile passen.
        union_note = ""
        union_existing = tuple(plan.target for plan in skipped if output_matches_header(plan.target, options.header_cols))
        if union_path is not None and len(union_existing) < len(skipped):
            union_note = (f"Sammel-Layer ohne {len(skipped) - len(union_existing)} übersprungene Datei(en), "
                          "deren vorhandene Ausgabe nicht zur aktuellen Kopfzeilen-Einstellung passt.")
        self._start_worker(jobs, skipped, options, union_path, union_existing, union_note)

    def _start_worker(self, jobs: list, skipped: list, options: ConvertOptions, union_path: Optional[Path],
                      union_existing: tuple = (), union_note: str = ""):
        self.running = True
        self.cancel_event.clear()
        self.events = queue.Queue()
        self.run_state = {"total": len(jobs), "done": 0, "results": [], "planned": len(jobs) + len(skipped),
                          "cancelled": False, "started": time.monotonic(), "union_note": union_note}

        for plan in skipped:
            result = ConversionResult(source=plan.source, planned_target=plan.target, skipped=True)
            self.results[plan.source] = result
            self.run_state["results"].append(result)
            self._set_row_status(plan.source, *self._result_status(result))
        for plan in jobs:
            self.results.pop(plan.source, None)
            self._set_row_status(plan.source, "⏳ wartet", "note")

        self.log(f"── Konvertierung gestartet: {len(jobs)} Datei(en) ──", "head")
        self._set_running_ui(True)
        self.worker = threading.Thread(
            target=self._worker_main, args=(jobs, options, union_path, union_existing), daemon=True
        )
        self.worker.start()
        self.root.after(40, self._poll_events)

    def _worker_main(self, jobs: list, options: ConvertOptions, union_path: Optional[Path],
                     union_existing: tuple = ()):
        written = []
        finished_all = True
        for plan in jobs:
            if self.cancel_event.is_set():
                self.events.put(("cancelled", None))
                finished_all = False
                break
            self.events.put(("start", plan.source))
            result = convert_file(plan.source, plan.target, options)
            if result.target is not None:
                written.append(result)
            self.events.put(("file", result))
        if union_path is not None:
            if not finished_all:
                self.events.put(("union", (union_path, "", "Sammel-Layer wegen Abbruch nicht geschrieben.")))
            elif not written and not union_existing:
                self.events.put(("union", (union_path, "", "Kein Sammel-Layer – es wurde keine Datei geschrieben.")))
            else:
                try:
                    write_union_vrt(union_path, written, options, union_existing)
                    self.events.put(("union", (union_path, "", "")))
                except Exception as exc:
                    self.events.put(("union", (union_path, friendly_error(exc), "")))
        self.events.put(("done", None))

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "start":
                    self._set_row_status(payload, "▶ läuft …", "note")
                elif kind == "file":
                    self._handle_result(payload)
                elif kind == "union":
                    path, error, note = payload
                    if error:
                        self.log(f"❌ Sammel-Layer {path.name}: {error}", "error")
                        self.run_state["union_error"] = True
                    elif note:
                        self.log(f"⚠ {note}", "warn")
                    else:
                        self.written_outputs.add(_path_key(path))
                        self.log(f"🗂 Sammel-Layer geschrieben: {path}", "ok")
                elif kind == "cancelled":
                    self.run_state["cancelled"] = True
                elif kind == "done":
                    self._finish_run()
                    return
        except queue.Empty:
            pass
        self.root.after(40, self._poll_events)

    def _handle_result(self, result: ConversionResult):
        self.results[result.source] = result
        self.run_state["results"].append(result)
        self.run_state["done"] += 1
        for path in result.written:
            self.written_outputs.add(_path_key(path))
        self._set_row_status(result.source, *self._result_status(result))
        total = max(1, self.run_state["total"])
        self.progress.configure(value=100 * self.run_state["done"] / total)
        self.lbl_progress.configure(text=f"{self.run_state['done']} von {self.run_state['total']} Datei(en)")
        self._log_result(result)

    def _log_result(self, result: ConversionResult):
        name = result.source.name
        if result.error:
            self.log(f"❌ {name}: {result.error}", "error")
            return
        parsed = result.parsed
        meta = f"{parsed.encoding}, {DELIMITER_NAMES.get(parsed.delimiter, parsed.delimiter)}" if parsed else ""
        if result.target is None:
            reason = f"keine Messpunkte – {parsed.skip_reason}" if parsed and parsed.skip_reason \
                else "keine Messpunkte erkannt"
            self.log(f"⚠ {name}: {reason} – nichts geschrieben ({meta})", "warn")
            warnings = result.warnings[1:]
        else:
            points = f"{result.points:,}".replace(",", ".")
            unit = "Punkt" if result.points == 1 else "Punkte"
            symbol, tag = ("⚠", "warn") if result.warnings else ("✅", "ok")
            self.log(f"{symbol} {name} → {result.target.name}: {points} {unit} ({meta})", tag)
            warnings = result.warnings
        for text in warnings:
            self.log(f"     • {text}", "warn")
        for text in result.infos:
            self.log(f"     · {text}")

    def _finish_run(self):
        state = self.run_state
        results = state["results"]
        cancelled = state.get("cancelled") or self.cancel_event.is_set()
        if cancelled:
            for path, plan in self.planned.items():
                if path not in self.results and self.tree.exists(str(path)):
                    self._set_row_status(path, "– abgebrochen", "note")

        converted = [r for r in results if r.target is not None]
        errors = [r for r in results if r.error]
        warned = [r for r in results if r.level == "warn"]
        skipped = [r for r in results if r.skipped]
        total_points = sum(r.points for r in converted)
        points = f"{total_points:,}".replace(",", ".")
        summary = (
            f"{'Abgebrochen' if cancelled else 'Fertig'}: {len(converted)} von {state['planned']} Datei(en) "
            f"konvertiert, insgesamt {points} {'Messpunkt' if total_points == 1 else 'Messpunkte'}."
        )
        if state.get("union_note"):
            self.log(f"⚠ {state['union_note']}", "warn")
        details = []
        if warned:
            details.append(f"{len(warned)} mit Warnungen")
        if errors:
            details.append(f"{len(errors)} mit Fehlern")
        if skipped:
            details.append(f"{len(skipped)} übersprungen")
        if details:
            summary += " " + ", ".join(details) + "."
        self.log(summary, "error" if errors else ("warn" if warned or cancelled else "ok"))

        self.running = False
        self._set_running_ui(False)
        self._save_settings()
        if self.closing:
            return
        if errors or warned or state.get("union_error"):
            messagebox.showwarning(
                "Konvertierung abgeschlossen",
                summary + "\n\nEinzelheiten stehen im Protokoll unten; ein Doppelklick auf eine Zeile "
                "der Liste zeigt die Details zu dieser Datei.",
                parent=self.root,
            )

    def _set_running_ui(self, running: bool):
        widgets = (self.btn_add_files, self.btn_add_folder, self.btn_clear, self.btn_remove, self.chk_recursive,
                   *self.option_widgets)
        for widget in widgets:
            widget.state(["disabled"] if running else ["!disabled"])
        if not running:
            self._update_option_states()  # abhängige Felder wieder korrekt sperren
        if running:
            self.btn_convert.configure(text="⏹ Abbrechen", command=self._on_convert_button, state=tk.NORMAL)
            self.progress.configure(value=0)
            self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=(self.px(6), 0))
            self.lbl_progress.configure(text=f"0 von {self.run_state['total']} Datei(en)")
            self.lbl_progress.pack(side=tk.LEFT, padx=(self.px(8), 0), pady=(self.px(6), 0))
        else:
            self.btn_convert.configure(text=self.CONVERT_TEXT, state=tk.NORMAL)
            self.progress.pack_forget()
            self.lbl_progress.pack_forget()

    def _set_row_status(self, path: Path, status: str, tag: str = ""):
        iid = str(path)
        if self.tree.exists(iid):
            self.tree.set(iid, "status", status)
            self.tree.item(iid, tags=(tag,) if tag else ())

    # -----------------------------------------------------------------
    # LOG, FEHLER, EINSTELLUNGEN & BEENDEN
    # -----------------------------------------------------------------
    def log(self, message: str, tag: str = ""):
        self.txt_log.configure(state=tk.NORMAL)
        self.txt_log.insert(tk.END, message.rstrip() + "\n", (tag,) if tag else ())
        lines = int(self.txt_log.index("end-1c").split(".")[0])
        if lines > 3000:
            self.txt_log.delete("1.0", f"{lines - 3000}.0")
        self.txt_log.see(tk.END)
        self.txt_log.configure(state=tk.DISABLED)

    def _report_callback_exception(self, exc_type, exc_value, exc_tb):
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        if sys.stderr is not None:  # beim Start über die Konsole auch dort ausgeben
            try:
                sys.stderr.write(details)
            except (OSError, ValueError):
                pass
        try:
            self.log("Unerwarteter Fehler:\n" + details, "error")
        except tk.TclError:
            pass
        messagebox.showerror(
            "Unerwarteter Fehler",
            f"{exc_type.__name__}: {exc_value}\n\nDetails stehen im Protokoll.",
            parent=self.root,
        )

    def _current_settings(self) -> dict:
        crs = parse_crs_choice(self.var_crs.get())
        return {
            "theme": self.theme_mode,
            "recursive": self.var_recursive.get(),
            "header": self.var_header.get(),
            "header_text": self.var_header_text.get(),
            "round_z": self.var_round_z.get(),
            "fixed_z": self.var_fixed_z.get(),
            "clean_name": self.var_clean_name.get(),
            "suffix": self.var_suffix.get(),
            "create_csvt": self.var_create_csvt.get(),
            "create_vrt": self.var_create_vrt.get(),
            "crs": DEFAULT_CRS if crs is None else crs,
            "union_vrt": self.var_union_vrt.get(),
            "use_custom_out": self.var_use_custom_out.get(),
            "custom_out_dir": self.var_custom_out_dir.get(),
        }

    def _save_settings(self):
        save_settings(self._current_settings())

    def on_close(self):
        if self.closing:
            return  # wird bereits beendet, sobald die aktuelle Datei fertig ist
        if self.running:
            if not messagebox.askyesno(
                "Konvertierung läuft", "Die Konvertierung läuft noch. Abbrechen und beenden?", parent=self.root
            ):
                return
            self.closing = True
            self.cancel_event.set()
            self.btn_convert.configure(text="⏹ Wird beendet …", state=tk.DISABLED)
            self._close_when_idle()
            return
        self._save_settings()
        self.root.destroy()

    def _close_when_idle(self):
        if self.running or (self.worker is not None and self.worker.is_alive()):
            self.root.after(100, self._close_when_idle)
            return
        self._save_settings()
        self.root.destroy()

    # -----------------------------------------------------------------
    # THEME (DARK / LIGHT MODE)
    # -----------------------------------------------------------------
    def _theme_button_text(self) -> str:
        return "☀ Light Mode" if self.theme_mode == "dark" else "☾ Dark Mode"

    def toggle_theme(self):
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        self.btn_theme.configure(text=self._theme_button_text())
        self._apply_theme()
        self._set_titlebar_theme(self.root)

    def _set_titlebar_theme(self, window):
        """Dunkle bzw. helle Windows-Titelleiste (ab Windows 10 20H1, sonst ohne Wirkung)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(window.wm_frame(), 16)
            value = ctypes.c_int(1 if self.theme_mode == "dark" else 0)
            for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (neu / älter)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                ) == 0:
                    break
        except Exception:
            pass

    def _apply_theme(self):
        t = self.THEMES[self.theme_mode]
        s = self.style
        px = self.px
        self.root.configure(bg=t["bg"])

        s.configure(
            ".",
            background=t["bg"],
            foreground=t["fg"],
            fieldbackground=t["entry_bg"],
            bordercolor=t["border"],
            lightcolor=t["panel"],
            darkcolor=t["panel"],
            troughcolor=t["bg"],
            selectbackground=t["tree_sel"],
            selectforeground="#ffffff",
            insertcolor=t["fg"],
        )
        # Zustände des clam-Themes überschreiben, sonst werden Hover-Flächen hellgrau
        s.map(".", background=[("disabled", t["bg"]), ("active", t["panel"])],
              foreground=[("disabled", t["muted"])])
        s.configure("TFrame", background=t["bg"])
        s.configure("TLabel", background=t["bg"], foreground=t["fg"])
        s.configure("Title.TLabel", background=t["bg"], foreground=t["fg"], font=("Segoe UI", 14, "bold"))
        s.configure("Muted.TLabel", background=t["bg"], foreground=t["muted"])
        s.configure("Footer.TLabel", background=t["bg"], foreground=t["muted"], font=("Segoe UI", 8))
        s.configure("Error.TLabel", background=t["bg"], foreground=t["error"])
        s.configure(
            "TCheckbutton",
            background=t["bg"],
            foreground=t["fg"],
            indicatorbackground=t["entry_bg"],
            indicatorforeground=t["fg"],
            upperbordercolor=t["border"],
            lowerbordercolor=t["border"],
        )
        s.map(
            "TCheckbutton",
            background=[("active", t["bg"])],
            foreground=[("disabled", t["muted"])],
            indicatorbackground=[("disabled", t["bg"]), ("pressed", t["panel"])],
        )
        s.configure("TLabelframe", background=t["bg"], bordercolor=t["border"])
        s.configure("TLabelframe.Label", background=t["bg"], foreground=t["fg"])
        s.configure("TButton", background=t["panel"], foreground=t["fg"], bordercolor=t["border"],
                    padding=(px(8), px(4)))
        s.map(
            "TButton",
            background=[("disabled", t["bg"]), ("pressed", t["accent"]), ("active", t["entry_bg"])],
            foreground=[("disabled", t["muted"]), ("pressed", t["accent_fg"])],
        )
        s.configure("TEntry", fieldbackground=t["entry_bg"], foreground=t["fg"], insertcolor=t["fg"],
                    bordercolor=t["border"])
        s.map("TEntry", fieldbackground=[("disabled", t["bg"])], foreground=[("disabled", t["muted"])])
        s.configure("TCombobox", fieldbackground=t["entry_bg"], background=t["panel"], foreground=t["fg"],
                    arrowcolor=t["fg"], bordercolor=t["border"], insertcolor=t["fg"])
        s.map(
            "TCombobox",
            fieldbackground=[("disabled", t["bg"]), ("readonly", t["entry_bg"])],
            foreground=[("disabled", t["muted"])],
            background=[("active", t["entry_bg"])],
            arrowcolor=[("disabled", t["muted"])],
        )
        s.configure("Treeview", background=t["tree_bg"], fieldbackground=t["tree_bg"], foreground=t["fg"],
                    rowheight=self.row_height, bordercolor=t["border"])
        s.map("Treeview", background=[("selected", t["tree_sel"])], foreground=[("selected", "#ffffff")])
        s.configure("Treeview.Heading", background=t["panel"], foreground=t["fg"], bordercolor=t["border"],
                    font=("Segoe UI", 9, "bold"))
        s.map("Treeview.Heading", background=[("active", t["entry_bg"])], foreground=[("active", t["fg"])])
        s.configure("Vertical.TScrollbar", background=t["panel"], troughcolor=t["bg"], bordercolor=t["border"],
                    arrowcolor=t["fg"], lightcolor=t["panel"], darkcolor=t["panel"])
        s.map("Vertical.TScrollbar", background=[("active", t["entry_bg"]), ("disabled", t["bg"])],
              arrowcolor=[("disabled", t["muted"])])
        s.configure("Horizontal.TProgressbar", background=t["accent"], troughcolor=t["entry_bg"],
                    bordercolor=t["border"], lightcolor=t["accent"], darkcolor=t["accent"])

        # Aufklappliste der KBS-Auswahl
        self.root.option_add("*TCombobox*Listbox.background", t["entry_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", t["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", t["tree_sel"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        try:
            popdown = self.root.tk.call("ttk::combobox::PopdownWindow", str(self.cmb_crs))
            self.root.tk.call(f"{popdown}.f.l", "configure", "-background", t["entry_bg"],
                              "-foreground", t["fg"], "-selectbackground", t["tree_sel"],
                              "-selectforeground", "#ffffff")
        except tk.TclError:
            pass

        # Zeilenfarben der Dateiliste
        self.tree.tag_configure("ok", foreground=t["ok"])
        self.tree.tag_configure("warn", foreground=t["warn"])
        self.tree.tag_configure("error", foreground=t["error"])
        self.tree.tag_configure("note", foreground=t["muted"])

        # Klassische Tk-Widgets
        self.drop_zone.configure(
            bg=t["drop_bg"],
            fg=t["fg"],
            highlightbackground=t["drop_border"],
            highlightcolor=t["accent"],
            highlightthickness=2,
        )
        self.btn_paypal.configure(
            bg=t["paypal_bg"],
            fg=t["paypal_fg"],
            activebackground=t["accent"],
            activeforeground="#ffffff",
        )
        self.btn_convert.configure(
            bg=t["accent"],
            fg=t["accent_fg"],
            activebackground=t["success"],
            activeforeground="#ffffff",
            disabledforeground=t["muted"],
        )
        self.txt_log.configure(
            bg=t["tree_bg"],
            fg=t["fg"],
            insertbackground=t["fg"],
            selectbackground=t["tree_sel"],
            selectforeground="#ffffff",
            highlightbackground=t["drop_border"],
            highlightthickness=1,
        )
        self.txt_log.tag_configure("ok", foreground=t["ok"])
        self.txt_log.tag_configure("warn", foreground=t["warn"])
        self.txt_log.tag_configure("error", foreground=t["error"])
        self.txt_log.tag_configure("head", foreground=t["accent"], font=("Consolas", 9, "bold"))


# =====================================================================
# PROGRAMMSTART
# =====================================================================

def enable_windows_dpi_awareness():
    """Scharfe Darstellung bei Bildschirmskalierung über 100 % (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def create_root() -> tk.Tk:
    """Erzeugt das Hauptfenster; fehlt die native tkdnd-Bibliothek, ohne Drag & Drop."""
    global DND_BACKEND, DND_ERROR
    if DND_BACKEND == "tkinterdnd2":
        try:
            return TkinterDnD.Tk()
        except (RuntimeError, tk.TclError) as exc:
            # Das halb initialisierte Fenster schließen, sonst bleibt ein leeres Fenster offen
            stale = getattr(tk, "_default_root", None)
            if stale is not None:
                try:
                    stale.destroy()
                except tk.TclError:
                    pass
            DND_BACKEND = None
            DND_ERROR = f"Die tkdnd-Bibliothek konnte nicht geladen werden ({exc})."
    return tk.Tk()


def main():
    enable_windows_dpi_awareness()
    root = create_root()
    HaXKonverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
