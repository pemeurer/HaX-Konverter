# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests der Kernlogik des HaX-Konverters (ohne Oberfläche, nur Standardbibliothek).

Aufruf im Projektordner:  py -m unittest discover -s tests -v
Alle Testdaten sind synthetisch und entstehen in temporären Ordnern.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("hax_konverter", ROOT / "HaX-Konverter.py")
hax = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hax
_spec.loader.exec_module(hax)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text, encoding="utf-8"):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode(encoding))
        return path


class NumberTests(unittest.TestCase):
    def test_parse_number(self):
        self.assertEqual(str(hax.parse_number("1,5")), "1.5")
        self.assertEqual(str(hax.parse_number(" 500100.120 ")), "500100.120")
        self.assertEqual(hax.format_number(hax.parse_number("3.25E+7")), "32500000")
        for text in ("1.234,56", "nan", "inf", "1_000", "abc", "", "12 m", "1e99999"):
            self.assertIsNone(hax.parse_number(text), text)

    def test_z_rounding_half_up(self):
        self.assertEqual(hax.format_z_value("34.795"), "34.80")
        self.assertEqual(hax.format_z_value("34.805"), "34.81")
        self.assertEqual(hax.format_z_value("-34.805"), "-34.81")
        self.assertEqual(hax.format_z_value("100,995"), "101.00")

    def test_z_variants(self):
        self.assertEqual(hax.format_z_value("34.8", fixed_2_dec=False), "34.8")
        self.assertEqual(hax.format_z_value("100", fixed_2_dec=False), "100")
        self.assertEqual(hax.format_z_value("-0.001"), "0.00")  # keine negative Null
        self.assertEqual(hax.format_z_value("101.5551", round_2_dec=False), "101.5551")
        self.assertEqual(hax.format_z_value(""), "")
        self.assertIsNone(hax.format_z_value("-"))


class FilenameTests(unittest.TestCase):
    def test_clean_filename(self):
        self.assertEqual(hax.clean_filename("Messung_0815(2)"), "Messung_0815_QGIS.csv")
        self.assertEqual(hax.clean_filename("Messung - Kopie"), "Messung_QGIS.csv")
        self.assertEqual(hax.clean_filename("Messung - Kopie (2)"), "Messung_QGIS.csv")
        self.assertEqual(hax.clean_filename("Fläche 3.2"), "Fläche_3_2_QGIS.csv")
        self.assertEqual(hax.clean_filename("X_QGIS"), "X_QGIS.csv")
        self.assertEqual(hax.clean_filename("Mit Leerzeichen", sanitize=False), "Mit Leerzeichen_QGIS.csv")
        self.assertEqual(hax.clean_filename("(1)"), "1_QGIS.csv")  # nie den ganzen Namen entfernen
        self.assertEqual(hax.clean_filename("___"), "messpunkte_QGIS.csv")

    def test_suffix_is_made_safe(self):
        self.assertEqual(hax.clean_filename("a", suffix="_neu:1/x"), "a_neu_1_x.csv")
        self.assertEqual(hax.clean_filename("nul", suffix=""), "nul_.csv")


class DecodeTests(unittest.TestCase):
    def test_encodings(self):
        text = "Fundstück Süd;Maß"
        self.assertEqual(hax.decode_bytes(text.encode("utf-8")), (text, "UTF-8"))
        self.assertEqual(hax.decode_bytes(b"\xef\xbb\xbf" + text.encode("utf-8")), (text, "UTF-8"))
        self.assertEqual(hax.decode_bytes(text.encode("utf-16")), (text, "UTF-16"))
        self.assertEqual(hax.decode_bytes(text.encode("utf-16-le")), (text, "UTF-16"))
        self.assertEqual(hax.decode_bytes(text.encode("cp1252")), (text, "Windows-1252"))
        self.assertEqual(hax.decode_bytes(text.encode("cp850")), (text, "DOS (cp850)"))
        typographic = "1;500100;5600200;100;„Mauer“ … Ecke"
        self.assertEqual(hax.decode_bytes(typographic.encode("cp1252")), (typographic, "Windows-1252"))


