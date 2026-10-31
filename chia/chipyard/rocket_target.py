"""Acceptance gates for the public single-core Rocket F2 application target."""

import hashlib
from pathlib import Path

AGFI = "agfi-033a86c6e5d006fc8"
AFI = "afi-065352b4754b46048"
CHIPYARD = "19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe"
FIRESIM = "b7927ea504c501194eaec3e993c415f2270170f8"
ROCKET = "55bcad0f59436de98ea510334121de8546b9e9d7"
SDK = "80b34d3c25aff03353c0b4f2d304bb6067a5011d"
QUINTUPLET = ("f2-firesim-FireSim-WithDefaultFireSimBridges_"
              "WithFireSimHighPerfConfigTweaks_chipyard.RocketConfig-BaseF2Config")
SCALAR_FLAGS = "-mtune=rocket -fno-tree-loop-vectorize -fno-tree-slp-vectorize"


def validate_hardware(manifest: dict) -> None:
    """Reject unverified source/driver provenance or another FPGA target.

    Args:
        manifest: Private hardware manifest with verified build evidence and
            an existing matching driver bundle. Discovery JSON is insufficient.
    """
    expected = {"AGFI": AGFI, "AFI": AFI, "quintuplet": QUINTUPLET,
                "shell": "0x10212415", "Chipyard_revision": CHIPYARD,
                "FireSim_revision": FIRESIM, "Rocket_revision": ROCKET, "SDK_revision": SDK}
    for name, value in expected.items():
        if manifest.get(name) != value:
            raise ValueError(f"Rocket target mismatch: {name}")
    if manifest.get("matching_source_verified") is not True:
        raise ValueError("Rocket matching source/bridge metadata is not verified")
    # Evidence is recorded separately from the runnable driver. Both are pinned.
    for field in ("driver_bundle", "build_evidence"):
        name, digest = manifest.get(field), manifest.get(field + "_sha256")
        if not isinstance(name, str) or not Path(name).is_file():
            raise ValueError(f"Rocket {field} is missing")
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Rocket {field} hash differs")


def validate_image(manifest: dict, image: dict) -> None:
    """Check fresh AWS metadata against a previously verified local manifest."""
    validate_hardware(manifest)
    if (image.get("FpgaImageGlobalId") != AGFI or image.get("FpgaImageId") != AFI
            or image.get("ShellVersion") != manifest["shell"]
            or image.get("State", {}).get("Code") != "available"):
        raise ValueError("Rocket AWS image identity/state differs")
    tags = dict(part.split(":", 1) for part in image.get("Description", "").split(",")
                if ":" in part)
    if (tags.get("firesim-deployquintuplet") != QUINTUPLET
            or tags.get("firesim-commit") != FIRESIM):
        raise ValueError("Rocket AWS image build metadata differs")
