"""Atomically update the tested random-loop module without restarting the UI."""

from __future__ import annotations

import hashlib
import json
import marshal
import os
import py_compile
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import CodeType

ROOT = Path(r"D:\codex\CodexWork\clash")
REPO = ROOT / "py-clash-bot"
WORK = ROOT / "work/startup-resume-repair-20261005"
BACKEND = ROOT / "outputs/wpf-desktop-stop-repair-20261004/backend"
SOURCE = REPO / "pyclashbot/bot/cn_random_mastery_loop.py"
EXPECTED_SOURCE = "90AF73DCA68C5C6E578F66DF795BF2724389499C242211858355368103A3531D"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def normalized(code):
    constants = tuple(normalized(value) if isinstance(value, CodeType) else value for value in code.co_consts)
    return code.replace(co_filename="<verified-source>", co_consts=constants)


def main():
    assert sys.version_info[:2] == (3, 12), sys.version
    assert digest(SOURCE) == EXPECTED_SOURCE
    os.environ["PYCLASHBOT_DATA_ROOT"] = str(ROOT)
    sys.path.insert(0, str(REPO))
    from pyclashbot.utils.process_ownership import ExclusiveFileLock, read_process_state, verified_process

    stage = WORK / "runtime-stage"
    stage.mkdir(exist_ok=True)
    target_code = BACKEND / "lib/pyclashbot/bot/cn_random_mastery_loop.pyc"
    target_source = BACKEND / "source/pyclashbot/bot/cn_random_mastery_loop.py"
    for path in (target_code, target_source):
        assert path.resolve().is_relative_to(BACKEND.resolve()) and path.is_file(), path
    staged_code = stage / "cn_random_mastery_loop.pyc"
    py_compile.compile(str(SOURCE), cfile=str(staged_code), dfile=str(SOURCE), doraise=True, optimize=0)
    expected = compile(SOURCE.read_bytes(), str(SOURCE), "exec", dont_inherit=True, optimize=0)
    assert normalized(marshal.loads(staged_code.read_bytes()[16:])) == normalized(expected)
    shutil.copy2(SOURCE, stage / "cn_random_mastery_loop.py")
    targets = [(stage / "cn_random_mastery_loop.py", target_source), (staged_code, target_code)]
    changes = []
    with ExclusiveFileLock(ROOT / "work/bot-processes.lock"), ExclusiveFileLock(ROOT / "work/cn-runner.lock"):
        state = read_process_state(ROOT / "work/bot-processes.json")
        for role, script in (("runner", "run_cn_1v1.py"), ("watchdog", "watch_cn_1v1.py")):
            owner = verified_process(state.get(f"{role}_pid"), REPO / "scripts" / script,
                                     state.get(f"{role}_created_at"), trusted_executables=(BACKEND / "ClashBackend.exe",))
            assert owner is None, f"An active {role} prevents updating its module"
        for staged, target in targets:
            backup = WORK / "before" / ("runtime-" + target.name)
            assert not backup.exists(), backup
            shutil.copy2(target, backup)
            before = digest(target)
            shutil.copy2(staged, target.with_suffix(target.suffix + ".repair.tmp"))
            os.replace(target.with_suffix(target.suffix + ".repair.tmp"), target)
            changes.append({"target": str(target), "before_sha256": before, "after_sha256": digest(target),
                            "rollback_file": str(backup)})
        assert digest(target_source) == EXPECTED_SOURCE
        assert normalized(marshal.loads(target_code.read_bytes()[16:])) == normalized(expected)
    record = {"status": "PASS_INSTALLED_RUNTIME_MODULE", "installed_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "python": sys.version, "source_sha256": EXPECTED_SOURCE, "changes": changes,
              "compiled_code_matches_tested_source": True, "frontend_restarted": False,
              "checkpoint_manually_modified": False}
    (WORK / "runtime-installation.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": record["status"], "source_sha256": EXPECTED_SOURCE, "updated_files": len(changes)}))


if __name__ == "__main__":
    main()
