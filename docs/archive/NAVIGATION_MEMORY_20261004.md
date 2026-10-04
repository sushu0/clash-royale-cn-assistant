# 皇室战争导航记忆与覆盖证据

更新时间：2026-10-04（Asia/Shanghai），最后实机导航检查结束于约 20:01，部署后于 20:16 从 WPF 实际启动，20:22:37 的运行验收通过。状态为 **completed_verified**：本轮当前可进入、可查看的导航及安全返回已记录；新后台完成两局连续闭环，第三局继续进行。110 个规则族不等于 110 张不同屏幕，260 个识别区域不等于按钮数量；本次验收不扩展为所有未来布局、未开放内部页面或购买 / 账户 / 社交最终提交均已完成。

用户要求包括三部分：查看 08:00 与 11:44 两份异常报告；每日奖励再次出现时选择“我想变好看”；实际查看顶层页面、下拉内容和子页面，并让机器人能逐步返回经典 1V1，最后恢复无限对战。

机器人持久页面记忆保存在 [页面图谱 manifest](D:/codex/CodexWork/clash/py-clash-bot/pyclashbot/detection/reference_images/cn_pages/manifest.json) 及同目录模板中。规则来源是当前游戏截图，不是只有这份文字。日常奖励的独立规则与模板在 [cn_daily_gift.py](D:/codex/CodexWork/clash/py-clash-bot/pyclashbot/detection/cn_daily_gift.py) 和 [每日奖励 manifest](D:/codex/CodexWork/clash/py-clash-bot/pyclashbot/detection/reference_images/cn_daily_gift/manifest.json)。

## 两份异常报告

| 原报告 | 画面事实 | 本次处理要求 |
| --- | --- | --- |
| [2026-10-04 08:00:06 报告](D:/codex/CodexWork/clash/outputs/error-reports/20261004-080006-841991-13d659b07abe29404c728160/report.md) | [截图](D:/codex/CodexWork/clash/outputs/error-reports/20261004-080006-841991-13d659b07abe29404c728160/game.png) 是“福袋天降 好事成三”，含“我想变富有”“我想碰碰运气”“我想变好看”三个选择；当天计数为第 3 天 / 共 9 天。原机器人在导航之后未确认经典 1V1 大厅。 | 只在完整识别这一奖励选择画面时点击“我想变好看”。模板不依赖天数和礼物图案，次日仍需重新识别。下一天尚未发生，不能声称已在次日实测。 |
| [2026-10-04 11:44:18 报告](D:/codex/CodexWork/clash/outputs/error-reports/20261004-114418-817250-ce8a6400e704409b19f7445d/report.md) | [截图](D:/codex/CodexWork/clash/outputs/error-reports/20261004-114418-817250-ce8a6400e704409b19f7445d/game.png) 是收藏里的勋章页面，已向下滚动，上方标签离开屏幕；不是卡组页。原暂停原因是“未确认 deck 页面，暂停操作”。 | 识别收藏页及滚动态底部导航，用当前截图找到对战页入口，再确认经典 1V1；不能继续沿用普通卡组页的盲点。 |

每日选择坐标来源是 419 × 633 游戏内容截图中的 `(210, 434)`。使用时必须由标题、三个原文标签与紫色外观面板共同确认，不能把别的奖励、购买页或暗背景弹窗当作这一选择。

## 当前证据与验收状态

本次文档已纳入 finish_main_pages 最终实机交接，root 已确认 page_navigation 图谱冻结：**110 个页面规则族、260 个导航识别区域，另有 3 张经典模式模板**。已读取最终 manifest 核对 110 / 260；19:35 的 91 / 216 仅为历史检查点。页面规则是可识别的结构及变体，不是逐一点击的独立按钮数量；PNG 包括 before/after、原生窗口、规范裁剪与同页变体，文件数不能证明完整覆盖。下表是 34 个入口 / 分支条目，也不等于 34 个按钮或所有可消费操作已完成。

文档状态为 **已验收，机器人继续无限经典 1V1**。finish_main_pages 已停止所有 Android / Windows 输入并把控制交回 root。root 已完成 backend 切换、真实“开始运行”和两局闭环 / 下一局运行验证。[JSON 验收摘要](D:/codex/CodexWork/clash/outputs/NAVIGATION_COVERAGE_20261004.json) 保存分支、证据路径、验收快照及实际边界。

