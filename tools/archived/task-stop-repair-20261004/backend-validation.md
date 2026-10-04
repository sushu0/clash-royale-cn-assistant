# Python backend stop repair validation

Validated in the background on 2026-10-05 (Asia/Shanghai). No computer-use tools, user application processes, emulator input, current application replacement, or packaging actions were used by this subtask.

## Changes

- `scripts/cn_wpf_backend.py`: reserves control requests in JSONL input order; accepts Stop concurrently with a pending Start; cancellation interrupts startup instead of queueing behind it; rejects Start during Stop and while a previous Stop is unconfirmed. Stop waits at most 2 seconds for the cancelled startup to finish, otherwise reports unconfirmed and preserves that status across reconnects. Startup watchdog identities are persisted immediately to `.pending.json`, including before the watchdog publishes its main PID file. Failed startup cleans up that exact child or preserves the unknown state for a later Stop retry. Historical ingestion retains the previous snapshot and reconnects/retries after recoverable ingestion or SQLite failures.
- `scripts/cn_bot_control.py`: startup accepts a cancellation event; startup subprocess waits and sleeps are interruptible; watchdog spawn is serialized with Stop and registered before the launch lock is released. Stop calls the Python stopping routine directly instead of launching another frozen executable. Explicit user stop overrides stale random-mode pause telemetry.
- `scripts/stop_cn_1v1.py`: idempotent stopping handles absent/stale PID files; publishes a durable stop barrier, verifies PID + creation time + exact entrypoint/executable, freezes verified watchdog/runner owners and any base-Python components below Windows venv launcher processes, enumerates their owned descendants, terminates and verifies exit. It can also stop persisted unpublished watchdogs and explicitly trusted previous package executables. Identity access denial remains unconfirmed. It leaves the emulator, game and calibration DRAIN files alone.
- `scripts/watch_cn_1v1.py`: checks the launch timestamp against the stop barrier before spawning, while waiting for a runner, and during recovery delay. An older stop does not block a later explicit Start. Recovery-delay sleeps clamp their remaining time to zero.
- `pyclashbot/utils/process_ownership.py`: supports caller-supplied exact trusted component executables and reads durable stop barriers.
- `tests/test_cn_wpf_backend.py` and new `tests/test_cn_stop_lifecycle.py`: meaningful cancellation, control ordering, persistent unknown state, pending-process retries, history recovery and isolated real-process stopping regressions.

## Validation

Each shell process initialized `D:\codex\bin\Initialize-CodexEnvironment.ps1`. Tests and compilation used the existing `D:\codex\CodexWork\clash\work\venv\Scripts\python.exe`; no interpreter, lockfile or dependency installation was changed.

The final targeted pytest invocation passed **127 tests and 6 subtests in 3.85 seconds**:

```powershell
..\work\venv\Scripts\python.exe -m pytest -q --basetemp=..\work\task-stop-repair-20261004\pytest-backend-6 tests\test_cn_control_startup.py tests\test_process_ownership.py tests\test_cn_finite_batch.py tests\test_cn_wpf_backend.py tests\test_cn_stop_lifecycle.py tests\test_cn_desktop_lifecycle.py tests\test_cn_control_random.py tests\test_cn_entrypoints.py
```

`py_compile` passed for all 7 changed Python files. `D:\codex\bin\ruff.exe check` passed under the existing project lint configuration, and `ruff format --check` reported all 7 files already formatted. The local `ty` executable was unavailable; no new tooling was installed for this subtask.

Real process tests used only temporary, hidden Python helper processes owned by the tests. They verified that a repeatedly spawning watchdog and its descendants actually exited, that an unrelated helper remained alive, and that a failed startup cleanup retained an unpublished watchdog identity across backend reconnect so a later Stop could kill it. They also interrupted a blocking 30-second startup helper in under 2 seconds. Tests did not send any ADB or emulator input.

Final source hashes are saved in `backend-source-hashes.json`. The final backend hash is `D88BF0BFD713F850D9B61EA7643169981FDE87002ED221FE52F535E695C3C475`.

## Rollback and limits

Before-source copies are under `before/py-clash-bot/` for all modified pre-existing files. The `cn_bot_control.py` copy retains pre-existing uncommitted UI work; its startup/stop methods were reconstructed from their unchanged repository versions after the first narrow patches. The new lifecycle test had no original file. Rollback can restore only these backed-up files and archive the new test; do not reset the repository or overwrite unrelated dirty files.

This evidence confirms source behavior and isolated OS process termination. Frozen packaging and installed application acceptance belong to the parent task and are not claimed by this report.
