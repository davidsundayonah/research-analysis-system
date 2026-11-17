"""Validate that a release candidate is an Inno Setup installer executable."""

from __future__ import annotations

import sys
from pathlib import Path


def is_inno_setup_installer(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 1024 * 1024:
            return False
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                return False
            overlap = b""
            while chunk := stream.read(1024 * 1024):
                if b"Inno Setup Setup Data" in overlap + chunk:
                    return True
                overlap = chunk[-22:]
        return False
    except OSError:
        return False


if __name__ == "__main__":
    candidate = Path(sys.argv[1]) if len(sys.argv) == 2 else Path()
    if not is_inno_setup_installer(candidate):
        raise SystemExit(
            f"Not a valid Inno Setup installer: {candidate}. "
            "Refusing to publish a portable application executable as the installer."
        )
    print(f"Validated Inno Setup installer: {candidate}")
