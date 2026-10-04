"""Check a narrow logger rebuild against the preserved frozen backend closure."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import marshal
import types
from datetime import UTC, datetime
from pathlib import Path

TASK = Path(r"D:\codex\CodexWork\clash")
BEFORE = TASK / "work/ui-polish-20261004/package-before/backend"
AFTER = TASK / "outputs/wpf-desktop-20261004/backend"
EVIDENCE = TASK / "work/ui-polish-20261004/final-package-verification"
ALLOWED_SCRIPT_CHANGES = {"cn_wpf_backend.py", "build_wpf_backend.py"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path) -> dict[str, dict]:
    return {
        path.relative_to(root).as_posix(): {"sha256": digest(path), "bytes": path.stat().st_size}
        for path in root.rglob("*")
        if path.is_file()
    }


def source_diff(folder: str, allowed: set[str]) -> dict:
    old = inventory(BEFORE / folder)
    new = inventory(AFTER / folder)
    differences = []
    for name in sorted(old.keys() | new.keys()):
        if old.get(name) == new.get(name):
            continue
        differences.append({"path": name, "before": old.get(name), "after": new.get(name), "allowed": name in allowed})
    return {
        "folder": folder,
        "before_file_count": len(old),
        "after_file_count": len(new),
        "differences": differences,
        "only_explicit_changes": all(item["allowed"] and item["before"] and item["after"] for item in differences),
    }


def code(path: Path) -> types.CodeType:
    content = path.read_bytes()
    assert content[:4] == importlib.util.MAGIC_NUMBER, path
    result = marshal.loads(content[16:])
    assert isinstance(result, types.CodeType), path
    return result


def normalized(value):
    if isinstance(value, types.CodeType):
        return value.replace(co_filename="frozen-core", co_consts=tuple(normalized(item) for item in value.co_consts))
    if isinstance(value, tuple):
        return tuple(normalized(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(normalized(item) for item in value)
    return value


def bytecode_diff(folder: str, allowed: set[str]) -> dict:
    old_paths = {path.relative_to(BEFORE / folder).as_posix(): path for path in (BEFORE / folder).rglob("*.pyc")}
    new_paths = {path.relative_to(AFTER / folder).as_posix(): path for path in (AFTER / folder).rglob("*.pyc")}
    checks = []
    for name in sorted(old_paths.keys() | new_paths.keys()):
        old = old_paths.get(name)
        new = new_paths.get(name)
        matches = bool(old and new and normalized(code(old)) == normalized(code(new)))
        checks.append({"path": name, "code_matches": matches, "allowed_change": name in allowed})
    return {"folder": folder, "module_count": len(checks), "checks": checks,
            "only_explicit_code_changes": all(item["code_matches"] or item["allowed_change"] for item in checks)}


def main():
    sources = [
        source_diff("source/pyclashbot", set()),
        source_diff("scripts", ALLOWED_SCRIPT_CHANGES),
        source_diff("assets", set()),
    ]
    compiled = [
        bytecode_diff("lib/pyclashbot", set()),
        bytecode_diff("lib/scripts", {"cn_wpf_backend.pyc", "build_wpf_backend.pyc"}),
    ]
    logger_source = AFTER / "scripts/cn_wpf_backend.py"
    logger_code = AFTER / "lib/scripts/cn_wpf_backend.pyc"
    logger_matches = normalized(code(logger_code)) == normalized(compile(logger_source.read_bytes(), str(logger_source), "exec", dont_inherit=True))
    config = json.loads((AFTER / "desktop-runtime.json").read_text(encoding="utf-8"))
    result = {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "core_source_origin": str(BEFORE),
        "published_backend": str(AFTER),
        "allowed_source_changes": sorted(ALLOWED_SCRIPT_CHANGES),
        "source_tree_checks": sources,
        "compiled_module_checks": compiled,
        "only_allowed_source_files_changed": all(item["only_explicit_changes"] for item in sources),
        "core_executed_bytecode_unchanged_ignoring_source_filename": all(item["only_explicit_code_changes"] for item in compiled),
        "logger_source_sha256": digest(logger_source),
        "logger_compiled_sha256": digest(logger_code),
        "logger_compiled_matches_published_source": logger_matches,
        "runtime_configuration": config,
        "data_root_preserved": Path(config["data_root"]).resolve() == TASK,
        "original_backend_exe_sha256": digest(BEFORE / "ClashBackend.exe"),
        "published_backend_exe_sha256": digest(AFTER / "ClashBackend.exe"),
        "bot_commands_sent": False,
    }
    (EVIDENCE / "backend-lineage-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert result["only_allowed_source_files_changed"], "Unapproved source/resource difference in frozen core"
    assert result["core_executed_bytecode_unchanged_ignoring_source_filename"], "Unapproved executed core code difference"
    assert logger_matches, "Logger frozen code differs from packaged narrow patch source"
    assert result["data_root_preserved"], "Backend data root changed"
    print(json.dumps({key: result[key] for key in ("only_allowed_source_files_changed", "core_executed_bytecode_unchanged_ignoring_source_filename", "logger_compiled_matches_published_source", "data_root_preserved")}, indent=2))


if __name__ == "__main__":
    main()