[CONTINUE.md](D:/codex/CodexWork/clash/work/navigation-learning-20261004/CONTINUE.md) 是协作检查点，实际当前画面及进程仍需现场读取。[inspection-actions.jsonl](D:/codex/CodexWork/clash/work/navigation-learning-20261004/inspection-actions.jsonl) 保留逐次实际操作及新截图；[page-definitions.json](D:/codex/CodexWork/clash/work/navigation-learning-20261004/page-definitions.json) 是构建输入；[pages](D:/codex/CodexWork/clash/work/navigation-learning-20261004/pages) 是页面观察资料。

证据分为：**已查看**（实际截图）、**静态规则已定义**（manifest 中有两处独立识别特征及返回动作）、**实际返回**（实际输入之后的新截图与日志）、**入口受限/操作未提交**。前三项不能互相代替。动作采集时的 after_kind=unknown 是当时识别器的结果；后续新增模板可改变识别，但必须重新回放验证，不能把日志中的旧 unknown 改写成已通过。

最终 [navigation-final-validation.json](D:/codex/CodexWork/clash/work/navigation-learning-20261004/navigation-final-validation.json) 与 [page-replay.json](D:/codex/CodexWork/clash/work/navigation-learning-20261004/page-replay.json) 更新为 **110 条规则 / 518 张 BGR 游戏内容帧，其中 422 帧识别为导航，5 帧保留 unknown**。四张是过渡 / loading：card_skin_close_before、daily_activity_returned_before、drain_observation、game_relaunched；另一张 final_classic_lobby_native 是桌面原生裁剪，其模糊与颜色像素不满足严格运行时核心识别，仅作视觉旁证。真正 ADB final_classic_lobby.png 已确认 lobby + classic_selected=true。其余帧包括正常大厅、模式和状态资料，不能由 518−422 直接推断未覆盖页。[native-heldout-replay.json](D:/codex/CodexWork/clash/work/navigation-learning-20261004/native-heldout-replay.json) 中五张赛季长文章新裁剪均命中既有文章规则，无需修改冻结资产；完整 Windows 窗口和图标不直接当作 419 × 633 游戏内容帧。Unknown 继续禁止盲点，重放数字不替代实机返回。

## 可见入口覆盖矩阵

表中给出四类证据：导航查看、滑动及子页、实际关闭/返回、API/识别。文件名均相对于上面的 pages 文件夹；返回“规则”只说明静态目标存在，缺少实际操作链的分支仍保留缺口。

