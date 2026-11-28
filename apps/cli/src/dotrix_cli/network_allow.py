"""Which hosts a native sandbox's commands may reach, through the host's relay.

A native turn's sandbox has no network of its own. When its list names hosts, the sandbox's
bridge accepts HTTPS proxy tunnels (`CONNECT host:port`) and the host's `Relay` opens each one only to a host on the
list, only on the port the entry names (443 by default), and only to a public address. A listed name that resolves to
a loopback, private or link-local address is refused, so the list can't reach services on this computer or its
network. Entries are separated by commas or spaces:

- `example.com`: that host, on port 443
- `*.example.com`: hosts under it, not `example.com` itself
- `registry.example.com:8443`: that host on that port

The format is the platform's network policy (dotrix_engine/network_policy.py). A turn gets the list its coding
session pinned (Settings → Environments & network), which this computer's variable can only narrow (`for_turn`).
The host resolves names; the sandbox has no DNS. Unencrypted HTTP is not tunnelled.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket

from dotrix_engine import network_policy
from dotrix_engine.network_policy import Entry as Rule  # the one format, shared with the platform

ENV = 'DOTRIX_CODING_NETWORK_ALLOW'
NONE = 'none'  # this computer allows its sandbox no hosts, whatever a session's project allows


def parse(value: str | None) -> tuple[Rule, ...]:
    """The rules in `value`. An entry that isn't a host name (with an optional port) is an error, so a typo is
    reported rather than silently allowing nothing."""
    try:
        return tuple(network_policy.parse_text(value))
    except network_policy.InvalidEntry as exc:
        raise ValueError(f'{ENV}: {exc}') from exc


def from_environment(environ: dict[str, str] | None = None) -> tuple[Rule, ...]:
    value = (environ if environ is not None else os.environ).get(ENV)
    return () if (value or '').strip().lower() == NONE else parse(value)


def for_turn(session: list[str] | None, environ: dict[str, str] | None = None) -> tuple[Rule, ...]:
    """What a turn's sandbox may reach. `session` is the list the platform pinned on the turn's coding session (its
    project's network policy within the workspace's limit), or None from a platform that doesn't send one. This
    computer's `DOTRIX_CODING_NETWORK_ALLOW` can only narrow a session's list: unset keeps it, `none` allows nothing,
    and a list keeps only the session's entries that it covers. Without a session list, the variable alone applies."""
    environ = environ if environ is not None else os.environ
    local = environ.get(ENV)
    if session is None:
        return from_environment(environ)
    pinned = [str(rule) for rule in parse(' '.join(session))]
    if local is None or not local.strip():
        return parse(' '.join(pinned))
    if local.strip().lower() == NONE:
        return ()
    return parse(' '.join(network_policy.narrow(pinned, [str(rule) for rule in parse(local)])))


def permits(rules: tuple[Rule, ...], host: str, port: int) -> bool:
    return network_policy.permits(rules, host, port)


def split_target(target: str) -> tuple[str, int]:
    """`host:port` from a CONNECT request line."""
    host, separator, port = target.rpartition(':')
    if not separator or not port.isdigit() or not host or host.startswith('['):
        raise ValueError('A tunnel names a host and a port')
    return host, int(port)


async def connect(rules: tuple[Rule, ...], host: str, port: int, *, timeout: float = 20):
    """Opens a TCP connection to an allowed host's public address, or raises PermissionError / OSError."""
    if not permits(rules, host, port):
        raise PermissionError(f'{host}:{port} is not on {ENV}')
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout)
    addresses = []
    for family, _, _, _, address in infos:
        ip = ipaddress.ip_address(address[0])
        if ip.is_global and not ip.is_multicast:
            addresses.append((family, address[0]))
    if not addresses:
        raise PermissionError(f'{host} has no public address')
    last: OSError | None = None
    for _, ip in addresses:
        try:
            return await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
        except (OSError, TimeoutError) as exc:
            last = exc if isinstance(exc, OSError) else OSError(str(exc))
    raise last or OSError(f"Couldn't reach {host}")