class ParseTests(unittest.TestCase):
    def test_semicolon_with_decimal_comma_and_header(self):
        parsed = hax.parse_survey_text(
            "PNr;Rechtswert;Hochwert;Höhe;Code;;;\n"
            "3.10;500100,123;5600200,456;101,555;Mauer;;;\n"
            "0010;500101,1;5600201,2;101,2;BP\n"
        )
        self.assertEqual(parsed.delimiter, ";")
        self.assertEqual(parsed.rows, [
            ["3.10", "500100.123", "5600200.456", "101.56", "Mauer"],
            ["0010", "500101.1", "5600201.2", "101.20", "BP"],
        ])
        self.assertEqual(parsed.text_lines, [1])

    def test_comma_tab_and_whitespace(self):
        comma = hax.parse_survey_text('1,500100.1,5600200.1,99.5,"Mauer, Ecke"\n')
        self.assertEqual((comma.delimiter, comma.rows[0][4]), (",", "Mauer, Ecke"))
        tab = hax.parse_survey_text("1\t500100.1\t5600200.1\t99.5\tStein;klein\n")
        self.assertEqual((tab.delimiter, tab.rows[0][4]), ("\t", "Stein;klein"))
        space = hax.parse_survey_text("1   500100,1  5600200,1 99,5 Mauer Nord\n2 500101.1 5600201.1 Grenzstein\n")
        self.assertEqual(space.delimiter, " ")
        self.assertEqual(space.rows, [
            ["1", "500100.1", "5600200.1", "99.50", "Mauer Nord"],
            ["2", "500101.1", "5600201.1", "", "Grenzstein"],
        ])

    def test_leading_tab_keeps_columns(self):
        parsed = hax.parse_survey_text("\t500100.1\t5600200.1\t99.5\tMP\n7\t500101.1\t5600201.1\t99.6\tBP\n")
        self.assertEqual(parsed.rows[0], ["", "500100.1", "5600200.1", "99.50", "MP"])
        self.assertEqual(parsed.empty_id_lines, [1])

    def test_3d_file_with_problems(self):
        parsed = hax.parse_survey_text(
            "# Kommentar\n"
            "1;500100.1;5600200.1;100.1;A\n"
            "2;500101.1;5600201.1\n"
            "3;500102.1;5600202.1;-;BP\n"
            "4;500103.1x;5600203.1;100;Tippfehler\n"
            "5;500104.1;5600204.1;100;A;Zusatz\n"
            "6;500105.1;5600205.1;12a;\n"
            "7;500106.1;5600206.1;101,23m;C\n"
        )
        self.assertEqual([row[0] for row in parsed.rows], ["1", "2", "3", "5", "6", "7"])
        self.assertEqual(parsed.rows[2][3:], ["", "BP"])  # Platzhalter '-' = fehlende Höhe
        self.assertEqual(parsed.rows[4][3:], ["", "12a"])  # Text geht nicht verloren
        self.assertEqual(parsed.rows[5][3:], ["101.23", "C"])  # Einheit m ist erlaubt
        self.assertEqual(parsed.comment_lines, [1])
        self.assertEqual(parsed.no_height_lines, [3, 4])
        self.assertEqual(parsed.bad_height_lines, [7])
        self.assertEqual(parsed.invalid_lines, [5])
        self.assertEqual(parsed.extra_column_lines, [6])
        warnings, _ = hax.describe_parsed(parsed)
        self.assertTrue(any("Zeile 5" in w for w in warnings))
        self.assertTrue(any("Zeile 7" in w for w in warnings))

    def test_missing_height_placeholders_keep_the_code(self):
        for marker in ("-", "n.v.", "nan", "NA"):
            parsed = hax.parse_survey_text(
                f"PNr;R;H;Z;Code\n1;500100,1;5600200,1;{marker};Grenzstein\n2;500101,1;5600201,1;{marker};Mauer\n"
            )
            self.assertEqual([row[3:] for row in parsed.rows], [["", "Grenzstein"], ["", "Mauer"]], marker)
            self.assertEqual((parsed.bad_height_lines, parsed.extra_column_lines), ([], []), marker)
        space = hax.parse_survey_text("1 500100.10 5600200.10 101.5 Mauer\n2 500101.10 5600201.10 - Mauer Nord\n")
        self.assertEqual(space.rows[1][3:], ["", "Mauer Nord"])

    def test_header_decides_whether_column_4_is_a_code(self):
        parsed = hax.parse_survey_text(
            "PNr;Rechtswert;Hochwert;Code\n1;500100,1;5600200,1;0501\n2;500101,1;5600201,1;1100\n3;500102,1;5600202,1;GP\n"
        )
        self.assertEqual([row[3:] for row in parsed.rows], [["", "0501"], ["", "1100"], ["", "GP"]])

    def test_2d_file_with_codes_and_trailing_delimiters(self):
        for text in ("PNr;R;H;Code;;\n1;500100,4;5600200,1;Grenzstein;;\n2;500101,8;5600201,9;Mauer Nord;;\n",
                     "1;500100,4;5600200,1;Grenzstein;\n2;500101,8;5600201,9;Mauer Nord;\n",
                     "1\t500100.4\t5600200.1\tGrenzstein\t\n2\t500101.8\t5600201.9\tMauer Nord\t\n"):
            parsed = hax.parse_survey_text(text)
            self.assertEqual([row[3:] for row in parsed.rows], [["", "Grenzstein"], ["", "Mauer Nord"]], text)
            self.assertEqual(parsed.bad_height_lines, [])

    def test_nan_line_is_reported(self):
        parsed = hax.parse_survey_text("1;500100;5600200;1;A\n2;nan;inf;1;B\n")
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(parsed.invalid_lines, [2])

    def test_broken_first_data_line_is_reported(self):
        parsed = hax.parse_survey_text(
            "PNr;Rechtswert;Hochwert;Hoehe;Code\n"
            "1;512.346,678;5678902,234;101,6;MP\n"
            "2;512347,678;5678903,234;101,7;MP\n"
            "3;512348,678;5678904,234;101,8;MP\n"
        )
        self.assertEqual(parsed.text_lines, [1])
        self.assertEqual(parsed.invalid_lines, [2])

    def test_missing_coordinates_after_first_point(self):
        parsed = hax.parse_survey_text(
            "1;500100,1;5600200,1;100,1;A\nStationswechsel;;;;\n17;;;101,23;Grenzstein\n2;500101,1;5600201,1;100,2;B\n"
        )
        self.assertEqual(parsed.text_lines, [2])
        self.assertEqual(parsed.invalid_lines, [3])

    def test_not_survey_files(self):
        grid = "ncols 3\nnrows 2\nxllcorner 500000\nyllcorner 5600000\ncellsize 1\nNODATA_value -9999\n" \
               "100.1 100.2 100.3\n100.4 100.5 100.6\n"
        self.assertIn("Raster", hax.parse_survey_text(grid).skip_reason)
        xyz = "".join(f"{500000 + i}.5 5600000.5 10{i}.2\n" for i in range(5))
        self.assertIn("x-y-z", hax.parse_survey_text(xyz).skip_reason)
        for notes in ("Grabung 2026 Schnitt 3\nTag 1 12 Befunde dokumentiert\nTag 2 15 Befunde\n",
                      "Grabungstagebuch Schnitt 3\nTag 1: Oberboden abgetragen, ca. 0.3 m\n"
                      "Befund 12 1.5 m breit, 0.4 m tief\nBefund 13 2.1 m lang\nFund 7 0.25 kg Keramik\n"):
            self.assertEqual(hax.parse_survey_text(notes).rows, [])

    def test_local_2d_list_with_large_ids_is_not_a_grid(self):
        text = "".join(f"{10001 + i};{120 + 10 * i:.2f};{1 + i / 10:.2f}\n" for i in range(10))
        parsed = hax.parse_survey_text(text)
        self.assertEqual((parsed.skip_reason, len(parsed.rows)), ("", 10))

    def test_lines_with_other_delimiter_are_reported(self):
        parsed = hax.parse_survey_text(
            "1;500100,5;5600200,5;100,5;Mauer\n2,500101.5,5600201.5,100.6,Grube\n3;500102,5;5600202,5;100,7;Mauer\n"
        )
        self.assertEqual(len(parsed.rows), 2)
        self.assertEqual(parsed.delimiter_lines, [2])
        warnings, _ = hax.describe_parsed(parsed)
        self.assertTrue(any("Trennzeichen" in w and "Zeile 2" in w for w in warnings))

    def test_header_with_digits_is_no_error(self):
        parsed = hax.parse_survey_text(
            "PNr;X_ETRS89;Y_ETRS89;H_DHHN2016;Code\n1;500100,1;5600200,1;100,1;A\n2;500101,1;5600201,1;100,2;B\n"
        )
        self.assertEqual((parsed.text_lines, parsed.invalid_lines), ([1], []))

    def test_two_survey_areas_are_not_outliers(self):
        north = "".join(f"A{i};500100.1;56202{i}0.1;100;MP\n" for i in range(5))
        south = "".join(f"B{i};520100.1;56002{i}0.1;100;MP\n" for i in range(5))
        parsed = hax.parse_survey_text(north + south)
        self.assertEqual(parsed.outlier_lines, [])
        self.assertTrue(parsed.multiple_areas)

    def test_long_preamble_before_data(self):
        text = "".join(f"Vorspann Zeile {i}\n" for i in range(150)) + "1,500100.1,5600200.1,99.5,A\n"
        parsed = hax.parse_survey_text(text)
        self.assertEqual((parsed.delimiter, len(parsed.rows)), (",", 1))

    def test_outliers_are_reported(self):
        rows = "".join(f"{i};5001{i:02d}.1;56002{i:02d}.1;100;A\n" for i in range(5))
        parsed = hax.parse_survey_text(rows + "Datum;28;10;2026\n")
        self.assertEqual(parsed.outlier_lines, [6])
        warnings, _ = hax.describe_parsed(parsed)
        self.assertTrue(any("10 km" in w for w in warnings))


