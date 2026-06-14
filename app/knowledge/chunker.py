"""Parse tài liệu (PDF/DOCX/TXT/MD) → text → chunk cho RAG.

Tái dùng pypdf/python-docx (đã là dependency). Tách riêng khỏi app/api/upload.py để
cả upload-chat lẫn ingest-knowledge dùng chung logic parse.
"""

from io import BytesIO


class UnsupportedDocument(ValueError):
    """Định dạng không hỗ trợ hoặc không trích được text (vd PDF scan)."""


def extract_text(filename: str, raw: bytes) -> str:
    """Trích text thuần từ file. Raise UnsupportedDocument nếu không đọc được."""
    name = (filename or "").lower()
    if name.endswith((".txt", ".md")):
        return raw.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        return _extract_pdf(raw)
    if name.endswith(".docx"):
        return _extract_docx(raw)
    raise UnsupportedDocument(f"Định dạng không hỗ trợ cho knowledge: {filename}")


def _extract_pdf(raw: bytes) -> str:
    from pypdf import PdfReader
    try:
        reader = PdfReader(BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as e:  # noqa: BLE001
        raise UnsupportedDocument(f"Không đọc được PDF: {e}") from e
    text = "\n\n".join(p for p in pages if p.strip())
    if not text.strip():
        raise UnsupportedDocument("PDF không có text layer (ảnh scan) — cần OCR, ngoài phạm vi.")
    return text


def _extract_docx(raw: bytes) -> str:
    import docx
    try:
        doc = docx.Document(BytesIO(raw))
    except Exception as e:  # noqa: BLE001
        raise UnsupportedDocument(f"Không đọc được DOCX: {e}") from e
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if not text.strip():
        raise UnsupportedDocument("DOCX rỗng — không có nội dung.")
    return text


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    """Chia text thành các chunk ~size ký tự, ưu tiên ranh giới đoạn, overlap để giữ ngữ cảnh.

    Gộp theo đoạn (\\n\\n) cho tới khi đạt ~size; đoạn quá dài thì cắt cứng theo size.
    overlap: ký tự cuối chunk trước được nối vào đầu chunk sau (giữ liên tục ngữ nghĩa).
    """
    if not text or not text.strip():
        return []
    size = max(200, size)
    overlap = max(0, min(overlap, size // 2))

    # Tách theo đoạn; đoạn dài hơn size → cắt cứng thành nhiều mảnh.
    paragraphs: list[str] = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            paragraphs.append(para)
        else:
            for i in range(0, len(para), size):
                paragraphs.append(para[i:i + size])

    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) + 2 > size:
            chunks.append(buf)
            # nối overlap từ cuối chunk vừa chốt để giữ ngữ cảnh
            buf = (buf[-overlap:] + "\n\n" + para) if overlap else para
        else:
            buf = (buf + "\n\n" + para) if buf else para
    if buf.strip():
        chunks.append(buf)
    return chunks
