"""Upia RAG: ingest_text + knowledge_search scope theo conversation (tài liệu lớn)."""

from types import SimpleNamespace

from app.core.chat_engine import ChatEngine
from app.core.models import Agent, ItemStatus
from app.knowledge.service import KnowledgeService
from app.tools.catalog import SystemProvider, ToolCatalog


def _kb_settings():
    return SimpleNamespace(
        rag_top_k=5, rag_score_threshold=0.6,
        knowledge_chunk_chars=1200, knowledge_chunk_overlap=150,
    )


class _FakeStore:
    def __init__(self):
        self.inserted = []

    def insert_chunks(self, scope, filename, chunks):
        self.inserted.append((scope, filename, len(chunks)))
        return len(chunks)


class _FakeDocs:
    def __init__(self):
        self.added = []

    def add(self, scope, filename, n, by):
        self.added.append((scope, filename, n, by))
        return len(self.added)


def test_ingest_text_chunks_and_scopes():
    store, docs = _FakeStore(), _FakeDocs()
    svc = KnowledgeService(store, docs, _kb_settings())
    res = svc.ingest_text("Upia::conv-1", "api.pdf", "x " * 5000, "user-a")
    assert res["chunk_count"] >= 1
    # ghi đúng scope theo conversation
    assert store.inserted and store.inserted[0][0] == "Upia::conv-1"
    assert docs.added and docs.added[0][0] == "Upia::conv-1"


class _RecordingKnowledge:
    """knowledge service giả — ghi lại scope của search."""
    def __init__(self):
        self.searched_scope = None

    def search(self, scope, query):
        self.searched_scope = scope
        return [{"source": "api.pdf", "content": "auth = hmac", "score": 0.9}]

    def has_docs(self, _name):
        return False


def _engine(knowledge):
    cat = ToolCatalog([SystemProvider()])
    return ChatEngine(agents=None, skills=None, usage=None, memory=None, llm=None,
                      catalog=cat, knowledge=knowledge)


def test_knowledge_search_uses_conversation_scope():
    kb = _RecordingKnowledge()
    eng = _engine(kb)
    agent = Agent(name="Upia", description="d", system_prompt="p",
                  connectors=[], domain="x", status=ItemStatus.public)
    # has_kb=True + knowledge_scope theo conversation → executor phải search đúng scope đó
    _tools, execute = eng._assemble_tools(
        agent, "hi", has_kb=True, knowledge_scope="Upia::conv-9",
    )
    res = execute("knowledge_search", {"query": "auth"})
    assert kb.searched_scope == "Upia::conv-9"
    assert "hmac" in res.content


def test_knowledge_search_defaults_to_agent_name():
    kb = _RecordingKnowledge()
    eng = _engine(kb)
    agent = Agent(name="Em Bé CS", description="d", system_prompt="p",
                  connectors=[], domain="x", status=ItemStatus.public)
    _tools, execute = eng._assemble_tools(agent, "hi", has_kb=True)  # không truyền scope
    execute("knowledge_search", {"query": "faq"})
    assert kb.searched_scope == "Em Bé CS"  # fallback agent.name
