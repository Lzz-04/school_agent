"""配置加载（无密钥硬编码；全部可经环境变量覆盖）。

- CAMPUS_AGENT_DB_PATH : SQLite 数据库路径（默认项目内 data/campus_agent.db）
- CAMPUS_AGENT_LLM     : 是否启用 LLM 意图识别（默认 off，走确定性规则路由）
- CAMPUS_AGENT_SINK    : 通知投递通道（log）
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.project_root: Path = _PROJECT_ROOT
        self.db_path: str = os.getenv(
            "CAMPUS_AGENT_DB_PATH", str(_PROJECT_ROOT / "data" / "campus_agent.db")
        )
        self.llm_enabled: bool = _env_bool("CAMPUS_AGENT_LLM", False)
        self.llm_model: str = os.getenv("CAMPUS_AGENT_LLM_MODEL", "gpt-4o")
        self.llm_api_key: str = os.getenv("CAMPUS_AGENT_LLM_API_KEY", "")
        self.notify_sink: str = os.getenv("CAMPUS_AGENT_SINK", "log")
        self.rate_limit_per_minute: int = int(os.getenv("CAMPUS_AGENT_RATE_LIMIT", "60"))
        self.max_agent_steps: int = int(os.getenv("CAMPUS_AGENT_MAX_STEPS", "20"))
        # 允许的跨域来源（生产收敛，勿用 *；默认本地前端开发源 + 同源托管）
        self.cors_origins: list[str] = [
            o.strip()
            for o in os.getenv(
                "CAMPUS_AGENT_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if o.strip()
        ]

    def ensure_data_dir(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
