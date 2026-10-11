"""Archive exact experiment sources and linked assembly without reading timings."""
import argparse
import json
from pathlib import Path
import subprocess

from run_timing import TUNES, file_hash


def prepare(root, objdump):
    """Verify recorded inputs, preserve sources, and save disassembly manifests."""
    source = Path(__file__).resolve().parent
    archive = root / "sources"
    archive.mkdir(exist_ok=True)
    manifests = []
    for layout in range(3):
        directory = root / f"medium-layout{layout}"
        metadata = directory / "metadata.json"
        meta = json.loads(metadata.read_text())
        binary = directory / "timing.riscv"
        if file_hash(binary) != meta["binary_sha256"]:
            raise ValueError("Binary differs from recorded experiment")
        for name, digest in meta["source_sha256"].items():
            if Path(name).name != name:
                raise ValueError("Source names must be basenames")
            saved = archive / name
            if saved.exists():
                if file_hash(saved) != digest:
                    raise ValueError("Existing source archive does not match this run")
            else:
                original = source / name
                if not original.is_file():
                    original = source / "kernels" / name
                if file_hash(original) != digest:
                    raise ValueError("Source changed since compilation; cannot archive exact input")
                saved.write_bytes(original.read_bytes())
        manifest = {"metadata_sha256": file_hash(metadata), "binary_sha256": file_hash(binary),
                    "disassembly_sha256": {}}
        for symbol in meta["kernel_addresses"]:
            for tune in TUNES:
                suffix = "_" + tune.replace("-", "_")
                if symbol.endswith(suffix):
                    kernel = symbol.removesuffix(suffix)
                    if not kernel or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in kernel):
                        raise ValueError("Invalid kernel symbol")
                    assembly = subprocess.check_output([str(objdump), "-d", f"--disassemble={symbol}", str(binary)], text=True)
                    path = directory / f"{kernel}.{tune}.linked.asm"
                    path.write_text(assembly)
                    manifest["disassembly_sha256"][path.name] = file_hash(path)
                    break
            else:
                raise ValueError("Kernel symbol lacks a known tune suffix")
        (directory / "artifacts.json").write_text(json.dumps(manifest, indent=2) + "\n")
        manifests.append(manifest)
    return manifests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--objdump", type=Path, required=True)
    args = parser.parse_args()
    if not args.objdump.is_file():
        parser.error("--objdump must be an existing executable")
    manifests = prepare(args.runs, args.objdump.resolve())
    print(f"Archived sources and disassembly for {len(manifests)} layouts; no timing logs read.")


if __name__ == "__main__":
    main()
