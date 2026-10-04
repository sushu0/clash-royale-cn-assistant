# Continue the active navigation goal

Goal remains ACTIVE and unfinished. Do not mark complete until the remaining visible navigation/hidden pages are explored, updated code is deployed into the current WPF backend, and the actual robot is restarted for infinite Classic 1v1 with complete-cycle evidence.

## Current game/runtime

- Last game action: `daily_activity_closed` (exact activity footer Confirm at ADB 210,601); game is now Classic 1v1 lobby. Last screenshot: `pages/daily_activity_closed.png`.
- Robot was stopped initially, then another chat deployed WPF and started two fights. Root set DRAIN and it completed safely at total 1198 / closed_loops 1198. All pending flags in work/random-mastery/checkpoint.json are false. Keep robot paused until inspection/deployment is done.
- Current WPF frontend: outputs/wpf-desktop-20261004/app/ClashAssistant.Desktop.exe. Preserve it and desktop shortcut. Current backend is OLD outputs/wpf-desktop-20261004/backend/ClashBackend.exe and must be rebuilt/switched.
- Root created work/random-mastery/DRAIN. Before final restart, preserve it by a narrow move into this task's work directory, or let normal app start clear its own marker. Do not broad delete/reset data.
- User explicitly answered they have paused other game operations; this task can now exclusively inspect the game. Do not ask again.

## Skills/runtime/tools

- windows-development and computer-use skills were read/announced, plus all computer-use docs. Initialize every shell with D:/codex/bin/Initialize-CodexEnvironment.ps1; cwd always D:/codex or a real subfolder.
- Python: work/repair-20261003/verification-env/Scripts/python.exe. Preserve existing runtime/locks.
- For Android game inspection use existing bot ADB APIs via work/navigation-learning-20261004/inspect_game.py (PYTHONPATH points to py-clash-bot). Each invocation records before/after PNG and one observed action in inspection-actions.jsonl, then source classification. Options --tap X Y, --swipe X1 Y1 X2 Y2 --swipe-ms 70|420, --recover, --classic, --back. --expect NAME checks current frame against pages/NAME.png; do not reuse a stale source. Look at before PNG if mismatch. Use --recover for actual newly implemented robot nav validation.
- ADB: D:/codex/CodexWork/tool_runtimes/android-platform-tools/platform-tools/adb.exe, serial 127.0.0.1:21503, fixed 419x633 /160.
- Windows app actions must use sky through node_repl. Helpers return screenshot-0 IDs that may fail if supplied. Some mouse/index actions had DPI issues; keyboard Alt_L+F4 safely hides WPF to tray and detaches MEmu (does NOT exit). Keyboard Tab focus can operate buttons without DPI. Read current state before inputs. No direct PowerShell UIA.
- SDK/news produced a stale ADB base lobby while native screen showed article. A safe installed-game relaunch was performed only after confirming closed checkpoint/no battle/no claim; it restored input/screenshots. Never repeat that recovery on an active/owed battle/receipt.

## Implemented source

- Root owns cn_1v1_loop.py and cn_random_mastery_loop.py. Backups in this task's backup/; do not overwrite originals. Existing dirty frontend/WPF work is user-owned, no resets.
- Daily gift helper cn_daily_gift.py recognizes actual 08:00 report, exact title + all three labels + purple cosmetic panel, then chooses 我想变好看 at 210,434. Both loops integrated, 3-choice cap, fresh frame, isolated free reward context follows ONLY known reward/continuation, 40 taps/120 sec maximum. Actual tomorrow cosmetic follow-up was not available, do not pretend tested.
- cn_page_navigation.py/coords.py/nav.py/state_detect.py owned by page_navigation agent. Current approx 73 learned rules/180 crops before latest daily activity pages. All page evidence/definitions under this task; runtime atlas in pyclashbot/detection/reference_images/cn_pages/manifest.json.
- Known return helper recover_cn_page_once has flags allow_spectator_exit and allow_unowned_confirmation; defaults prevent unowned confirmation cancellation. Root passes unowned only outside generating_deck, with pending battle/claim guards. Owned new-deck confirmation workflow remains separate.
- Both loops asynchronously cancel ONLY exact game exit confirmation via small cn_game_exit_cancel helper, even in battle; 3 cap, fresh frame, no state/receipt mutations. Does not cancel generation, clear-deck or spectator prompts.
- Random manual CardMastery -> CardInfo -> card editor -> confirmed deck normalization added. card editor has weak legacy deck match: startup/require deck/source nav explicitly exclude learned page card_editor until footer Confirm. Back in card editor actually opens game quit dialog! Do not use Back there; footer Confirm 210,609 closes editing. No cards were altered during inspection.
- Initial mode causal gate added to both loops; random `_prepare_classic_lobby` calls verify_menu=True, verifies fresh lobby + classic, protects battle/result/reward, one idle app relaunch allowed through existing budget. Source/asset identity includes helpers and all new PNG/JSON. Random policy v25-learned-navigation.
- Run startup Collection now returns to lobby before switching to classic and entering deck; inspect/tests this latest small branch and unowned flag additions as needed.

## Critical real mode evidence

