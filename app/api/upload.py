"""POST /upload — trích nội dung file để inject vào chat (text/image)."""

import base64
import logging
from io import BytesIO

from fastapi import APIRouter, HTTPException, UploadFile

log = logging.getLogger(__name__)
router = APIRouter(tags=["upload"])

MAX_BYTES = 5 * 1024 * 1024  # 5 MB

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8"


def _detect_image_type(raw: bytes) -> str | None:
    if raw[:8] == _PNG_MAGIC:
        return "image/png"
    if raw[:2] == _JPEG_MAGIC:
        return "image/jpeg"
    return None


@router.post("/upload")
async def upload_file(file: UploadFile):
    raw = await file.read()
    if not raw:
        raise HTTPException(422, "File rỗng — không có nội dung để xử lý")
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "File quá lớn (tối đa 5 MB)")

    name = (file.filename or "").lower()
    ct = (file.content_type or "").split(";")[0].strip()

    if name.endswith((".txt", ".md")) or ct in ("text/plain", "text/markdown"):
        return {"filename": file.filename, "content_type": "text",
                "text": raw.decode("utf-8", errors="replace")}

    if name.endswith(".pdf") or ct == "application/pdf":
        return {"filename": file.filename, "content_type": "text", "text": _extract_pdf(raw)}

    if name.endswith(".docx") or ct == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return {"filename": file.filename, "content_type": "text", "text": _extract_docx(raw)}

    if name.endswith((".png", ".jpg", ".jpeg")) or ct in ("image/png", "image/jpeg"):
        # I-07: detect thật bằng magic bytes thay vì tin extension/content-type client gửi
        media_type = _detect_image_type(raw) or ("image/png" if name.endswith(".png") else "image/jpeg")
        return {"filename": file.filename, "content_type": "image",
                "base64": base64.b64encode(raw).decode(), "media_type": media_type}

    raise HTTPException(415, f"Định dạng không hỗ trợ: {file.filename}")


def _extract_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(p for p in pages if p.strip())
        if not text:
            raise HTTPException(422, "PDF không có text layer (ảnh scan — thử upload ảnh trực tiếp)")
        return text
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"Không đọc được PDF: {e}") from e


def _extract_docx(raw: bytes) -> str:
    try:
        import docx
        doc = docx.Document(BytesIO(raw))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        raise HTTPException(422, f"Không đọc được DOCX: {e}") from e
