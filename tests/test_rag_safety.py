"""原知识库的安全与重复入库回归测试。"""

from pathlib import Path

from langchain_core.documents import Document

from config import Config
from rag.embedder import Embedder
from rag.vectorstore import VectorStore


def test_embedding_dimension_lookup_does_not_call_api(monkeypatch) -> None:
    """维度读取只看已知模型配置，不发测试向量请求。"""

    embedder = object.__new__(Embedder)
    embedder.model_name = "openai"
    monkeypatch.setattr(Config, "OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setattr(
        embedder, "embed_query", lambda _text: (_ for _ in ()).throw(AssertionError())
    )

    assert embedder.get_dimension() == 1536


def test_reingesting_source_replaces_stale_chunks(tmp_path: Path, monkeypatch) -> None:
    """同一来源更新后只保留新分块。"""

    monkeypatch.setattr(Config, "DATA_DIR", tmp_path)
    store = VectorStore(collection_name="replace_stale_chunks", embedding_dimension=2)
    source = "policy.txt"
    store.add_documents(
        [
            Document(page_content="old first", metadata={"source": source}),
            Document(page_content="old second", metadata={"source": source}),
        ],
        [[1.0, 0.0], [0.9, 0.1]],
    )
    store.add_documents(
        [Document(page_content="new only", metadata={"source": source})],
        [[0.0, 1.0]],
    )

    saved = store.collection.get(where={"source": source}, include=["documents"])
    assert saved["documents"] == ["new only"]
