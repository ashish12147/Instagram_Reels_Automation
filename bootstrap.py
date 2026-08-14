#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import runpy
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = ROOT / "source_parts"
EXPECTED = {
    "app.py": "7a439e7752b69d822252bddf60c561af729f2fe53167b76bb269d94723fd3bcd",
    "instagram_reel_poster.py": "a39139d23929e7e3cdab73743c55ab56a1b966596fb0fe4f09f2b08771ba4da7",
}

def rebuild(name: str, target: Path) -> None:
    chunks = sorted(PARTS.glob(f"{name}.part*"))
    if not chunks:
        raise SystemExit(f"Missing source chunks for {name}")
    data = b"".join(p.read_bytes() for p in chunks)
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED[name]:
        raise SystemExit(f"Checksum mismatch for {name}: {digest}")
    target.write_bytes(data)

def main() -> None:
    runtime = Path(tempfile.mkdtemp(prefix="ig-reels-runtime-"))
    rebuild("instagram_reel_poster.py", runtime / "instagram_reel_poster.py")
    rebuild("app.py", runtime / "app.py")
    sys.path.insert(0, str(runtime))
    os.chdir(runtime)
    runpy.run_path(str(runtime / "app.py"), run_name="__main__")

if __name__ == "__main__":
    main()
