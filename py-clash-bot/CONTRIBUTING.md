# 开发与提交约定

本地开发遵守项目和各层 `AGENTS.md`。Windows 的工作、缓存、依赖和输出放在 `D:\codex`；已有运行器解释器与环境保留，新增验证环境单独创建。当前维护目标和入口差异见 [README](README.md)。

## 可复现环境

Python 固定在 3.12 系列，当前验证解释器为 3.12.14。运行依赖精确对齐已验证的 Windows 环境，开发工具为 Ruff 0.16.10、ty 0.0.49、pre-commit 4.2.0、pytest 9.1.1；uv.lock 同时固定间接依赖和 wheel 哈希。CI 使用 uv 0.12.19。

```powershell
Set-Location -LiteralPath D:\codex\CodexWork\clash\py-clash-bot
. D:\codex\bin\Initialize-CodexEnvironment.ps1
$env:UV_PROJECT_ENVIRONMENT = 'D:\codex\CodexWork\clash\work\verification-env'
uv sync --locked --group build --python 3.12
uv lock --check
```

这个示例创建独立环境，不修改 `work\venv`。每个新的 shell 都需重新初始化环境并设置 `UV_PROJECT_ENVIRONMENT`；变量只在当前进程内生效。Makefile 同样接受该变量。依赖升级先修改声明、生成新锁、在独立环境验证，再记录版本与结果；不要用宽泛 `pip install -U` 升级正在运行的机器人。

## 检查与测试

```powershell
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync ty check
uv run --locked --no-sync pytest -q -p no:cacheprovider --basetemp=D:\codex\CodexWork\clash\work\pytest-validation
```

或使用 `make dev-validation`。修改 Python 后另用同一解释器运行 `python -m py_compile <修改文件>`。为已复现的行为边界添加离线回归，测试必须证明失败条件被处理；模拟器测试使用 `@pytest.mark.emulator`，默认离线集合不会启动模拟器。

`make test-emulator EMULATOR=memu` 或 `uv run pytest --integration` 会调用实例的 `restart()` 并发送游戏输入。运行它们前确认实际目标和当前任务的实机范围。旧通用 VM 与国服当前 VM 是不同后端合同，不能从一次适配器 mock 通过推导实机兼容或策略胜率。

Windows CI 运行默认离线测试，Linux CI 执行共享静态检查。Windows GUI/进程 API mocks 尚未全部移植到 POSIX，不能把 Linux 静态通过写成 Linux 全套行为验收。构建/发布 jobs 等待复用的验证 workflow，锁文件漂移或检查失败会阻止打包。

## Pre-commit 和代码范围

```powershell
uv run --locked --no-sync pre-commit install
uv run --locked --no-sync pre-commit run --all-files
```

或 `make install-hooks`、`make lint`。Ruff/ty hooks 使用 `language: system` 和已锁定的项目工具，避免 hook 单独安装另一版本；pre-commit 的远程基础 hooks 仍使用固定 revision。`lint` 可以改格式；`lint-check` 是只读。若仓库设置了 `core.hooksPath`，先检查其用途，不要自动清除用户已有配置。提交前需完成 lint，禁止通过 `--no-verify` 绕开检查。

保留已有未提交工作和日志。新增坐标放入 `bot/coords.py`，识别函数保持各层依赖边界，生命周期操作只面向证明归属的实例/进程。记录下牌尝试与已确认部署的区别；错误、未知、证据缺失和未发布结果应保持可见。新增处理不得把保存失败或未验证状态写为成功。

## 构建与提交

Windows 国服安装器入口为 `scripts/cn_windows_entry.py`，安装包包含 `scripts` Python 包、OCR PowerShell 与检测 PNG/JSON。macOS DMG 保留旧 `pyclashbot/__main__.py` GUI。以下构建命令不安装应用、不启动游戏、不发布产物：

```powershell
uv run --locked --group build python scripts/setup_msi.py bdist_msi --target-version v0.0.0-local
```

macOS 上使用 `uv run --locked --group build python scripts/setup_macos.py --target-version v0.0.0-local`。在干净目录执行 Windows exe 的 `--self-check --self-check-output <路径>`，检查资源及环境，再单独进行已授权的实机验收。不要把源码可运行视为冻结包已经可运行。

提交仅暂存本任务路径，使用 Conventional Commits。PR 说明包含实际行为变化、验证结果和限制。版本评估需要规则、源码、素材、运行环境身份一致；混合历史统计与不同对手样本不能直接作为因果提升证明。

## 授权与许可

贡献者应拥有所提交内容的权利。源码贡献沿用 [NC-CL-1.0](LICENSE)，素材及文档沿用 CC BY-NC-SA 4.0，不纳入未获许可的第三方内容。Clash Royale 游戏素材归 Supercell 所有；商业使用限制见项目许可。原始内容、冻结资产和用户数据不应随开发重置或删除。
