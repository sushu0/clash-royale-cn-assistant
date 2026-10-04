# Portable backend source

This directory contains the Python source corresponding to the portable WPF
desktop edition in `../desktop-portable`. It includes the runtime dispatcher,
JSONL backend, detector reference images, icons, and the existing locked Python
dependencies. It does not contain an account, battle history, local runtime
configuration, MEmu installation, or Android platform-tools binaries.

The source version is `v0.0.0`, a development placeholder. The file
`pyclashbot/__version__` is checked in because the frozen backend needs it at
runtime. Dependency versions in `uv.lock` are retained from the tested source.

On Windows x64, install Python 3.12, uv, and the .NET 10 SDK, then run from the
repository root:

```powershell
uv run --project portable-backend --locked --group build python tools/build_portable.py --check
uv run --project portable-backend --locked --group build python tools/build_portable.py
```

The build uses these sources directly with cx_Freeze; no earlier private frozen
package is needed. The result is `dist/portable/app/ClashAssistant.Desktop.exe`,
`dist/portable/backend/ClashBackend.exe`, and an initially empty
`dist/portable/data` directory. The desktop is published as a self-contained
.NET application. First-run setup asks for the user's existing `memuc.exe` and
`adb.exe` paths and stores configuration under that installation's `data/work`.
Choose a new `--output` directory to build another package; the build command
does not replace an existing application or copy runtime data.

For advanced backend-only development, the freezer entry is
`scripts/build_wpf_backend.py build_exe`. It honors
`PYCLASHBOT_WPF_BACKEND_OUTPUT` and `PYCLASHBOT_WPF_BACKEND_WORK`.

See the root README and LICENSE for project usage, attribution, and the
noncommercial licensing terms.
