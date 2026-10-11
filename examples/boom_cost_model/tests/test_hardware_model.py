"""Test probe fitting, held-out prediction, and provenance rejection."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from hardware_model import evaluate, extract_loops, fit_model, load_runs, predict_cycles
from run_probes import CASES, KERNELS, MARKER, parse_probe_results
from run_timing import TUNES, file_hash

FIR_ASM = """
1000: 00000013 li a0,0
1004: 00000013 li a3,0
1008: 00000013 lw a4,0(a1)
100c: 00000013 lw a5,0(a2)
1010: 00000013 mulw a4,a4,a5
1014: 00000013 addw a3,a3,a4
1018: 00000013 bne a1,a2,1008 <fir+0x8>
101c: 00000013 sw a3,0(a6)
1020: 00000013 addi a6,a6,4
1024: 00000013 bne a6,a7,1004 <fir+0x4>
1028: 00000013 ret
"""
MATRIX_ASM = """
1000: 00000013 li a0,0
1004: 00000013 li t0,0
1008: 00000013 li a3,0
100c: 00000013 lw a4,0(a1)
1010: 00000013 lw a5,0(a2)
1014: 00000013 mulw a4,a4,a5
1018: 00000013 addw a3,a3,a4
101c: 00000013 bne a1,a2,100c <mat+0xc>
1020: 00000013 sw a3,0(a6)
1024: 00000013 addi a6,a6,4
1028: 00000013 bne a6,a7,1008 <mat+0x8>
102c: 00000013 addi t0,t0,1
1030: 00000013 addi t1,t1,4
1034: 00000013 bne t0,t2,1004 <mat+0x4>
1038: 00000013 ret
"""


def synthetic_runs():
    """Known chain/throughput rates, with fixed overhead canceled by slopes."""
    costs = {"probe_mul": (6, 1), "probe_shift": (4, 2),
             "probe_add": (1, 0.5), "probe_load": (4, 1)}
    runs = []
    for layout in range(3):
        run = {}
        for k, n, w in CASES:
            for tune in TUNES:
                rate = costs[KERNELS[k]][0 if w == 1 else 1]
                run[KERNELS[k], n, w, tune] = {"median_cycles": 40 + layout + 2 * n * rate}
        runs.append(run)
    return runs


class TestHardwareModel(unittest.TestCase):
    def test_fit_cancels_overhead_and_predicts_ranking_reversal(self):
        runs = synthetic_runs()
        model = fit_model(runs)
        self.assertEqual(model["operations"]["mul"]["1"]["cycles_per_operation"], 6)
        self.assertEqual(model["operations"]["mul"]["8"]["cycles_per_operation"], 1)
        self.assertEqual(model["fixed_overhead_cycles"], 40)
        self.assertEqual([model["mul13_choices"][str(w)]["preferred"] for w in (1, 2, 4, 8)],
                         ["shift", "shift", "mul", "mul"])
        runs[0]["probe_mul", 512, 1, "rocket"]["median_cycles"] = 1
        with self.assertRaises(ValueError):
            fit_model(runs)

    def test_extract_and_predict_heldout_loops(self):
        model = fit_model(synthetic_runs())
        features = extract_loops(FIR_ASM)
        self.assertEqual(features["loop_span_lengths"], [5, 9])
        self.assertEqual(features["loads_per_inner"], 2)
        prediction = predict_cycles(model, features, "fir", 10, 8)
        self.assertEqual(prediction["dynamic_instruction_estimate"], 442)
        self.assertEqual(prediction["predicted_cycles"], 482)
        matrix = extract_loops(MATRIX_ASM)
        self.assertEqual(matrix["loop_span_lengths"], [5, 9, 13])
        self.assertEqual(predict_cycles(model, matrix, "matmul", 3, 0)["predicted_cycles"], 225)
        with self.assertRaises(ValueError):
            extract_loops(FIR_ASM.replace("mulw", "addw"))
        with self.assertRaises(ValueError):
            predict_cycles(model, features, "pointer_chase", 10, 8)
        with self.assertRaises(ValueError):
            predict_cycles(model, features, "matmul", 3, 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = []
            for layout in range(3):
                folder = root / f"medium-layout{layout}"
                folder.mkdir()
                (folder / "fir.rocket.linked.asm").write_text(FIR_ASM)
                runs.append({("fir", 10, 8, "rocket"): {"median_cycles": 482}})
            original = json.dumps(model, sort_keys=True)
            result = evaluate(model, runs, root)
            self.assertEqual(result["mean_absolute_percentage_error"], 0)
            self.assertEqual(json.dumps(model, sort_keys=True), original)

    def test_run_validation_rejects_modified_artifacts_and_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            simulator = root / "simulator-MediumBoomV3Config"
            simulator.write_bytes(b"simulator fixture")
            archive = root / "sources"
            archive.mkdir()
            (archive / "fixture.c").write_text("fixture")
            for layout in range(3):
                run = root / f"medium-layout{layout}"
                run.mkdir()
                (run / "timing.riscv").write_bytes(b"binary fixture")
                addresses = {f"{k}_{t.replace('-', '_')}": f"{0x80000000 + ki * 0x3000 + ((ti + layout) % 3) * 0x1000:x}"
                             for ki, k in enumerate(KERNELS) for ti, t in enumerate(TUNES)}
                meta = {"experiment": "probes", "suite": False, "layout": layout, "opt": "O3",
                        "simulator": str(simulator), "simulator_sha256": file_hash(simulator),
                        "gcc": "GCC15", "runtime_gcc": "GCC13", "kernel_addresses": addresses,
                        "source_sha256": {"fixture.c": file_hash(archive / "fixture.c")},
                        "binary_sha256": file_hash(run / "timing.riscv")}
                (run / "metadata.json").write_text(json.dumps(meta))
                lines = [MARKER]
                for k, n, p in CASES:
                    for t in range(3):
                        lines.append(f"P {k} {n} {p} {t} 100 100 100")
                (run / "simulation.log").write_text("\n".join(lines))
            runs, metas = load_runs(root, "probes", KERNELS, parse_probe_results)
            self.assertEqual(len(runs), 3)
            self.assertEqual(len(metas), 3)
            path = root / "medium-layout1" / "metadata.json"
            original = json.loads(path.read_text())
            for key, value in (("gcc", "different"), ("layout", 2), ("simulator_sha256", "different"),
                               ("source_sha256", {"fixture.c": "different"}),
                               ("binary_sha256", "different"),
                               ("kernel_addresses", {k: "0" for k in original["kernel_addresses"]})):
                changed = dict(original)
                changed[key] = value
                path.write_text(json.dumps(changed))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load_runs(root, "probes", KERNELS, parse_probe_results)


if __name__ == "__main__":
    unittest.main()
