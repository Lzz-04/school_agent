"""RAG 检索器。

两级策略：
- 配了 LLM key → 调 embedding API 做向量余弦相似度检索（语义召回）
- 未配 key 或 embedding 失败 → 回退 TF-IDF 关键词检索（离线可用）

向量缓存在内存，进程内只算一次 chunk 向量。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

from ..storage.database import Database


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    en_words = re.findall(r"[a-z0-9]+", text)
    cn_chars = re.findall(r"[\u4e00-\u9fff]", text)
    cn_bigrams = [cn_chars[i] + cn_chars[i + 1] for i in range(len(cn_chars) - 1)]
    return en_words + cn_bigrams


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class Retriever:
    """从 knowledge_chunks 检索 top-k 相关片段。"""

    def __init__(self, db: Database):
        self.db = db
        self._chunks: list[dict] = []
        self._idf: dict[str, float] = {}
        self._tf_cache: dict[str, Counter] = {}
        self._chunk_embeddings: list[list[float]] = []
        self._use_vector = False
        self._loaded = False

    # ------------------------------------------------------------------
    def load(self) -> None:
        rows = self.db.execute(
            "SELECT chunk_id, category, title, content, keywords FROM knowledge_chunks"
        ).fetchall()
        self._chunks = [dict(r) for r in rows]

        # TF-IDF 兜底索引
        df: Counter = Counter()
        self._tf_cache = {}
        for c in self._chunks:
            tokens = _tokenize(f"{c['title']} {c['content']} {c['keywords']}")
            self._tf_cache[c["chunk_id"]] = Counter(tokens)
            for t in set(tokens):
                df[t] += 1
        n = max(len(self._chunks), 1)
        self._idf = {t: math.log((n + 1) / (df[t] + 1)) + 1.0 for t in df}

        # 尝试加载向量索引
        self._try_load_embeddings()
        self._loaded = True

    def _try_load_embeddings(self) -> None:
        """配了 LLM key 就给 chunk 建向量索引；失败静默回退。"""
        from ..llm import get_llm
        llm = get_llm()
        if not llm.enabled:
            self._use_vector = False
            return
        try:
            texts = [f"{c['title']}。{c['content']}" for c in self._chunks]
            self._chunk_embeddings = llm.embed(texts)
            self._use_vector = True
        except Exception:
            self._use_vector = False

    # ------------------------------------------------------------------
    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        if not self._loaded:
            self.load()
        if not self._chunks:
            return []
        if self._use_vector:
            return self._retrieve_vector(query, top_k)
        return self._retrieve_tfidf(query, top_k)

    def _retrieve_vector(self, query: str, top_k: int) -> list[dict]:
        from ..llm import get_llm
        try:
            qv = get_llm().embed([query])[0]
        except Exception:
            return self._retrieve_tfidf(query, top_k)
        scored = []
        for c, cv in zip(self._chunks, self._chunk_embeddings):
            scored.append((_cosine(qv, cv), c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"score": round(s, 3), "chunk_id": c["chunk_id"], "category": c["category"],
             "title": c["title"], "content": c["content"]}
            for s, c in scored[:top_k]
        ]

    def _retrieve_tfidf(self, query: str, top_k: int) -> list[dict]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        scored = []
        for c in self._chunks:
            tf = self._tf_cache.get(c["chunk_id"], Counter())
            score = 0.0
            for t in q_tokens:
                if t in tf:
                    score += (1 + math.log(tf[t])) * self._idf.get(t, 1.0)
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"score": round(s, 3), "chunk_id": c["chunk_id"], "category": c["category"],
             "title": c["title"], "content": c["content"]}
            for s, c in scored[:top_k]
        ]

    def stats(self) -> dict:
        """返回当前检索模式，便于前端/日志观测。"""
        return {
            "mode": "vector" if self._use_vector else "tfidf",
            "chunks": len(self._chunks),
        }
