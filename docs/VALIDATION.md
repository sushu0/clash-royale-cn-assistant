# 首次公开版本验证记录

日期：2026-10-05。验证对象为本仓库公开源码副本，原项目的运行环境和数据未被覆盖。

## Python 核心

使用 Python 3.12.14 和 `uv.lock` 的独立验证环境。以下检查通过：

- `uv sync --locked --group build`、`uv lock --check`。
- Ruff 静态检查、格式检查和修改文件的 `python -m py_compile`。
- 根目录 `pre-commit run --all-files`：AST、末尾空白、文件结尾、Ruff 和 ty 全部通过。
- `ty check`：0 errors，保留 109 个已有 warnings。
- 默认离线 pytest：**1670 passed、1 skipped、15 deselected、172 subtests passed**，226.22 秒。

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

构建、资源自检和接口检查均为离线验证。本次发布没有连接游戏、启停模拟器或发送对战输入；上述结果不代表胜率、其他客户端或任意模拟器组合的实机兼容性验收。

## 复现

环境、构建命令和离线检查命令见 [BUILD.md](BUILD.md)。安装器源码及其独立验收脚本见 [installer](../installer/README.md)。使用者应自行安装 MEmu、ADB 和腾讯国服游戏，并在首次设置中选择自己的环境。

