"""KnowledgeService — public API của module RAG: ingest / search / list / delete tài liệu.

Module bật/tắt bằng config: make_knowledge_service() trả None khi RAG tắt (settings.rag_active=False).
Mọi nơi tích hợp (engine, API) chỉ cần kiểm tra `if knowledge is not None`.
"""

import logging

from app.knowledge.chunker import UnsupportedDocument, chunk_text, extract_text
from app.knowledge.store import AgentBaseKnowledgeStore
from app.tools.mcp_gateway import IamTokenProvider

log = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self, store: AgentBaseKnowledgeStore, docs_repo, settings):
        self._store = store
        self._docs = docs_repo
        self._top_k = settings.rag_top_k
        self._threshold = settings.rag_score_threshold
        self._chunk_chars = settings.knowledge_chunk_chars
        self._overlap = settings.knowledge_chunk_overlap

    def ingest(self, agent_name: str, filename: str, raw: bytes, created_by: str) -> dict:
        """Parse → chunk → insert vào knowledge store → ghi registry. Raise UnsupportedDocument nếu file lỗi."""
        text = extract_text(filename, raw)  # raise UnsupportedDocument
        chunks = chunk_text(text, size=self._chunk_chars, overlap=self._overlap)
        if not chunks:
            raise UnsupportedDocument("Tài liệu không có nội dung sau khi xử lý.")
        n = self._store.insert_chunks(agent_name, filename, chunks)
        doc_id = self._docs.add(agent_name, filename, n, created_by)
        log.info("knowledge ingest: agent=%s file=%s chunks=%d", agent_name, filename, n)
        return {"doc_id": doc_id, "filename": filename, "chunk_count": n}

    def search(self, agent_name: str, query: str) -> list[dict]:
        """Top-k đoạn liên quan [{source, content, score}] — đã lọc threshold. Lỗi → trả rỗng (không chặn chat)."""
        if not query.strip():
            return []
        return self._store.search(agent_name, query, limit=self._top_k, threshold=self._threshold)

    def list_docs(self, agent_name: str) -> list[dict]:
        return self._docs.list(agent_name)

    def has_docs(self, agent_name: str) -> bool:
        return self._docs.count(agent_name) > 0

    def delete_doc(self, agent_name: str, doc_id: int) -> bool:
        doc = self._docs.get(doc_id)
        if not doc or doc["agent_name"] != agent_name:
            return False
        try:
            self._store.delete_doc(agent_name, doc["filename"])
        except Exception:  # noqa: BLE001 — vẫn xoá registry kể cả store lỗi
            log.exception("knowledge delete_doc store lỗi (agent=%s doc=%s)", agent_name, doc_id)
        self._docs.delete(doc_id)
        return True


def make_knowledge_service(settings, docs_repo) -> "KnowledgeService | None":
    """Factory gated bởi config. Trả None khi RAG tắt → flow chạy y như cũ."""
    if not settings.rag_active:
        log.info("RAG: tắt (rag_active=False) — không khởi tạo knowledge module")
        return None
    token = IamTokenProvider(settings.greennode_client_id, settings.greennode_client_secret)
    store = AgentBaseKnowledgeStore(token, settings.knowledge_store_id, settings.knowledge_strategy_id)
    log.info("RAG: bật (store=%s) — knowledge module hoạt động", settings.knowledge_store_id)
    return KnowledgeService(store, docs_repo, settings)
