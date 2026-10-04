"""Stop only this task's recorded watchdog and runner process trees."""

# Native operational messages intentionally retain full-width Chinese punctuation.
# ruff: noqa: RUF001

import argparse
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import psutil

from pyclashbot.utils.persistence import atomic_write_json
from pyclashbot.utils.process_ownership import read_process_state, verified_process
from pyclashbot.utils.runtime_config import RESOURCE_ROOT


@contextmanager
def _suspend_watchdog(process, dry_run):
    """Freeze old watchdogs before enumeration, closing their respawn race too."""
    suspended = False
    identity = None
    if process is not None and not dry_run:
        try:
            identity = process.create_time()
            process.suspend()
            suspended = True
        except psutil.NoSuchProcess:
            pass
    try:
        yield
    finally:
        if suspended:
            try:
                if process.is_running() and abs(process.create_time() - identity) < 0.01:
                    process.resume()
            except psutil.NoSuchProcess:
                pass


def stop_bot(pid_file: Path, *, dry_run=False, trusted_executables=(), pending_watchdog=None) -> list[int]:
    """Stop verified owners in-process, and publish a durable user-stop barrier."""
    pid_file = Path(pid_file)
    request = {"requested_at_ns": time.time_ns(), "confirmed": False}
    if not dry_run:
        atomic_write_json(pid_file.with_suffix(".stop.json"), request)
    state = read_process_state(pid_file)
    pending_state = read_process_state(pid_file.with_suffix(".pending.json"))
    if pending_watchdog is None and pending_state.get("watchdog_pid"):
        pending_watchdog = (pending_state["watchdog_pid"], pending_state.get("watchdog_created_at"))
    watchdog = verified_process(
        state.get("watchdog_pid"),
        RESOURCE_ROOT / "scripts/watch_cn_1v1.py",
        state.get("watchdog_created_at"),
        trusted_executables=trusted_executables,
    )
    pending_process = None
    if pending_watchdog is not None:
        pending_process = verified_process(
            pending_watchdog[0],
            RESOURCE_ROOT / "scripts/watch_cn_1v1.py",
            pending_watchdog[1],
            trusted_executables=trusted_executables,
        )
    runner = verified_process(
        state.get("runner_pid"),
        RESOURCE_ROOT / "scripts/run_cn_1v1.py",
        state.get("runner_created_at"),
        trusted_executables=trusted_executables,
    )
    # A denied identity query is not proof that the recorded owner stopped.
    identities = [(state.get("watchdog_pid"), watchdog), (state.get("runner_pid"), runner)]
    if pending_watchdog is not None:
        identities.append((pending_watchdog[0], pending_process))
    for pid, process in identities:
        if process is None and isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            try:
                candidate = psutil.Process(pid)
                candidate.exe()
                candidate.cmdline()
                candidate.create_time()
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied as error:
                raise RuntimeError("无法核实后台进程身份，停止状态尚未确认") from error
    roots = list(
        {process.pid: process for process in (watchdog, runner, pending_process) if process is not None}.values()
    )
    with ExitStack() as suspension:
        for process in roots:
            suspension.enter_context(_suspend_watchdog(process, dry_run))
        if not dry_run:
            # A Windows venv launcher has a base-Python child which actually
            # executes the watchdog. Freeze those exact components as well;
            # suspending only the launcher leaves its watchdog free to respawn.
            frozen = {process.pid for process in roots}
            while True:
                added = False
                for root in roots:
                    try:
                        descendants = root.children(recursive=True)
                    except psutil.NoSuchProcess:
                        continue
                    for child in descendants:
                        if child.pid in frozen:
                            continue
                        try:
                            created = child.create_time()
                        except psutil.NoSuchProcess:
                            continue
                        component = any(
                            verified_process(
                                child.pid,
                                RESOURCE_ROOT / "scripts" / script,
                                created,
                                trusted_executables=trusted_executables,
                            )
                            is not None
                            for script in ("watch_cn_1v1.py", "run_cn_1v1.py")
                        )
                        if component:
                            suspension.enter_context(_suspend_watchdog(child, False))
                            frozen.add(child.pid)
                            added = True
                if not added:
                    break
        result = _stop_verified(pid_file, state, watchdog, roots, dry_run, request)
        if not dry_run:
            atomic_write_json(pid_file.with_suffix(".pending.json"), {"phase": "stopped"})
        return result


def _stop_verified(pid_file, state, watchdog, roots, dry_run, request):
    targets = []
    for process in roots:
        if process:
            try:
                targets.extend(process.children(recursive=True))
                targets.append(process)
            except psutil.NoSuchProcess:
                continue
    targets = list({process.pid: process for process in targets}.values())
    identities = {}
    live_targets = []
    for process in targets:
        try:
            identities[process.pid] = process.create_time()
            live_targets.append(process)
        except psutil.NoSuchProcess:
            continue
    targets = live_targets
    identities_list = sorted(process.pid for process in targets)
    if dry_run:
        return identities_list
    if watchdog:
        try:
            if watchdog.pid in identities and abs(watchdog.create_time() - identities[watchdog.pid]) < 0.01:
                watchdog.terminate()  # stop the process that would otherwise restart the runner
        except psutil.NoSuchProcess:
            pass
    for process in targets:
        if process is not watchdog:
            try:
                if abs(process.create_time() - identities[process.pid]) < 0.01:
                    process.terminate()
            except psutil.NoSuchProcess:
                pass
    _, alive = psutil.wait_procs(targets, timeout=2)
    for process in alive:
        try:
            if abs(process.create_time() - identities[process.pid]) < 0.01:
                process.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=2)
    remaining = [process.pid for process in alive if process.is_running()]
    if remaining:
        raise RuntimeError(f"Verified bot processes did not stop: {remaining}")
    atomic_write_json(
        pid_file,
        {**state, "phase": "stopped", "exit_reason": "user_stopped", "ended_at": time.strftime("%Y-%m-%d %H:%M:%S")},
    )
    atomic_write_json(pid_file.with_suffix(".stop.json"), {**request, "confirmed": True})
    return identities_list


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid-file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    targets = stop_bot(args.pid_file, dry_run=args.dry_run)
    if sys.stdout is not None:
        print("Verified bot process IDs:", targets)
        if not args.dry_run:
            print("Bot stopped")


if __name__ == "__main__":
    main()
