"""The existing desktop fields show daily totals, independent of last-run zeros."""

from datetime import datetime, timedelta, timezone

from scripts.cn_wpf_backend import BackendBridge
from tests.test_cn_wpf_backend import fake_control as _fake_control

fake_control = _fake_control
SHANGHAI = timezone(timedelta(hours=8))


def confirmed_items():
    return [
        {"slot": 0, "currency": "free", "price": 0, "state": "claimed", "evidence": "recognized_reward"},
        *(
            {"slot": slot, "currency": "gold", "price": price, "state": "purchased", "evidence": "purchased_marker"}
            for slot, price in enumerate((500, 1000, 1500, 2000), 1)
        ),
        {"slot": 5, "currency": "gems", "price": 100, "state": "skipped_gems"},
    ]


def test_zero_repeat_keeps_today_totals_and_latest_run_separate(fake_control):
    bridge = BackendBridge(control=fake_control)
    bridge._publish_shop({"state": "completed", "items": confirmed_items()})
    bridge._publish_shop(
        {
            "state": "completed",
            "free_claimed": 0,
            "gold_purchased": 0,
            "gold_spent": 0,
            "gems_skipped": 1,
            "items": [{"slot": slot, "state": "already_purchased"} for slot in range(5)]
            + [{"slot": 5, "currency": "gems", "price": 100, "state": "skipped_gems"}],
        }
    )
    snapshot = bridge.snapshot()
    shop = snapshot["shopDaily"]
    assert (shop["free_claimed"], shop["gold_purchased"], shop["gold_spent"], shop["gems_skipped"]) == (1, 4, 5000, 1)
    assert shop["counter_scope"] == "today" and shop["date"] == snapshot["shopDailyToday"]["date"]
    assert snapshot["shopDailyLastRun"]["gold_spent"] == 0
    assert snapshot["shop_daily_history_error"] is None
    fake_control.ControlWindow._start_worker.assert_not_called()
    fake_control.ControlWindow._stop_worker.assert_not_called()


def test_readonly_reconnect_reads_daily_ledger_without_writing(fake_control):
    writable = BackendBridge(control=fake_control)
    writable._publish_shop({"state": "completed", "items": confirmed_items()})
    before = {path: path.read_bytes() for path in fake_control.TASK_ROOT.rglob("*") if path.is_file()}
    reader = BackendBridge(control=fake_control, read_only=True)
    reader.initialize()
    assert reader.snapshot()["shopDaily"]["gold_spent"] == 5000
    reader.close()
    after = {path: path.read_bytes() for path in fake_control.TASK_ROOT.rglob("*") if path.is_file()}
    assert after == before


def test_absent_readonly_ledger_creates_no_files(fake_control):
    before = set(fake_control.TASK_ROOT.rglob("*"))
    reader = BackendBridge(control=fake_control, read_only=True)
    reader.initialize()
    assert reader.snapshot()["shopDailyToday"]["gold_spent"] == 0
    reader.close()
    assert set(fake_control.TASK_ROOT.rglob("*")) == before


def test_next_shanghai_day_shows_zero_without_erasing_previous_day(fake_control):
    bridge = BackendBridge(control=fake_control)
    now = datetime.now(SHANGHAI)
    bridge._publish_shop({"state": "completed", "items": confirmed_items(), "gold_spent": 5000})
    bridge.shop_history.clock = lambda: now + timedelta(days=1)
    snapshot = bridge.snapshot()
    assert snapshot["shopDaily"]["gold_spent"] == 0
    assert snapshot["shopDailyLastRun"]["gold_spent"] == 5000
    assert bridge.shop_history.snapshot(now.date())["gold_spent"] == 5000


def test_run_level_counts_without_receipts_cannot_invent_today_totals(fake_control):
    bridge = BackendBridge(control=fake_control)
    bridge._publish_shop({"state": "completed", "free_claimed": 1, "gold_purchased": 4, "gold_spent": 5000})
    snapshot = bridge.snapshot()
    assert snapshot["shopDaily"]["gold_spent"] == 0
    assert snapshot["shopDailyLastRun"]["gold_spent"] == 5000


def test_running_bot_is_not_stopped_or_started_for_stats_refresh(fake_control):
    fake_control.mutable_state["value"] = "running"
    bridge = BackendBridge(control=fake_control)
    bridge._publish_shop({"state": "completed", "items": confirmed_items()})
    assert bridge.snapshot()["state"] == "running"
    assert bridge.snapshot()["shopDailyToday"]["gold_purchased"] == 4
    fake_control.ControlWindow._start_worker.assert_not_called()
    fake_control.ControlWindow._stop_worker.assert_not_called()
