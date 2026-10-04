# 运行环境、验证与回退

2026-10-04 的修复将当前 Windows 运行依赖写入 `pyproject.toml` 与 `uv.lock`，验证环境与正在运行的环境分开。原 `D:\codex\CodexWork\clash\work\venv` 保留；此次隔离环境为 `D:\codex\CodexWork\clash\work\repair-20261003\verification-env`。直接依赖版本见下表，间接依赖与平台构建依赖见锁文件。

| 组件 | 固定版本 |
| --- | --- |
| Python | 3.12 系列，当前验证 3.12.14 |
| OpenCV / NumPy | 4.14.0.94 / 2.5.3 |
| Pillow / ttkbootstrap | 12.3.0 / 1.20.4 |
| PyMemuc / psutil / pypresence | 0.6.0 / 7.2.2 / 4.6.2 |
| pytest / Ruff | 9.1.1 / 0.16.10 |
| ty / pre-commit | 0.0.49 / 4.2.0 |
| uv | CI 和本次验证 0.12.19 |

## 同步与检查

```powershell
Set-Location -LiteralPath D:\codex\CodexWork\clash\py-clash-bot
. D:\codex\bin\Initialize-CodexEnvironment.ps1
$env:UV_PROJECT_ENVIRONMENT = 'D:\codex\CodexWork\clash\work\repair-20261003\verification-env'
uv lock --check
uv sync --locked --group build --python 3.12
uv run --locked --no-sync python -m scripts.cn_windows_entry --self-check
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync ty check
uv run --locked --no-sync pytest -q -p no:cacheprovider --basetemp=D:\codex\CodexWork\clash\work\repair-20261003\pytest-final
```

`--locked` 拒绝自动改锁，`--no-sync` 确保检查阶段不悄悄同步另一个环境。默认 pytest 排除实机项目。CI 的 Windows 数据/环境/缓存/临时目录放在 `D:\codex\ci`；Linux 共享静态门控使用仓库下的 `.venv`、`.ci-data`、`.ci-cache` 和 `.ci-tmp`。两个平台分别解释路径，不在 POSIX 上依赖 Windows ADB/MEmu 路径。

## 路径及产物合同

源码资源从仓库读取，冻结包从可执行文件旁读取；源码身份镜像位于冻结包的 `source` 目录。普通日志和用户状态只写数据根的 `work` 与 `outputs`。环境变量优先级及 JSON 配置字段见 [README](../README.md#运行配置)。开发环境与子进程的解释器可不同，应显式在独立运行配置的 `python` 字段指定新环境，验证新入口后再切换实际运行器。

结算事件使用稳定结果身份及可重放的待发布结果文件，checkpoint 通过原子替换提交。JSONL 是源记录，SQLite 可重建。关键截图按内容哈希保留，旧截图被覆盖时显示证据缺失；哈希不能重建已经丢失的像素。策略比较按规则、源码、素材、环境身份分组，证据不足的旧批次保持未知。

Windows 安装器构建目标为国服控制台，macOS DMG 仍为旧通用 GUI。构建包的 `--self-check` 只验包内资源和环境，不连接 ADB、不启动 VM。还需分别记录界面可运行、目标设备可达、一次完整游戏闭环、停止/恢复行为；上述结果不代表策略胜率提升或全球服实机兼容。

## 回退

本次修改前源码备份在 `D:\codex\CodexWork\clash\work\repair-20261003\source-before.zip`；最终修复报告会列出实际修改路径和验证结果。回退时先结束该运行器或等待当前对局闭环，再按清单恢复所需源码与相应的 `pyproject.toml` / `uv.lock`，通过同一版本解释器重新验证。新环境可以保留用于复核，不对运行中的 `work\venv` 执行逆向升级或删除。

不要用仓库级 `git reset --hard` 回退混合工作树，不删除原始日志、断点、领奖收据或 VM 磁盘。恢复旧源码并不会自动撤销已经确认的游戏奖励；新的统计索引可以从保留原始事件重建。历史被覆盖的图片、已经发生的对局和第三方服务状态无法靠源码回退恢复。
