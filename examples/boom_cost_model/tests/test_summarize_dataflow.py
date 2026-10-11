"""Reject incomparable dataflow measurements before reporting speedups."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from run_dataflow import KERNELS, MARKER, cases
from run_timing import TUNES, file_hash
from summarize_dataflow import summarize


class TestDataflowSummary(unittest.TestCase):
    def test_complete_summary_and_reject_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for layout in range(3):
                run = root / f"medium-layout{layout}"
                run.mkdir()
                (run / "timing.riscv").write_bytes(b"fixture")
                addresses = {f"{k}_{t.replace('-', '_')}": f"{0x80000000 + ki * 0x3000 + ((ti + layout) % 3) * 0x1000:x}"
                             for ki, k in enumerate(KERNELS) for ti, t in enumerate(TUNES)}
                meta = {"experiment": "dataflow", "suite": False, "layout": layout,
                        "opt": "O3", "simulator": "/fixture/MediumBoomV3Config",
                        "simulator_sha256": "same", "source_sha256": {"a.c": "same"},
                        "gcc": "GCC15", "runtime_gcc": "GCC13", "kernel_addresses": addresses,
                        "binary_sha256": file_hash(run / "timing.riscv")}
                (run / "metadata.json").write_text(json.dumps(meta))
                lines = [MARKER]
                for n, k, w in cases():
                    for t in range(3):
                        v = (800 if t == 0 else 400) // w
                        lines.append(f"D {n} {k} {w} {t} {v} {v} {v}")
                (run / "simulation.log").write_text("\n".join(lines))
            result = summarize(root)
            self.assertEqual(len(result["cases"]), 54)
            self.assertEqual(len(result["groups"]), 12)
            self.assertEqual(result["groups"][0]["speedup_geomean"], 2)
            self.assertEqual(result["groups"][0]["wins_every_layout_over_1pct"], 3)
            row = next(r for r in result["cases"] if r["kernel"] == "independent_streams" and r["streams"] == 8)
            self.assertAlmostEqual(row["speedup_vs_one_stream"], 8)
            path = root / "medium-layout1" / "metadata.json"
            original = json.loads(path.read_text())
            for key, value in (("source_sha256", {"a.c": "different"}),
                               ("gcc", "different"), ("runtime_gcc", "different"),
                               ("layout", 2), ("simulator_sha256", "different"),
                               ("binary_sha256", "different"),
                               ("kernel_addresses", {k: "0" for k in original["kernel_addresses"]})):
                changed = dict(original)
                changed[key] = value
                path.write_text(json.dumps(changed))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    summarize(root)
            path.write_text(json.dumps(original))
            log = root / "medium-layout2" / "simulation.log"
            log.write_text(log.read_text().rsplit("\n", 1)[0])
            with self.assertRaises(ValueError):
                summarize(root)


if __name__ == "__main__":
    unittest.main()