| 可见入口 / 分支 | 导航查看 | 滑动及子页 | 实际关闭 / 返回 | API / 识别证据 |
| --- | --- | --- | --- | --- |
| 每日福袋三选一 / 左紫卡片 | 已看 08:00 原异常截图；本轮左紫卡片 (42,320) 实际进入 purple_cards_news，显示今日已领取 | daily_gift_info 概率提示；i (352,67) 再点关闭；当前第 4 天 / 共 9 天仅为观察值，不作为识别特征 | daily_gift_info_lobby 底确认 (210,606) → lobby；本轮未领奖；次日选择及免费奖励后续仍待真实事件 | daily_gift_action 只在完整三选一画面选择“我想变好看”；已领取页及概率提示另有安全关闭规则；**当前已领取不能推断今日选择内容** |
| 收藏 → 勋章 | collection_badges；11:44 原报告下拉页 | 已看顶部和标题离屏后的勋章列表；资料勋章点击没有进入独立详情 | validated_home 使用 collection_scrolled 恢复后新帧为 lobby | collection_badges / collection_scrolled 双导航特征；不把收藏当卡组 |
| 卡组 → 卡组槽 / 2V2 卡组 | classic_deck、deck_current | 卡组槽、操作菜单与决斗卡组入口已看 | deck_2v2_return 后新帧 lobby；2V2 只是模式选择，未启动匹配 | deck_2v2 的返回规则；经典模式另由因果 gate 确认 |
| 卡组 → 普通卡牌 | deck_card_menu、card_information | card_stats、card_description、card_text_description；视频/统计/文字滑动 | 信息 × 到编辑层；card_editor_confirmed 点击底部确认 (210,609) 回卡组 | card_information / card_editor；**编辑层不能用 Android Back 返回** |
| 普通卡牌 → 大师任务 / 皮肤 | card_mastery_from_info、card_skin_selector | mastery_task_info、mastery_locked_task；皮肤抽屉 | mastery_to_card_info、card_skin_close 回信息；再关闭编辑层 | card_mastery_detail / card_skin_selector 规则；没有领奖或更换皮肤 |
| 卡组 → 英雄 | hero_information | 视频、技能、统计、说明、文字共五类面板，横向正反滑；未拥有英雄 locked_hero_information | hero_closed 后仍编辑层；hero_editor_finished 底部确认；locked_hero_closed 回收藏 | hero_card_information / hero_card_chrome / gold / unit_chrome，按已观察不同标题栏识别 |
| 收藏 → 塔兵 | locked_tower_card_menu | 初始说明、视频、统计、描述四面板 | tower_closed 点击 × 后回收藏 | tower_card_information；未拥有塔兵只看资料，没有购买或解锁 |
| 收藏 → 卡牌全集 | collection_open | 排序菜单五项循环、正反序、筛选；collection_cards_scrolled/lower 到底部英雄与塔兵 | 排序恢复；collection_direction_restored；collection_filter_closed；validated_home 回大厅 | collection_scrolled / collection_filter_options；逐帧识别控制位置 |
| 收藏 → 卡牌形态 / 精英 | collection_card_forms、elite_info、elite_gameplay_info | 精英获取与玩法说明已看 | 已定义 elite_close → 收藏；当前 jsonl 缺早期完整返回链 | elite_info / elite_gameplay_info；未兑换、解锁或升级 |
| 收藏 → 觉醒说明 / 筛选 | awakening_info、awakening_collection | awakening_sources 横向第二页；awakening_filter_dialog | awakening_closed 回收藏；awakening_filter_restored + restored_collection 恢复过滤 | awakening_information / collection_filter_options |
| 收藏 → 大师 / 外观 / 表情 | collection_mastery、tower_skins、emotes、badges | 六类收藏入口已看；具体每个外观物品不是逐一提交修改 | 静态 collection 返回规则；早期逐层实际日志仍需补充 | 各 collection_* 加滚动通用底部导航规则 |
| 卡组 → 决斗卡组 | deck_options | duel_deck_help 子页 | duel_help_closed 关闭说明；duel_deck_back 以安全 Back 回卡组 | duel_deck，受 idle 的 Back guard 保护 |
| 卡组操作菜单 → 生成 / 清空 | deck_action_menu、deck_menu_again | random_deck_confirmation、delete_deck_confirmation；弹窗内容已看 | deck_confirmation_cancelled、clear_deck_cancelled 均取消；menu_closed 闭合 | unowned_deck_confirmation / unowned_clear_deck_confirmation 需要明确 unowned guard；未创建/清空 |
| 大厅 → 模式选择 / 经典 1V1 | game_modes_top/middle/scrolled；经典 2V2 选择状态 | 实际轻滑 (320,520→320,355) 后完整 1V1 行出现；大滑动失败样本已保留 | mode-trace 最新第 7、8、9 帧连续 lobby + classic=true | 真实 helper trace ok=true；精确 1V1 行点击 (319,534)，耗时检查点 9.46 秒；不是 mock 证明 |
| 右上菜单 → 记录 / 排行榜 | burger_menu、battle_log、tournament_history；排行榜三标签 | 玩家资料上/中/赛季/统计/下方，部落详情、成员菜单 | 各 × / 外部闭合规则已定义；当前 jsonl 缺这组早期完整返回链 | burger_menu / battle_log / leaderboard_* / player_profile / clan_detail / clan_member_menu |
| 右上菜单 → TV / 观战 | royale_tv、royale_tv_arena、spectate | 竞技场切换、观战、退出确认页均已看 | Back → 退出确认 → 是 → TV → × 的规则；早期日志链仍需补足 | spectate / spectate_exit_confirm 只能在 idle、允许退出观战时恢复 |
| 右上菜单 → 锦标赛 | tournaments | tournament_help、tournament_create 表单 | 帮助 ×、创建 ×、列表返回规则；未提交创建 | tournaments / tournament_help / tournament_create；离线覆盖嵌套返回 |
| 右上菜单 → 收件箱 / 设置 | inbox、settings | more_settings_top/bottom 滚动已看 | 关闭更多设置 → 关闭设置的规则；未更改账号安全信息 | inbox / settings / more_settings |
| 商店 → 分类、宝箱、资源 | 已看优惠/周限购/礼券/外观/表情及宝箱/资源分类 | 优惠和资源上、中、下；shop_offer_info；emote_market 上、下及 emote_offer_info | 说明 × → 商店，市场底部 × → 商店，商店底部对战规则；早期实际链待补 | shop_* / shop_scrolled / emote_market / emote_offer_info；没有购买 |
| 社交 → 好友 / 部落 | social_home、filter、add_friend、friend_menu | 部落介绍/搜索/高级/创建/徽章及徽章下拉；大厅朋友三标签 | social_return_verified → lobby；friends_return × → lobby；其他层返回规则 | social_* / clan_* / friends_dialog；个人内容 fixture 只留公共识别区域 |
| 大厅 → 自己资料 / 外观 | own_profile | 横幅、背景、国王、塔皮肤、表情页签与表情下拉 | profile_edit_back 实际回资料，badge_detail_return × → lobby；未确认修改 | profile_editor 使用 idle Back；player_profile 使用 ×；勋章点击未产生独立详情 |
| 大厅 → 部落战 | clan_war_intro | 当天提示暂未开放、未加入部落条件；没有内部画面 | 点击后仍大厅 | **入口不可进入**，不伪造已探索部落战内部 |
| 顶部资讯 / 赛事入口 (338,67) | top_news_fresh_window、news_list_scrolled_window；当前左紫卡片实际是福袋，不是资讯 | 列表滚动；短正文 news_article_fresh_window；带图片赛季正文 news_season_article_loaded/middle/bottom_window；赛事标签 (293,69) → news_esports_live_window | 短文及赛季文返回列表 (210,600) 均成功；列表关闭 (210,600) → news_closed_lobby_window；直播 X (381,64) → news_esports_closed_window 列表 | 原生素材通过 (0,32,419,665) 规范裁剪；news_list/article 原生变体及直播安全 X 规则已纳入 110 族冻结图谱。**长文只证明向下查看，不证明到文末；SDK 真实表层已关闭** |
| 大厅 → 皇室令牌 | pass_actual 打开于第 90 阶 | pass_scroll_probe、pass_track_middle/lower 已看 90/85/71 阶；滚动须从左栏开始 | pass_closed_verified 底部确定 (210,602) → lobby | pass_royale_track；没有购买/领取令牌奖励 |
| 大厅 → 每日学院活动 | daily_activity：学院闹翻天，已领取状态 | daily_activity_help 第一/第二页；special_piece 说明 | 帮助 × (357,56) 回活动；daily_activity_closed 确定 (210,601) → lobby | daily_activity / help / help_alt；未重复领奖 |
| 大厅 → 左上礼包入口 | evolution_shop_entry | custom_bundle_choices；custom_bundle_help 与 bottom 看完全部可见内容 | chooser × (357,146) → 礼包；内容 × (364,31) → 礼包；custom_bundle_closed × (359,159) → lobby | custom_bundle / choices / help；没有选择购买商品或提交交易 |
| 大厅 → CRL 冠军之路 | crl_native_page、crl_reopen | crl_rules / native_bottom 滚动；需同时看原生与 ADB 实际表层 | crl_return (155,594) → lobby；规则 × (369,119) → CRL | crl_champion_road / adb 与 crl_activity_rules / native；只看活动及规则 |
| CRL → 助威商城 | crl_support_shop_raw / crl_support_shop_window | 商城商品区下拉到 crl_shop_bottom_window；规则首、中、末 crl_support_shop_rules / crl_shop_rules_bottom/end_window；原生规范裁剪保留 provenance | 规则 X (369,119) → crl_shop_rules_closed_window 商城；商城底部返回 (155,594) → crl_shop_return_lobby_window；ADB crl_shop_return_lobby 同为 lobby | crl_support_shop / native / scrolled；原图与规范图哈希保留。所有兑换与助威提交均未操作 |
| 大厅 → 蓝色背包 / 觉醒贩卖机 | blue_backpack (375,195) | 规则上/中/末；奖池上/中/末；单项道具信息 awakening_prize_detail；记录与记录下拉 | 道具 X (363,214) → 奖池；奖池 / 规则 / 记录 X (350,124) → 主页；awakening_machine_closed 主 X (360,116) → lobby | awakening_machine 及规则、奖池、记录、道具信息规则已纳入冻结图谱与最终重放；未开启、加币或购买 |
| 大厅 → 红色活动 | red_event (375,270)、red_event_barbarian 两标签 | 两标签规则首、中、末与记录；炽焰奖池上 / 下；黄金武神详情 red_barbarian_item / stats / hero 三形态；奖池普通皮肤图点击没有新页 | 规则 / 记录 X (350,124) → 当前标签；炽焰奖池 X (348,75) → 主页；精英详情 X (351,30) → red_barbarian_item_closed；red_event_closed 主 X (366,21) → lobby | 主标签、奖池和三形态详情已交付图谱；规则 / 记录共享已观察 chrome；未开启、购买或改变外观 |
| 大厅中央王冠 (210,424) | crown_quests 实际为“对战获胜奖励”提示层 | 显示奖励说明，未出现任务子页面 | 原点再次点击 → crown_tooltip_closed 大厅 | crown_reward_tooltip；不依赖奖励数量或倒计时；没有领取 |
| 大厅左下哥布林 (40,460) | goblin_event：龙宝国王 | 规则首 / 末；奖池上 / 下；记录上 / 下；绿色竖标放大镜 (94,327) → goblin_king_preview；右上炮管仅演示预览，无独立页 | 规则 / 记录 X (350,124) → 主页；奖池 X (348,75) → 主页；预览确定 (210,616) → goblin_preview_closed；goblin_event_closed 主 X (367,22) → lobby | 主页、预览及共享规则 / 奖池 / 记录规则；未抽奖、消耗货币或改变跳过动画复选项 |
| 大厅左上等级 (15,16) | king_xp 实际为卡牌收藏等级；底塔标签 (158,589) → king_level_chests 国王塔说明 | 双方向滑动均无滚动 king_collection_lower/upper；等级上限说明和未来奖励点按均无新页；没有“旅途”页面 | 底卡牌标签 (263,588) 返回收藏等级；king_level_closed X (354,33) → lobby | card_collection_levels / king_tower_level；不依赖具体等级、数值或奖励图；无领奖或升级 |
| 经典说明蓝 i (356,453) | classic_battle_info：经典 1 对 1 | 单页规则说明，无滚动或后续导航控件 | classic_battle_info_closed X (345,253) → lobby | classic_battle_information；同页恢复仍需当前明亮说明层 |

