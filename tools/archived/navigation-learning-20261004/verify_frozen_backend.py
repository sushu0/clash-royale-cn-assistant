"""Verify a built WPF backend without starting/stopping the robot or opening UI.

Preparation: --capture-baseline records only the current WPF files/shortcut.
Verification: compare copied sources, compiled code and all PNG/JSON resources,
then send only snapshot/reports/shutdown to an isolated read-only JSONL bridge.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import marshal
import shutil
import subprocess
import types
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

TASK = Path(__file__).resolve().parent
WORKSPACE = TASK.parents[1]
STORAGE = Path(r"D:\codex")
SHANGHAI = timezone(timedelta(hours=8))
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
READ_COMMANDS = ("snapshot", "reports", "shutdown")
COMPILED_FILES = (
    "scripts/cn_wpf_backend.py",
    "scripts/cn_windows_entry.py",
    "scripts/cn_desktop_entry.py",
    "scripts/cn_bot_control.py",
    "scripts/run_cn_1v1.py",
    "scripts/watch_cn_1v1.py",
    "scripts/stop_cn_1v1.py",
    "pyclashbot/bot/cn_random_mastery_loop.py",
    "pyclashbot/bot/cn_1v1_loop.py",
    "pyclashbot/bot/coords.py",
    "pyclashbot/bot/nav.py",
    "pyclashbot/bot/state_detect.py",
    "pyclashbot/detection/cn_daily_gift.py",
    "pyclashbot/detection/cn_page_navigation.py",
    "pyclashbot/utils/runtime_config.py",
)


def now():
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def owned(path: Path, root: Path = STORAGE) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path must stay inside {root}: {resolved}")
    return resolved


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata(path: Path):
    path = owned(path)
    row = {"path": str(path), "exists": path.is_file()}
    if row["exists"]:
        stat = path.stat()
        row.update(bytes=stat.st_size, sha256=digest(path), modified_at=datetime.fromtimestamp(stat.st_mtime, SHANGHAI).isoformat())
    return row


def write_json(path: Path, value):
    path = owned(path, TASK)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_shortcut(path: Path, workspace: Path):
    if not path.is_file():
        raise FileNotFoundError(path)
    shell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if not shell:
        raise RuntimeError("Existing PowerShell is required for read-only shortcut inspection")
    quoted = str(path).replace("'", "''")
    code = (
        "$ErrorActionPreference='Stop'\n"
        ". 'D:\\codex\\bin\\Initialize-CodexEnvironment.ps1'\n"
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
        "$shell = New-Object -ComObject WScript.Shell\n"
        f"$link = $shell.CreateShortcut('{quoted}')\n"
        "[ordered]@{target=$link.TargetPath;arguments=$link.Arguments;working_directory=$link.WorkingDirectory} | ConvertTo-Json -Compress\n"
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", code],
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=True,
        creationflags=CREATE_NO_WINDOW,
    )
    return json.loads(result.stdout)


def frontend_baseline(workspace: Path, app: Path, shortcut: Path):
    paths = {
        "executable": app / "ClashAssistant.Desktop.exe",
        "assembly": app / "ClashAssistant.Desktop.dll",
        "config": app / "wpf-runtime.json",
        "shortcut": shortcut,
    }
    files = {name: metadata(path) for name, path in paths.items()}
    config = json.loads(paths["config"].read_text(encoding="utf-8-sig"))
    shortcut_details = read_shortcut(shortcut, workspace)
    backend = owned(app / config["backend_path"])
    gates = {
        "all_files_exist": all(row["exists"] for row in files.values()),
        "data_root_matches": owned(Path(config["data_root"])) == workspace,
        "shortcut_targets_existing_wpf": Path(shortcut_details["target"]).resolve() == paths["executable"].resolve(),
        "shortcut_has_no_extra_arguments": not shortcut_details["arguments"],
    }
    return {
        "schema": "clash-wpf-deployment-baseline-v1",
        "created_at": now(),
        "workspace": str(workspace),
        "app_directory": str(app),
        "files": files,
        "config": config,
        "resolved_backend": str(backend),
        "shortcut": shortcut_details,
        "gates": gates,
        "passed": all(gates.values()),
        "ui_input_sent": False,
        "robot_start_or_stop_requested": False,
    }


def compare_frontend(baseline, current, backend: Path, allow_pointer_change: bool):
    same = {name: row.get("sha256") == current["files"][name].get("sha256") for name, row in baseline["files"].items()}
    old_config, new_config = baseline["config"], current["config"]
    config_without_backend_equal = (
        {k: v for k, v in old_config.items() if k != "backend_path"}
        == {k: v for k, v in new_config.items() if k != "backend_path"}
    )
    config_allowed = (
        config_without_backend_equal and Path(current["resolved_backend"]) == backend
        if allow_pointer_change
        else same["config"]
    )
    gates = {
        "baseline_was_valid": baseline.get("passed") is True,
        "current_wpf_identity_valid": current["passed"],
        "wpf_exe_unchanged": same["executable"],
        "wpf_dll_unchanged": same["assembly"],
        "desktop_shortcut_unchanged": same["shortcut"] and baseline["shortcut"] == current["shortcut"],
        "only_authorized_config_change": config_allowed,
    }
    return {"passed": all(gates.values()), "gates": gates, "file_hash_equal": same, "current": current}


def compare_files(source_root: Path, packaged_root: Path, relative_paths):
    rows = []
    for relative in relative_paths:
        source, packaged = owned(source_root / relative), owned(packaged_root / relative)
        source_hash = digest(source)
        package_hash = digest(packaged) if packaged.is_file() else None
        rows.append({"relative": relative.as_posix(), "source_sha256": source_hash, "packaged_sha256": package_hash, "matches": source_hash == package_hash})
    return {"passed": all(row["matches"] for row in rows), "count": len(rows), "differences": [row["relative"] for row in rows if not row["matches"]], "files": rows}


def normalized_constant(value):
    if isinstance(value, types.CodeType):
        return code_identity(value)
    if value is None or isinstance(value, (bool, int, str)):
        return [type(value).__name__, value]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, (float, complex)):
        return [type(value).__name__, repr(value)]
    if isinstance(value, tuple):
        return ["tuple", [normalized_constant(item) for item in value]]
    if isinstance(value, frozenset):
        items = [normalized_constant(item) for item in value]
        return ["frozenset", sorted(items, key=lambda item: json.dumps(item, sort_keys=True))]
    if value is Ellipsis:
        return ["ellipsis"]
    raise ValueError(f"Unsupported compiled constant type: {type(value).__name__}")


def code_identity(code):
    # Compare actual executable contents, ignoring build-path/line metadata.
    return {
        "code": code.co_code.hex(),
        "constants": [normalized_constant(item) for item in code.co_consts],
        "names": code.co_names,
        "varnames": code.co_varnames,
        "freevars": code.co_freevars,
        "cellvars": code.co_cellvars,
        "name": code.co_name,
        "qualname": code.co_qualname,
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "flags": code.co_flags,
        "stacksize": code.co_stacksize,
        "exceptiontable": code.co_exceptiontable.hex(),
    }


def code_digest(code):
    encoded = json.dumps(code_identity(code), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def compare_compiled(source_root: Path, backend_root: Path):
    rows = []
    for relative in COMPILED_FILES:
        source = owned(source_root / relative)
        compiled = owned(backend_root / "lib" / Path(relative).with_suffix(".pyc"))
        row = {"relative": relative, "compiled": str(compiled), "matches": False}
        try:
            data = compiled.read_bytes()
            if len(data) < 16 or data[:4] != importlib.util.MAGIC_NUMBER:
                raise ValueError("Compiled Python version/magic mismatch")
            # Locally generated cx_Freeze code; marshal loading does not execute it.
            packaged_code = marshal.loads(data[16:])
            if not isinstance(packaged_code, types.CodeType):
                raise ValueError("Packaged bytecode is not a code object")
            row["compiled_sha256"] = hashlib.sha256(data).hexdigest()
            row["semantic_sha256"] = code_digest(packaged_code)
            for optimization in (0, 1, 2):
                expected = compile(source.read_bytes(), str(source), "exec", dont_inherit=True, optimize=optimization)
                if code_digest(expected) == row["semantic_sha256"]:
                    row.update(matches=True, optimization=optimization)
                    break
        except (OSError, EOFError, ValueError, TypeError, SyntaxError) as error:
            row["error"] = f"{type(error).__name__}: {error}"
        rows.append(row)
    return {"passed": all(row["matches"] for row in rows), "count": len(rows), "differences": [row["relative"] for row in rows if not row["matches"]], "files": rows}


def runtime_evidence(workspace: Path):
    protected = [
        workspace / "work" / "bot-processes.json",
        workspace / "work" / "random-mastery" / "checkpoint.json",
        workspace / "outputs" / "random-mastery-live-status.json",
    ]
    reports = workspace / "outputs" / "error-reports"
    if reports.is_dir():
        protected.extend(path for path in reports.rglob("*") if path.is_file())
    return {str(path.relative_to(workspace)): digest(owned(path, workspace)) for path in sorted(protected) if path.is_file()}


def probe_backend(executable: Path, workspace: Path):
    before = runtime_evidence(workspace)
    requests = [{"id": str(uuid.uuid4()), "command": command} for command in READ_COMMANDS]
    command = [str(executable), "--data-root", str(workspace), "--read-only"]
    child = subprocess.Popen(
        command,
        cwd=workspace,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=CREATE_NO_WINDOW,
    )
    try:
        stdout, stderr = child.communicate("\n".join(json.dumps(request) for request in requests) + "\n", timeout=40)
    except subprocess.TimeoutExpired:
        # Only the read-only bridge created here, never any existing process/tree.
        child.kill()
        stdout, stderr = child.communicate(timeout=5)
    after = runtime_evidence(workspace)
    responses, parse_error = [], None
    try:
        responses = [json.loads(line) for line in stdout.splitlines()]
    except json.JSONDecodeError as error:
        parse_error = str(error)
    valid = len(responses) == len(requests) and all(
        isinstance(response, dict) and response.get("id") == request["id"] and response.get("ok") is True
        for request, response in zip(requests, responses)
    )
    snapshot = responses[0].get("data", {}) if valid else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    runtime = snapshot.get("runtime", {})
    runtime = runtime if isinstance(runtime, dict) else {}
    shutdown = responses[-1].get("data", {}) if valid else {}
    shutdown = shutdown if isinstance(shutdown, dict) else {}
    reports = responses[1].get("data", {}) if valid else {}
    reports = reports if isinstance(reports, dict) else {}
    data_root, runtime_python = runtime.get("data_root"), runtime.get("python")
    scopes = snapshot.get("scopes")
    gates = {
        "exit_zero": child.returncode == 0,
        "strict_three_jsonl_responses": valid and parse_error is None,
        "frozen_backend": snapshot.get("frozen") is True,
        "data_root_matches": isinstance(data_root, str) and bool(data_root) and Path(data_root).resolve() == workspace,
        "runtime_executable_matches": isinstance(runtime_python, str) and bool(runtime_python) and Path(runtime_python).resolve() == executable,
        "snapshot_is_from_probe_process": snapshot.get("bridge_pid") == child.pid,
        "snapshot_shape_valid": snapshot.get("state") in ("running", "starting", "stopped", "paused") and isinstance(scopes, dict) and set(scopes) == {"random", "567", "hog", "all"},
        "reports_shape_valid": isinstance(reports.get("reports"), list),
        "shutdown_confirmed": shutdown.get("shutdown") is True,
        "process_checkpoint_reports_unchanged": before == after,
    }
    return {
        "passed": all(gates.values()), "gates": gates, "command": command, "pid": child.pid,
        "requested_commands": list(READ_COMMANDS), "exit_code": child.returncode,
        "parse_error": parse_error, "stderr": stderr, "responses": responses,
        "protected_hashes_before": before, "protected_hashes_after": after,
        "robot_start_or_stop_requested": False, "game_input_sent": False,
    }


def verify(args, workspace: Path, app: Path, shortcut: Path):
    backend = owned(args.backend)
    if backend.name != "ClashBackend.exe" or not backend.is_file():
        raise FileNotFoundError(f"Newly built ClashBackend.exe is required: {backend}")
    baseline = json.loads(owned(args.baseline, TASK).read_text(encoding="utf-8"))
    current = frontend_baseline(workspace, app, shortcut)
    source = workspace / "py-clash-bot"
    python_relative = sorted(path.relative_to(source / "pyclashbot") for path in (source / "pyclashbot").rglob("*.py"))
    python_relative.append(Path("__version__"))
    script_relative = sorted(path.relative_to(source / "scripts") for path in (source / "scripts").rglob("*") if path.is_file() and path.suffix in {".py", ".ps1"})
    image_source = source / "pyclashbot" / "detection" / "reference_images"
    image_package = backend.parent / "pyclashbot" / "detection" / "reference_images"
    image_relative = sorted(path.relative_to(image_source) for path in image_source.rglob("*") if path.is_file() and path.suffix.lower() in {".png", ".json"})
    checks = {
        "frontend_preserved": compare_frontend(baseline, current, backend, args.allow_backend_pointer_change),
        "copied_python_sources": compare_files(source / "pyclashbot", backend.parent / "source" / "pyclashbot", python_relative),
        "copied_scripts": compare_files(source / "scripts", backend.parent / "scripts", script_relative),
        "compiled_modules": compare_compiled(source, backend.parent),
        "reference_assets": compare_files(image_source, image_package, image_relative),
    }
    packaged_assets = {
        path.relative_to(image_package)
        for path in image_package.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".json"}
    }
    extras = sorted(path.as_posix() for path in packaged_assets - set(image_relative))
    checks["reference_assets"]["unexpected_packaged_files"] = extras
    checks["reference_assets"]["passed"] &= not extras
    backend_config = json.loads((backend.parent / "desktop-runtime.json").read_text(encoding="utf-8"))
    checks["runtime_config"] = {"passed": Path(backend_config["data_root"]).resolve() == workspace, "config": backend_config}
    checks["readonly_probe"] = probe_backend(backend, workspace) if all(check["passed"] for check in checks.values()) else {"passed": False, "skipped": "Structural/hash gates must pass before executing a bridge"}
    if not checks["readonly_probe"].get("skipped"):
        checks["frontend_preserved_after_probe"] = compare_frontend(
            baseline, frontend_baseline(workspace, app, shortcut), backend, args.allow_backend_pointer_change
        )
    return {
        "schema": "clash-wpf-frozen-backend-verification-v1", "created_at": now(),
        "backend": metadata(backend), "workspace": str(workspace), "checks": checks,
        "passed": all(check["passed"] for check in checks.values()),
        "ui_input_sent": False, "robot_start_or_stop_requested": False,
        "limitation": "This verifies packaging and read-only JSONL. Actual UI switching, navigation and infinite battle cycles require separate live evidence.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument("--app-directory", type=Path, default=WORKSPACE / "outputs/wpf-desktop-20261004/app")
    parser.add_argument("--shortcut", type=Path, default=Path(r"D:\codex\profile\Desktop\皇室战争助手.lnk"))
    parser.add_argument("--backend", type=Path, default=WORKSPACE / "outputs/wpf-desktop-navigation-20261004/backend/ClashBackend.exe")
    parser.add_argument("--baseline", type=Path, default=TASK / "deployment-baseline.json")
    parser.add_argument("--report", type=Path, default=TASK / "frozen-backend-verification.json")
    parser.add_argument("--capture-baseline", action="store_true", help="Only save current WPF hashes/shortcut; no backend is launched")
    parser.add_argument("--allow-backend-pointer-change", action="store_true", help="Permit only appconfig backend_path to change to --backend")
    args = parser.parse_args()
    workspace, app, shortcut = owned(args.workspace), owned(args.app_directory), owned(args.shortcut)
    if args.capture_baseline:
        if args.baseline.exists():
            raise FileExistsError("Preserve the existing deployment baseline; choose a new --baseline path if a new baseline is intended")
        result = frontend_baseline(workspace, app, shortcut)
        write_json(args.baseline, result)
        print(json.dumps({"baseline": str(args.baseline), "passed": result["passed"], "backend_launched": False}))
    else:
        result = verify(args, workspace, app, shortcut)
        write_json(args.report, result)
        print(json.dumps({"report": str(args.report), "passed": result["passed"], "gates": {name: check["passed"] for name, check in result["checks"].items()}}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
