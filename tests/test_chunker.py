"""Test chunker.extract_text — đảm bảo kho tri thức agent đọc được CSV/Excel."""

from io import BytesIO

import pytest

from app.knowledge.chunker import UnsupportedDocument, extract_text


class TestExtractTextCsv:
    def test_csv_normalized(self):
        out = extract_text("fees.csv", b"a,b\n1,2\n")
        assert out == "a | b\n1 | 2"

    def test_csv_utf8_bom_vietnamese(self):
        raw = "Đối tác,Phí\nEVN,1500\n".encode("utf-8-sig")
        out = extract_text("p.csv", raw)
        assert "Đối tác | Phí" in out and "EVN | 1500" in out

    def test_csv_empty_raises(self):
        with pytest.raises(UnsupportedDocument):
            extract_text("e.csv", b"\n  \n")


class TestExtractTextExcel:
    @staticmethod
    def _xlsx(rows, title="Sheet1") -> bytes:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = title
        for r in rows:
            ws.append(r)
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_xlsx_basic(self):
        out = extract_text("p.xlsx", self._xlsx([["a", "b"], [1, 2]], title="Phí"))
        assert "# Sheet: Phí" in out and "a | b" in out and "1 | 2" in out

    def test_xlsx_skips_blank_rows(self):
        out = extract_text("p.xlsx", self._xlsx([["a", "b"], [None, None], [1, 2]]))
        assert out.count("\n") == 2  # header sheet + 2 data rows

    def test_xlsx_corrupt_raises(self):
        with pytest.raises(UnsupportedDocument):
            extract_text("bad.xlsx", b"not-an-xlsx")


def test_unsupported_extension_still_rejected():
    with pytest.raises(UnsupportedDocument):
        extract_text("x.bin", b"random")