订制礼包内容截图合并后可见八种商品：野蛮人滚桶、雷电精灵、火球、渔夫、猎人、皇家幽灵、皇家巨人、骷髅兵。这里记录的是说明列表，未选择或购买商品。

## 必须保持的返回规则

1. 每次导航先读取新游戏画面。每日奖励、普通导航、比赛、结算与奖励 receipt 分别识别；不能用背景大厅直接穿透点击表层。
2. 一次只执行图谱提供的一步关闭或返回。弹窗关闭后重新读取，再确认父页；没有新图像证据不能跳过嵌套层。
3. 收藏/商店与社交/活动的底部对战标签位置不同。匹配当前图像中的目标控件，而不是把同一坐标复用于所有页面。
4. 卡牌编辑必须用底部“确认” (210,609)。Android Back 在该页实际打开游戏退出确认；退出确认只点“取消”，最多三次，并保持已有对战、奖励、receipt 状态。
5. 观战、决斗和资料编辑的 Back 路径需要 idle 与显式允许；默认普通恢复不点。生成/清空弹窗只有明确不是机器人自己持有的生成流程时才允许取消。
6. 进入经典 1V1 使用真实因果检查：展开模式、轻滑完整目标行、点击精确行、读取连续新大厅与模式标识。已选择 2V2 后恢复只改变模式，没有启动 2V2 对战。
7. 学习后的普通导航仍有 12 步上限，未知画面不发盲点。动态新赛季、未开放页或今后改变的布局需要新证据。

