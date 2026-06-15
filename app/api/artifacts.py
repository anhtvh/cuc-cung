"""GET /artifacts/{conversation_id}/{filename} — tải ZIP project do Upia đóng gói (Flow 5).

Quyền: chỉ user SỞ HỮU conversation đó mới tải được (đối chiếu conv_meta) + phải đăng nhập.
File nằm dưới data/upia_artifacts/{conversation_id}/ do tool package_project sinh ra.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import Container, get_container, get_user_id, require_login
from app.tools.partner_integration import _ARTIFACT_ROOT, _safe_segment

log = logging.getLogger(__name__)
router = APIRouter(tags=["artifacts"])


@router.get("/artifacts/{conversation_id}/{filename}")
def download_artifact(
    conversation_id: str,
    filename: str,
    c: Container = Depends(get_container),
    user=Depends(require_login),  # chặn guest (401)
    user_id: str = Depends(get_user_id),
) -> FileResponse:
    # Owner check: conversation_id phải thuộc về user đang đăng nhập.
    owned = {row.get("conversation_id") for row in c.conv_meta.list(user_id)}
    if conversation_id not in owned:
        raise HTTPException(status_code=403, detail="Bạn không có quyền tải file của cuộc trò chuyện này.")

    # Chỉ cho basename (chống traversal) + giới hạn .zip.
    if filename != Path(filename).name or not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ.")

    art_dir = _ARTIFACT_ROOT / _safe_segment(conversation_id, "default")
    path = (art_dir / filename).resolve()
    if art_dir.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy file.")

    return FileResponse(path, media_type="application/zip", filename=filename)
