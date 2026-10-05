"""Vector memory dùng Chroma (embedded) để truy xuất ngữ nghĩa."""

from __future__ import annotations

import uuid
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings


class VectorMemory:
    def __init__(self, persist_dir: str):
        self._client = chromadb.PersistentClient(
            path=persist_dir, settings=ChromaSettings(anonymized_telemetry=False)
        )
        self._collection = self._client.get_or_create_collection(
            name="lifeos_memory", metadata={"hnsw:space": "cosine"}
        )

    def add(self, text: str, metadata: Optional[dict] = None) -> str:
        doc_id = uuid.uuid4().hex
        self._collection.add(
            ids=[doc_id], documents=[text], metadatas=[metadata or {}]
        )
        return doc_id

    def search(self, query: str, k: int = 4) -> list[dict]:
        res = self._collection.query(query_texts=[query], n_results=k)
        out: list[dict] = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        for i, doc_id in enumerate(ids):
            out.append(
                {"id": doc_id, "text": docs[i] if i < len(docs) else "", "metadata": metas[i] if i < len(metas) else {}}
            )
        return out

    def count(self) -> int:
        return self._collection.count()