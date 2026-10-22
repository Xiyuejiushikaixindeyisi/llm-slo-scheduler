#!/usr/bin/env python3
"""Verify an extracted candidate's complete file inventory without activation."""

import hashlib
import json
import sys
from pathlib import Path


def verify(root):
    data = json.loads((root / "SHA256.json").read_text())
    for name, expected in data["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("missing/escaping bundle member: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("checksum mismatch: " + name)
    print(
        json.dumps(
            {
                "verified_files": len(data["files"]),
                "version": data["version"],
                "activated": False,
            }
        )
    )


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
