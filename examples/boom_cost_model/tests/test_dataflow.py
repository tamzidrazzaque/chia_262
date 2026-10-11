"""Validate unsigned reference results, failure detection, and complete logs."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from run_dataflow import KERNELS, MARKER, cases, parse_dataflow_results
from run_timing import TUNES


class TestDataflow(unittest.TestCase):
    def test_complete_measurements_and_rejections(self):
        lines = [MARKER]
        for n, k, w in cases():
            for t in range(3):
                v = 200 if t == 0 else 100
                lines.append(f"D {n} {k} {w} {t} {v} {v} {v}")
        good = "\n".join(lines)
        rows = parse_dataflow_results(good)
        self.assertEqual(len(rows), 54)
        self.assertEqual(rows[1]["speedup"], 2)
        for bad in (good.replace("DATAFLOW_OK", "FAILED"),
                    good.rsplit("\n", 1)[0], good + "\n" + lines[1],
                    good.replace("200 200 200", "0 200 200", 1),
                    good.replace("D 32 0 1", "D 32 0 8", 1),
                    good.replace("200 200 200", "200 200", 1)):
            with self.subTest(log=bad[:80]), self.assertRaises(ValueError):
                parse_dataflow_results(bad)

    @unittest.skipUnless(shutil.which("cc"), "Host C compiler required")
    def test_harness_correctness_and_each_kernel_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            objects = []
            for tune in TUNES:
                for kernel in KERNELS:
                    obj = out / f"{kernel}.{tune}.o"
                    subprocess.run(["cc", "-O3", "-Wall", "-Wextra", "-Werror",
                                    f"-D{kernel}={kernel}_{tune.replace('-', '_')}",
                                    "-c", str(SOURCE / "kernels" / f"{kernel}.c"),
                                    "-o", str(obj)], check=True)
                    objects.append(obj)
            binary = out / "check"

            def link(parts):
                subprocess.run(["cc", "-O2", "-DHOST_CHECK", "-fsanitize=undefined",
                                str(SOURCE / "dataflow_timing.c"),
                                *map(str, parts), "-o", str(binary)], check=True)

            link(objects)
            result = subprocess.run([str(binary)], text=True, capture_output=True, check=True)
            self.assertIn(MARKER, result.stdout)
            self.assertEqual(result.stderr, "")
            self.assertEqual(sum(line.startswith("D ") for line in result.stdout.splitlines()), 54)
            for k, kernel in enumerate(KERNELS):
                stub = out / "bad.c"
                stub.write_text(f"#include <stdint.h>\nuint32_t {kernel}_rocket"
                                "(const uint32_t *a, int n, int w) { return 0; }\n")
                replacement = out / "bad.o"
                subprocess.run(["cc", "-c", str(stub), "-o", str(replacement)], check=True)
                parts = list(objects)
                parts[k] = replacement
                link(parts)
                result = subprocess.run([str(binary)], capture_output=True)
                self.assertEqual(result.returncode, k + 1)
                self.assertNotIn(MARKER.encode(), result.stdout)


if __name__ == "__main__":
    unittest.main()
