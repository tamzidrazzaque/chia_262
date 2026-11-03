"""Validate the actual FireMarshal tar layout without booting a guest."""

import io
import tarfile

import pytest

from examples.rocket_cost_model.validate_zstd_guest import validate_archive


def archive(name, kind=tarfile.REGTYPE):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as stream:
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        stream.addfile(root)
        member = tarfile.TarInfo(name)
        member.type = kind
        if kind == tarfile.SYMTYPE:
            member.linkname = "/etc/passwd"
        stream.addfile(member)
    return buf.getvalue()


def test_accepts_firemarshal_root_directory_and_flat_files():
    validate_archive(archive("./job.json"))


@pytest.mark.parametrize("name,kind", [("..", tarfile.REGTYPE), ("../outside", tarfile.REGTYPE),
    ("/absolute", tarfile.REGTYPE), ("nested/file", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)])
def test_rejects_unsafe_extraction_members(name, kind):
    with pytest.raises(ValueError):
        validate_archive(archive(name, kind))
