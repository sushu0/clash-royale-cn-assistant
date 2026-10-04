"""Read Chinese game labels using the installed local Windows OCR recognizer."""

import json
import subprocess
from pathlib import Path

import cv2

from pyclashbot.utils.runtime_config import resource_path


def read_local_ocr(frame, destination: Path, scale=3, language=None):
    image = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if not cv2.imwrite(str(destination), image):
        raise RuntimeError("Could not persist local OCR input")
    script = resource_path("scripts/ocr_cn_footer.ps1")
    command = ["powershell.exe", "-NoProfile", "-File", str(script), "-ImagePath", str(destination)]
    if language:
        command.extend(["-RequestedLanguage", language])
    result = subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        timeout=20,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError("Local Chinese OCR failed: " + result.stderr[-400:])
    data = json.loads(result.stdout.strip().lstrip("\ufeff"))
    for line in data.get("lines", []):
        for field in ("x", "y", "width", "height"):
            line[field] /= scale
    return data
