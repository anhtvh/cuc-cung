"""Test upload helpers — không cần full FastAPI app, chỉ test helper functions."""

from io import BytesIO

import pytest

from app.api.upload import _detect_image_type, _extract_csv, _extract_excel


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


class TestExtractCsv:
    def test_basic_csv_normalized(self):
        raw = "a,b,c\n1,2,3\n".encode("utf-8")
        out = _extract_csv(raw)
        assert out == "a | b | c\n1 | 2 | 3"

    def test_utf8_bom_and_vietnamese(self):
        # Excel export hay kèm BOM → utf-8-sig phải nuốt được, giữ tiếng Việt.
        raw = "Đối tác,Phí\nEVN SPC,1500\n".encode("utf-8-sig")
        out = _extract_csv(raw)
        assert "Đối tác | Phí" in out
        assert "EVN SPC | 1500" in out

    def test_skips_blank_rows(self):
        raw = "a,b\n\n1,2\n".encode("utf-8")
        out = _extract_csv(raw)
        assert out == "a | b\n1 | 2"

    def test_empty_csv_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            _extract_csv(b"\n  \n")
        assert ei.value.status_code == 422


class TestExtractExcel:
    @staticmethod
    def _make_xlsx(rows, title="Sheet1") -> bytes:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = title
        for r in rows:
            ws.append(r)
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_basic_excel(self):
        raw = self._make_xlsx([["a", "b"], [1, 2]], title="Phí")
        out = _extract_excel(raw)
        assert "# Sheet: Phí" in out
        assert "a | b" in out
        assert "1 | 2" in out

    def test_skips_blank_rows(self):
        raw = self._make_xlsx([["a", "b"], [None, None], [1, 2]])
        out = _extract_excel(raw)
        assert out.count("\n") == 2  # header sheet + 2 data rows, không có dòng rỗng

    def test_corrupt_excel_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            _extract_excel(b"not-an-xlsx")
        assert ei.value.status_code == 422
