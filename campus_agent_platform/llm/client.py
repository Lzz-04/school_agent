"""LLM 客户端：OpenAI 兼容协议（豆包/DeepSeek/通义/OpenAI 均可）。

配置（环境变量）：
- CAMPUS_LLM_API_KEY    : API Key
- CAMPUS_LLM_BASE_URL    : 兼容端点，默认 https://ark.cn-beijing.volces.com/api/v3（豆包）
- CAMPUS_LLM_MODEL       : 模型名，默认 doubao-pro-4k
- CAMPUS_LLM_ENABLED    : 1/true 启用；未配 API key 时自动禁用，回退规则回答
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_EMBED_MODEL = os.getenv("CAMPUS_LLM_EMBED_MODEL", "Pro/BAAI/bge-m3")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.getenv("CAMPUS_LLM_API_KEY", "")
        self.base_url = (base_url or os.getenv("CAMPUS_LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.model = model or os.getenv("CAMPUS_LLM_MODEL", DEFAULT_MODEL)
        self.embed_model = os.getenv("CAMPUS_LLM_EMBED_MODEL", DEFAULT_EMBED_MODEL)
        self.enabled = bool(self.api_key) and _env_bool("CAMPUS_LLM_ENABLED", True)

    def chat(
        self,
        system: str,
        messages: list[dict],
        temperature: float = 0.3,
        timeout: float = 30.0,
    ) -> str:
        """调用 /chat/completions，返回 assistant 文本。失败抛异常。"""
        text, _ = self.chat_with_usage(system, messages, temperature=temperature, timeout=timeout)
        return text

    def chat_with_usage(
        self,
        system: str,
        messages: list[dict],
        temperature: float = 0.3,
        timeout: float = 30.0,
    ) -> tuple[str, dict | None]:
        """调用 /chat/completions，返回 (assistant 文本, usage)。

        usage 形如 {"prompt_tokens": N, "completion_tokens": M}（OpenAI 兼容），
        供 F1 可观测性埋点统计 token 成本；部分兼容端点不返回 usage 时为 None。
        失败抛异常。
        """
        if not self.enabled:
            raise RuntimeError("LLM 未启用（未配置 CAMPUS_LLM_API_KEY）")
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage")
        return text, (usage if isinstance(usage, dict) else None)

    # ------------------------------------------------------------------
    def embed(self, texts: list[str], timeout: float = 20.0) -> list[list[float]]:
        """调用 /embeddings，返回向量列表。失败抛异常。"""
        if not self.enabled:
            raise RuntimeError("LLM 未启用（未配置 CAMPUS_LLM_API_KEY）")
        payload = {"model": self.embed_model, "input": texts}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/embeddings"
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        # OpenAI 兼容返回 {"data": [{"embedding": [...]}, ...]}
        return [item["embedding"] for item in data["data"]]


# 全局单例
_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
