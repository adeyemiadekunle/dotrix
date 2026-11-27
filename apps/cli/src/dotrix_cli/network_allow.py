"""Which hosts a native sandbox's commands may reach, through the host's relay.

A native turn's sandbox has no network of its own. When `DOTRIX_CODING_NETWORK_ALLOW` names hosts, the sandbox's
bridge accepts HTTPS proxy tunnels (`CONNECT host:port`) and the host's `Relay` opens each one only to a host on the
list, only on the port the entry names (443 by default), and only to a public address. A listed name that resolves to
a loopback, private or link-local address is refused, so the list can't reach services on this computer or its
network. Entries are separated by commas or spaces:

- `example.com`: that host, on port 443
- `*.example.com`: hosts under it, not `example.com` itself
- `registry.example.com:8443`: that host on that port

The host resolves names; the sandbox has no DNS. Unencrypted HTTP is not tunnelled.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from dataclasses import dataclass

ENV = 'DOTRIX_CODING_NETWORK_ALLOW'
_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')


@dataclass(frozen=True)
class Rule:
    host: str
    port: int
    subdomains: bool = False

    def permits(self, host: str, port: int) -> bool:
        if port != self.port:
            return False
        if self.subdomains:
            return host.endswith('.' + self.host)
        return host == self.host


def _valid_host(host: str) -> bool:
    """A DNS name. An address isn't one: the list names hosts, and the host resolves them."""
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return 0 < len(host) <= 253 and all(_LABEL.fullmatch(label) for label in host.split('.'))


def parse(value: str | None) -> tuple[Rule, ...]:
    """The rules in `value`. An entry that isn't a host name (with an optional port) is an error, so a typo is
    reported rather than silently allowing nothing."""
    rules = []
    for entry in re.split(r'[\s,]+', (value or '').strip().lower()):
        if not entry:
            continue
        host, _, port_text = entry.partition(':')
        subdomains = host.startswith('*.')
        host = host[2:] if subdomains else host
        port = int(port_text) if port_text.isdigit() else (443 if not port_text else -1)
        if not _valid_host(host) or not 1 <= port <= 65535 or '.' not in host:
            raise ValueError(f'{ENV}: {entry!r} is not a host name such as example.com, *.example.com or example.com:8443')
        rules.append(Rule(host, port, subdomains))
    return tuple(rules)


def from_environment(environ: dict[str, str] | None = None) -> tuple[Rule, ...]:
    return parse((environ if environ is not None else os.environ).get(ENV))


def permits(rules: tuple[Rule, ...], host: str, port: int) -> bool:
    host = host.lower().rstrip('.')
    return _valid_host(host) and any(rule.permits(host, port) for rule in rules)


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
