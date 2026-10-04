"""Refresh the single concurrently updated script in our isolated backend.

The old package stays untouched. The complete package verifier must still pass
after this compilation; no desktop, robot or device is started here.
"""

import hashlib
import json
import py_compile
from pathlib import Path

root = Path(r"D:\codex\CodexWork\clash")
source = root / "py-clash-bot/scripts/stop_cn_1v1.py"
package = root / "outputs/wpf-desktop-loss-optimized-20261004-r2/backend"
data = source.read_bytes()
snapshot = root / "work/loss-optimization-20261004/stop_cn_1v1.package-snapshot.py"
snapshot.write_bytes(data)
(package / "scripts/stop_cn_1v1.py").write_bytes(data)
py_compile.compile(
    str(snapshot),
    cfile=str(package / "lib/scripts/stop_cn_1v1.pyc"),
    dfile=str(source),
    doraise=True,
    optimize=0,
)
if source.read_bytes() != data:
    raise RuntimeError("Source changed during isolated package refresh")
print(json.dumps({"script": str(source), "sha256": hashlib.sha256(data).hexdigest()}))
