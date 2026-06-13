"""Test upload helpers — không cần full FastAPI app, chỉ test helper functions."""

import base64
import struct

import pytest

from app.api.upload import _detect_image_type


# --- magic bytes helpers ---

def _make_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 10


def _make_jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 10


def _make_fake_png_with_jpg_ext() -> bytes:
    """File có content PNG nhưng được đặt tên .jpg."""
    return _make_png()


class TestDetectImageType:
    def test_detect_png(self):
        assert _detect_image_type(_make_png()) == "image/png"

    def test_detect_jpeg(self):
        assert _detect_image_type(_make_jpeg()) == "image/jpeg"

    def test_unknown_returns_none(self):
        assert _detect_image_type(b"\x00\x01\x02\x03") is None

    def test_png_content_detected_regardless_of_name(self):
        # I-07: content PNG phải detect đúng dù extension là .jpg
        result = _detect_image_type(_make_fake_png_with_jpg_ext())
        assert result == "image/png"

    def test_empty_bytes(self):
        assert _detect_image_type(b"") is None

    def test_short_bytes(self):
        assert _detect_image_type(b"\x89") is None