[mode-trace-latest.log](D:/codex/CodexWork/clash/work/navigation-learning-20261004/mode-trace-latest.log) 和 [trace.json](D:/codex/CodexWork/clash/work/navigation-learning-20261004/mode-trace/trace.json) 保存真实模式恢复，trace 的 ok=true。这证明该检查点的经典选择与返回，尚不能证明当前冻结 WPF backend 已加载这些新逻辑，更不能单独证明无限对战运行闭环。

最后导航收尾再次执行 `inspect_game.py final_classic_lobby --expect daily_gift_info_lobby --classic`，返回 **exit 0**，动作日志记录 `classic_mode_round_trip_verified`、after_kind=`lobby`。该命令只有 helper `navigate_cn_classic_1v1(..., verify_menu=True)` 成功才写这一动作。最新 [final_classic_lobby.png](D:/codex/CodexWork/clash/work/navigation-learning-20261004/pages/final_classic_lobby.png) SHA256 为 `cada7a058cfc1c0bb4f2b5092bf1de8e84de0fba044220d36be9eeb66cc8e37c`；最终验证文件再次确认该 ADB 帧为 lobby + classic_selected=true。随后原生 [final_classic_lobby_window.png](D:/codex/CodexWork/clash/work/navigation-learning-20261004/pages/final_classic_lobby_window.png) 在视觉上显示同一个经典 1V1 大厅，其裁剪只作旁证，不替代运行时 ADB 识别。资讯和直播 SDK 层真实关闭，未用旧 ADB 大厅背景当作成功，也未执行新的 relaunch。

