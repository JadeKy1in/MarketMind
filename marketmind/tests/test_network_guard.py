"""The offline suite blocks non-loopback network access (tests/conftest.py)."""
import asyncio
import socket

import pytest

from marketmind.tests.conftest import NetworkBlockedError


def test_external_connect_is_blocked():
    s = socket.socket()
    try:
        with pytest.raises(NetworkBlockedError, match="mark the test"):
            s.connect(("93.184.216.34", 80))
    finally:
        s.close()


def test_external_dns_lookup_is_blocked():
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)


def test_httpx_request_is_blocked():
    import httpx
    with pytest.raises(Exception) as exc:
        httpx.get("https://example.com", timeout=5)
    assert isinstance(exc.value, NetworkBlockedError) or "blocked" in str(exc.value)


def test_asyncio_ip_literal_connect_is_blocked():
    async def main():
        await asyncio.open_connection("93.184.216.34", 80)
    with pytest.raises(NetworkBlockedError):
        asyncio.run(main())


def test_loopback_is_allowed():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket()
    try:
        client.connect(server.getsockname())
        assert socket.getaddrinfo("localhost", 80)
    finally:
        client.close()
        server.close()


def test_asyncio_loop_still_works():
    async def main():
        await asyncio.sleep(0)
        return 1
    assert asyncio.run(main()) == 1
