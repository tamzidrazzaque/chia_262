"""Reproduce the observed __FILE__ contamination as a compiler correctness check."""

import shutil
import subprocess

import pytest

from examples.rocket_cost_model.prepare_zstd import compile_flags


def test_build_directory_does_not_change_embedded_file_paths(tmp_path):
    cc = shutil.which("cc")
    if not cc:
        pytest.skip("native compiler unavailable")
    binaries = []
    for name in ("original-long-prefix", "rebuilt-short"):
        root = tmp_path / name
        root.mkdir()
        source = root / "input.c"
        source.write_text('#include <stdio.h>\nint main(void){puts(__FILE__);return 0;}\n')
        binary = root / "program"
        subprocess.run([cc, *compile_flags(root, False), str(source), "-o", str(binary)], check=True, capture_output=True)
        assert subprocess.check_output([str(binary)], text=True).strip() == "/zstd-src/input.c"
        binaries.append(binary.read_bytes())
    assert binaries[0] == binaries[1]
