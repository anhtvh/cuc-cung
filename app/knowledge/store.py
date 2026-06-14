"""Knowledge store client — AgentBase Memory store (managed vector search) cho tài liệu RAG.

Tách store khỏi store hội thoại. Partition theo agent: namespace dùng actorId = agent_name
→ tài liệu của agent nào isolate agent đó, chia sẻ cho mọi user dùng agent.

Endpoint (xác minh qua spike + memory.sh):
- insert-directly: POST {BASE}/memories/{store}/memory-records:insert-directly?namespace=  body {memoryRecords:[str]}
- search:          POST {BASE}/memories/{store}/memory-records:search?namespace=          body {query,limit,scoreThreshold}
- list:            GET  {BASE}/memories/{store}/memory-records?namespace=&limit=
- delete record:   DELETE {BASE}/memories/{store}/memory-records/{record_id}
"""

import logging

import httpx

from app.tools.mcp_gateway import IamTokenProvider

log = logging.getLogger(__name__)

MEMORY_BASE = "https://agentbase.api.vngcloud.vn/memory"
# Đánh dấu nguồn ở đầu mỗi record để (1) trích nguồn khi search, (2) xoá theo tài liệu.
_SRC_PREFIX = "«src:"
_SRC_SUFFIX = "»\n"


def _wrap(filename: str, chunk: str) -> str:
    return f"{_SRC_PREFIX}{filename}{_SRC_SUFFIX}{chunk}"


def _unwrap(text: str) -> tuple[str, str]:
    """Tách (filename, content) từ record text. Trả ('', text) nếu không có marker."""
    if text.startswith(_SRC_PREFIX) and _SRC_SUFFIX in text:
        head, _, body = text.partition(_SRC_SUFFIX)
        return head[len(_SRC_PREFIX):], body
    return "", text


class AgentBaseKnowledgeStore:
    """Client tới 1 knowledge store. Chỉ khởi tạo khi RAG bật (xem service.make_knowledge_service)."""

    def __init__(self, token_provider: IamTokenProvider, store_id: str, strategy_id: str):
        self._token = token_provider
        self._store_id = store_id
        self._strategy_id = strategy_id
        self._http = httpx.Client(timeout=15.0)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token.get_token()}", "Content-Type": "application/json"}

    def _namespace(self, agent_name: str) -> str:
        # actorId = agent_name → partition tài liệu theo agent.
        return f"/strategies/{self._strategy_id}/actors/{agent_name}"

    def _records_url(self, suffix: str = "") -> str:
        return f"{MEMORY_BASE}/memories/{self._store_id}/memory-records{suffix}"

    def insert_chunks(self, agent_name: str, filename: str, chunks: list[str]) -> int:
        """Insert-directly các chunk (kèm marker nguồn). Trả số chunk đã insert."""
        if not chunks:
            return 0
        ns = self._namespace(agent_name)
        records = [_wrap(filename, c) for c in chunks]
        resp = self._http.post(
            self._records_url(":insert-directly"),
            headers=self._headers(), params={"namespace": ns},
            json={"memoryRecords": records},
        )
        resp.raise_for_status()
        return len(records)

    def search(self, agent_name: str, query: str, limit: int = 5, threshold: float = 0.6) -> list[dict]:
        """Semantic search trong namespace của agent. Trả [{source, content, score}] đã lọc threshold."""
        ns = self._namespace(agent_name)
        body = {"query": query, "limit": max(5, limit), "scoreThreshold": threshold}
        try:
            resp = self._http.post(
                self._records_url(":search"),
                headers=self._headers(), params={"namespace": ns}, json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            arr = data if isinstance(data, list) else data.get("listData", data.get("data", []))
        except Exception:  # noqa: BLE001 — search lỗi không được chặn chat
            log.exception("KnowledgeStore.search lỗi (agent=%s)", agent_name)
            return []
        out: list[dict] = []
        for r in arr:
            raw = str(r.get("memory") or r.get("content") or "")
            src, content = _unwrap(raw)
            out.append({"source": src, "content": content, "score": r.get("score")})
        return out

    def delete_doc(self, agent_name: str, filename: str) -> int:
        """Xoá mọi record của 1 tài liệu (match marker nguồn). Trả số record đã xoá."""
        ns = self._namespace(agent_name)
        resp = self._http.get(
            self._records_url(), headers=self._headers(),
            params={"namespace": ns, "limit": 200},
        )
        resp.raise_for_status()
        data = resp.json()
        arr = data if isinstance(data, list) else data.get("listData", data.get("data", []))
        marker = f"{_SRC_PREFIX}{filename}{_SRC_SUFFIX}"
        n = 0
        for r in arr:
            raw = str(r.get("memory") or r.get("content") or "")
            rid = r.get("id") or r.get("memoryRecordId")
            if rid and raw.startswith(marker):
                try:
                    self._http.delete(self._records_url(f"/{rid}"), headers=self._headers()).raise_for_status()
                    n += 1
                except Exception:  # noqa: BLE001
                    log.warning("KnowledgeStore.delete_doc: không xoá được record %s", rid)
        return n
