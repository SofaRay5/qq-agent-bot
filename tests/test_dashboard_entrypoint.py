import asyncio
from pathlib import Path

import pytest

import dashboard.__main__ as entrypoint


class FakeManager:
    instances: list["FakeManager"] = []

    def __init__(self, _root: Path) -> None:
        self.stopped = False
        self.instances.append(self)

    async def stop(self) -> None:
        self.stopped = True


class FakeRunner:
    instances: list["FakeRunner"] = []

    def __init__(self, _app: object) -> None:
        self.cleaned = False
        self.instances.append(self)

    async def setup(self) -> None:
        return None

    async def cleanup(self) -> None:
        self.cleaned = True


class FakeSite:
    instance: "FakeSite | None" = None
    started = asyncio.Event()
    fail = False

    def __init__(self, _runner: FakeRunner, host: str, port: int) -> None:
        self.host = host
        self.port = port
        type(self).instance = self

    async def start(self) -> None:
        if type(self).fail:
            raise OSError("address already in use")
        type(self).started.set()


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeManager.instances.clear()
    FakeRunner.instances.clear()
    FakeSite.instance = None
    FakeSite.started = asyncio.Event()
    FakeSite.fail = False
    monkeypatch.setattr(entrypoint, "BotManager", FakeManager)
    monkeypatch.setattr(entrypoint.web, "AppRunner", FakeRunner)
    monkeypatch.setattr(entrypoint.web, "TCPSite", FakeSite)
    monkeypatch.setattr(entrypoint, "create_app", lambda _root, _manager: object())


@pytest.mark.asyncio
async def test_binds_local_port_opens_after_bind_and_stops_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(entrypoint.webbrowser, "open", opened.append)
    task = asyncio.create_task(entrypoint.run())

    await asyncio.wait_for(FakeSite.started.wait(), timeout=1)
    assert FakeSite.instance is not None
    assert (FakeSite.instance.host, FakeSite.instance.port) == ("127.0.0.1", 8765)
    assert opened == ["http://127.0.0.1:8765/"]
    assert FakeManager.instances[0].stopped is False

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert FakeManager.instances[0].stopped
    assert FakeRunner.instances[0].cleaned


@pytest.mark.asyncio
async def test_occupied_port_does_not_open_browser_or_start_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    FakeSite.fail = True
    monkeypatch.setattr(entrypoint.webbrowser, "open", opened.append)

    with pytest.raises(OSError, match="address already in use"):
        await entrypoint.run()

    assert opened == []
    assert FakeManager.instances[0].stopped
    assert FakeRunner.instances[0].cleaned