## 看过但没有提交的非导航操作

- 升级、觉醒/精英解锁、购买礼包/令牌/宝箱、金币/宝石/礼券/活动货币消耗与兑换：只看说明与详情，未提交。
- 清空卡组、生成/新建卡组：只看菜单与确认弹窗并取消。正常无限随机卡组策略的生成流程，仍由机器人原有持有状态控制，不能被“取消陌生弹窗”误取消。
- 复制、粘贴、分享、聊天、邀请、添加好友、加入/创建部落、发送或开放外部链接：只记入口，不提交发出操作。
- 登录、认证、账号设置和安全选项、外观确认：未提交，未读 Cookie、密码或验证码。
- 收藏排序、方向和觉醒筛选只是本轮查看用的可逆选项，已回到此前状态；资料、普通卡牌和英雄编辑层未改变卡组卡牌。

## 最终检验与运行验收

[pytest-final.log](D:/codex/CodexWork/clash/work/navigation-learning-20261004/pytest-final.log) 在 19:27:58 的 552 passed / 6 subtests passed 仅为旧检查点。已读取最终 [pytest-navigation-final.log](D:/codex/CodexWork/clash/work/navigation-learning-20261004/pytest-navigation-final.log)：**371 passed，36.55 秒**；root 表明这是六项 owner 检查。随后最终 [pytest-deployment-final.log](D:/codex/CodexWork/clash/work/navigation-learning-20261004/pytest-deployment-final.log) 记录 **708 passed、6 subtests passed，136.93 秒**。这是离线源码与模板检验，仍需部署后运行闭环。

root 已报告 7 个生产 Python 文件的 py_compile、Ruff check / format 和显式环境的 ty 全部通过；已读取 [quality-final.log](D:/codex/CodexWork/clash/work/navigation-learning-20261004/quality-final.log)，其中有两条 All checks passed 和 7 files already formatted。页面 agent 的暗层拒绝与对应动作回归已纳入最终检查。198 / 196 等早期例数不用于最终验收；具体命令、解释器和冻结包文件身份由 root 的最终审计绑定。

最终结果及保留边界：

