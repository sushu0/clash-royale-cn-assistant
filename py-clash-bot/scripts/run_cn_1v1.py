"""Run the minimal Chinese-client 1v1 loop. Ctrl+C stops it."""

# Chinese operational messages keep native punctuation.
# ruff: noqa: RUF001

import argparse
import logging
from pathlib import Path

from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop, RecoveryExhausted
from pyclashbot.detection.cn_threats import threat_template_health
from pyclashbot.utils.process_ownership import ExclusiveFileLock, OwnershipError, device_lock_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, help="Path to the existing adb.exe")
    parser.add_argument("--serial", required=True, help="ADB serial of the MEmu instance")
    parser.add_argument("--memuc", help="Path to memuc.exe for VM recovery")
    parser.add_argument("--vm-index", type=int, default=0)
    parser.add_argument("--strategy", choices=("567", "hog", "random"), default="567")
    parser.add_argument("--log", required=True, help="Concise battle log under D: drive")
    parser.add_argument(
        "--max-battles", type=int, default=0, help="End a finite validation at the lobby; 0 runs indefinitely"
    )
    args = parser.parse_args()
    if args.max_battles < 0:
        parser.error("--max-battles must be nonnegative")

    # One Android device must have only one input owner, across all strategies.
    device_lock = ExclusiveFileLock(device_lock_path())
    try:
        device_lock.acquire()
    except OwnershipError:
        parser.exit(78, "Another verified runner already owns this emulator.\n")

    try:
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        )
        logging.getLogger("pyclashbot.emulators.adb_base").setLevel(logging.WARNING)
        runner_class = ChineseOneVOneLoop
        if args.strategy == "random":
            from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop  # noqa: PLC0415 - selected mode only

            runner_class = RandomMasteryLoop
        try:
            health = threat_template_health(include_567=args.strategy in ("random", "567"), force=True)
            if health["status"] != "healthy":
                raise RecoveryExhausted("识别素材库校验失败；已停止启动：" + str(health["errors"]))
            runner = runner_class(
                args.adb, args.serial, logging.getLogger("cn-1v1"), args.memuc, args.vm_index, args.strategy
            )
            runner.run_forever(max_battles=args.max_battles)
        except KeyboardInterrupt:
            logging.getLogger("cn-1v1").info("用户停止；已保留当前断点")
        except (RecoveryExhausted, ValueError, RuntimeError) as error:
            logging.getLogger("cn-1v1").error("恢复失败，运行器已停止: %s", error)
            raise SystemExit(78) from error
    finally:
        device_lock.release()


if __name__ == "__main__":
    main()
