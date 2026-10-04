"""Capture portable package identity and compare its source resource copies."""

from __future__ import annotations

import ctypes
import hashlib
import json
import marshal
import struct
from datetime import UTC, datetime
from pathlib import Path

TASK = Path(r"D:\codex\CodexWork\clash")
SOURCE = TASK / "py-clash-bot"
PACKAGE = TASK / "outputs" / "desktop-app-history-20261004"
WORK = TASK / "work" / "error-history-20261004"
CRITICAL = (
    "scripts/cn_bot_control.py",
    "scripts/watch_cn_1v1.py",
    "pyclashbot/interface/cn_console_theme.py",
    "pyclashbot/interface/cn_native_view.py",
    "pyclashbot/interface/cn_desktop_shell.py",
    "pyclashbot/utils/cn_error_report.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    files = []
    for relative in CRITICAL:
        original = SOURCE / relative
        resource = PACKAGE / ("source/" + relative if relative.startswith("pyclashbot/") else relative)
        compiled = PACKAGE / "lib" / Path(relative).with_suffix(".pyc")
        files.append(
            {
                "source": str(original),
                "packaged_copy": str(resource),
                "source_sha256": digest(original),
                "package_sha256": digest(resource),
                "matches": digest(original) == digest(resource),
                "compiled_module": str(compiled),
                "compiled_module_exists": compiled.is_file(),
                "compiled_module_sha256": digest(compiled),
                "compiled_code_matches_source": marshal.loads(compiled.read_bytes()[16:])
                == compile(original.read_bytes(), str(original), "exec", dont_inherit=True),
            }
        )
    exe = PACKAGE / "ClashAssistant.exe"
    content = exe.read_bytes()
    pe_start = struct.unpack_from("<I", content, 0x3C)[0]
    subsystem = struct.unpack_from("<H", content, pe_start + 24 + 68)[0]
    shell = ctypes.WinDLL("shell32")
    shell.ExtractIconExW.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    shell.ExtractIconExW.restype = ctypes.c_uint
    icon_groups = shell.ExtractIconExW(str(exe), -1, None, None, 0)
    all_files = list(PACKAGE.rglob("*"))
    before = json.loads((WORK / "package-before.json").read_text(encoding="utf-8-sig"))
    prior_reports = [
        {"path": item["Path"], "preserved": Path(item["Path"]).is_file() and digest(Path(item["Path"])) == item["Sha256"].lower()}
        for item in before["ReportFiles"]
    ]
    result = {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "exe": str(exe),
        "exe_sha256": digest(exe),
        "exe_bytes": exe.stat().st_size,
        "pe_subsystem": subsystem,
        "gui_subsystem_verified": subsystem == 2,
        "embedded_icon_groups": icon_groups,
        "source_copy_checks": files,
        "all_six_source_copies_match": all(item["matches"] for item in files),
        "all_six_compiled_modules_present": all(item["compiled_module_exists"] for item in files),
        "all_six_compiled_modules_match_source": all(item["compiled_code_matches_source"] for item in files),
        "package_file_count": sum(path.is_file() for path in all_files),
        "package_bytes": sum(path.stat().st_size for path in all_files if path.is_file()),
        "frozen_self_check": json.loads((WORK / "frozen-self-check-final.json").read_text(encoding="utf-8")),
        "desktop_shortcut": json.loads((WORK / "desktop-shortcut.json").read_text(encoding="utf-8-sig")),
        "prior_executable": before["OldExe"],
        "prior_executable_preserved": digest(Path(before["OldExe"])) == before["OldExeSha256"].lower(),
        "prior_report_files": prior_reports,
        "prior_report_files_preserved": all(item["preserved"] for item in prior_reports),
    }
    target = WORK / "package-manifest.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert result["all_six_source_copies_match"]
    assert result["all_six_compiled_modules_present"]
    assert result["all_six_compiled_modules_match_source"]
    assert subsystem == 2 and icon_groups >= 1
    assert result["frozen_self_check"]["status"] == "ok"
    assert result["prior_executable_preserved"]
    assert result["prior_report_files_preserved"]
    print(target)
    print(json.dumps({key: result[key] for key in ("exe_sha256", "gui_subsystem_verified", "embedded_icon_groups", "all_six_source_copies_match", "package_file_count", "package_bytes")}, indent=2))


if __name__ == "__main__":
    main()
