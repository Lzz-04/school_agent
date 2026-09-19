"""pytest 公共 fixture：独立临时数据库 + 引擎 + 工具 + 编排图。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from campus_agent_platform.app import CampusAgentApp


@pytest.fixture()
def app() -> CampusAgentApp:
    """独立应用实例（临时 SQLite 文件，含种子模板）。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    Path(tmp.name).unlink(missing_ok=True)
    instance = CampusAgentApp(db_path=tmp.name)
    yield instance
    instance.close()
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture()
def engine(app: CampusAgentApp):
    return app.engine


@pytest.fixture()
def graph(app: CampusAgentApp):
    return app.graph
