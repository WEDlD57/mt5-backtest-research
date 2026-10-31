import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
"""Small synthetic, unlicensed-data-free fixtures for the local tick converter."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from histdata_ticks import DataQualityError, convert_archives, main


class HistDataTicksTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.out = self.root / "minutes.csv"
        self.report = self.root / "report.json"

    def tearDown(self):
        self.directory.cleanup()

    def archive(self, month, rows, *, name=None):
        path = self.root / (name or f"XAUUSD_T_{month}.zip")
        text = "\n".join(",".join(map(str, row)) for row in rows) + "\n"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"DAT_ASCII_XAUUSD_T_{month}.csv", text)
        return path

    def read_output(self):
        with self.out.open(newline="") as stream:
            return list(csv.DictReader(stream))

    def convert(self, archives, **kwargs):
        return convert_archives(archives, self.out, self.report, **kwargs)

    def test_fixed_est_utc_month_boundary_and_exclusive_clip(self):
        january = self.archive("202301", [
            ("20230101 000000000", "1800", "1801", "0"),
            ("20230131 235959900", "1810", "1811", "0"),
        ])
        february = self.archive("202302", [
            ("20230201 000000001", "1820", "1822", "0"),
            ("20230201 000100000", "1830", "1833", "0"),
        ])
        audit = self.convert([february, january], start="2023-02-01T04:59:00Z",
                             until="2023-02-01T00:01:00-05:00", chunk_size=1)
        rows = self.read_output()
        self.assertEqual([row["time"] for row in rows], ["2023.02.01 04:59", "2023.02.01 05:00"])
        self.assertEqual(rows[0]["first_tick_time_utc"], "2023-02-01T04:59:59.900000Z")
        self.assertEqual(rows[1]["last_tick_time_utc"], "2023-02-01T05:00:00.001000Z")
        self.assertEqual(audit["raw_quote_rows_validated"], 4)
        self.assertEqual(audit["quote_rows_in_output_minutes"], 2)
        self.assertEqual([item["source_month_est"] for item in audit["archives"]], ["2023-01", "2023-02"])
        self.assertNotIn(str(self.root), self.report.read_text())

    def test_minute_split_across_chunks_keeps_both_sides_and_actual_ticks(self):
        january = self.archive("202301", [
            ("20230102 120000001", "100", "101", "0"),
            ("20230102 120010000", "103", "105", "0"),
            ("20230102 120020000", "99", "99.5", "0"),
            ("20230102 120059999", "102", "102.25", "0"),
            ("20230102 120100000", "104", "105", "0"),
        ])
        audit = self.convert([january], chunk_size=2)
        rows = self.read_output()
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual([float(first[key]) for key in ("open", "high", "low", "close")], [100, 103, 99, 102])
        self.assertEqual([float(first[key]) for key in ("ask_open", "ask_high", "ask_low", "ask_close")], [101, 105, 99.5, 102.25])
        self.assertEqual(int(first["tick_volume"]), 4)
        self.assertEqual(float(first["spread"]), 25)
        self.assertEqual([float(first[key]) for key in ("spread_price_min", "spread_price_max", "spread_price_open")], [.25, 2, 1])
        self.assertEqual(first["first_tick_time_utc"], "2023-01-02T17:00:00.001000Z")
        self.assertEqual(first["last_tick_time_utc"], "2023-01-02T17:00:59.999000Z")
        self.assertTrue(audit["actual_tick_bounds_valid"])

    def test_later_backstep_outside_clip_rejects_without_partial_output(self):
        january = self.archive("202301", [("20230102 120000000", "1800", "1801", "0")])
        february = self.archive("202302", [
            ("20230201 000030000", "1810", "1811", "0"),
            ("20230201 000010000", "1812", "1813", "0"),
        ])
        for existing in (False, True):
            with self.subTest(existing_output=existing):
                if existing:
                    self.out.write_text("previous complete output\n")
                with self.assertRaisesRegex(DataQualityError, "clock moves backward"):
                    self.convert([january, february], start="2023-01-01", until="2023-02-01", chunk_size=1)
                if existing:
                    self.assertEqual(self.out.read_text(), "previous complete output\n")
                else:
                    self.assertFalse(self.out.exists())
                audit = json.loads(self.report.read_text())
                self.assertEqual(audit["status"], "rejected")
                self.assertEqual(audit["archives"][1]["status"], "rejected")
                self.assertEqual(audit["archives"][1]["first_backstep"]["seconds"], -20)
                self.assertEqual(audit["archives"][1]["first_backstep"]["raw_row_number"], 2)
                self.assertFalse(audit["output_csv_replaced"])
                self.assertFalse(list(self.root.glob(".histdata-minutes-*.tmp")))

    def test_invalid_and_crossed_prices_are_rejected(self):
        for bid, ask in [("NaN", "2"), ("1", "inf"), ("0", "2"), ("-1", "2"), ("2", "1"), ("oops", "2")]:
            with self.subTest(bid=bid, ask=ask):
                archive = self.archive("202301", [("20230102 120000000", bid, ask, "0")])
                with self.assertRaises(DataQualityError):
                    self.convert([archive])
                self.assertFalse(self.out.exists())
                self.assertEqual(json.loads(self.report.read_text())["status"], "rejected")

    def test_source_month_mismatch_is_not_hidden_by_clip(self):
        archive = self.archive("202301", [("20230201 000000000", "1800", "1801", "0")])
        with self.assertRaisesRegex(DataQualityError, "does not match"):
            self.convert([archive], start="2023-01-01", until="2023-02-01")
        self.assertEqual(json.loads(self.report.read_text())["archives"][0]["source_month_mismatch_rows"], 1)

    def test_extra_field_at_chunk_boundary_and_short_rows_rejected(self):
        for invalid in [
            ("20230102 120001000", "1800", "1801", "0", "extra"),
            ("20230102 120001000", "1800", "1801"),
        ]:
            with self.subTest(fields=len(invalid)):
                archive = self.archive("202301", [
                    ("20230102 120000000", "1800", "1801", "0"), invalid,
                ])
                with self.assertRaisesRegex(DataQualityError, "exactly 4 fields"):
                    self.convert([archive], chunk_size=1)
                self.assertFalse(self.out.exists())

    def test_equal_time_quotes_preserve_original_order(self):
        archive = self.archive("202301", [
            ("20230102 120000001", "1800", "1801", "0"),
            ("20230102 120000001", "1803", "1804", "0"),
            ("20230102 120000001", "1802", "1802.5", "0"),
        ])
        audit = self.convert([archive], chunk_size=1)
        first = self.read_output()[0]
        self.assertEqual(float(first["open"]), 1800)
        self.assertEqual(float(first["close"]), 1802)
        self.assertEqual(float(first["ask_close"]), 1802.5)
        self.assertEqual(int(first["tick_volume"]), 3)
        self.assertEqual(audit["archives"][0]["equal_timestamp_pairs_preserved"], 2)

    def test_duplicate_month_and_destructive_paths_rejected(self):
        rows = [("20230102 120000000", "1800", "1801", "0")]
        first = self.archive("202301", rows)
        other = self.archive("202301", rows, name="copy.zip")
        with self.assertRaisesRegex(DataQualityError, "same source month"):
            self.convert([first, other])
        before = first.read_bytes()
        with self.assertRaisesRegex(DataQualityError, "distinct"):
            convert_archives([first], first, self.report)
        self.assertEqual(first.read_bytes(), before)

    def test_malformed_clock_and_nonminute_clip_rejected(self):
        for stamp in ("20230102 120000", "20230102 246000000"):
            with self.subTest(stamp=stamp):
                archive = self.archive("202301", [(stamp, "1800", "1801", "0")])
                with self.assertRaises(DataQualityError):
                    self.convert([archive])
                self.assertFalse(self.out.exists())
        with self.assertRaisesRegex(DataQualityError, "minute-aligned"):
            self.convert([archive], start="2023-01-01T00:00:01Z")

    def test_corrupted_zip_crc_rejects_before_output(self):
        path = self.root / "corrupted.zip"
        member = "DAT_ASCII_XAUUSD_T_202301.csv"
        payload = b"20230102 120000000,1800,1801,0\n"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(member, payload)
            info = archive.getinfo(member)
        content = bytearray(path.read_bytes())
        start = info.header_offset + 30 + len(member.encode("ascii")) + len(info.extra)
        content[start + payload.index(b"1800")] = ord("2")
        path.write_bytes(content)
        with self.assertRaisesRegex(DataQualityError, "integrity failure"):
            self.convert([path])
        self.assertFalse(self.out.exists())
        self.assertEqual(json.loads(self.report.read_text())["archives"][0]["status"], "rejected")

    def test_cli_local_inputs_and_explicit_missing_minute_gap(self):
        archive = self.archive("202301", [
            ("20230102 120000000", "1800", "1801", "0"),
            ("20230102 120200000", "1802", "1803", "0"),
        ])
        code = main(["--zip", str(archive), "--out", str(self.out), "--report", str(self.report),
                     "--from", "2023-01-02", "--until", "2023-01-03", "--chunk-size", "1"])
        self.assertEqual(code, 0)
        audit = json.loads(self.report.read_text())
        self.assertEqual(audit["minute_rows"], 2)
        self.assertEqual(audit["imputed_quotes_or_minutes"], 0)
        self.assertEqual(audit["observed_minute_gaps"][0]["missing_minutes"], 1)


if __name__ == "__main__":
    unittest.main()
