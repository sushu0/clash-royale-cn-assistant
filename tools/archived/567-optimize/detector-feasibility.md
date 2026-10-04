# 战场单位检测器可行性核对

核对日期：2026-09-28。只读联网研究；未安装依赖、下载权重、上传本地截图或操作游戏。本轮继续现有截图识别链路，不引入双 YOLO 框架。

结论：没有找到同时满足“轻量 CPU、公开预训练权重、许可证明确、覆盖 Giant / PEKKA / Baby Dragon、国服可直接用”的成熟方案。最可信的后续离线评估候选是 KataCR，但不适合直接替换当前实战识别器。

## 候选 1：KataCR（仅保留为后续离线研究候选）

- 官方仓库：https://github.com/wty-yy/KataCR
- 项目根许可证是 MIT；内部 YOLO 配置包含 Ultralytics AGPL-3.0 标记。没有核实出独立权重许可证声明，不能仅凭根 MIT 宣称所有依赖和权重均无额外许可条件。
- 官方 README 确实提供两份预训练权重链接，版本 v0.7.13，日期 2024-05-01：
  - detector1：https://drive.google.com/file/d/1DMD-EYXa1qn8lN4JjPQ7UIuOMwaqS5w_/view?usp=drive_link
  - detector2：https://drive.google.com/file/d/1yEq-6liLhs_pUfipJM1E-tMj6l4FSbxD/view?usp=drive_link
- 本次只核实了官方链接及页面文件名，没有下载，因此未确认匿名下载完整性、文件大小、哈希及实际可加载性。
- 官方模型配置为 2 个 YOLOv8l，imgsz=896；定制 YOLO_CR 增加阵营输出，不是标准 YOLO 权重直接加载即可保证运行。
- 类别表包含 giant、pekka、baby-dragon、mega-minion、bomber、goblin-giant、x-bow、mortar 及部分进化单位；未包含 goblin-machine / goblinstein。不能把缺失的新卡映射为近似旧卡，也不能因已有进化标签就假定覆盖全部当前进化版本。
- 完整工程依赖 PyTorch、JAX CUDA、Paddle GPU / OCR 等；原作者验证环境是 Ubuntu + NVIDIA GPU，未发布 CPU 推理延迟结果。单独提取检测部分理论上可减少依赖，但需要适配与实测；本次没有安装，无法给出真实磁盘占用或 CPU 延迟。
- 原始画面为 1080×2400，竞技场 / 手牌裁剪按该宽高比设定，不能照搬当前模拟器坐标。2024 标签、国服画面、当前竞技场背景、效果遮挡和新卡均有域差异，需要本地标注截图的离线检测评估。
- 关键源码：
  - https://github.com/wty-yy/KataCR/blob/master/katacr/yolov8/ClashRoyale.yaml
  - https://github.com/wty-yy/KataCR/blob/master/katacr/yolov8/detector_combo/data.yaml
  - https://github.com/wty-yy/KataCR/blob/master/katacr/yolov8/combo_detect.py
  - https://github.com/wty-yy/KataCR/blob/master/requirements.txt

## 候选 2：ClashRoyaleYoloModel（不满足本轮接入条件）

- 官方仓库：https://github.com/valaskaomer/ClashRoyaleYoloModel
- README 明确为 YOLOv8n、19 类，仓库中存在 best.pt，GitHub API 文件大小为 6,265,827 字节。
- 权重页面：https://github.com/valaskaomer/ClashRoyaleYoloModel/blob/master/best.pt
- 仓库未声明许可证；README 没有列出足以核实全部所需单位的类别表，也没有 CPU 基准。本次没有下载或反序列化 .pt。因此即使权重小，也不能标为现成可用。

## 排除结果

- CR Vision：https://github.com/bytkim/cr_vision — README 明确 models 不跟踪进 git，要求用户自行放置 bestv2.pt，未给公开权重下载；不能把运行脚手架当作可运行的预训练模型。
- TITAN：https://github.com/krishbindal/TITAN — README 权重 Releases 链接为 coming soon，不能当作已发布权重。
- jawadstalker/Clash-Royale：https://github.com/jawadstalker/Clash-Royale — MIT，但只提供训练流程，未发布预训练权重；描述以卡面合成背景，不足以证明战场单位检测有效。
- Droused070807/clash-royale-ai-models：https://github.com/Droused070807/clash-royale-ai-models — API 列出的 cr_yolo.pt / elixir_classifier.pt / ocr_digits.onnx 都是 0 字节，未声明许可证。
- AngelFireLA/Clash-Royale-AI 与 vegetableleaf/ClashAI：前者存在 .pt 但没有许可证；后者当前仓库无公开 .pt / .onnx，且未声明许可证。不能只凭 README 效果描述接入。

检索路线：依照 agent-reach 的 search.md / dev.md。mcporter list exa --json 返回 Unknown MCP server 'exa'；gh 当前不在 PATH；后续使用普通网页搜索、官方 GitHub 页面 / API 和 Hugging Face 模型目录。只对官方来源作上述事实核对，搜索命中摘要未作为权重存在性证明。