- 本轮 finish_main_pages 剩余入口、子页、滚动与返回交接已完成；部落战内部当时未开放、非导航提交未操作。部分早期分支保留静态规则与截图而非完整输入链，表中如实标出其证据类型，不将其伪造为本轮再次实测或消费提交。
- 最终图谱冻结、page-replay、源回归与冻结包 source / asset 检验已完成；未知画面仍不能盲点。打包验证不替代实际无限循环。
- 只重建了 backend；当前前端仍为 [ClashAssistant.Desktop.exe](D:/codex/CodexWork/clash/outputs/wpf-desktop-20261004/app/ClashAssistant.Desktop.exe)。[打包验证](D:/codex/CodexWork/clash/outputs/navigation-verification-20261004/frozen-backend-verification.json)（20:12:34）与 [切换后验证](D:/codex/CodexWork/clash/outputs/navigation-verification-20261004/frozen-backend-post-switch-verification.json)（20:14:07）均 passed=true，覆盖 copied source、编译模块、PNG/JSON 身份和只读 JSONL；WPF EXE / DLL 与桌面快捷方式哈希保持，配置只改变 backend_path。outputs 中的最终报告副本与 work 原件 SHA256 相同。
- root 已通过旧 WPF 的“退出软件”正常退出，CIM 确认旧前端 / bridge 均已离开；原配置备份到 deployment/wpf-runtime.before-navigation.json。新 backend 为 [ClashBackend.exe](D:/codex/CodexWork/clash/outputs/wpf-desktop-navigation-20261004/backend/ClashBackend.exe)，SHA256 `fb69b45ce017e5882e3dbee5df18bc460d87b1d2e2f876c69f5011831dae618a`。原 DRAIN 用窄范围 Move 保存在 deployment/DRAIN.navigation-calibration-completed，没有删除统计或收据。
- root 于 20:16 通过新 WPF 真实“开始运行”按钮启动（观察到索引 39 Begin）；[wpf-started.png](D:/codex/CodexWork/clash/work/navigation-learning-20261004/deployment/wpf-started.png) 保存界面及原生对战。新 WPF PID 18348、bridge 32720、watchdog 30636、runner 29224，session 20261004-201600。运行事件中的 max_battles=0 表示无限，新策略为 random-mastery-v25-learned-navigation-20261004。
- [无限运行验收](D:/codex/CodexWork/clash/outputs/navigation-verification-20261004/infinite-runtime-verification.json) 在 **20:22:37** 得到 passed=true、**15 项 gates 全部 true**。基线 completed=closed_loops=1198；新 session 在第 1199、1200 局均出现有序 battle_started → battle_finished → result_committed → returned_lobby → mastery_checked → cycle_complete，累计与闭环均增长至 **1200（+2）**。第 1199 局结算事件 20:18:23，确认出牌 13/15，闭环 20:18:38；第 1200 局结算 20:21:38，确认出牌 22/22，闭环 20:21:52；第 **1201 局于 20:22:06 开始**，验收时仍 battle。pending_mastery / pending_claim_all=false，pending_battle=true 与第三局正在对战一致。
- 运行验收同时证明新 runner / watchdog 使用新 backend、运行 manifest 与冻结源码和资产相等、经典模式已确认、DRAIN 已归档、没有 pause 事件、两份原异常报告 added / removed / changed 均为空。资产身份重算为 `d7fabac272b00cf34f626bf3df438dc911cc9c6988fe65e1bd5fe6a0a6fd254a`。[20:24 最终界面](D:/codex/CodexWork/clash/outputs/INFINITE_1V1_VERIFIED_20261004.png) 另保存运行中与累计 1200 的画面；机器人持续运行，不为文档收尾停止它。
- 下一次真正出现每日福袋后，才能声称现场选择与后续免费奖励处理已经发生；**明早的新事件尚未现场测试**。当前只证明完整匹配三选一时选择“我想变好看”的规则与授权已实现，本轮已领取页面不能倒推今日选择。

## 持久记忆与回退

用户每日外观选择偏好已经保存在本任务新建的 ad_hoc 笔记，旧笔记和 MEMORY.md 未改。root 另行保存了最终验收小笔记；本文件编辑阶段没有修改记忆笔记，也不把未来事件或未开放入口写成已完成。

回退使用 root 本次部署留下的旧 backend、wpf-runtime.json 备份和源文件备份：先正常停止新 runner / 退出软件，再恢复此次切换前的 backend_path，启动同一 WPF 前端。保存所有战绩、奖励账本、异常报告与模拟器状态，不能重置或使用历史 Tk GUI 路径推断当前包。

本次文档阶段只更新上述 Markdown 与 JSON；实机探索已经结束并交回 root。本轮页面探索没有启动机器人、改变战绩 / 收据 / checkpoint 或提交资源、奖励、账户与社交操作。机器人由 root 的真实 WPF 开始操作恢复；20:22:37 快照已证明两局闭环及第三局活跃，最终状态为 completed_verified。今后出现新赛季、未知表层或未开放页仍须现场识别，不能由本次范围推断已覆盖。

