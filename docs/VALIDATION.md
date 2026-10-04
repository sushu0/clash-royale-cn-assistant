# 首次公开版本验证记录

日期：2026-10-05。验证对象为本仓库公开源码副本，原项目的运行环境和数据未被覆盖。

## Python 核心

使用 Python 3.12.14 和 `uv.lock` 的独立验证环境。以下检查通过：

- `uv sync --locked --group build`、`uv lock --check`。
- Ruff 静态检查、格式检查和修改文件的 `python -m py_compile`。
- 根目录 `pre-commit run --all-files`：AST、末尾空白、文件结尾、Ruff 和 ty 全部通过。
- `ty check`：0 errors，保留 109 个已有 warnings。
- Unicode 路径回归加入前的全套离线 pytest：**1670 passed、1 skipped、15 deselected、172 subtests passed**，226.22 秒。
- 新增 12 项 Unicode 图片 I/O 回归全部通过，覆盖两份源码、BGR 像素、彩色/灰度/原样读取、中文证据写入、失败语义与重复初始化。

默认测试排除需要真实模拟器的 `emulator` 标记。首次克隆时两个测试模块依赖预先存在的 `work` 目录，公开副本已改用进程临时目录，保留全部业务断言。另有 8 个类型错误通过局部类型约束和受控测试桩修复，没有扩大全局忽略规则。

## 桌面与便携后端

- 原 WPF 开发版：.NET 10 `dotnet build` 成功，0 warnings、0 errors。
- 分享版：从 `desktop-portable` 和 `portable-backend` 公开源码生成自包含 win-x64 桌面及 cx_Freeze 后端。
- 冻结后端 `--self-check`：退出码 0，6 个手牌样本，威胁模板状态 healthy，依赖版本匹配验证锁。
- 冻结后端 `--read-only`：JSONL `snapshot` 与 `shutdown` 响应成功；状态 stopped，frozen=true。
- 桌面 `--settings-check`：退出码 0；后端存在、安装目录所有权有效、拒绝越界输出；首次配置不存在，符合新安装状态。
- 分发目录 `data` 为空；未打包 ADB、MEmu 或作者运行数据。
- 分发包包含上游署名、原许可证，以及 19 个第三方组件的 44 份原始法律文本；全部 SHA-256 校验通过。
- 便携 ZIP 全部文件 CRC 检查通过。

发布前复查发现 OpenCV 在中文安装路径中无法正常读取图片。公开源码加入局部兼容处理，并完整重新构建分享版；ASCII 与“朋友电脑 中文安装目录”两套完整复制安装的冻结资源自检、只读接口与桌面设置检查均通过，主识别模板保持原始像素。

最终安装器完成 12 项隔离检查，包括原有 8 项内嵌 ZIP 自检、全新目录解压、空运行数据及非法路径保护，以及中文和空格安装路径解压、桌面设置检查、冻结资源自检、只读 snapshot/shutdown。调用者环境变量精确恢复；原始分发 data 继续为空。最终下载文件的校验值随发行包提供。

GitHub Actions 在公开仓库的独立 Windows runner 上通过 Python 锁文件、格式、类型和全套离线测试，以及两种 WPF 源码构建。中文路径修复对应检查记录：[Source validation](https://github.com/sushu0/clash-royale-cn-assistant/actions/runs/37225687784)。

构建、资源自检和接口检查均为离线验证。本次发布没有连接游戏、启停模拟器或发送对战输入；上述结果不代表胜率、其他客户端或任意模拟器组合的实机兼容性验收。

## 复现

环境、构建命令和离线检查命令见 [BUILD.md](BUILD.md)。安装器源码及其独立验收脚本见 [installer](../installer/README.md)。使用者应自行安装 MEmu、ADB 和腾讯国服游戏，并在首次设置中选择自己的环境。
