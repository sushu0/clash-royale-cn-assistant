"""Daily purchases share control ownership and remain cancellable over IPC."""

import json
import threading
from unittest.mock import Mock

import pytest

from pyclashbot.bot import cn_1v1_loop, cn_shop_daily_state
from pyclashbot.utils.process_ownership import OwnershipError
from scripts import cn_wpf_backend as backend
from tests.test_cn_wpf_backend import fake_control as _fake_control

fake_control = _fake_control


def test_shop_rejects_active_battle_and_pending_control(fake_control):
    bridge = backend.BackendBridge(control=fake_control)
    fake_control.mutable_state["value"] = "running"
    with pytest.raises(RuntimeError, match="停止对战"):
        bridge.command("shop_daily")
    fake_control.mutable_state["value"] = "stopped"
    reserved = bridge.prepare_control("shop_daily")
    assert bridge.snapshot()["busy"] == "shop_daily"
    for command in ("shop_daily", "start"):
        with pytest.raises(RuntimeError, match="尚未完成"):
            bridge.prepare_control(command)
    reserved["cancel"].set()
    bridge.close()
    fake_control.ControlWindow._start_worker.assert_not_called()


def test_shop_preserves_calibration_or_drain_request(fake_control):
    request = fake_control.TASK_ROOT / "work" / "random-mastery" / "DRAIN"
    request.parent.mkdir()
    request.write_text("navigation calibration", encoding="utf-8")
    bridge = backend.BackendBridge(control=fake_control)
    with pytest.raises(RuntimeError, match="校准请求"):
        bridge.command("shop_daily")
    assert request.read_text() == "navigation calibration"
    assert bridge.busy is None


def test_shop_stop_waits_until_input_owner_has_cancelled(fake_control, monkeypatch):
    entered = threading.Event()
    bridge = backend.BackendBridge(control=fake_control)
    result = {}

    def shopping(operation):
        entered.set()
        assert operation["cancel"].wait(3)
        bridge._publish_shop({"state": "cancelled", "message": "已取消", "gold_purchased": 1})
        return {"state": "stopped", "message": "已取消"}

    monkeypatch.setattr(bridge, "_run_shop_daily", shopping)
    worker = threading.Thread(target=lambda: result.update(bridge.command("shop_daily")))
    worker.start()
    assert entered.wait(3)
    assert bridge.snapshot()["busy"] == "shop_daily"
    stopped = bridge.command("stop")
    worker.join(3)
    assert not worker.is_alive()
    assert stopped["state"] == "stopped"
    assert result["message"] == "已取消"
    assert bridge.snapshot()["shopDaily"]["state"] == "cancelled"
    assert bridge.busy is None and bridge._shop_operation is None
    fake_control.ControlWindow._stop_worker.assert_not_called()
    assert json.loads(fake_control.PID_FILE.with_suffix(".stop.json").read_text())["confirmed"] is True


def test_shop_result_survives_reconnection_without_replaying_purchase(fake_control):
    bridge = backend.BackendBridge(control=fake_control)
    bridge._publish_shop(
        {
            "state": "completed",
            "gold_purchased": 4,
            "free_claimed": 1,
            "gold_spent": 5000,
            "items": [{"slot": 0, "currency": "free", "price": 0, "state": "claimed", "evidence": "recognized_reward"}]
            + [
                {"slot": slot, "currency": "gold", "price": price, "state": "purchased", "evidence": "purchased_marker"}
                for slot, price in enumerate((500, 1000, 1500, 2000), 1)
            ],
        }
    )
    before = bridge.shop_path.read_bytes()
    readonly = backend.BackendBridge(control=fake_control, read_only=True)
    assert readonly.snapshot()["shopDaily"]["gold_spent"] == 5000
    assert readonly.shop_path.read_bytes() == before
    fake_control.ControlWindow._start_worker.assert_not_called()
    fake_control.ControlWindow._stop_worker.assert_not_called()


def test_failed_shop_releases_reservation_without_auto_retry(fake_control, monkeypatch):
    bridge = backend.BackendBridge(control=fake_control)
    calls = []

    def shopping(_operation):
        calls.append(1)
        raise RuntimeError("receipt unknown")

    monkeypatch.setattr(bridge, "_run_shop_daily", shopping)
    with pytest.raises(RuntimeError, match="receipt unknown"):
        bridge.command("shop_daily")
    assert calls == [1]
    assert bridge.busy is None and bridge._shop_operation is None


def test_disconnect_cancels_shop_reservation(fake_control):
    bridge = backend.BackendBridge(control=fake_control)
    operation = bridge.prepare_control("shop_daily")
    bridge.cancel_pending_start()
    assert operation["cancel"].is_set()


def _publish_previous_completed_result(bridge):
    bridge._publish_shop(
        {
            "state": "completed",
            "status": "previous run",
            "message": "previous receipt",
            "gold_purchased": 4,
            "free_claimed": 1,
            "gems_skipped": 1,
            "gold_spent": 5000,
            "items": [{"slot": 1, "state": "purchased"}],
            "evidence_dir": "previous-evidence",
        }
    )


