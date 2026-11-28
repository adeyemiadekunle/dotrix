"""The native sandbox's network allowlist (network_allow) and the relay's HTTPS tunnels (fx_native.Relay)."""
from __future__ import annotations

import asyncio
import base64
import json
import socket
import struct

import pytest

from dotrix_cli import fx_native, network_allow
from dotrix_cli.network_allow import Rule, parse, permits


def test_entries_name_hosts_subdomains_and_ports():
    rules = parse("registry.npmjs.org, *.pythonhosted.org  github.com:8443")
    assert rules == (Rule("registry.npmjs.org", 443), Rule("pythonhosted.org", 443, True), Rule("github.com", 8443))
    assert permits(rules, "registry.npmjs.org", 443)
    assert permits(rules, "REGISTRY.npmjs.org.", 443)
    assert not permits(rules, "registry.npmjs.org", 80)
    assert permits(rules, "files.pythonhosted.org", 443)
    assert not permits(rules, "pythonhosted.org", 443)  # *. names what is under it, not the host itself
    assert not permits(rules, "evilpythonhosted.org", 443)
    assert permits(rules, "github.com", 8443) and not permits(rules, "github.com", 443)
    assert parse("") == () and parse(None) == ()


@pytest.mark.parametrize("entry", ["localhost", "127.0.0.1", "http://example.com", "exa mple.com:x", "*.com.", "example.com:0"])
def test_an_entry_that_is_not_a_host_name_is_an_error(entry):
    with pytest.raises(ValueError, match="DOTRIX_CODING_NETWORK_ALLOW"):
        parse(entry)


async def test_a_listed_name_that_resolves_to_this_network_is_refused(monkeypatch):
    rules = parse("rebind.example.com")
    loop = asyncio.get_running_loop()

    async def resolves_inside(host, port, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in ("127.0.0.1", "10.0.0.5", "169.254.169.254")]

    monkeypatch.setattr(loop, "getaddrinfo", resolves_inside)
    with pytest.raises(PermissionError, match="no public address"):
        await network_allow.connect(rules, "rebind.example.com", 443)
    with pytest.raises(PermissionError, match="not on"):
        await network_allow.connect(rules, "other.example.com", 443)


def _frame(value: dict) -> bytes:
    data = json.dumps(value).encode()
    return struct.pack("!I", len(data)) + data


async def _read_frame(sock: socket.socket) -> dict:
    loop = asyncio.get_running_loop()

    async def exact(size):
        out = bytearray()
        while len(out) < size:
            chunk = await loop.sock_recv(sock, size - len(out))
            if not chunk:
                raise EOFError()
            out.extend(chunk)
        return bytes(out)

    return json.loads(await exact(struct.unpack("!I", await exact(4))[0]))


async def _relay(network):
    host_side, sandbox_side = socket.socketpair()
    for sock in (host_side, sandbox_side):
        sock.setblocking(False)
    relay = fx_native.Relay(host_side, "https://model.example/v1", "key", "m", None, network=network)
    return relay, asyncio.create_task(relay.run()), host_side, sandbox_side


async def test_an_allowed_tunnel_carries_bytes_both_ways(monkeypatch):
    async def echo(reader, writer):
        while data := await reader.read(1024):
            writer.write(b"echo:" + data)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    opened = []

    async def to_local(rules, host, target_port, timeout=20):  # the test server isn't public; the rule check still runs
        assert permits(rules, host, target_port)
        opened.append((host, target_port))
        return await asyncio.open_connection("127.0.0.1", port)

    monkeypatch.setattr(network_allow, "connect", to_local)
    relay, task, host_side, sandbox_side = await _relay(parse("pkg.example.com"))
    loop = asyncio.get_running_loop()
    try:
        await loop.sock_sendall(sandbox_side, _frame({"id": 1, "tunnel": "pkg.example.com:443"}))
        assert await asyncio.wait_for(_read_frame(sandbox_side), 5) == {"id": 1, "status": 200}
        await loop.sock_sendall(sandbox_side, _frame({"id": 1, "data": base64.b64encode(b"hello").decode()}))
        reply = await asyncio.wait_for(_read_frame(sandbox_side), 5)
        assert base64.b64decode(reply["data"]) == b"echo:hello"
        await loop.sock_sendall(sandbox_side, _frame({"id": 1, "end": True}))
        assert await asyncio.wait_for(_read_frame(sandbox_side), 5) == {"id": 1, "end": True}
        assert opened == [("pkg.example.com", 443)] and relay.tunnels == {}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        host_side.close()
        sandbox_side.close()
        server.close()


async def test_without_an_allowlist_every_tunnel_is_refused(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("No connection may open without an allowlist")

    monkeypatch.setattr(network_allow, "connect", forbidden)
    relay, task, host_side, sandbox_side = await _relay(())
    try:
        await asyncio.get_running_loop().sock_sendall(sandbox_side, _frame({"id": 7, "tunnel": "pkg.example.com:443"}))
        assert await asyncio.wait_for(_read_frame(sandbox_side), 5) == {"id": 7, "status": 403, "end": True}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        host_side.close()
        sandbox_side.close()


async def test_a_host_off_the_list_is_refused_without_connecting(monkeypatch):
    relay, task, host_side, sandbox_side = await _relay(parse("pkg.example.com"))
    try:
        await asyncio.get_running_loop().sock_sendall(sandbox_side, _frame({"id": 2, "tunnel": "evil.example.net:443"}))
        assert await asyncio.wait_for(_read_frame(sandbox_side), 5) == {"id": 2, "status": 403}
        assert await asyncio.wait_for(_read_frame(sandbox_side), 5) == {"id": 2, "end": True}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        host_side.close()
        sandbox_side.close()


def test_the_sandbox_is_told_about_tunnels_only_with_an_allowlist():
    assert "DOTRIX_NETWORK_TUNNELS" not in fx_native.sandbox_env("/home/p", None)
    assert fx_native.sandbox_env("/home/p", None, True)["DOTRIX_NETWORK_TUNNELS"] == "1"


def test_a_turn_gets_its_sessions_list_which_this_computer_may_only_narrow():
    session = ["pypi.org", "*.example.com", "registry.example.com:8443"]
    assert [str(r) for r in network_allow.for_turn(session, {})] == session
    assert network_allow.for_turn(session, {network_allow.ENV: "none"}) == ()
    narrowed = network_allow.for_turn(session, {network_allow.ENV: "pypi.org api.example.com"})
    assert [str(r) for r in narrowed] == ["pypi.org"]  # the variable can't add api.example.com
    assert network_allow.for_turn([], {network_allow.ENV: "pypi.org"}) == ()
    # A platform that sends no list: the variable alone, as before.
    assert [str(r) for r in network_allow.for_turn(None, {network_allow.ENV: "pypi.org"})] == ["pypi.org"]
    assert network_allow.for_turn(None, {}) == ()
