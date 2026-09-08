"""SHA-256 manifests for data pulls. Git for code, Notion for decisions, Drive for bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, obj) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, sort_keys=True)
    path.write_text(text + "\n")
    return sha256_file(path)


def write_manifest(root: Path, dest: Path | None = None) -> Path:
    lines = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "manifest.sha256":
            continue
        rel = path.relative_to(root).as_posix()
        lines.append(f"{sha256_file(path)}  {rel}")
    dest = dest or (root / "manifest.sha256")
    dest.write_text("\n".join(lines) + "\n")
    return dest


DRIVE_FOLDER_ID = "1xOQAz-RCBxfArm36OFWs5fG8lwVBjigG"
DRIVE_FOLDER_NAME = "Consistency Capital — Data Pulls"
