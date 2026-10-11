"""Check balanced-layout aggregation and reject incomparable experiment runs."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("summarize_suite", SOURCE / "summarize_suite.py")
SUMMARY = importlib.util.module_from_spec(SPEC)
with patch.object(sys, "path", [str(SOURCE), *sys.path]):
    SPEC.loader.exec_module(SUMMARY)


class TestSummary(unittest.TestCase):
    def make_runs(self, root):
        for core in ("small", "medium"):
            for layout in range(3):
                directory = root / f"{core}-layout{layout}"
                directory.mkdir()
                addresses = {f"{k}_{t.replace('-', '_')}": hex(4096 + 512 * ki + 128 * ((ti + layout) % 3))
                             for ki, k in enumerate(SUMMARY.KERNELS) for ti, t in enumerate(SUMMARY.TUNES)}
                meta = {"suite": True, "layout": layout, "opt": "O3",
                        "source_sha256": {"timing.c": "same"}, "gcc": "same", "runtime_gcc": "same",
                        "simulator": f"simulator-{core.capitalize()}BoomV3Config",
                        "simulator_sha256": core, "kernel_addresses": addresses}
                (directory / "metadata.json").write_text(json.dumps(meta))
                lines = ["SUITE_OK sizes=32,128,512 patterns=4 repeats=2 samples=3"]
                for n in SUMMARY.SIZES:
                    for p in range(len(SUMMARY.PATTERNS)):
                        for k in range(len(SUMMARY.KERNELS)):
                            for t in range(len(SUMMARY.TUNES)):
                                v = 200 if t == 0 else 100
                                lines.append(f"S {n} {p} {k} {t} {v} {v} {v}")
                (directory / "simulation.log").write_text("\n".join(lines))

    def test_complete_summary_and_reject_incomparable_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_runs(root)
            result = SUMMARY.summarize(root)
            self.assertEqual(len(result["groups"]), 16)
            self.assertEqual(len(result["cases"]), 192)
            self.assertEqual(result["groups"][0]["speedup_geomean"], 2)
            self.assertEqual(result["groups"][0]["wins_all_layouts_over_1pct"], 12)
            path = root / "small-layout0/metadata.json"
            original = json.loads(path.read_text())
            for field, value in (("gcc", "different"), ("runtime_gcc", "different"), ("layout", 2),
                                 ("simulator_sha256", "different"),
                                 ("source_sha256", {"timing.c": "different"})):
                with self.subTest(field=field):
                    path.write_text(json.dumps({**original, field: value}))
                    with self.assertRaises(ValueError):
                        SUMMARY.summarize(root)
            path.write_text(json.dumps(original))
            path = root / "small-layout1/metadata.json"
            meta = json.loads(path.read_text())
            meta["kernel_addresses"]["branchy_rocket"] = original["kernel_addresses"]["branchy_rocket"]
            path.write_text(json.dumps(meta))
            with self.assertRaises(ValueError):
                SUMMARY.summarize(root)


if __name__ == "__main__":
    unittest.main()
