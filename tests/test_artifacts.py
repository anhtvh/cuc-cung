"""Endpoint /artifacts: chỉ owner conversation tải được; chặn traversal / file lạ."""

import shutil
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.api.artifacts import download_artifact
from app.tools import partner_integration as pi

CID = "pytest-art-conv"
USER = "user-a"


def _container(owned_cids):
    conv_meta = SimpleNamespace(list=lambda uid: [{"conversation_id": c} for c in owned_cids])
    return SimpleNamespace(conv_meta=conv_meta)


def _make_zip(cid: str, name: str = "provider-x.zip") -> None:
    art = pi._artifact_dir(cid)
    art.mkdir(parents=True, exist_ok=True)
    (art / name).write_bytes(b"PK\x03\x04 fake zip")


@pytest.fixture(autouse=True)
def _clean():
    shutil.rmtree(pi._artifact_dir(CID), ignore_errors=True)
    yield
    shutil.rmtree(pi._artifact_dir(CID), ignore_errors=True)


def _call(conversation_id, filename, owned):
    return download_artifact(
        conversation_id, filename,
        c=_container(owned), user=object(), user_id=USER,
    )


def test_owner_can_download():
    _make_zip(CID)
    resp = _call(CID, "provider-x.zip", owned=[CID])
    assert isinstance(resp, FileResponse)
    assert str(resp.path).endswith("provider-x.zip")


def test_non_owner_403():
    _make_zip(CID)
    with pytest.raises(HTTPException) as e:
        _call(CID, "provider-x.zip", owned=["other-conv"])
    assert e.value.status_code == 403


def test_bad_filename_400():
    _make_zip(CID)
    with pytest.raises(HTTPException) as e:  # không phải .zip
        _call(CID, "secret.txt", owned=[CID])
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e2:  # traversal trong tên file
        _call(CID, "../../etc/passwd.zip", owned=[CID])
    assert e2.value.status_code == 400


def test_missing_file_404():
    with pytest.raises(HTTPException) as e:  # owner nhưng file chưa tồn tại
        _call(CID, "provider-x.zip", owned=[CID])
    assert e.value.status_code == 404
