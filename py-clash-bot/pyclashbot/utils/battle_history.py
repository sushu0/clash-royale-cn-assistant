"""Incremental, restart-safe index of local battle traces for the control UI.

Only battle_end / random-mode battle_finished is a completed game. Unknowns remain in the denominator. The
source JSONL and result screenshots stay authoritative; this DB is an index.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

OUTCOMES = ("胜利", "失败", "平局", "未知")


def summarize(records: list[dict]) -> dict:
    counts = {name: sum(r["result"] == name for r in records) for name in OUTCOMES}
    total = len(records)
    best = current = 0
    last = None
    for row in records:
        result = row["result"]
        current = current + 1 if result == last and result in {"胜利", "失败"} else int(result in {"胜利", "失败"})
        last = result
        if result == "胜利":
            best = max(best, current)
    return {
        "total": total,
        "wins": counts["胜利"],
        "losses": counts["失败"],
        "draws": counts["平局"],
        "unknown": counts["未知"],
        "win_rate": counts["胜利"] / total if total else None,
        "streak": current,
        "streak_result": last if current else None,
        "best_win_streak": best,
    }


class BattleHistory:
    """Use from one background thread; readers receive ordinary snapshots."""

    def __init__(self, database: Path):
        self.database = Path(database).resolve()
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                path TEXT PRIMARY KEY, identity TEXT, offset INTEGER,
                anchor TEXT, malformed INTEGER NOT NULL DEFAULT 0, strategy TEXT
            );
            CREATE TABLE IF NOT EXISTS battles (
                strategy TEXT, session TEXT, battle INTEGER, time TEXT,
                policy TEXT, mode TEXT, result TEXT, confirmed INTEGER,
                attempts INTEGER, evidence TEXT, conflict INTEGER DEFAULT 0,
                PRIMARY KEY (strategy, session, battle)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                strategy TEXT, session TEXT, time TEXT, policy TEXT,
                event TEXT, detail TEXT,
                PRIMARY KEY (strategy, session)
            );
            CREATE TABLE IF NOT EXISTS mastery_rewards (
                claim_id TEXT, item_id TEXT, time TEXT, kind TEXT,
                amount INTEGER, evidence TEXT,
                PRIMARY KEY (claim_id,item_id)
            );
        """)
        # Version 3 also imports pre-session legacy results and scopes errors. Rebuild
        # cursors, not original logs or already indexed games.
        with self.connection:
            if self.connection.execute("PRAGMA user_version").fetchone()[0] < 3:
                columns = {row[1] for row in self.connection.execute("PRAGMA table_info(sources)")}
                if "strategy" not in columns:
                    self.connection.execute("ALTER TABLE sources ADD COLUMN strategy TEXT")
                self.connection.execute(
                    "UPDATE sources SET offset=0, anchor=?, malformed=0", (hashlib.sha256(b"").hexdigest(),)
                )
                self.connection.execute("PRAGMA user_version=3")
            columns = {row[1] for row in self.connection.execute("PRAGMA table_info(mastery_rewards)")}
            if "quantity_unknown_initial" not in columns:
                self.connection.execute(
                    "ALTER TABLE mastery_rewards ADD COLUMN quantity_unknown_initial INTEGER DEFAULT 0"
                )
                self.connection.execute("UPDATE mastery_rewards SET quantity_unknown_initial=1 WHERE amount IS NULL")
            if self.connection.execute("PRAGMA user_version").fetchone()[0] < 4:
                self.connection.execute(
                    "UPDATE sources SET offset=0,anchor=? WHERE strategy='rewards'", (hashlib.sha256(b"").hexdigest(),)
                )
                self.connection.execute("PRAGMA user_version=4")
            columns = {row[1] for row in self.connection.execute("PRAGMA table_info(battles)")}
            for column in ("rule_version", "strategy_hash", "asset_hash", "environment_hash", "evidence_hash"):
                if column not in columns:
                    self.connection.execute(f"ALTER TABLE battles ADD COLUMN {column} TEXT")
            if self.connection.execute("PRAGMA user_version").fetchone()[0] < 5:
                self.connection.execute(
                    "UPDATE sources SET offset=0,anchor=?,malformed=0", (hashlib.sha256(b"").hexdigest(),)
                )
                self.connection.execute("PRAGMA user_version=5")
        self._manifest_cache = {}
        self._evidence_cache = {}

    def close(self):
        self.connection.close()

    @staticmethod
    def _anchor(stream, offset):
        stream.seek(max(0, offset - 128))
        return hashlib.sha256(stream.read(min(offset, 128))).hexdigest()

    @staticmethod
    def _valid_row(row):
        if not isinstance(row, dict) or not isinstance(row.get("event"), str):
            return False
        for name in ("policy_observation", "evidence", "decision", "experiment"):
            if row.get(name) is not None and not isinstance(row[name], dict):
                return False
        for name in ("time", "session", "mode", "policy", "policy_version", "strategy_version"):
            if row.get(name) is not None and not isinstance(row[name], str):
                return False
        for name in ("confirmed", "attempts", "cards_confirmed", "card_attempts"):
            value = row.get(name)
            if (
                name == "confirmed"
                and isinstance(value, bool)
                and row["event"] not in ("battle_end", "battle_finished")
            ):
                continue
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                return False
        evidence = row.get("evidence") or {}
        if evidence.get("sha256") is not None and not isinstance(evidence["sha256"], str):
            return False
        if row["event"] == "rewards_confirmed":
            if not isinstance(row.get("claim_id"), str) or not isinstance(row.get("receipts"), list):
                return False
        if row["event"] == "reward_quantity_corrected":
            if not isinstance(row.get("claim_id"), str) or not isinstance(row.get("item_id"), str):
                return False
        return True

    def _experiment(self, row, source, strategy, session):
        explicit = row.get("experiment") or {}
        if explicit:
            return explicit
        key = (str(source), strategy, session)
        if key not in self._manifest_cache:
            found = {}
            if re.fullmatch(r"[\w.-]+", session):
                root = source.parent.parent / "work"
                folder = "random-mastery" if strategy == "random" else f"{strategy}-validation"
                manifest = (
                    root / folder / session / ("manifest.json" if strategy == "random" else "policy-manifest.json")
                )
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    hashes = data.get("sha256", data.get("source_sha256", {}))
                    assets = data.get("asset_sha256", {})
                    if isinstance(hashes, dict):
                        suffix = (
                            "random_deck_strategy.py"
                            if strategy == "random"
                            else ("double_air_567_strategy.py" if strategy == "567" else "hog_cycle_strategy.py")
                        )
                        digest = next((value for name, value in hashes.items() if name.endswith(suffix)), None)
                        found["strategy_hash"] = digest
                        # A complete source/asset identity is available even for
                        # older sessions without a separately named rules version.
                        found["asset_hash"] = hashlib.sha256(
                            json.dumps(
                                assets or {k: v for k, v in hashes.items() if k.endswith((".png", ".json"))},
                                sort_keys=True,
                            ).encode()
                        ).hexdigest()
                        found["environment_hash"] = data.get("environment_hash")
                except (OSError, ValueError, AttributeError):
                    pass
            self._manifest_cache[key] = found
        return self._manifest_cache[key]

    def ingest(self, path: Path, strategy: str, max_bytes: int = 4_000_000) -> bool:
        """Read only complete appended lines. Return True while backlog remains."""
        try:
            stream = path.open("rb")
        except FileNotFoundError:
            return False
        with stream, self.connection:
            stat = path.stat()
            identity = f"{stat.st_dev}:{stat.st_ino}"
            source = self.connection.execute("SELECT * FROM sources WHERE path=?", (str(path),)).fetchone()
            offset = source["offset"] if source else 0
            malformed = source["malformed"] if source else 0
            if source and (
                source["identity"] != identity
                or stat.st_size < offset
                or self._anchor(stream, offset) != source["anchor"]
            ):
                offset = 0  # rotation/truncation: replay safely through unique keys
            start = offset
            stream.seek(offset)
            sessions = {}
            while offset - start < max_bytes:
                line = stream.readline()
                if not line or not line.endswith(b"\n"):
                    break  # writer may still be writing UTF-8 / JSON
                offset = stream.tell()
                try:
                    row = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    malformed += 1
                    continue
                if not self._valid_row(row):
                    malformed += 1
                    continue
                if strategy == "rewards":
                    if (
                        row["event"] == "reward_quantity_corrected"
                        and isinstance(row.get("amount"), int)
                        and not isinstance(row["amount"], bool)
                        and row["amount"] > 0
                    ):
                        self.connection.execute(
                            "UPDATE mastery_rewards SET amount=? WHERE claim_id=? AND item_id=? AND quantity_unknown_initial=1",
                            (row["amount"], row.get("claim_id"), row.get("item_id")),
                        )
                    if row["event"] == "rewards_confirmed" and isinstance(row.get("claim_id"), str):
                        for receipt in row.get("receipts", []):
                            if not isinstance(receipt, dict) or not isinstance(receipt.get("id"), str):
                                malformed += 1
                                continue
                            amount = receipt.get("amount")
                            evidence = receipt.get("evidence") or {}
                            if (
                                not isinstance(receipt.get("kind"), str)
                                or not isinstance(evidence, dict)
                                or (evidence.get("path") is not None and not isinstance(evidence["path"], str))
                            ):
                                malformed += 1
                                continue
                            if amount is not None and (
                                not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0
                            ):
                                malformed += 1
                                continue
                            self.connection.execute(
                                """INSERT OR IGNORE INTO mastery_rewards
                                (claim_id,item_id,time,kind,amount,evidence,quantity_unknown_initial) VALUES(?,?,?,?,?,?,?)""",
                                (
                                    row["claim_id"],
                                    receipt["id"],
                                    row.get("time"),
                                    receipt.get("kind"),
                                    amount,
                                    evidence.get("path"),
                                    int(amount is None),
                                ),
                            )
                    continue
                stamp = str(row.get("time", ""))
                session = row.get("session")
                if not session:
                    # Early traces have neither session nor policy. A result's
                    # timestamp is its legacy identity, never a guessed batch.
                    if row["event"] != "battle_end":
                        continue
                    if not stamp:
                        malformed += 1
                        continue
                    session = "legacy:" + stamp
                if not isinstance(session, str):
                    malformed += 1
                    continue
                event, policy = row.get("event"), str(row.get("policy_version", row.get("policy", "未记录版本")))
                detail = {
                    "battle": row.get("battle"),
                    "decision": row.get("decision"),
                    "confirmed": row.get("confirmed"),
                    "wait_reason": (row.get("policy_observation") or {}).get("wait_reason"),
                }
                sessions[session] = (strategy, session, stamp, policy, event, json.dumps(detail, ensure_ascii=False))
                random_result = strategy == "random" and event == "battle_finished"
                if event != "battle_end" and not random_result:
                    continue
                battle = row.get("finished_battle", row.get("battle")) if random_result else row.get("battle")
                if not isinstance(battle, int) or isinstance(battle, bool) or battle < 1:
                    malformed += 1
                    continue
                outcome = row.get("outcome") if random_result else row.get("result")
                outcome = outcome if outcome in OUTCOMES else "未知"
                evidence = row.get("evidence") or {}
                evidence_path = evidence.get("path") if isinstance(evidence, dict) else None
                if evidence_path is not None and not isinstance(evidence_path, str):
                    malformed += 1
                    continue
                experiment = self._experiment(row, path, strategy, session)
                if any(
                    experiment.get(name) is not None and not isinstance(experiment[name], str)
                    for name in ("rule_version", "strategy_hash", "asset_hash", "environment_hash")
                ):
                    malformed += 1
                    continue
                self.connection.execute(
                    """
                    INSERT INTO battles(strategy,session,battle,time,policy,mode,result,confirmed,attempts,evidence,
                        rule_version,strategy_hash,asset_hash,environment_hash,evidence_hash)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(strategy,session,battle) DO UPDATE SET
                        conflict = CASE WHEN battles.result != excluded.result
                            OR battles.policy != excluded.policy
                            OR (battles.strategy_hash IS NOT NULL AND excluded.strategy_hash IS NOT NULL
                                AND battles.strategy_hash != excluded.strategy_hash)
                            OR (battles.asset_hash IS NOT NULL AND excluded.asset_hash IS NOT NULL
                                AND battles.asset_hash != excluded.asset_hash)
                            OR (battles.environment_hash IS NOT NULL AND excluded.environment_hash IS NOT NULL
                                AND battles.environment_hash != excluded.environment_hash)
                            OR (battles.rule_version IS NOT NULL AND excluded.rule_version IS NOT NULL
                                AND battles.rule_version != excluded.rule_version)
                            THEN 1 ELSE battles.conflict END,
                        rule_version=COALESCE(battles.rule_version,excluded.rule_version),
                        strategy_hash=COALESCE(battles.strategy_hash,excluded.strategy_hash),
                        asset_hash=COALESCE(battles.asset_hash,excluded.asset_hash),
                        environment_hash=COALESCE(battles.environment_hash,excluded.environment_hash),
                        evidence_hash=COALESCE(battles.evidence_hash,excluded.evidence_hash)
                """,
                    (
                        strategy,
                        session,
                        battle,
                        stamp,
                        policy,
                        row.get("mode", "classic_1v1" if random_result else "未记录模式"),
                        outcome,
                        row.get("cards_confirmed", row.get("confirmed")),
                        row.get("card_attempts", row.get("attempts")),
                        evidence_path,
                        experiment.get("rule_version", row.get("strategy_version")),
                        experiment.get("strategy_hash"),
                        experiment.get("asset_hash"),
                        experiment.get("environment_hash"),
                        evidence.get("sha256"),
                    ),
                )
            self.connection.executemany(
                """
                INSERT INTO sessions VALUES(?,?,?,?,?,?)
                ON CONFLICT(strategy,session) DO UPDATE SET time=excluded.time,
                    policy=excluded.policy,event=excluded.event,detail=excluded.detail
                WHERE excluded.time >= sessions.time
            """,
                sessions.values(),
            )
            anchor = self._anchor(stream, offset)
            self.connection.execute(
                "INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?)",
                (str(path), identity, offset, anchor, malformed, strategy),
            )
            return offset < stat.st_size and offset - start >= max_bytes

    def snapshot(self, strategy: str = "567") -> dict:
        where, params = ("", ()) if strategy == "all" else ("WHERE strategy=?", (strategy,))
        rows = [
            dict(r)
            for r in self.connection.execute(
                f"SELECT * FROM battles {where} ORDER BY time,session,battle,strategy", params
            )
        ]
        for row in rows:
            if row["conflict"]:
                row["result"] = "未知"
        for row in rows[-60:]:
            row["evidence_status"] = self._evidence_status(row)
        sessions = [
            dict(r)
            for r in self.connection.execute(f"SELECT * FROM sessions {where} ORDER BY time,session,strategy", params)
        ]
        latest = sessions[-1] if sessions else None
        session_rows = [
            r for r in rows if latest and r["session"] == latest["session"] and r["strategy"] == latest["strategy"]
        ]
        versions = {}
        for row in rows:
            identity = tuple(
                row[key] for key in ("policy", "rule_version", "strategy_hash", "asset_hash", "environment_hash")
            )
            versions.setdefault(identity, []).append(row)
        malformed = self.connection.execute(
            f"SELECT COALESCE(SUM(malformed),0) FROM sources {where}", params
        ).fetchone()[0]
        return {
            "strategy": strategy,
            "total": summarize(rows),
            "recent": summarize(rows[-20:]),
            "session": summarize(session_rows),
            "latest_session": latest,
            "records": rows[-60:][::-1],
            "recent_results": [r["result"] for r in rows[-20:]],
            "versions": [
                {
                    "policy": k[0],
                    "rule_version": k[1],
                    "strategy_hash": k[2],
                    "asset_hash": k[3],
                    "environment_hash": k[4],
                    **summarize(v),
                }
                for k, v in versions.items()
            ][::-1],
            "malformed_lines": malformed,
            "conflicts": sum(r["conflict"] for r in rows),
            "first_at": rows[0]["time"] if rows else None,
            "last_at": rows[-1]["time"] if rows else None,
        }

    def _evidence_status(self, row):
        try:
            picture = Path(row.get("evidence") or "").resolve()
            work = self.database.parent.parent / "work"
            if not picture.is_relative_to(work.resolve()) or picture.suffix.lower() != ".png":
                return "未记录"
            stat = picture.stat()
            expected = row.get("evidence_hash")
            if not expected:
                return "未核验"
            key = (str(picture), stat.st_size, stat.st_mtime_ns, expected)
            if key not in self._evidence_cache:
                valid = hashlib.sha256(picture.read_bytes()).hexdigest() == expected
                self._evidence_cache[key] = "可复核" if valid else "已覆盖"
                if len(self._evidence_cache) > 512:
                    self._evidence_cache = {key: self._evidence_cache[key]}
            return self._evidence_cache[key]
        except (OSError, ValueError, TypeError):
            return "缺失"

    def reward_snapshot(self):
        row = self.connection.execute("""SELECT COUNT(*) AS rewards,
            COALESCE(SUM(CASE WHEN kind='coins' THEN amount ELSE 0 END),0) AS coins,
            COALESCE(SUM(CASE WHEN kind='coins' AND amount IS NULL THEN 1 ELSE 0 END),0) AS unknown_coin_items
            FROM mastery_rewards""").fetchone()
        return dict(row)