class HeaderAndCrsTests(unittest.TestCase):
    def test_parse_header(self):
        self.assertEqual(hax.parse_header("ID;x;y;z;Code"), ["ID", "x", "y", "z", "Code"])
        for text in ("ID,x,y,z", "ID,x,y,z,x", "ID,x,,z,Code"):
            with self.assertRaises(ValueError):
                hax.parse_header(text)

    def test_crs_choice(self):
        self.assertEqual(hax.parse_crs_choice(hax.crs_display("EPSG:25832")), "EPSG:25832")
        self.assertEqual(hax.parse_crs_choice(hax.CRS_NONE_LABEL), "")
        self.assertEqual(hax.parse_crs_choice("epsg: 3044"), "EPSG:3044")
        self.assertIsNone(hax.parse_crs_choice("UTM"))

    def test_crs_plausibility(self):
        good = [["1", "500100.1", "5600200.1", "", ""]]
        zoned = [["1", "32500100.1", "5600200.1", "", ""]]
        self.assertIsNone(hax.crs_plausibility("EPSG:25832", good))
        message = hax.crs_plausibility("EPSG:25832", zoned)
        self.assertIn("EPSG:4647", message)
        self.assertIsNone(hax.crs_plausibility("", zoned))
        # einzelne Ausreißer sind Sache der Ausreißerprüfung, nicht des KBS
        self.assertIsNone(hax.crs_plausibility("EPSG:25832", good * 3 + [["9", "28", "10", "", ""]]))

    def test_union_source_field_avoids_own_columns(self):
        self.assertEqual(hax.union_source_field(["ID", "x", "y", "z", "Punktcode"]), "Quelle")
        self.assertEqual(hax.union_source_field(["ID", "x", "y", "z", "quelle"]), "Quelldatei")


