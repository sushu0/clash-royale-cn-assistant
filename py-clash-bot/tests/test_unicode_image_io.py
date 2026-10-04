"""Offline regression for Chinese installation paths in both source editions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


@pytest.fixture(params=("py-clash-bot", "portable-backend"))
def unicode_io(request, monkeypatch):
    source = Path(__file__).resolve().parents[2] / request.param / "pyclashbot" / "utils" / "runtime_config.py"
    specification = importlib.util.spec_from_file_location("unicode_runtime_under_test", source)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    monkeypatch.setitem(sys.modules, specification.name, module)
    specification.loader.exec_module(module)
    # Record originals before the helper replaces the global OpenCV methods.
    monkeypatch.setattr(cv2, "imread", cv2.imread)
    monkeypatch.setattr(cv2, "imwrite", cv2.imwrite)
    monkeypatch.setattr(cv2, "_pyclashbot_unicode_io_installed", False, raising=False)
    module.install_unicode_image_io()
    return module


@pytest.fixture
def bgr_image():
    image = np.empty((9, 11, 3), dtype=np.uint8)
    image[:, :, 0] = 19
    image[:, :, 1] = 113
    image[:, :, 2] = 227
    return image


@pytest.mark.parametrize("flags", (cv2.IMREAD_COLOR, cv2.IMREAD_GRAYSCALE, cv2.IMREAD_UNCHANGED))
def test_chinese_path_read_preserves_bgr_and_flags(unicode_io, tmp_path, bgr_image, flags):
    path = tmp_path / "中文安装目录" / "参考模板.png"
    path.parent.mkdir()
    encoded_ok, encoded = cv2.imencode(".png", bgr_image)
    assert encoded_ok
    path.write_bytes(encoded.tobytes())
    expected = cv2.imdecode(encoded, flags)
    actual = cv2.imread(str(path), flags)
    default_read = cv2.imread(str(path))
    assert expected is not None
    assert actual is not None
    assert default_read is not None
    assert np.array_equal(actual, expected)
    assert np.array_equal(default_read, bgr_image)


def test_chinese_evidence_write_roundtrip(unicode_io, tmp_path, bgr_image):
    path = tmp_path / "中文证据目录" / "战斗证据.png"
    path.parent.mkdir()
    assert cv2.imwrite(str(path), bgr_image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    actual = cv2.imread(str(path))
    assert actual is not None
    assert np.array_equal(actual, bgr_image)


def test_missing_and_invalid_images_still_fail(unicode_io, tmp_path, bgr_image):
    missing = tmp_path / "不存在的目录" / "missing.png"
    assert cv2.imread(str(missing)) is None
    assert not cv2.imwrite(str(missing), bgr_image)
    invalid = tmp_path / "不是图片.png"
    invalid.write_bytes(b"invalid png")
    assert cv2.imread(str(invalid)) is None
    with pytest.raises(cv2.error):
        cv2.imwrite(str(tmp_path / "证据.unsupported_extension"), bgr_image)


def test_ascii_paths_and_repeated_install(unicode_io, tmp_path, bgr_image):
    path = tmp_path / "ascii-reference.png"
    assert cv2.imwrite(str(path), bgr_image)
    actual = cv2.imread(str(path))
    assert actual is not None
    assert np.array_equal(actual, bgr_image)
    reader, writer = cv2.imread, cv2.imwrite
    unicode_io.install_unicode_image_io()
    assert cv2.imread is reader
    assert cv2.imwrite is writer
