"""Reject incomplete/invalid simulation output and check harness correctness."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_timing", SOURCE / "run_timing.py")
TIMING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TIMING)


def complete_log():
    lines = ["CHECKS_OK n=128 repeats=8 samples=6"]
    for kernel in TIMING.KERNELS:
        for tune in TIMING.TUNES:
            for sample in range(TIMING.SAMPLES):
                value = 200 if tune == "rocket" else 100
                lines.append(f"RESULT {kernel} {tune} {sample} {value}")
    return "\n".join(lines)


class TestMeasurements(unittest.TestCase):
    def test_suite_validation_and_speedup(self):
        lines = ["SUITE_OK sizes=32,128,512 patterns=4 repeats=2 samples=3"]
        for n in TIMING.SIZES:
            for p in range(len(TIMING.PATTERNS)):
                for k in range(len(TIMING.KERNELS)):
                    for t in range(len(TIMING.TUNES)):
                        v = 200 if t == 0 else 100
                        lines.append(f"S {n} {p} {k} {t} {v} {v} {v}")
        good = "\n".join(lines)
        rows = TIMING.parse_suite_results(good)
        self.assertEqual(len(rows), 144)
        self.assertEqual(rows[1]["speedup"], 2)
        for bad in (good.replace("SUITE_OK", "FAILED"),
                    good.rsplit("\n", 1)[0], good + "\n" + lines[1],
                    good.replace("200 200 200", "0 200 200", 1),
                    good.replace("S 32 0", "S 99 0", 1),
                    good.replace("200 200 200", "200 200", 1)):
            with self.subTest(log=bad[:80]), self.assertRaises(ValueError):
                TIMING.parse_suite_results(bad)

    def test_speedup_and_sample_count(self):
        rows = TIMING.parse_results(complete_log())
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[1]["speedup"], 2)
        self.assertEqual(len(rows[1]["cycles"]), 6)

    def test_reject_invalid_measurements(self):
        good = complete_log()
        for bad in (good.replace("CHECKS_OK", "FAILED"),
                    good.rsplit("\n", 1)[0],
                    good + "\nRESULT branchy rocket 0 200",
                    good.replace("RESULT branchy rocket 0 200", "RESULT branchy rocket 0 0"),
                    good.replace("RESULT branchy rocket 0 200", "RESULT bogus rocket 0 200")):
            with self.subTest(log=bad[:80]), self.assertRaises(ValueError):
                TIMING.parse_results(bad)

    @unittest.skipUnless(shutil.which("cc"), "Host C compiler required")
    def test_harness_correctness_and_failure_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            objects = []
            for tune in TIMING.TUNES:
                for kernel in TIMING.KERNELS:
                    obj = out / f"{kernel}.{tune}.o"
                    subprocess.run(["cc", "-O2", f"-D{kernel}={kernel}_{tune.replace('-', '_')}",
                                    "-c", str(SOURCE / "kernels" / f"{kernel}.c"), "-o", str(obj)], check=True)
                    objects.append(str(obj))
            binary = out / "check"
            for flags, marker in (([], "CHECKS_OK"), (["-DBENCH_SUITE"], "SUITE_OK")):
                subprocess.run(["cc", "-O2", "-DHOST_CHECK", *flags, str(SOURCE / "timing.c"),
                                *objects, "-o", str(binary)], check=True)
                result = subprocess.run([str(binary)], capture_output=True, text=True, check=True)
                self.assertIn(marker, result.stdout)
            # Replace one kernel with an incorrect implementation; timing must
            # abort instead of reporting a plausible-looking speedup.
            stub = out / "bad.c"
            stub.write_text("int branchy_rocket(const int *a, int n) { return 0; }\n")
            subprocess.run(["cc", "-O2", "-c", str(stub), "-o", objects[0]], check=True)
            for flags in ([], ["-DBENCH_SUITE"]):
                subprocess.run(["cc", "-O2", "-DHOST_CHECK", *flags, str(SOURCE / "timing.c"),
                                *objects, "-o", str(binary)], check=True)
                self.assertEqual(subprocess.run([str(binary)], capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
