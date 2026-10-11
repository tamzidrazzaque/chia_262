"""Test source/disassembly provenance and workload aggregation."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from prepare_runs import prepare
from run_timing import TUNES, file_hash
from run_workloads import CASES, KERNELS, MARKER
from summarize_workloads import summarize


def make_fixture(root, source_hashes):
    """Create checked-input fixtures with balanced addresses and known ratios."""
    simulator = root / "simulator-MediumBoomV3Config"
    simulator.write_bytes(b"simulator")
    for layout in range(3):
        run = root / f"medium-layout{layout}"
        run.mkdir()
        (run / "timing.riscv").write_bytes(b"binary")
        addresses = {f"{k}_{t.replace('-', '_')}": f"{0x80000000 + ki * 0x3000 + ((ti + layout) % 3) * 0x1000:x}"
                     for ki, k in enumerate(KERNELS) for ti, t in enumerate(TUNES)}
        meta = {"experiment": "workloads", "suite": False, "layout": layout, "opt": "O3",
                "simulator": str(simulator), "simulator_sha256": file_hash(simulator),
                "binary_sha256": file_hash(run / "timing.riscv"), "kernel_addresses": addresses,
                "source_sha256": source_hashes, "gcc": "fixture15", "runtime_gcc": "fixture13"}
        (run / "metadata.json").write_text(json.dumps(meta))
        lines = [MARKER]
        for k, n, p in CASES:
            for t in range(3):
                v = (2000 if t == 0 else 1000) // (p if k == 2 else 1)
                lines.append(f"W {k} {n} {p} {t} {v} {v} {v}")
        (run / "simulation.log").write_text("\n".join(lines))


class TestWorkloadArtifacts(unittest.TestCase):
    def test_prepare_manifest_and_reject_changed_source_or_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = file_hash(SOURCE / "run_timing.py")
            make_fixture(root, {"run_timing.py": digest})
            with patch("prepare_runs.subprocess.check_output", return_value="verified fixture asm\n") as disassemble:
                manifests = prepare(root, Path("/fixture/objdump"))
                self.assertEqual(disassemble.call_count, 27)
            self.assertEqual(len(manifests), 3)
            self.assertEqual(file_hash(root / "sources/run_timing.py"), digest)
            saved = root / "medium-layout0/fir.rocket.linked.asm"
            self.assertEqual(manifests[0]["disassembly_sha256"][saved.name], file_hash(saved))
            (root / "sources/run_timing.py").write_text("modified")
            with self.assertRaises(ValueError):
                prepare(root, Path("/fixture/objdump"))
            (root / "sources/run_timing.py").write_bytes((SOURCE / "run_timing.py").read_bytes())
            (root / "medium-layout0/timing.riscv").write_bytes(b"modified")
            with self.assertRaises(ValueError):
                prepare(root, Path("/fixture/objdump"))

    def test_summary_and_reject_missing_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sources").mkdir()
            (root / "sources/fixture.c").write_text("fixture")
            make_fixture(root, {"fixture.c": file_hash(root / "sources/fixture.c")})
            result = summarize(root)
            self.assertEqual(len(result["cases"]), 45)
            self.assertEqual(len(result["groups"]), 6)
            self.assertAlmostEqual(result["groups"][0]["speedup_geomean"], 2)
            row = next(r for r in result["cases"] if r["kernel"] == "pointer_chase" and r["parameter"] == 4)
            self.assertAlmostEqual(row["speedup_vs_one_chain"], 4)
            log = root / "medium-layout1/simulation.log"
            log.write_text(log.read_text().rsplit("\n", 1)[0])
            with self.assertRaises(ValueError):
                summarize(root)


if __name__ == "__main__":
    unittest.main()