- `mode-trace-latest.log` and mode-trace/trace.json now show ok=true. Physical flow: lobby -> selector315493 -> 3 menu observations -> gentle swipe320520320355 -> exact 1v1 row319534 -> one tap -> unknown transition -> 3 fresh lobby/classic true. Runtime 9.46 seconds.
- Earlier large swipes skipped the full Classic1v1 row and stuck at bottom. Real failure frames saved under mode-trace/*-navigation.png and copied fixtures by nav agent. Agent fixed gentle forward and reverse after no progress. Do NOT accept mocks alone as live mode proof.
- Initial Classic2v2 selection was only mode selection, no 2v2 match. Restored 1v1 (source exact blue icon correlation .9999997 vs 2v2 .123).

## Completed inspected families

- Main burger menu; battle log/tournament history; leaderboards 3 tabs, clan detail/member menu, full player profile top/middle/season/stats/bottom; TV + arena variants + spectator exit confirmed; tournament list/help/create form; inbox; settings/more settings top/bottom (no security/account changes); shop 4 top categories/9 subcategories/scroll regions, offer detail, emote market scroll/info; social/no clan intro/search/advanced/create/emblem scrolled/filter/addfriend/friend menu, 3 friends tabs; profile editor banner/background/king/tower/emotes+scroll using safe Back; collection 6 categories including full card collection, sorting 5 choices and direction restored, filters; bottom unowned heroes and royal tower troops; ordinary card info video/stats/text, card skins drawer; hero all 5 panels, unowned hero; tower all 4 panels; manual mastery/task tooltip, duel deck/help, card editing; deck action menu + generator/clear confirmations cancelled; elite/how-to/gameplay and awakening 2-page explanations.
- War button gave 暂未开放, source remained lobby. Treat unavailable as unavailable, not entered.
- Card library sorting and awakening filter were restored after inspecting; no upgrade/purchase/unlock/clear/create deck or clipboard/send operations.
- `daily_activity` is 学院闹翻天, already claimed; help two pages/special-piece info inspected and X35756 returned. Footer Confirm210601 -> lobby verified as daily_activity_closed. Notify nav agent it can activate these shared cues (shop label + footer; help fixed explanation + X).
- Royal pass opened at tier90, scrolled through tier85/71 with left-column swipes (start y315; starting on sticky header does not scroll), footer210602 -> lobby verified. Atlas rule already added, no claim/purchase.

## Still required before completion

- Explore remaining major lobby icon entries after prior SDK stale state: upper-left diamond-plus, CRL event, purple cards/news, right blue backpack/card icon and red event icon, central crown/quests, king XP/旅途, goblin lower-left, classic info i, reward/pass child informational entry where navigational, any newly revealed menu/subpages. Skip final resource/account/external actions; read-only view is authorized. Some need scroll. Do not shrink goal to current atlas alone.
- News list/article snapshots exist (`left_cards_event`, `news_article_back`), but actual return chain was complicated by SDK stale surface. Atlas rules exist; validate actual current paths or clear through causal startup recovery as appropriate.
- Ask page_navigation agent for final atlas/gate validation when new screenshots are added; it must not touch game. Helpers must not confuse dark background/battle/result/reward or duplicate cue/too-small crop.
- Final scoped py_compile, Ruff check/format, ty check and appropriate regression suite. Recent checkpoints: initial 277 passed; later 111 scoped passed incl safeexit15/manualnav42/daily24/modegate30; detector/mode most recent196 (before last gentle trace fix); mode real-frame25 tests passed. These were checkpoints, not final latest full suite.
- Rebuild ONLY backend with scripts/build_wpf_backend.py using env PYCLASHBOT_WPF_BACKEND_OUTPUT outputs/wpf-desktop-navigation-20261004/backend, PYCLASHBOT_WPF_BACKEND_WORK work/navigation-learning-20261004/wpf-backend-build. WPF exe/dll/shortcut stay same.
- New backend does not support --self-check. Read-only JSONL snapshot/reports/shutdown probe with --data-root ROOT --read-only, CREATE_NO_WINDOW, verify frozen/runtime and exit0. Verify copied source, compiled helper files, PNG/JSON hashes equal final source.
- Safe switch: restore WPF from tray (launch same exe invokes existing singleton show), use normal 退出软件 (NOT X, NOT kill), verify old app/bridge gone. Back up app/wpf-runtime.json, change only backend_path to new absolute D path, restart same WPF exe. Settings loaded only in ctor, no hotreload. Verify frontend-state backend_path new; start via actual Start UI as requested; then prove infinity max_battles=0, new policy/assets, at least complete repeated cycles and next match active. Preserve all stats/receipts/reports/VM.
- Update outputs/NAVIGATION_MEMORY_20261004.md and durable acceptance JSON/report; documentation agent wrote interim draft and memory note only. Memory updates only via new small ad_hoc note, do not edit registry. Do not claim all buttons/unknown future layouts validated by PNG counts alone.

## Agents

- page_navigation: owns atlas/coords/nav/state_detect + tests, current mainEvents update pending, no live game inputs.
- deployment_audit: read-only deployment audit + tests; existing test_cn_classic_mode_gate30, safeexit15, learned_navigation_integration42; can help final package audit. No UI/robot mutation.
- daily_reward completed helper/tests; navigation_documentation completed interim doc + note. Reuse via followup_task if needed.

Remember: user wants actual updated robot resumed infinitely AFTER exploration, not just source edits, tests, or a plan. Goal is not complete yet.