class ConvertFileTests(TempDirTestCase):
    def test_csv_csvt_and_vrt(self):
        src = self.write("Messung (1).csv", "PNr;R;H;Z;Code\n3.10;500100,1;5600200,1;100,005;A\n", "cp1252")
        dst = self.dir / "Messung_QGIS.csv"
        options = hax.ConvertOptions(header_cols=hax.parse_header(hax.DEFAULT_HEADER), create_vrt=True)
        result = hax.convert_file(src, dst, options)
        self.assertEqual(result.level, "ok", result.report_lines())
        self.assertEqual(dst.read_text(encoding="utf-8").splitlines(),
                         ["ID,x,y,z,Punktcode", "3.10,500100.1,5600200.1,100.01,A"])
        self.assertEqual(dst.with_suffix(".csvt").read_text(encoding="utf-8").strip(), hax.CSVT_LINE)
        layer = ET.parse(dst.with_suffix(".vrt")).getroot().find("OGRVRTLayer")
        self.assertEqual(layer.findtext("LayerSRS"), "EPSG:25832")
        self.assertEqual(layer.findtext("SrcDataSource"), "Messung_QGIS.csv")
        self.assertEqual(layer.find("GeometryField").attrib, {"encoding": "PointFromColumns", "x": "x", "y": "y", "z": "z"})
        self.assertEqual(layer.find("Field").attrib, {"name": "ID", "type": "String"})
        self.assertEqual([p.name for p in self.dir.glob("*.tmp")], [])

    def test_without_header_and_crs(self):
        src = self.write("a.txt", "1 500100.1 5600200.1\n")
        dst = self.dir / "a_QGIS.csv"
        result = hax.convert_file(src, dst, hax.ConvertOptions(header_cols=None, create_vrt=True, crs=""))
        self.assertEqual(dst.read_text(encoding="utf-8").splitlines(), ["1,500100.1,5600200.1,,"])
        layer = ET.parse(dst.with_suffix(".vrt")).getroot().find("OGRVRTLayer")
        self.assertIsNone(layer.find("LayerSRS"))
        self.assertEqual(layer.findtext("GeometryType"), "wkbPoint")
        self.assertEqual(layer.find("OpenOptions/OOI").attrib, {"key": "HEADERS"})
        self.assertEqual(result.level, "ok")

    def test_zero_points_writes_nothing(self):
        src = self.write("leer.txt", "Nur ein Protokoll\nohne Koordinaten\n")
        dst = self.dir / "leer_QGIS.csv"
        result = hax.convert_file(src, dst, hax.ConvertOptions())
        self.assertFalse(dst.exists())
        self.assertEqual(result.level, "warn")
        self.assertIn("Keine Messpunkte", result.warnings[0])

    def test_missing_source_is_reported(self):
        result = hax.convert_file(self.dir / "fehlt.csv", self.dir / "x.csv", hax.ConvertOptions())
        self.assertEqual(result.level, "error")

    def test_never_writes_into_the_source_itself(self):
        src = self.write("roh.csv", "1;500100;5600200;1;A\n")
        alias = self.dir / "alias.csv"
        os.link(src, alias)  # zweiter Name derselben Datei (wie Netzlaufwerk/Junction)
        result = hax.convert_file(src, alias, hax.ConvertOptions())
        self.assertEqual(result.level, "error")
        self.assertEqual(src.read_text(encoding="utf-8"), "1;500100;5600200;1;A\n")

    def test_write_errors_are_reported_immediately(self):
        target = self.dir / "a_QGIS.csv"
        with mock.patch("builtins.open", side_effect=PermissionError(13, "Zugriff verweigert")):
            with self.assertRaises(PermissionError) as caught:
                hax.write_text_atomic(target, "x")
        self.assertEqual(caught.exception.filename, str(target))

    def test_locked_target_is_overwritten_in_place(self):
        target = self.write("a_QGIS.csv", "alt\n")
        with mock.patch.object(hax.os, "replace", side_effect=PermissionError(13, "gesperrt")):
            hax.write_text_atomic(target, "neu\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "neu\n")
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_stale_csvt_is_removed(self):
        src = self.write("a.csv", "1;500100;5600200;1;A\n")
        dst = self.dir / "a_QGIS.csv"
        hax.convert_file(src, dst, hax.ConvertOptions(create_csvt=True))
        self.assertTrue(dst.with_suffix(".csvt").exists())
        hax.convert_file(src, dst, hax.ConvertOptions(create_csvt=False))
        self.assertFalse(dst.with_suffix(".csvt").exists())

    def test_union_vrt(self):
        options = hax.ConvertOptions(header_cols=hax.parse_header(hax.DEFAULT_HEADER), create_vrt=True)
        results = []
        for name in ("A/Punkte.csv", "B/Punkte.csv"):
            src = self.write(name, "1;500100;5600200;1;X\n")
            results.append(hax.convert_file(src, src.with_name("Punkte_QGIS.csv"), options))
        union = self.dir / "Sammellayer_QGIS.vrt"
        hax.write_union_vrt(union, results, options)
        root = ET.parse(union).getroot().find("OGRVRTUnionLayer")
        self.assertEqual(root.findtext("SourceLayerFieldName"), "Quelle")
        layers = root.findall("OGRVRTLayer")
        self.assertEqual([layer.findtext("SrcDataSource") for layer in layers],
                         ["A/Punkte_QGIS.csv", "B/Punkte_QGIS.csv"])
        self.assertEqual(len({layer.get("name") for layer in layers}), 2)


class PlanTargetTests(TempDirTestCase):
    def test_copies_do_not_overwrite_each_other(self):
        sources = [self.write(n, "") for n in ("Punkte(1).csv", "Punkte(2).csv", "Punkte.csv", "Messung - Kopie.csv", "Messung.txt")]
        plans = {p.source.name: p for p in hax.plan_targets(sources)}
        self.assertEqual(plans["Punkte.csv"].target.name, "Punkte_QGIS.csv")
        self.assertEqual(plans["Punkte(1).csv"].target.name, "Punkte_1_QGIS.csv")
        self.assertEqual(plans["Punkte(2).csv"].target.name, "Punkte_2_QGIS.csv")
        self.assertEqual(plans["Messung.txt"].target.name, "Messung_QGIS.csv")
        self.assertEqual(plans["Messung - Kopie.csv"].target.name, "Messung_2_QGIS.csv")
        self.assertTrue(plans["Punkte(1).csv"].renamed)
        self.assertFalse(plans["Punkte.csv"].renamed)

    def test_source_files_are_never_targets(self):
        sources = [self.write("Messung (1).csv", ""), self.write("Messung.csv", "")]
        plans = hax.plan_targets(sources, suffix="")
        source_keys = {hax._path_key(s) for s in sources}
        for plan in plans:
            self.assertNotIn(hax._path_key(plan.target), source_keys)

    def test_fixed_output_folder_keeps_subfolders(self):
        root = self.dir / "Grabung"
        sources = [self.write("Grabung/Schnitt1/Punkte.csv", ""), self.write("Grabung/Schnitt2/Punkte.csv", "")]
        out = self.dir / "Ausgabe"
        plans = hax.plan_targets(sources, {s: root for s in sources}, out_dir=out)
        self.assertEqual([p.target.relative_to(out).as_posix() for p in plans],
                         ["Schnitt1/Punkte_QGIS.csv", "Schnitt2/Punkte_QGIS.csv"])
        # ohne bekannten Quellordner landen beide flach im Ausgabeordner – dann wird nummeriert
        flat = hax.plan_targets(sources, out_dir=out)
        self.assertEqual([p.target.name for p in flat], ["Punkte_QGIS.csv", "Punkte_2_QGIS.csv"])

    def test_companion_files(self):
        src = self.write("a.csv", "")
        # eigene .csvt ohne CSV: wird stillschweigend mit ersetzt
        self.write("a_QGIS.csvt", hax.CSVT_LINE + "\n")
        plan = hax.plan_targets([src], companion_exts=(".csvt", ".vrt"))[0]
        self.assertEqual((plan.target.name, plan.existing), ("a_QGIS.csv", []))
        # fremde .vrt gleichen Namens: Ziel wird nummeriert statt sie zu ersetzen
        self.write("a_QGIS.vrt", "<OGRVRTDataSource><OGRVRTLayer name='x'><SrcDataSource>Z:/andere.csv"
                                 "</SrcDataSource></OGRVRTLayer></OGRVRTDataSource>")
        plan = hax.plan_targets([src], companion_exts=(".csvt", ".vrt"))[0]
        self.assertEqual(plan.target.name, "a_2_QGIS.csv")
        self.assertIn(".vrt", plan.reason)

    def test_foreign_union_file_is_never_replaced(self):
        src = self.write("a.csv", "")
        self.write("Sammellayer_QGIS.vrt", "<OGRVRTDataSource>von Hand</OGRVRTDataSource>")
        plans = hax.plan_targets([src])
        self.assertEqual(hax.union_vrt_path(plans, None, "_QGIS").name, "Sammellayer_2_QGIS.vrt")

    def test_output_matches_header(self):
        with_header = self.write("a_QGIS.csv", hax.DEFAULT_HEADER + "\n1,500100,5600200,1,A\n")
        without = self.write("b_QGIS.csv", "1,500100,5600200,1,A\n")
        cols = hax.parse_header(hax.DEFAULT_HEADER)
        self.assertEqual((hax.output_matches_header(with_header, cols), hax.output_matches_header(without, cols)),
                         (True, False))
        self.assertEqual((hax.output_matches_header(with_header, None), hax.output_matches_header(without, None)),
                         (False, True))

    def test_foreign_files_are_never_replaced(self):
        src = self.write("Profil.csv", "")
        self.write("Profil_neu.csv", "PNr;R;H;Z;Code\n1;500100;5600200;1;Rohdaten\n")
        plan = hax.plan_targets([src], suffix="_neu")[0]
        self.assertEqual(plan.target.name, "Profil_2_neu.csv")
        self.assertTrue(plan.renamed)
        self.assertIn("nicht als eigene Ausgabe", plan.reason)
        # eine eigene frühere Ausgabe darf (nach Rückfrage) ersetzt werden
        self.write("Profil_QGIS.csv", hax.DEFAULT_HEADER + "\n1,500100,5600200,1,A\n")
        own = hax.plan_targets([src])[0]
        self.assertEqual((own.target.name, [p.name for p in own.existing]), ("Profil_QGIS.csv", ["Profil_QGIS.csv"]))


class ScanTests(TempDirTestCase):
    def test_scan_skips_outputs_hidden_and_lock_files(self):
        self.write("roh.csv", "")
        self.write("roh.asc", "")
        self.write("notiz.pdf", "")
        self.write("~$roh.csv", "")
        self.write(".versteckt.csv", "")
        self.write("roh_QGIS.csv", "")
        self.write("alt_neu.csv", "")
        self.write("alt_neu.csvt", hax.CSVT_LINE + "\n")
        self.write("alt_v2.csv", hax.DEFAULT_HEADER + "\n1,500100,5600200,1,A\n")
        self.write("Unterordner/tief.txt", "")
        skipped = []
        found = sorted(p.name for p in hax.scan_folder(self.dir, recursive=True, skipped=skipped))
        self.assertEqual(found, ["roh.asc", "roh.csv", "tief.txt"])
        self.assertEqual(sorted(p.name for p in skipped), ["alt_neu.csv", "alt_v2.csv", "roh_QGIS.csv"])
        flat = sorted(p.name for p in hax.scan_folder(self.dir, recursive=False))
        self.assertEqual(flat, ["roh.asc", "roh.csv"])

    def test_output_dir_input(self):
        self.assertEqual(hax.normalize_dir_input(f'"{self.dir}"'), self.dir)
        quoted = self.dir / "Fundstelle 'Am Bach'"
        self.assertEqual(hax.normalize_dir_input(str(quoted)), quoted)
        for text in ("", "relativ\\pfad"):
            with self.assertRaises(ValueError):
                hax.normalize_dir_input(text)


class GuiSmokeTest(TempDirTestCase):
    """Startet die Oberfläche unsichtbar; wird übersprungen, wenn kein Bildschirm verfügbar ist."""

    def test_add_remove_and_plan(self):
        import os
        import tkinter as tk

        os.environ["HAX_KONVERTER_EINSTELLUNGEN"] = str(self.dir / "einstellungen.json")
        try:
            root = hax.create_root()
        except tk.TclError as exc:
            os.environ.pop("HAX_KONVERTER_EINSTELLUNGEN", None)
            self.skipTest(f"Keine Anzeige verfügbar: {exc}")
        root.withdraw()
        try:
            app = hax.HaXKonverterApp(root)
            self.write("daten/A.csv", "1;500100;5600200;1;X\n")
            self.write("daten/B.csv", "2;500101;5600201;2;Y\n")
            app._process_incoming_paths([self.dir / "daten"])
            self.assertEqual(len(app.tree.get_children()), 2)
            app.tree.selection_set(app.tree.get_children()[0])
            app.remove_selected()
            app.rebuild_file_list()
            self.assertEqual([app.tree.set(i, "src_name") for i in app.tree.get_children()], ["B.csv"])
        finally:
            root.destroy()
            os.environ.pop("HAX_KONVERTER_EINSTELLUNGEN", None)


if __name__ == "__main__":
    unittest.main()
