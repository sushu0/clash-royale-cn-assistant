"""Build the portable Windows desktop and backend from public sources."""

# Standalone command-line entry; tools is not an importable package.
# ruff: noqa: INP001

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
BACKEND = REPOSITORY / "portable-backend"
DESKTOP = REPOSITORY / "desktop-portable" / "ClashAssistant.Desktop.csproj"


def require_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"Required source or resource is missing: {path}")


def check_sources(dotnet: str) -> str:
    """Check prerequisites without starting a desktop, emulator, or backend."""
    if sys.platform != "win32":
        raise RuntimeError("Portable WPF builds require Windows x64.")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use Python 3.12, as required by portable-backend/pyproject.toml.")
    if sys.maxsize <= 2**32:
        raise RuntimeError("Use a 64-bit Python interpreter for the win-x64 package.")
    if importlib.util.find_spec("cx_Freeze") is None:
        raise RuntimeError("cx_Freeze is missing. Run with uv --locked --group build.")
    executable = shutil.which(dotnet)
    if executable is None:
        raise RuntimeError("The .NET SDK is missing; install .NET 10 or use --dotnet PATH.")
    version = subprocess.run(
        [executable, "--version"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    if not version.startswith("10."):
        raise RuntimeError(f"The desktop targets .NET 10; the selected SDK reports {version}.")
    for path in (
        BACKEND / "scripts" / "build_wpf_backend.py",
        BACKEND / "scripts" / "cn_wpf_backend.py",
        BACKEND / "pyclashbot" / "__version__",
        BACKEND / "assets" / "clash-desktop.ico",
        BACKEND / "README.md",
        BACKEND / "uv.lock",
        DESKTOP,
        DESKTOP.parent / "wpf-runtime.json",
        REPOSITORY / "LICENSE",
        REPOSITORY / "NOTICE",
        REPOSITORY / "THIRD_PARTY_NOTICES.md",
    ):
        require_file(path)
    references = BACKEND / "pyclashbot" / "detection" / "reference_images"
    if not any(references.rglob("*.png")):
        raise RuntimeError("Detector reference images are missing.")
    config = json.loads((DESKTOP.parent / "wpf-runtime.json").read_text(encoding="utf-8"))
    expected = {"data_root": "../data", "backend_path": "../backend/ClashBackend.exe", "distribution": True}
    if config != expected:
        raise RuntimeError("desktop-portable/wpf-runtime.json must use portable sibling paths.")
    print(f"Prerequisites OK: Python {sys.version.split()[0]}, .NET SDK {version}, cx_Freeze.")
    return executable


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def collect_distribution_notices(output: Path, dotnet: str) -> None:
    """Copy unmodified license files for the actual frozen distributions."""
    for filename in ("README.md", "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        source = REPOSITORY / filename
        require_file(source)
        shutil.copy2(source, output / filename)

    library = output / "backend" / "lib" / "library.zip"
    require_file(library)
    # cx_Freeze and freeze-core provide the launcher/bootstrap. Other package
    # selections come from frozen METADATA, including vendored distributions.
    selected = dict.fromkeys((
        "cx-freeze", "freeze-core", "opencv-python", "numpy", "pymemuc",
        "psutil", "pypresence", "pillow", "ttkbootstrap",
    ))
    parser = Parser()
    with zipfile.ZipFile(library) as archive:
        for filename in archive.namelist():
            if filename.endswith(".dist-info/METADATA"):
                metadata = parser.parsestr(archive.read(filename).decode("utf-8"))
                name = normalized_name(metadata["Name"])
                if name != "pyclashbot":
                    selected[name] = metadata["Version"]
    for path in (output / "backend" / "lib").glob("*.dist-info/METADATA"):
        metadata = parser.parsestr(path.read_text(encoding="utf-8"))
        name = normalized_name(metadata["Name"])
        if name != "pyclashbot":
            selected[name] = metadata["Version"]

    distributions = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            distributions[normalized_name(name)] = distribution
    # cx_Freeze may include importlib_metadata/zipp from setuptools' bundled
    # copies even though setuptools itself is excluded from the frozen output.
    setuptools = distributions.get("setuptools")
    if setuptools is not None:
        vendor = setuptools.locate_file("setuptools/_vendor")
        for distribution in importlib.metadata.distributions(path=[str(vendor)]):
            name = distribution.metadata.get("Name")
            if name:
                distributions.setdefault(normalized_name(name), distribution)

    destination = output / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    records = []

    def copy_license(source: Path, relative: Path) -> dict:
        require_file(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != source_hash:
            raise RuntimeError(f"License copy verification failed: {relative}")
        return {"path": relative.as_posix(), "sha256": source_hash}

    for name, frozen_version in sorted(selected.items()):
        distribution = distributions.get(name)
        if distribution is None or frozen_version not in (None, distribution.version):
            raise RuntimeError(f"Matching installed metadata is required to collect licenses for {name} {frozen_version}.")
        files = {}
        for package_file in distribution.files or []:
            relative = Path(str(package_file))
            if relative.is_absolute() or ".." in relative.parts:
                continue
            in_license_tree = "licenses" in relative.parts and any(
                part.endswith(".dist-info") for part in relative.parts
            )
            legal_filename = relative.name.upper().startswith(("LICENSE", "NOTICE", "COPYING", "COPYRIGHT"))
            if in_license_tree or (legal_filename and relative.suffix.lower() not in {".py", ".pyc", ".xml"}):
                source = Path(distribution.locate_file(package_file))
                if source.is_file():
                    files[relative] = source
                # Copy entire dist-info/licenses trees, including bundled
                # NumPy notices that might not be named LICENSE themselves.
                if in_license_tree:
                    index = relative.parts.index("licenses")
                    license_root = Path(*relative.parts[:index + 1])
                    tree = Path(distribution.locate_file(license_root))
                    for child in tree.rglob("*"):
                        if child.is_file():
                            files[license_root / child.relative_to(tree)] = child
        if not files:
            raise RuntimeError(f"No original license texts found for frozen/build component {name} {distribution.version}.")
        copied = [copy_license(source, Path(f"{name}-{distribution.version}") / path)
                  for path, source in sorted(files.items())]
        records.append({
            "name": name, "version": distribution.version,
            "license_expression": distribution.metadata.get("License-Expression") or distribution.metadata.get("License"),
            "files": copied,
        })

    python_files = [copy_license(Path(sys.base_prefix) / "LICENSE.txt", Path("python") / "LICENSE.txt")]
    for component in ("tcl8.6", "tk8.6"):
        text = Path(sys.base_prefix) / "tcl" / component / "license.terms"
        if text.is_file():
            python_files.append(copy_license(text, Path("python") / component / "license.terms"))
    records.append({"name": "python", "version": sys.version.split()[0], "files": python_files})
    dotnet_executable = shutil.which(dotnet)
    if dotnet_executable is None:
        raise RuntimeError("The selected .NET SDK executable was not found while collecting notices.")
    sdk_root = Path(dotnet_executable).resolve().parent
    dotnet_files = [copy_license(sdk_root / name, Path("dotnet") / name)
                    for name in ("LICENSE.txt", "ThirdPartyNotices.txt")]
    records.append({"name": "dotnet", "files": dotnet_files})
    (destination / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "components": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Copied and hash-verified original license texts for {len(records)} components into {destination}.")


def build(output: Path, work: Path, dotnet: str) -> None:
    """Build into a fresh destination and preserve existing installations."""
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Output is not empty: {output}. Choose a new --output directory.")
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    temp = work / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "PYCLASHBOT_WPF_BACKEND_OUTPUT": str(output / "backend"),
        "PYCLASHBOT_WPF_BACKEND_WORK": str(work / "backend"),
        "TEMP": str(temp),
        "TMP": str(temp),
        "PYTHONPYCACHEPREFIX": str(work / "pycache"),
        "NUGET_PACKAGES": str(REPOSITORY / ".build" / "nuget-packages"),
        "DOTNET_CLI_HOME": str(REPOSITORY / ".build" / "dotnet-home"),
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
        "DOTNET_NOLOGO": "1",
    })
    subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "build_wpf_backend.py"), "build_exe"],
        cwd=BACKEND, env=environment, check=True,
    )
    subprocess.run(
        [dotnet, "publish", str(DESKTOP), "--configuration", "Release", "--runtime", "win-x64",
         "--self-contained", "true", "--output", str(output / "app"), "-p:PublishSingleFile=false"],
        cwd=REPOSITORY, env=environment, check=True,
    )
    collect_distribution_notices(output, dotnet)
    (output / "data").mkdir(exist_ok=True)
    require_file(output / "app" / "ClashAssistant.Desktop.exe")
    require_file(output / "backend" / "ClashBackend.exe")
    if any((output / "data").iterdir()):
        raise RuntimeError("A new distribution must contain no pre-existing user data.")
    forbidden = {"adb.exe", "memuc.exe", "memu.exe"}
    for path in output.rglob("*"):
        if path.is_file() and path.name.lower() in forbidden:
            raise RuntimeError(f"Third-party emulator/ADB tool must not be distributed: {path}")
    print(f"Build complete: {output}")
    print(f"Start {output / 'app' / 'ClashAssistant.Desktop.exe'} to configure your own MEmu/ADB installation.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Only verify tools, sources, and resources.")
    parser.add_argument("--output", type=Path, default=REPOSITORY / "dist" / "portable")
    parser.add_argument("--work", type=Path, default=REPOSITORY / ".build" / "portable")
    parser.add_argument("--dotnet", default="dotnet", help=".NET 10 SDK executable or command.")
    args = parser.parse_args()
    try:
        dotnet = check_sources(args.dotnet)
        if not args.check:
            build(args.output.expanduser().resolve(), args.work.expanduser().resolve(), dotnet)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
