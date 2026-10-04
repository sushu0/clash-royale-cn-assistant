"""Offline native-window lifecycle QA; fake Win32 calls are never live evidence."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

TASK = Path(r"D:\codex\CodexWork\clash")
REPO = TASK / "py-clash-bot"
RUN = TASK / "work" / "live-smooth-20261003"
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True


class FakeWindowAPI:
    """A single explicit emulator, unrelated top window, and stateful calls."""

    def __init__(self, snapshot_class):
        self.calls = []
        self.fail_once = None
        self.fail_plan = []
        self.hwnd = 4101
        self.pid = 4102
        self.state = SimpleNamespace(hwnd=self.hwnd, pid=self.pid, parent=0, style=0x16CF0000,
                                     ex_style=0x00040100, placement={"showCmd": 1, "normal": [73, 94, 565, 835]},
                                     rect=(73, 94, 565, 835), content_rect=None)
        self.original = copy.deepcopy(self.state)
        self.snapshot_class = snapshot_class
        self.exists = True
        self.discovered = self.hwnd

    def call(self, name, *args):
        self.calls.append({"name": name, "arguments": [str(value) if isinstance(value, Path) else value for value in args]})
        if self.fail_once == name:
            self.fail_once = None
            raise OSError(f"QA injected {name} failure")
        if self.fail_plan and self.fail_plan[0] == name:
            self.fail_plan.pop(0)
            raise OSError(f"QA injected {name} failure")

    def find_window(self, executable):
        self.call("find_window", executable)
        return self.discovered

    def snapshot(self, hwnd):
        self.call("snapshot", hwnd)
        values = copy.deepcopy(vars(self.state))
        return self.snapshot_class(**values)

    def is_window(self, hwnd, pid):
        self.call("is_window", hwnd, pid)
        return self.exists and hwnd == self.state.hwnd and pid == self.state.pid

    def set_style(self, hwnd, style):
        self.call("set_style", hwnd, style)
        self.state.style = style

    def set_ex_style(self, hwnd, style):
        self.call("set_ex_style", hwnd, style)
        self.state.ex_style = style

    def set_parent(self, hwnd, parent):
        self.call("set_parent", hwnd, parent)
        self.state.parent = parent

    def move_window(self, hwnd, x, y, width, height):
        self.call("move_window", hwnd, x, y, width, height)
        self.state.rect = (x, y, x + width, y + height)

    def restore(self, hwnd, snapshot):
        self.call("restore", hwnd)
        self.state = SimpleNamespace(**copy.deepcopy(vars(snapshot)))

    def original_restored(self):
        return vars(self.state) == vars(self.original)


class FakeSurfaceAPI(FakeWindowAPI):
    """Two render surfaces belong to the fake emulator, never to a real HWND."""

    def __init__(self, snapshot_class):
        super().__init__(snapshot_class)
        self.state.content_rect = (8, 36, 419, 633)
        self.original = copy.deepcopy(self.state)
        self.surfaces = ((419, 633), (419, 633))
        self.original_surfaces = self.surfaces
        self.fail_after_first_surface = False

    def resize_render_surfaces(self, hwnd):
        self.call("resize_render_surfaces", hwnd)
        left, top, right, bottom = self.state.rect
        saved_left, saved_top, saved_right, saved_bottom = self.original.rect
        source_width, source_height = self.original.content_rect[2:]
        size = (right - left - (saved_right - saved_left - source_width),
                bottom - top - (saved_bottom - saved_top - source_height))
        self.surfaces = (size, self.surfaces[1])
        if self.fail_after_first_surface:
            self.fail_after_first_surface = False
            raise OSError("QA failed after resizing the first render surface")
        self.surfaces = (size, size)

    def restore(self, hwnd, snapshot):
        super().restore(hwnd, snapshot)
        self.surfaces = self.original_surfaces

    def original_restored(self):
        return super().original_restored() and self.surfaces == self.original_surfaces


def main():
    output = RUN / "native-qa"
    output.mkdir(parents=True, exist_ok=True)
    guard_path = RUN / "validate_smooth_view.py"
    guard_spec = importlib.util.spec_from_file_location("qa_guard_only", guard_path)
    guard_module = importlib.util.module_from_spec(guard_spec)
    guard_spec.loader.exec_module(guard_module)
    forbidden = []
    guard_module.install_guard(output, forbidden)
    from pyclashbot.interface.cn_native_view import NativeWindowHost, Win32WindowAPI, WindowSnapshot

    report = {"checks": [], "scenarios": [], "forbidden_operations": forbidden,
              "scope": "NativeWindowHost state transitions against fake Win32 API",
              "limits": "No real HWND, simulator, bot input, capture, desktop embedding, or rendered video is exercised"}

    def check(name, condition, **details):
        report["checks"].append({"name": name, "passed": bool(condition), **details})

    def scenario(label, api, host):
        report["scenarios"].append({"name": label, "calls": api.calls, "diagnostics": host.diagnostics(),
                                   "original_restored": api.original_restored()})

    executable = RUN / "fake-MEmu.exe"
    try:
        # Exercise production discovery with fake enumeration and process paths.
        # Bypass the WinDLL-owning initializer; no real Win32 call is possible.
        candidates = {
            1001: {"class": "Qt5QWindowIcon", "pid": 2001, "exe": executable, "owner": 0, "renderer": 3001},
            1002: {"class": "Qt5QWindowIcon", "pid": 2002, "exe": RUN / "unrelated.exe", "owner": 0, "renderer": 3002},
            1003: {"class": "Qt5QWindowIcon", "pid": 2001, "exe": executable, "owner": 1001, "renderer": 3003},
            1004: {"class": "Notepad", "pid": 2001, "exe": executable, "owner": 0, "renderer": 3004},
            1005: {"class": "Qt5QWindowIcon", "pid": 2001, "exe": executable, "owner": 0, "renderer": None},
        }
        discovery = object.__new__(Win32WindowAPI)
        discovery._user32 = SimpleNamespace(GetWindow=lambda hwnd, _relation: candidates[hwnd]["owner"])
        discovery._windows = lambda: list(candidates)
        discovery._text = lambda hwnd, **_kwargs: candidates[hwnd]["class"]
        discovery._pid = lambda hwnd: candidates[hwnd]["pid"]
        discovery._renderer = lambda hwnd: candidates[hwnd]["renderer"]
        discovery._executable = lambda pid: next(row["exe"] for row in candidates.values() if row["pid"] == pid)
        check("production discovery selects only the unique exact executable renderer",
              discovery.find_window(executable) == 1001)
        candidates[1006] = {"class": "Qt5QWindowIcon", "pid": 2003, "exe": executable, "owner": 0, "renderer": 3006}
        check("production discovery refuses ambiguous emulator windows", discovery.find_window(executable) is None)
        candidates.pop(1006)
        candidates.pop(1001)
        check("production discovery refuses absent or non-renderer candidates", discovery.find_window(executable) is None)

        api = FakeSurfaceAPI(WindowSnapshot)
        host = NativeWindowHost(api, executable)
        host.attach(8101, 380, 620)
        check("attach synchronizes both optional fake render surfaces",
              any(call["name"] == "resize_render_surfaces" for call in api.calls)
              and api.surfaces[0] == api.surfaces[1] and api.surfaces != api.original_surfaces,
              surfaces=api.surfaces)
        resize_count = sum(call["name"] == "resize_render_surfaces" for call in api.calls)
        move_count = sum(call["name"] == "move_window" for call in api.calls)
        host.resize(380, 620)
        check("unchanged host dimensions do not repeat native move or surface resize",
              resize_count == sum(call["name"] == "resize_render_surfaces" for call in api.calls)
              and move_count == sum(call["name"] == "move_window" for call in api.calls))
        host.resize(300, 520)
        check("changed host dimensions synchronize optional surfaces again",
              sum(call["name"] == "resize_render_surfaces" for call in api.calls) == resize_count + 1)
        host.detach()
        check("detach restores original top window and both fake surfaces", api.original_restored())
        scenario("optional_surfaces_attach_resize_detach", api, host)

        for failure in ("before_surfaces", "after_first_surface"):
            api = FakeSurfaceAPI(WindowSnapshot)
            if failure == "before_surfaces":
                api.fail_once = "resize_render_surfaces"
            else:
                api.fail_after_first_surface = True
            host = NativeWindowHost(api, executable)
            caught = None
            try:
                host.attach(8101, 380, 620)
            except (OSError, RuntimeError) as error:
                caught = str(error)
            check(f"optional surface failure {failure} is reported", caught is not None, error=caught)
            check(f"optional surface failure {failure} restores top and surfaces",
                  api.original_restored() and host.snapshot_state is None and not host.embedded)
            host.attach(8101, 380, 620)
            host.detach()
            check(f"optional surface failure {failure} remains retryable", api.original_restored())
            scenario(f"optional_surfaces_failure_{failure}", api, host)

        api = FakeSurfaceAPI(WindowSnapshot)
        api.fail_after_first_surface = True
        api.fail_once = "restore"
        host = NativeWindowHost(api, executable)
        caught = None
        try:
            host.attach(8101, 380, 620)
        except (OSError, RuntimeError) as error:
            caught = str(error)
        check("surface failure and rollback failure keep the saved original state",
              caught is not None and host.snapshot_state is not None, error=caught)
        host.detach()
        check("detach retry restores after surface and rollback failures", api.original_restored())
        scenario("optional_surfaces_and_rollback_failure_retry", api, host)

        api = FakeSurfaceAPI(WindowSnapshot)
        host = NativeWindowHost(api, executable)
        host.attach(8101, 380, 620)
        saved = copy.deepcopy(vars(host.snapshot_state))
        api.fail_after_first_surface = True
        caught = None
        try:
            host.resize(280, 480)
        except (OSError, RuntimeError) as error:
            caught = str(error)
        check("surface failure during an existing embedding is reported", caught is not None, error=caught)
        check("surface resize failure preserves the original rollback snapshot", vars(host.snapshot_state) == saved)
        host.resize(280, 480)
        check("surface resize can retry after only one layer changed", api.surfaces[0] == api.surfaces[1])
        host.detach()
        check("detach restores top and both surfaces after a failed embedded resize", api.original_restored())
        scenario("embedded_surface_resize_failure_retry_detach", api, host)

        # Exercise production restore after the VM has removed its render tree.
        # All native calls, process identity, and placement application are fake.
        restore_calls = []
        restoring = object.__new__(Win32WindowAPI)
        restoring.is_window = lambda _hwnd, _pid: True
        restoring._user32 = SimpleNamespace(IsWindow=lambda _hwnd: True,
                                           SetWindowPlacement=lambda *_args: restore_calls.append("placement") or True)
        restoring.set_parent = lambda *_args: restore_calls.append("parent")
        restoring.set_style = lambda *_args: restore_calls.append("style")
        restoring.set_ex_style = lambda *_args: restore_calls.append("ex_style")
        restoring.move_window = lambda *_args: restore_calls.append("move")

        def no_render_tree(_hwnd):
            restore_calls.append("surface_unavailable")
            raise RuntimeError("QA VM render children have exited")

        restoring.resize_render_surfaces = no_render_tree
        saved = WindowSnapshot(hwnd=4101, pid=4102, parent=0, style=0x16CF0000, ex_style=0x40100,
                               placement={"flags": 0, "showCmd": 1, "ptMinPosition": (0, 0),
                                          "ptMaxPosition": (0, 0), "rcNormalPosition": (73, 94, 565, 835)},
                               rect=(73, 94, 565, 835))
        caught = None
        try:
            restoring.restore(4101, saved)
        except (OSError, RuntimeError) as error:
            caught = str(error)
        check("production restore permits a VM without render children after top restore",
              caught is None and restore_calls == ["parent", "style", "ex_style", "move", "placement", "surface_unavailable"],
              error=caught, calls=restore_calls)

        api = FakeWindowAPI(WindowSnapshot)
        host = NativeWindowHost(api, executable)
        host.attach(8101, 450, 700)
        check("discovery uses the explicit emulator executable",
              any(call["name"] == "find_window" and call["arguments"] == [str(executable)] for call in api.calls))
        check("attach selects the identified hwnd and saves original state",
              host.snapshot_state is not None and host.snapshot_state.hwnd == api.hwnd
              and host.snapshot_state.pid == api.pid and host.snapshot_state.parent == 0)
        check("attach reparents the identified emulator to the specified host", api.state.parent == 8101)
        check("embedded window uses child style", bool(api.state.style & 0x40000000) and not (api.state.style & 0x80000000))
        check("diagnostics accurately identifies native embedding",
              host.diagnostics().get("source") == "native_window" and host.diagnostics().get("embedded") is True,
              diagnostics=host.diagnostics())
        snapshot = copy.deepcopy(vars(host.snapshot_state))
        host.attach(8101, 380, 620)
        host.resize(300, 520)
        check("repeated attach and resize preserve the initial rollback snapshot", vars(host.snapshot_state) == snapshot)
        check("resize targets only the identified native hwnd",
              all(call["arguments"][0] == api.hwnd for call in api.calls if call["name"] == "move_window"))
        host.detach()
        check("detach restores parent styles placement and rectangle", api.original_restored(), current=vars(api.state))
        check("detached diagnostics stops claiming embedded", host.diagnostics().get("embedded") is False,
              diagnostics=host.diagnostics())
        restore_count = sum(call["name"] == "restore" for call in api.calls)
        host.detach()
        check("repeated detach is idempotent", restore_count == sum(call["name"] == "restore" for call in api.calls))
        host.attach(8101, 450, 700)
        host.detach()
        check("reattach and detach restore the original window again", api.original_restored())
        scenario("normal_attach_resize_detach_repeat", api, host)

        for failure in ("set_style", "set_ex_style", "set_parent", "move_window"):
            api = FakeWindowAPI(WindowSnapshot)
            api.fail_once = failure
            host = NativeWindowHost(api, executable)
            caught = None
            try:
                host.attach(8101, 450, 700)
            except (OSError, RuntimeError) as error:
                caught = str(error)
            check(f"attach failure at {failure} is reported", caught is not None, error=caught)
            check(f"attach failure at {failure} rolls original window state back",
                  api.original_restored() and not host.diagnostics().get("embedded"), diagnostics=host.diagnostics())
            host.attach(8101, 450, 700)
            host.detach()
            check(f"attach remains retryable after {failure} failure", api.original_restored())
            scenario(f"attach_failure_{failure}", api, host)

        api = FakeWindowAPI(WindowSnapshot)
        api.fail_plan = ["move_window", "restore"]
        host = NativeWindowHost(api, executable)
        caught = None
        try:
            host.attach(8101, 450, 700)
        except (OSError, RuntimeError) as error:
            caught = str(error)
        check("failed attach with failed rollback reports both unsafe steps", caught is not None, error=caught)
        check("failed attach rollback retains state needed for a safe detach retry", host.snapshot_state is not None,
              diagnostics=host.diagnostics())
        host.detach()
        check("detach retry repairs a failed initial attach rollback", api.original_restored())
        scenario("attach_and_rollback_failure_then_retry", api, host)

        api = FakeWindowAPI(WindowSnapshot)
        host = NativeWindowHost(api, executable)
        host.attach(8101, 450, 700)
        api.fail_once = "restore"
        caught = None
        try:
            host.detach()
        except (OSError, RuntimeError) as error:
            caught = str(error)
        check("detach failure is reported so the Tk host can remain alive", caught is not None, error=caught)
        check("failed detach retains the rollback snapshot", host.snapshot_state is not None)
        host.detach()
        check("detach retry restores the original native window", api.original_restored())
        scenario("detach_failure_then_retry", api, host)

        api = FakeWindowAPI(WindowSnapshot)
        host = NativeWindowHost(api, executable)
        api.discovered = None
        caught = None
        try:
            host.attach(8101, 450, 700)
        except (OSError, RuntimeError) as error:
            caught = str(error)
        check("missing emulator is reported without a fallback to unrelated windows", caught is not None)
        check("missing emulator causes no native mutation", not any(call["name"] in {
            "set_style", "set_ex_style", "set_parent", "move_window", "restore"} for call in api.calls))
        scenario("missing_explicit_emulator", api, host)

        api = FakeWindowAPI(WindowSnapshot)
        host = NativeWindowHost(api, executable)
        host.attach(8101, 450, 700)
        api.state.pid = 9999
        restore_count = sum(call["name"] == "restore" for call in api.calls)
        caught = None
        try:
            host.detach()
        except (OSError, RuntimeError) as error:
            caught = str(error)
        check("a reused hwnd belonging to another pid is never restored",
              restore_count == sum(call["name"] == "restore" for call in api.calls), error=caught)
        scenario("reused_hwnd_pid_guard", api, host)
        check("fake API makes no input shutdown process or network calls", not forbidden)
    except Exception as error:
        report["exception"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        check("native lifecycle QA completes without exception", False)

    report["passed_count"] = sum(item["passed"] for item in report["checks"])
    report["check_count"] = len(report["checks"])
    report["passed"] = bool(report["checks"]) and all(item["passed"] for item in report["checks"])
    (output / "native-host-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": report["check_count"], "passed_count": report["passed_count"],
                      "failures": [item["name"] for item in report["checks"] if not item["passed"]],
                      "exception": report.get("exception", {}).get("message"),
                      "report": str(output / "native-host-validation.json")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
