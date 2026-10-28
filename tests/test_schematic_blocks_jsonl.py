from collections import Counter
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import list_schematic_blocks as catalog

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "list_schematic_blocks.py"


class ReconfigurableStringIO(io.StringIO):
    def reconfigure(self, **kwargs):
        pass


class SchematicBlocksJsonlTests(unittest.TestCase):
    def test_jsonl_record_preserves_delimiters_and_unicode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "[group]|file.msch"
            with patch.object(catalog, "ROOT", root):
                line = catalog.format_jsonl_record(
                    path,
                    "Title | [lightgray]雪[]",
                    Counter({"router": 2, "duct": 1}),
                )

        record = json.loads(line)
        self.assertEqual(record["filename"], "[group]|file.msch")
        self.assertEqual(record["name"], "Title | [lightgray]雪[]")
        self.assertEqual(record["block_count"], 3)
        self.assertEqual(record["blocks"], {"duct": 1, "router": 2})

    def test_jsonl_index_covers_all_schematics(self):
        expected_files = {
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*.msch")
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "schematic_blocks.jsonl"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "--format",
                    "jsonl",
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            records = [
                json.loads(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(
            {record["filename"] for record in records},
            expected_files,
        )
        self.assertEqual(len(records), len(expected_files))
        for record in records:
            self.assertEqual(record["schema_version"], 1)
            self.assertIsInstance(record["name"], str)
            self.assertIsInstance(record["blocks"], dict)
            self.assertEqual(
                record["block_count"],
                sum(record["blocks"].values()),
                record["filename"],
            )

    def test_read_errors_do_not_replace_existing_catalog(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_path = root / "schematic_blocks.txt"
            output_path.write_text("existing catalog\n", encoding="utf-8")
            good_path = root / "good.msch"
            bad_path = root / "bad.msch"
            good_path.touch()
            bad_path.touch()

            def count_blocks(path):
                if path == bad_path:
                    raise ValueError("bad fixture")
                return "Good schematic", Counter({"router": 1})

            standard_output = ReconfigurableStringIO()
            standard_error = ReconfigurableStringIO()
            with patch.multiple(
                catalog,
                ROOT=root,
                OUTPUT_FILE=output_path,
            ), patch.object(
                catalog,
                "count_blocks",
                side_effect=count_blocks,
            ), patch.object(
                sys,
                "argv",
                ["list_schematic_blocks.py"],
            ), patch.object(
                sys,
                "stdout",
                standard_output,
            ), patch.object(
                sys,
                "stderr",
                standard_error,
            ):
                result = catalog.main()

            self.assertEqual(result, 1)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "existing catalog\n",
            )
            self.assertIn("No catalog was written", standard_error.getvalue())


if __name__ == "__main__":
    unittest.main()
