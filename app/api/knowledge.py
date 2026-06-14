"""API tài liệu RAG cho agent (Phase 3). Toàn bộ gated bởi module: RAG tắt → 404.

- POST   /agents/{name}/docs        upload 1 tài liệu (multipart) → parse + chunk + ingest
- GET    /agents/{name}/docs        liệt kê tài liệu của agent
- DELETE /agents/{name}/docs/{id}   xoá 1 tài liệu (registry + chunk ở store)

Quyền: chỉ owner/admin của agent (can_update) — dùng tài liệu nội bộ, không cho người lạ sửa.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import Container, get_container, require_login
from app.knowledge.chunker import UnsupportedDocument

log = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge"])


def _kb_or_404(c: Container):
    if c.knowledge is None:
        raise HTTPException(404, "Tính năng tài liệu (RAG) chưa được bật.")
    return c.knowledge


def _agent_or_403(c: Container, name: str, user) -> None:
    """Agent tồn tại + user có quyền sửa (owner/admin)."""
    agent = c.agents.get(name)
    if agent is None:
        raise HTTPException(404, f"agent '{name}' không tồn tại")
    if not c.governance.can_update(agent, user.email):
        raise HTTPException(403, "Bạn không có quyền quản lý tài liệu của agent này.")


@router.get("/agents/{name}/docs")
def list_docs(name: str, c: Container = Depends(get_container), user=Depends(require_login)):
    kb = _kb_or_404(c)
    _agent_or_403(c, name, user)
    return {"docs": kb.list_docs(name)}


@router.post("/agents/{name}/docs")
async def upload_doc(name: str, file: UploadFile, c: Container = Depends(get_container), user=Depends(require_login)):
    kb = _kb_or_404(c)
    _agent_or_403(c, name, user)
    raw = await file.read()
    if not raw:
        raise HTTPException(422, "File rỗng.")
    max_bytes = c.settings.knowledge_max_doc_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(413, f"File quá lớn (tối đa {c.settings.knowledge_max_doc_mb} MB).")
    try:
        result = kb.ingest(name, file.filename or "tài liệu", raw, created_by=user.email)
    except UnsupportedDocument as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # noqa: BLE001 — lỗi store → báo rõ, không 500 trống
        log.exception("knowledge upload lỗi (agent=%s file=%s)", name, file.filename)
        raise HTTPException(502, f"Không lưu được tài liệu vào kho kiến thức: {e}") from e
    return result


@router.delete("/agents/{name}/docs/{doc_id}")
def delete_doc(name: str, doc_id: int, c: Container = Depends(get_container), user=Depends(require_login)):
    kb = _kb_or_404(c)
    _agent_or_403(c, name, user)
    if not kb.delete_doc(name, doc_id):
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    return {"deleted": doc_id}
