"""Compiler preparation must reject a different baseline before writing files."""

import pytest

from examples.rocket_cost_model.prepare_compiler import prepare


def test_wrong_baseline_cannot_configure_or_download(tmp_path):
    prefix = tmp_path / "compiler"
    binary = prefix / "bin/riscv64-unknown-linux-gnu-gcc"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"wrong original compiler")
    root = tmp_path / "build"
    with pytest.raises(ValueError, match="audited baseline"):
        prepare(root, prefix)
    assert not root.exists()
