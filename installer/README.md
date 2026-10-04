# Windows 安装器工程

安装器使用 .NET 10 Windows Forms。发布产物是 Windows x64 自包含单文件 `ClashAssistant-Setup.exe`，运行安装器无需 Python 或 .NET，也不请求管理员权限。工程把便携 ZIP 及其 SHA-256 内嵌为资源，解压之前先校验完整性。

在 Windows 上安装 .NET 10 SDK，并确认普通 PowerShell 可以执行 `dotnet --version`。按仓库根 README 构建便携版，将 ZIP 放到 `dist/ClashAssistant-Windows-x64-portable.zip`，然后从仓库根目录运行：

```powershell
& .\installer\Build-Installer.ps1
```

默认安装器输出到 `dist/installer/`，中间编译文件与临时目录位于 `.build/installer/`。已有 `NUGET_PACKAGES` 和 `DOTNET_CLI_HOME` 设置会保留；未设置时使用该构建目录下的缓存。脚本运行后恢复调用者的环境变量。输出目录必须全新或为空，避免覆盖已保存的发行文件。

可使用自己的 ZIP 和输出目录；相对路径按调用时的工作目录解析：

```powershell
& .\installer\Build-Installer.ps1 `
    -PayloadZip .\dist\ClashAssistant-Windows-x64-portable.zip `
    -OutputDirectory .\dist\installer-custom
```

ZIP 内应直接包含 `app/`、`backend/` 和空的 `data/`，不应额外包裹一层目录。模拟器由使用者另行安装，公开便携包不包含原厂模拟器安装程序或个人运行数据。

构建脚本输出安装器路径、便携 ZIP 路径及两者的 SHA-256。安装器另提供无 UI 的自检接口，标准输出/错误为 JSON，成功返回 0，失败返回 1：

```powershell
& .\dist\installer\ClashAssistant-Setup.exe --self-check
```

开发用 `--extract-only` 保留原项目的隔离边界：只接受 `D:\codex` 内的全新或空目录，不创建快捷方式、不启动应用或模拟器。普通图形安装界面允许选择自己的本机磁盘位置。下面的自动验收覆盖自检、新目录和空目录解压、运行配置、空数据目录、拒绝非空目录、拒绝外部路径、相对路径及重解析路径，并检查已有文件未改变：

```powershell
& .\installer\Validate-Installer.ps1 `
    -Installer .\dist\installer\ClashAssistant-Setup.exe `
    -TestRoot D:\codex\workspaces\installer-validation-new
```

验收目录必须尚不存在。验收产生的 JSON 和解压文件保存在该目录中。

安装器拒绝 ZIP 越界、特殊链接、路径冲突和重复路径，先在本次创建的临时目录解压并生成配置，再提交到目标。取消或错误时只清理本次创建的文件。安装后的 `app/wpf-runtime.json` 使用相对目录：

```json
{
  "distribution": true,
  "data_root": "../data",
  "backend_path": "../backend/ClashBackend.exe"
}
```

首次安装的 `data/` 为空。普通快捷方式启动应用，开始菜单的“首次配置”快捷方式添加 `--setup` 参数。应用自动启动默认未选中。

安装程序未做发行者数字签名；SHA-256 用于下载与传输校验，不代表数字签名。原始机器维护工具与历史路径说明保存在 `tools/archived/` 和 `docs/archive/`。