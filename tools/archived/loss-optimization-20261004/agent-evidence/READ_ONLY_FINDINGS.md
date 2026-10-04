# 随机卡组失败对局的只读证据审计

审计源：`D:\codex\CodexWork\clash\outputs\cn-random-mastery.jsonl`，154,325,828 字节，153,115 行；SHA256 `75d1c85e84a98cd698c9a440ff54ca2b13b725c63324c780c5cd38aee50da47d`。源文件在分析前后 SHA256 相同。按 `(session, finished_battle)` 去重，只计 `battle_finished`；未完成第1263局不进入结果分母。没有发现 JSON 解析错误。

## 全部失败的证据级别

共1,262局已完成对局：278胜、984负。`all-random-losses.csv` 对全部984局逐局列出 session、battle、版本、原始源行、结果截图与 hash、部署计数、decision 数、截图完整性以及最新规则的可复现决策模式。

| 证据项目 | 失败局数 |
| --- | ---: |
| 已记录失败结果 | 984 |
| 有 play trace | 981 |
| 有结构化 decision trace | 848 |
| 结果截图 SHA256 与当时记录相同 | 677 |
| 结果图匹配且有结构化 decision trace | 577 |
| 至少有一张出牌后 play 帧 SHA256 匹配 | 380 |
| 结果图与至少一张 play 帧都匹配 | 353 |
| 结果截图文件仍在但 hash 不符 | 307 |

离线使用项目 `ChineseVision` 对677张匹配结果截图全部重新识别：677张全部是 result 页面、全部识别为失败，无不符。证据在 `result-vision-replay.json`。`work/random-result-evidence` 的3张归档全部已经在677局之内，不增加可复核局数。

对失败局的 `battle_started`、`battle_observed`、`play_evidence`、`selection_evidence`、`battle_finished` 共22,148条截图引用验证原始 SHA256：4,287条匹配、17,861条 hash 不符。这里是截图引用数，可能重复引用同一张图片。旧 `recent-*` 环形截图已被后来局覆盖；文件存在不能证明它对应早期 trace。不存在完整连续视频，不能把353局称为完整逐帧回放。

## 当前 v2.3 规则的复核模式

当前策略来源 hash `242f203691327d362ef27b207a414a7748a7c4d656aaa9f6099319abd2b304d7`，规则 `random-rules-v2.3-20261003-evidence-gates`。这版共有165局失败，165张结果图全部 hash 匹配。对应3,030条 play trace，98条未确认，未确认率3.23%。总体部署并非普遍失效。

| trace 中的模式 | 发生次数 | 涉及失败局数 | 解释边界 |
| --- | ---: | ---: | --- |
| 远端警戒存在时消耗唯一当帧可用对空防守牌进行轮转/支援/进攻 | 36 | 28 | 当帧唯一可用，不等同整个8卡组只有一张对空 |
| 远端警戒存在，非防守支出后余额低于其他当帧可用防守牌成本 | 31 | 22 | 固定3费不能覆盖某些随机手牌的响应成本 |
| 同路3秒内重复防御 | 101 | 62 | 其中可有合理紧急加防，不能直接全称浪费 |
| 确认目标法术后2秒内因“已有可见友军接敌”停止响应 | 5 | 5 | 法术进入 defense_commits；可复现状态错误 |
| 满10费仍处于 hold 的观察帧 | 115 | 23 | 包含合法的短暂等待/特殊卡等待，不能等同115次持续空费 |
| 10秒内重复下建筑 | 4 | 3 | 含左右换防，缺少建筑存活确认；不支持直接扩大冷却 |

详细原始 hand、cues、decision 与关联前后 trace 在 `v23-scenario-samples.json`。分析先列最近样本，不删除旧原证据。模式表示已观测决策行为，并不证明它是对应失败的唯一原因。

## 代表性场景

1. 第1257局，2026-10-04 23:11:02，原trace第152356行。右路远端警戒 `(285,215)`、`(321,214)`，8费将唯一当帧可用对空 `mother_witch` 4费按 cycle 投到左后场 `(169,467)`。23:11:04 右路敌方已在 `(311,348)`，23:11:05 到 `(319,378)`。相邻第152357行 `recent-play-43.png` 原 SHA256 匹配；离线看图可见右桥密集敌兵和己右塔受攻击，女巫婆婆在左后场。截图路径：`D:\codex\CodexWork\clash\work\random-mastery\20261004-201600\recent-play-43.png`。抽取整局 trace 在 `battle-1257-extracted.json`。
2. 第1259局，23:15:37，原trace第152549行。左路警戒 `(134,199)`，8费把唯一当帧可用对空电法投到右后场 `(250,467)`，数秒后左路敌方过桥。抽取在 `battle-1259-extracted.json`。
3. 第1041局，01:36:04，原trace第123602行。左路警戒 `(76,259)`，8费消耗5费女皇按 cycle 投后场，仅留3费；其他当帧可用防守牌只有7费超骑。固定3费应急预算无法覆盖剩余防守手牌。抽取在 `battle-1041-extracted.json`。
4. 第1172局，12:24:19，原trace第141400-141401行。雪球确认后，同路当前敌人由 `(307,333)` 到 `(305,348)`，己右塔 fill 从0.205到0.051，仍7费，却因“已有可见友军接敌” hold。三秒后才打火球，到12:24:28记录失败。日志表明法术被当作新防守单位提交后抑制了后续响应；当前hold不证明友军有效处理敌军。抽取在 `battle-1172-extracted.json`。
5. 第1049局，02:01:27-02:01:29，原trace第124783-124784行。满10费，可识别手牌三枪9费、火球4费、滚桶2费，当前没有近敌；因合法组合/轮转选择规则持续 hold。这是重费支援牌满费轮转缺口的可复现输入。抽取在 `battle-1049-extracted.json`。

## 验证与复现

仅创建本目录中的分析脚本、CSV、JSON和本说明，未修改源日志、截图或策略代码，未使用 Computer Use、未操作游戏或前台界面。

解释器：`D:\codex\CodexWork\clash\work\repair-20261003\verification-env\Scripts\python.exe`。三个新Python脚本均已执行 `-m py_compile`，分别完成全量审计、代表性trace抽取和677图离线重识别。PYTHONPYCACHEPREFIX 指向本目录的 `pycache`，shell均初始化 `D:\codex\bin\Initialize-CodexEnvironment.ps1`，cwd始终在当前项目内。脚本可按先 `audit_random_losses.py`、后 `extract_examples.py` 和 `replay_loss_results.py` 的顺序重跑。

这些是分析衍生物，无须回滚原项目；原日志与截图保持原位。
