"""Check new workload references, forced probes, and malformed-log rejection."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
import run_probes
import run_workloads
from run_timing import TUNES

PROFILES = ((run_workloads, "W", "workload_timing.c", run_workloads.parse_workload_results),
            (run_probes, "P", "probe_timing.c", run_probes.parse_probe_results))


class TestWorkloads(unittest.TestCase):
    def test_parser_coverage_and_invalid_logs(self):
        for profile, prefix, _, parse in PROFILES:
            lines = [profile.MARKER]
            for k, n, p in profile.CASES:
                for t in range(3):
                    value = 200 if t == 0 else 100
                    lines.append(f"{prefix} {k} {n} {p} {t} {value} {value} {value}")
            text = "\n".join(lines)
            rows = parse(text)
            self.assertEqual(len(rows), len(profile.CASES) * 3)
            self.assertEqual(rows[1]["speedup"], 2)
            for bad in (text.replace(profile.MARKER, "FAILED"), text.rsplit("\n", 1)[0],
                        text + "\n" + lines[1], text.replace("200 200 200", "0 200 200", 1),
                        text.replace("200 200 200", "200 200", 1),
                        text.replace(lines[1], f"{prefix} 99 32 1 0 200 200 200")):
                with self.subTest(profile=prefix, log=bad[:80]), self.assertRaises(ValueError):
                    parse(bad)

    @unittest.skipUnless(shutil.which("cc"), "Host C compiler required")
    def test_harness_correctness_output_validation_and_failure_detection(self):
        for profile, prefix, harness, _ in PROFILES:
            with self.subTest(profile=prefix), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                objects = []
                for tune in TUNES:
                    for kernel in profile.KERNELS:
                        obj = out / f"{kernel}.{tune}.o"
                        subprocess.run(["cc", "-O3", "-Wall", "-Wextra", "-Werror",
                                        "-DHOST_CHECK", "-fsanitize=undefined",
                                        f"-D{kernel}={kernel}_{tune.replace('-', '_')}",
                                        "-c", str(SOURCE / "kernels" / f"{kernel}.c"),
                                        "-o", str(obj)], check=True)
                        objects.append(obj)
                binary = out / "check"

                def link(parts):
                    subprocess.run(["cc", "-O2", "-DHOST_CHECK", "-Wall", "-Wextra", "-Werror",
                                    "-fsanitize=undefined", str(SOURCE / harness),
                                    *map(str, parts), "-o", str(binary)], check=True)

                link(objects)
                result = subprocess.run([str(binary)], capture_output=True, text=True, check=True)
                self.assertIn(profile.MARKER, result.stdout)
                self.assertEqual(result.stderr, "")
                self.assertEqual(sum(line.startswith(prefix + " ") for line in result.stdout.splitlines()), len(profile.CASES) * 3)
                for k, kernel in enumerate(profile.KERNELS):
                    stub = out / "bad.c"
                    stub.write_text(f"#include <stdint.h>\nuint32_t {kernel}_rocket"
                                    "(const uint32_t *a, uint32_t *out, int n, int p) { return 0; }\n")
                    replacement = out / "bad.o"
                    subprocess.run(["cc", "-c", str(stub), "-o", str(replacement)], check=True)
                    parts = list(objects)
                    parts[k] = replacement
                    link(parts)
                    failed = subprocess.run([str(binary)], capture_output=True)
                    self.assertEqual(failed.returncode, k + 1)
                    self.assertNotIn(profile.MARKER.encode(), failed.stdout)
                    # Keep the correct checksum but corrupt one output. This
                    # must fail even when the returned aggregate looks right.
                    oracle = out / "oracle.o"
                    subprocess.run(["cc", "-O3", "-DHOST_CHECK", "-fsanitize=undefined",
                                    f"-D{kernel}={kernel}_oracle", "-c",
                                    str(SOURCE / "kernels" / f"{kernel}.c"),
                                    "-o", str(oracle)], check=True)
                    stub.write_text(f"#include <stdint.h>\nuint32_t {kernel}_oracle"
                                    "(const uint32_t *, uint32_t *, int, int);\n"
                                    f"uint32_t {kernel}_rocket"
                                    "(const uint32_t *a, uint32_t *out, int n, int p) { "
                                    f"uint32_t value = {kernel}_oracle(a,out,n,p); "
                                    "out[0] ^= 1u; return value; }\n")
                    subprocess.run(["cc", "-c", str(stub), "-o", str(replacement)], check=True)
                    link(parts + [oracle])
                    corrupted = subprocess.run([str(binary)], capture_output=True)
                    self.assertEqual(corrupted.returncode, k + 1)
                    self.assertNotIn(profile.MARKER.encode(), corrupted.stdout)


if __name__ == "__main__":
    unittest.main()