def test_cancelled_shop_precheck_replaces_previous_completed_result(fake_control, monkeypatch):
    bridge = backend.BackendBridge(control=fake_control)
    _publish_previous_completed_result(bridge)
    operation = bridge.prepare_control("shop_daily")
    operation["cancel"].set()
    lock = Mock(side_effect=AssertionError("Cancelled precheck must not acquire a device lock"))
    emulator = Mock(side_effect=AssertionError("Cancelled precheck must not construct a device"))
    shopping = Mock(side_effect=AssertionError("Cancelled precheck must not replay a purchase"))
    monkeypatch.setattr(backend, "ExclusiveFileLock", lock)
    monkeypatch.setattr(cn_1v1_loop, "TimedAdbController", emulator)
    monkeypatch.setattr(cn_shop_daily_state, "run_shop_daily", shopping)

    with pytest.raises(RuntimeError, match="取消"):
        bridge.command("shop_daily", operation=operation)

    result = bridge.snapshot()["shopDaily"]
    saved = json.loads(bridge.shop_path.read_text(encoding="utf-8"))
    assert result["state"] == saved["state"] == "cancelled"
    assert result["gold_purchased"] == result["free_claimed"] == result["gold_spent"] == 0
    assert result["items"] == [] and "evidence_dir" not in result
    assert "previous" not in result["message"]
    assert operation["done"].is_set()
    assert bridge.busy is None and bridge._shop_operation is None
    lock.assert_not_called()
    emulator.assert_not_called()
    shopping.assert_not_called()


def test_shop_lock_failure_replaces_previous_completed_result_without_input(fake_control, monkeypatch):
    bridge = backend.BackendBridge(control=fake_control)
    _publish_previous_completed_result(bridge)
    lock = Mock(side_effect=OwnershipError("Another bot process owns cn-runner.lock"))
    emulator = Mock(side_effect=AssertionError("Unavailable lock must prevent device construction"))
    shopping = Mock(side_effect=AssertionError("Unavailable lock must prevent purchases"))
    monkeypatch.setattr(backend, "ExclusiveFileLock", lock)
    monkeypatch.setattr(cn_1v1_loop, "TimedAdbController", emulator)
    monkeypatch.setattr(cn_shop_daily_state, "run_shop_daily", shopping)

    with pytest.raises(OwnershipError, match="Another bot"):
        bridge.command("shop_daily")

    result = bridge.snapshot()["shopDaily"]
    saved = json.loads(bridge.shop_path.read_text(encoding="utf-8"))
    assert result["state"] == saved["state"] == "failed"
    assert result["gold_purchased"] == result["free_claimed"] == result["gold_spent"] == 0
    assert result["items"] == [] and "evidence_dir" not in result
    assert "Another bot" in result["message"]
    assert bridge.busy is None and bridge._shop_operation is None
    lock.assert_called_once_with(fake_control.PID_FILE.parent / "cn-runner.lock")
    emulator.assert_not_called()
    shopping.assert_not_called()


def test_shop_owner_change_after_reservation_cannot_retain_previous_success(fake_control, monkeypatch):
    bridge = backend.BackendBridge(control=fake_control)
    _publish_previous_completed_result(bridge)
    operation = bridge.prepare_control("shop_daily")
    fake_control.mutable_state["value"] = "running"
    emulator = Mock(side_effect=AssertionError("Active battle owner must prevent device construction"))
    shopping = Mock(side_effect=AssertionError("Active battle owner must prevent purchases"))
    monkeypatch.setattr(cn_1v1_loop, "TimedAdbController", emulator)
    monkeypatch.setattr(cn_shop_daily_state, "run_shop_daily", shopping)

    with pytest.raises(RuntimeError, match="对战任务"):
        bridge.command("shop_daily", operation=operation)

    result = bridge.snapshot()["shopDaily"]
    assert result["state"] == "failed"
    assert result["gold_purchased"] == result["free_claimed"] == result["gold_spent"] == 0
    assert result["items"] == [] and "evidence_dir" not in result
    assert operation["done"].is_set()
    assert bridge.busy is None and bridge._shop_operation is None
    emulator.assert_not_called()
    shopping.assert_not_called()


@pytest.mark.parametrize("cancelled", [False, True])
def test_shop_error_preserves_only_current_verified_receipts(fake_control, monkeypatch, cancelled):
    bridge = backend.BackendBridge(control=fake_control)
    _publish_previous_completed_result(bridge)

    def failed_after_one_receipt(operation):
        bridge._publish_shop(
            {
                "state": "running",
                "message": "current run",
                "free_claimed": 0,
                "gold_purchased": 1,
                "gold_spent": 500,
                "gems_skipped": 0,
                "items": [
                    {
                        "slot": 1,
                        "currency": "gold",
                        "price": 500,
                        "state": "purchased",
                        "evidence": "verified_gold_decrease",
                    }
                ],
            }
        )
        if cancelled:
            operation["cancel"].set()
        raise RuntimeError("current receipt stream interrupted")

    monkeypatch.setattr(bridge, "_execute_shop_daily", failed_after_one_receipt)
    with pytest.raises(RuntimeError, match="current receipt"):
        bridge.command("shop_daily")

    result = bridge.snapshot()["shopDaily"]
    assert result["state"] == ("cancelled" if cancelled else "failed")
    assert result["gold_purchased"] == 1 and result["gold_spent"] == 500
    assert result["free_claimed"] == result["gems_skipped"] == 0
    assert result["items"] == [
        {"slot": 1, "currency": "gold", "price": 500, "state": "purchased", "evidence": "verified_gold_decrease"}
    ]
    assert "evidence_dir" not in result
    assert bridge.busy is None and bridge._shop_operation is None
