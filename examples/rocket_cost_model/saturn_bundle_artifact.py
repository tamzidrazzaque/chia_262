"""Transferable private workload bundles, separate from FireMarshal images.

Archive bytes may contain licensed material. Pass these artifacts only over the
authorized private CHIA cluster; never log, commit or expose their repr.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import tarfile


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SaturnBundle:
    """Content-bound bundle transport; not a bootable FireMarshalArtifact."""

    archive: bytes = field(repr=False)
    archive_sha256: str
    manifest_sha256: str
    executable_sha256: str


def _members(artifact: SaturnBundle) -> dict[str, bytes]:
    if digest(artifact.archive) != artifact.archive_sha256:
        raise ValueError('bundle transport archive changed')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(artifact.archive), mode='r:') as archive:
        for member in archive:
            path = Path(member.name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts \
                    or str(path) != member.name or member.name in files:
                raise ValueError('unsafe or duplicate bundle transport member')
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError('missing transport member bytes')
            files[member.name] = stream.read()
    manifest_data = files.get('manifest.json')
    if manifest_data is None or digest(manifest_data) != artifact.manifest_sha256:
        raise ValueError('bundle transport manifest changed')
    manifest = json.loads(manifest_data)
    expected = manifest.get('files_sha256')
    if not isinstance(expected, dict) or set(files) != set(expected) | {'manifest.json'}:
        raise ValueError('bundle transport member set differs from manifest')
    for name, sha in expected.items():
        if digest(files[name]) != sha:
            raise ValueError('bundle transport payload changed')
    executable = manifest.get('executable')
    if executable not in expected or expected[executable] != artifact.executable_sha256:
        raise ValueError('bundle transport executable changed')
    if manifest.get('role') not in ('1-scalar', '2-generic-vector', '3-saturn-aware'):
        raise ValueError('bundle transport requires vector baseline or candidate')
    return files


def artifact_role(artifact: SaturnBundle) -> str:
    """Return the role only after verifying the complete transported bundle."""
    return json.loads(_members(artifact)['manifest.json'])['role']


def pack(bundle: Path) -> SaturnBundle:
    """Package regular files and validate every member against the manifest."""
    manifest_data = (bundle / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_data)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:') as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_symlink() or (not path.is_file() and not path.is_dir()):
                raise ValueError('bundle transport forbids nonregular files')
            if path.is_file():
                archive.add(path, arcname=path.relative_to(bundle).as_posix(), recursive=False)
    data = buffer.getvalue()
    artifact = SaturnBundle(data, digest(data), digest(manifest_data),
                            manifest['files_sha256'][manifest['executable']])
    _members(artifact)
    return artifact


def unpack(artifact: SaturnBundle, destination: Path) -> dict:
    """Verify before writing into a fresh private directory; never overwrite."""
    files = _members(artifact)
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
        target.chmod(0o600)
    executable = json.loads(files['manifest.json'])['executable']
    (destination / executable).chmod(0o500)
    return {'bundle_sha256': artifact.manifest_sha256,
            'role': json.loads(files['manifest.json'])['role'],
            'executable_sha256': artifact.executable_sha256,
            'archive_sha256': artifact.archive_sha256,
            'member_count': len(files)}
