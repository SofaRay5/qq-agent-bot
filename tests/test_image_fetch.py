import socket
from collections.abc import Callable
from typing import Any

import httpcore
import httpx
import pytest

import agent.image_fetch as image_fetch
from agent.image_fetch import _PinnedBackend, _public_addresses, fetch_image


def use_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[dict[str, Any]]:
    real_client = httpx.AsyncClient
    options: list[dict[str, Any]] = []

    def client(**kwargs: Any) -> httpx.AsyncClient:
        transport = kwargs.pop("transport")
        assert isinstance(transport, image_fetch._PinnedTransport)
        options.append(kwargs)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(image_fetch, "_public_addresses", lambda _host: _public_ip())
    return options


async def _public_ip() -> tuple[str, ...]:
    return ("8.8.8.8",)


@pytest.mark.parametrize(
    ("body", "mime"),
    [
        (b"\xff\xd8\xffimage", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nimage", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPimage", "image/webp"),
    ],
)
@pytest.mark.asyncio
async def test_downloads_supported_image_without_redirects_or_proxy(
    monkeypatch: pytest.MonkeyPatch, body: bytes, mime: str
) -> None:
    options = use_transport(monkeypatch, lambda request: httpx.Response(200, content=body))
    assert await fetch_image("https://multimedia.nt.qq.com.cn/image", len(body)) == (mime, body)
    assert options == [{"timeout": 10, "follow_redirects": False, "trust_env": False}]


@pytest.mark.parametrize(
    "url",
    [
        "",
        "file:///tmp/image.png",
        "http://127.0.0.1/image",
        "https://example.com/image",
        "https://user:pass@multimedia.nt.qq.com.cn/image",
        "https://multimedia.nt.qq.com.cn:443/image",
        "https://multimedia.nt.qq.com.cn/image#fragment",
    ],
)
@pytest.mark.asyncio
async def test_rejects_unsupported_urls_before_http(url: str) -> None:
    with pytest.raises(ValueError):
        await fetch_image(url, None)


@pytest.mark.asyncio
async def test_rejects_private_dns_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    async def private_host(_host: str) -> tuple[str, ...]:
        return ()

    monkeypatch.setattr(image_fetch, "_public_addresses", private_host)
    with pytest.raises(ValueError, match="public"):
        await fetch_image("https://multimedia.nt.qq.com.cn/image", None)
    assert not requested


@pytest.mark.parametrize(
    ("status", "headers", "body", "claimed_size"),
    [
        (302, {"location": "https://multimedia.nt.qq.com.cn/other"}, b"", None),
        (200, {"content-length": str(8 * 1024 * 1024 + 1)}, b"", None),
        (200, {}, b"\x89PNG\r\n\x1a\n" + b"x" * (8 * 1024 * 1024), None),
        (200, {}, b"\x89PNG\r\n\x1a\n", 8 * 1024 * 1024 + 1),
        (200, {}, b"not an image", None),
    ],
)
@pytest.mark.asyncio
async def test_rejects_bad_response_size_or_type(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    headers: dict[str, str],
    body: bytes,
    claimed_size: int | None,
) -> None:
    use_transport(
        monkeypatch,
        lambda request: httpx.Response(status, headers=headers, content=body),
    )
    with pytest.raises(ValueError):
        await fetch_image("https://cdn.qpic.cn/image", claimed_size)


@pytest.mark.asyncio
async def test_public_addresses_require_every_dns_answer_to_be_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [
            (2, 1, 6, "", ("8.8.8.8", 0)),
            (2, 1, 6, "", ("192.168.1.2", 0)),
        ],
    )
    assert not await _public_addresses("multimedia.nt.qq.com.cn")


@pytest.mark.asyncio
async def test_pinned_backend_connects_to_validated_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _PinnedBackend("8.8.8.8")
    connected: list[tuple[str, int]] = []

    async def connect_tcp(
        host: str,
        port: int,
        **_kwargs: Any,
    ) -> httpcore.AsyncNetworkStream:
        connected.append((host, port))
        return httpcore.AsyncMockStream([])

    monkeypatch.setattr(backend._backend, "connect_tcp", connect_tcp)
    await backend.connect_tcp("multimedia.nt.qq.com.cn", 443)
    assert connected == [("8.8.8.8", 443)]
