"""Safely download bounded image bytes from known NapCat hosts."""

import asyncio
import ipaddress
import os
import socket
import ssl
import stat
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx

MAX_IMAGE_BYTES = 8 * 1024 * 1024


class ImageDownloadError(ValueError):
    """The remote image could not be downloaded safely."""


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, address: str) -> None:
        self._address = address
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._backend.connect_tcp(
            self._address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._backend.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, address: str) -> None:
        super().__init__(trust_env=False, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=_PinnedBackend(address),
        )


async def _public_addresses(host: str) -> tuple[str, ...]:
    try:
        answers = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, host, None), timeout=3
        )
        addresses = tuple(dict.fromkeys(str(answer[4][0]) for answer in answers))
        if not addresses or not all(
            ipaddress.ip_address(address).is_global for address in addresses
        ):
            return ()
        return addresses
    except (OSError, TimeoutError, ValueError):
        return ()


def _image_mime(data: bytes | bytearray) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("Unsupported image type")


async def fetch_image(url: str, claimed_size: int | None) -> tuple[str, bytes]:
    """Validate and download one JPEG, PNG or WebP image without persisting it."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ValueError("Unsupported image URL") from exc
    host = (parts.hostname or "").lower()
    if (
        parts.scheme not in {"http", "https"}
        or parts.username
        or parts.password
        or port
        or parts.fragment
    ):
        raise ValueError("Unsupported image URL")
    if host != "multimedia.nt.qq.com.cn" and not host.endswith(".qpic.cn"):
        raise ValueError("Unsupported image host")
    addresses = await _public_addresses(host)
    if not addresses:
        raise ValueError("Non-public image host")
    if claimed_size is not None and claimed_size > MAX_IMAGE_BYTES:
        raise ValueError("Image too large")

    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        trust_env=False,
        transport=_PinnedTransport(addresses[0]),
    ) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise ValueError("Image download failed")
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > MAX_IMAGE_BYTES:
                raise ValueError("Image too large")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError("Image too large")
    return _image_mime(data), bytes(data)


def read_image_file(path: str, claimed_size: int | None) -> tuple[str, bytes]:
    """Read one bounded regular file returned by the authenticated NapCat connection."""
    if not os.path.isabs(path) or claimed_size is not None and claimed_size > MAX_IMAGE_BYTES:
        raise ValueError("Invalid image file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Invalid image file")
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image too large")
    return _image_mime(data), data
