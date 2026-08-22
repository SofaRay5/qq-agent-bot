import copy
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """读取 tests/fixtures/<name>.json，返回一份独立的 dict 副本（避免测试间互相污染）。"""
    path = FIXTURES_DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


@pytest.fixture
def private_message_json() -> dict[str, Any]:
    return load_fixture("private_message")


@pytest.fixture
def group_message_json() -> dict[str, Any]:
    return load_fixture("group_message")


@pytest.fixture
def heartbeat_json() -> dict[str, Any]:
    return load_fixture("heartbeat")
