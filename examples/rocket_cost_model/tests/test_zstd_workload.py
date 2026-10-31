"""Validate real-input preservation and failure handling, without FPGA timing."""

from pathlib import Path
import subprocess
import tarfile

from examples.rocket_cost_model.prepare_zstd import corpus


def test_corpus_preserves_real_bytes_and_is_reproducible(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.c").write_bytes(b"int main(void) { return 0; }\n")
    first, second = tmp_path / "a.tar", tmp_path / "b.tar"
    a = corpus(source, ["a.c"], first)
    b = corpus(source, ["a.c"], second)
    assert a == b and first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        assert archive.extractfile("a.c").read() == (source / "a.c").read_bytes()
        assert archive.getmember("a.c").mtime == 0


def test_application_failure_is_recorded_not_scored(tmp_path):
    fake = tmp_path / "broken-zstd"
    fake.write_text("#!/bin/sh\nexit 7\n")
    fake.chmod(0o755)
    data = tmp_path / "input.tar"
    data.write_bytes(b"input")
    output = tmp_path / "result"
    script = Path(__file__).parents[1] / "run_zstd.sh"
    result = subprocess.run(["bash", str(script), str(fake), str(data), str(output)], capture_output=True)
    assert result.returncode == 7
    assert (output / "job.status").read_text().strip() == "7"
    assert not (output / "correctness.txt").exists()


def test_completed_run_cannot_be_overwritten(tmp_path):
    output = tmp_path / "result"
    output.mkdir()
    (output / "job.status").write_text("0\n")
    data = tmp_path / "input"
    data.write_bytes(b"bytes")
    script = Path(__file__).parents[1] / "run_zstd.sh"
    result = subprocess.run(["bash", str(script), "/bin/false", str(data), str(output)], capture_output=True)
    assert result.returncode == 2
    assert (output / "job.status").read_text() == "0\n"
