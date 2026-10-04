"""Pure replay tests: no bot, device, source-file mutation, or image I/O."""
import copy
import unittest

from trial_ledger import ReplayEngine, digest


def config(target=3, required=2):
    return {"trial_id": "test-fixed-window", "first_session": "run-a",
            "target_count": target, "min_confirmed_wins": required,
            "manifest_fingerprint": "frozen"}


def transaction(kind, battle, tick, *, session="run-a", fingerprint="frozen", result=None,
                resumed=False, evidence=True, **extra):
    event = {"event": kind, "battle": battle, "time": f"2026-09-27 01:00:{tick:02d}", "session": session, **extra}
    if kind == "battle_start":
        event["resumed"] = resumed
    if result is not None:
        event["result"] = result
    frozen = [{"sha256": f"result-{session}-{battle}-{tick}", "verified": True}] if kind == "battle_end" and evidence else []
    return {"event_id": digest(event), "event": event, "manifest_fingerprint": fingerprint, "frozen_evidence": frozen}


def manual(slot, terminal, result):
    return {"trial_id": "test-fixed-window", "slot": slot, "result": result,
            "sha256": terminal["frozen_evidence"][0]["sha256"], "reviewer": "independent-test-reviewer"}


class TrialLedgerReplayTests(unittest.TestCase):
    def test_pre_anchor_events_are_excluded_without_changing_fixed_anchor(self):
        engine = ReplayEngine(config())
        engine.apply(transaction("battle_start", 1, 1, session="older-run"))
        self.assertEqual(engine.report()["slots_admitted"], 0)
        engine.apply(transaction("battle_start", 1, 2))
        self.assertEqual(engine.report()["slots_admitted"], 1)

    def test_auto_wins_do_not_become_independently_confirmed_wins(self):
        engine = ReplayEngine(config(target=1, required=1))
        end = transaction("battle_end", 1, 2, result="胜利")
        engine.apply(transaction("battle_start", 1, 1))
        engine.apply(end)
        self.assertEqual(engine.report()["confirmed_win"], 0)
        self.assertNotEqual(engine.report()["status"], "PASS")
        engine.apply_reviews([manual(1, end, "胜利")])
        self.assertEqual(engine.report()["status"], "PASS")

    def test_resumed_restart_merges_the_only_open_slot_and_keeps_recovery(self):
        events = [transaction("battle_start", 1, 1), transaction("recovery", 1, 2, reason="adb_disconnect"),
                  transaction("battle_start", 1, 3, session="run-b", resumed=True),
                  transaction("battle_end", 1, 4, session="run-b", result="失败"),
                  transaction("battle_start", 2, 5, session="run-b")]
        first = ReplayEngine(config())
        for event in events:
            first.apply(event)
        report = first.report()
        self.assertEqual(report["slots_admitted"], 2)
        self.assertEqual(report["slots_closed"], 1)
        self.assertEqual(report["slots"][0]["aliases"], [["run-a", 1], ["run-b", 1]])
        self.assertEqual(len(report["slots"][0]["recovery_events"]), 1)
        replay = ReplayEngine(config())
        for event in copy.deepcopy(events):
            replay.apply(event)
        self.assertEqual(report, replay.report())

    def test_silence_does_not_close_an_open_slot(self):
        engine = ReplayEngine(config())
        engine.apply(transaction("battle_start", 1, 1))
        engine.apply(transaction("screen_unknown", 1, 40))
        self.assertEqual(engine.report()["slots_closed"], 0)
        self.assertEqual(engine.report()["active_slot"], 1)

    def test_abandoned_slot_remains_nonwin_when_local_number_is_reused(self):
        engine = ReplayEngine(config())
        engine.apply(transaction("battle_start", 1, 1))
        engine.apply(transaction("battle_abandoned", 1, 2, reason="unexpected_lobby"))
        engine.apply(transaction("battle_start", 1, 3))
        engine.apply(transaction("battle_end", 1, 4, result="失败"))
        result = engine.report()
        self.assertEqual(result["slots_admitted"], 2)
        self.assertEqual(result["raw_result_counts"]["未知"], 1)
        self.assertEqual(result["raw_result_counts"]["失败"], 1)

    def test_new_fresh_start_closes_interrupted_old_slot_as_unknown(self):
        engine = ReplayEngine(config())
        engine.apply(transaction("battle_start", 1, 1))
        engine.apply(transaction("battle_start", 1, 10, session="run-b"))
        self.assertEqual(engine.report()["slots_admitted"], 2)
        self.assertEqual(engine.report()["slots"][0]["close_reason"], "new_fresh_start_before_result")
        self.assertEqual(engine.report()["raw_result_counts"]["未知"], 1)

    def test_orphan_resume_or_end_holds_without_manufacturing_a_game(self):
        for kind in ("battle_start", "battle_end"):
            with self.subTest(kind=kind):
                engine = ReplayEngine(config())
                engine.apply(transaction(kind, 1, 1, resumed=True, result="胜利" if kind == "battle_end" else None))
                self.assertEqual(engine.report()["status"], "HOLD")
                self.assertEqual(engine.report()["slots_admitted"], 0)

    def test_version_change_holds_and_never_restarts_window(self):
        engine = ReplayEngine(config())
        engine.apply(transaction("battle_start", 1, 1))
        engine.apply(transaction("battle_start", 1, 2, session="run-b", fingerprint="changed", resumed=True))
        engine.apply(transaction("battle_end", 1, 3, session="run-b", result="胜利"))
        self.assertEqual(engine.report()["status"], "HOLD")
        self.assertEqual(engine.report()["slots_admitted"], 1)
        self.assertEqual(engine.report()["slots_closed"], 0)

    def test_interleaved_run_ids_hold(self):
        engine = ReplayEngine(config())
        engine.apply(transaction("battle_start", 1, 1))
        engine.apply(transaction("battle_start", 1, 2, session="run-b", resumed=True))
        engine.apply(transaction("observe", 1, 3, session="run-a"))
        self.assertEqual(engine.report()["holds"][0]["code"], "INTERLEAVED_RUN_SESSIONS")

    def test_duplicate_event_does_not_double_count(self):
        engine = ReplayEngine(config())
        start = transaction("battle_start", 1, 1)
        end = transaction("battle_end", 1, 2, result="胜利")
        for event in (start, start, end, end):
            engine.apply(event)
        self.assertEqual(engine.report()["slots_closed"], 1)
        self.assertEqual(engine.report()["duplicate_events"], 2)

    def test_fixed_window_does_not_roll_forward_into_later_wins(self):
        engine = ReplayEngine(config(target=2, required=1))
        for battle in (1, 2, 3):
            engine.apply(transaction("battle_start", battle, battle*2))
            engine.apply(transaction("battle_end", battle, battle*2+1, result="失败" if battle<3 else "胜利"))
        self.assertEqual(engine.report()["slots_admitted"], 2)
        self.assertEqual(engine.report()["raw_result_counts"]["失败"], 2)
        self.assertEqual(engine.report()["raw_result_counts"]["胜利"], 0)

    def test_unknown_retains_denominator_and_requires_review(self):
        engine = ReplayEngine(config(target=2, required=1))
        win = transaction("battle_end", 1, 2, result="胜利")
        unknown = transaction("battle_end", 2, 4, result="未知")
        for event in (transaction("battle_start", 1, 1), win, transaction("battle_start", 2, 3), unknown):
            engine.apply(event)
        engine.apply_reviews([manual(1, win, "胜利")])
        self.assertNotEqual(engine.report()["status"], "PASS")
        engine.apply_reviews([manual(1, win, "胜利"), manual(2, unknown, "未知")])
        self.assertEqual(engine.report()["status"], "PASS")
        self.assertEqual(engine.report()["target_denominator"], 2)
        self.assertEqual(engine.report()["raw_result_counts"]["未知"], 1)

    def test_missing_or_wrong_result_hash_cannot_confirm_a_win(self):
        engine = ReplayEngine(config(target=1, required=1))
        engine.apply(transaction("battle_start", 1, 1))
        engine.apply(transaction("battle_end", 1, 2, result="胜利", evidence=False))
        engine.apply_reviews([{"trial_id":"test-fixed-window", "slot":1,"result":"胜利","sha256":"invented","reviewer":"tester"}])
        self.assertEqual(engine.report()["confirmed_win"], 0)
        self.assertEqual(engine.report()["missing_result_evidence_slots"], [1])

    def test_committed_plan_must_precede_first_admission(self):
        cfg = config()
        cfg["created_at"] = "2026-09-27T01:00:02"
        engine = ReplayEngine(cfg)
        engine.apply(transaction("battle_start", 1, 1))
        self.assertEqual(engine.report()["status"], "HOLD")
        self.assertEqual(engine.report()["slots_admitted"], 0)

    def test_100_slots_33_reviewed_wins_pass_and_32_do_not(self):
        engine = ReplayEngine(config(target=100, required=33))
        reviews = []
        for number in range(1,101):
            start = transaction("battle_start", number, 1)
            end = transaction("battle_end", number, 2, result="胜利" if number<=33 else "失败")
            engine.apply(start)
            engine.apply(end)
            if number<=33:
                reviews.append(manual(number, end, "胜利"))
        engine.apply_reviews(reviews[:32])
        self.assertNotEqual(engine.report()["status"], "PASS")
        engine.apply_reviews(reviews)
        self.assertEqual(engine.report()["status"], "PASS")
        self.assertEqual(engine.report()["confirmed_win"], 33)
        self.assertEqual(engine.report()["slots_closed"], 100)


if __name__ == "__main__":
    unittest.main()
