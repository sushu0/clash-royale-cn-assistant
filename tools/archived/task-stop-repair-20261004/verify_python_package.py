"""Verify saved source and frozen bytecode match the tested stop implementation."""

from __future__ import annotations

import hashlib
import json
import marshal
from pathlib import Path
from types import CodeType

ROOT = Path(r"D:\codex\CodexWork\clash")
TASK = ROOT / "work/task-stop-repair-20261004"
BACKEND = ROOT / "outputs/wpf-desktop-stop-repair-20261004/backend"


def normalize(code):
    constants = tuple(normalize(value) if isinstance(value, CodeType) else value for value in code.co_consts)
    return code.replace(co_filename="<verified-source>", co_consts=constants)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main():
    rows = []
    for item in json.loads((TASK / "backend-source-hashes.json").read_text(encoding="utf-8-sig")):
        relative = Path(item["file"])
        source = ROOT / "py-clash-bot" / relative
        assert digest(source) == item["sha256"], source
        if relative.parts[0] == "tests":
            continue
        packaged = BACKEND / relative if relative.parts[0] == "scripts" else BACKEND / "source" / relative
        bytecode = (BACKEND / "lib" / relative).with_suffix(".pyc")
        assert digest(packaged) == digest(source), packaged
        frozen_code = marshal.loads(bytecode.read_bytes()[16:])
        current_code = compile(source.read_bytes(), str(source), "exec", dont_inherit=True, optimize=0)
        assert normalize(frozen_code) == normalize(current_code), bytecode
        rows.append({"source": str(source), "source_sha256": digest(source), "packaged_source": str(packaged),
                     "packaged_bytecode": str(bytecode), "bytecode_sha256": digest(bytecode),
                     "compiled_code_equals_tested_source": True})
    record = {"status": "PASS", "files": rows, "count": len(rows), "backend_exe_sha256": digest(BACKEND / "ClashBackend.exe")}
    target = TASK / "package-verification/python-package-source-manifest.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS: {len(rows)} packaged Python sources and compiled code objects match tested source")


if __name__ == "__main__":
    main()
