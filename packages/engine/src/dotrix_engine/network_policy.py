"""The network policy: which hosts Kai's sandboxes may reach besides the model API.

One format and one validator for the platform (Settings → Environments, `coding/network.py`) and for the
local runner (`dotrix_cli/network_allow.py`), so a list means the same thing in the cloud and on a person's computer.

An entry is one of:

- `example.com`: that host, on port 443
- `*.example.com`: hosts under it, not `example.com` itself
- `registry.example.com:8443`: that host on that port (`*.example.com:8443` likewise)

Names only: no schemes, paths or IP addresses (a sandbox reaches names; whoever opens the connection resolves them).
`host:443` is stored as `host`. A preset names a package registry's hosts.

The layers (docs/cloud-environments.md): the workspace may set a limit, the most any project may allow; each project
chooses what its repository needs within it; a coding session pins its project's choice when its first turn is
admitted; and the limit as it is now still applies to every turn. `within` and `narrow` implement those checks.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass

DEFAULT_PORT = 443
MAX_ENTRIES = 50

PRESETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "npm": ("npm (and pnpm, Yarn)", ("registry.npmjs.org", "registry.yarnpkg.com")),
    "pypi": ("PyPI (pip, uv)", ("pypi.org", "files.pythonhosted.org")),
    "go": ("Go modules", ("proxy.golang.org", "sum.golang.org")),
    "crates": ("crates.io (Cargo)", ("crates.io", "index.crates.io", "static.crates.io")),
    "rubygems": ("RubyGems", ("rubygems.org", "index.rubygems.org")),
    "maven": ("Maven Central", ("repo.maven.apache.org", "repo1.maven.org")),
}

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class InvalidEntry(ValueError):
    """An entry that isn't a host name such as example.com, *.example.com or example.com:8443."""


@dataclass(frozen=True)
class Entry:
    host: str
    port: int = DEFAULT_PORT
    subdomains: bool = False

    def __str__(self) -> str:
        name = f"*.{self.host}" if self.subdomains else self.host
        return name if self.port == DEFAULT_PORT else f"{name}:{self.port}"

    def permits(self, host: str, port: int) -> bool:
        if port != self.port:
            return False
        return host.endswith("." + self.host) if self.subdomains else host == self.host

    def covers(self, other: Entry) -> bool:
        """Whether everything `other` allows, this allows too."""
        if other.port != self.port:
            return False
        if not self.subdomains:
            return not other.subdomains and other.host == self.host
        return other.host.endswith("." + self.host) or (other.subdomains and other.host == self.host)


def valid_host(host: str) -> bool:
    """A DNS name with at least two labels. An address isn't one."""
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return 0 < len(host) <= 253 and "." in host and all(_LABEL.fullmatch(label) for label in host.split("."))


def parse_entry(raw: str) -> Entry:
    text = raw.strip().lower()
    host, separator, port_text = text.rpartition(":") if ":" in text else (text, "", "")
    host = host.rstrip(".")
    if separator and not port_text.isdigit():
        raise InvalidEntry(f"{raw.strip()!r} isn't a host name like api.example.com, *.example.com or example.com:8443")
    port = int(port_text) if separator else DEFAULT_PORT
    subdomains = host.startswith("*.")
    name = host[2:] if subdomains else host
    try:
        ipaddress.ip_address(name.strip("[]"))
        raise InvalidEntry(f"{raw.strip()!r}: allow a host name, not an IP address")
    except ValueError:
        pass
    if not valid_host(name) or not 1 <= port <= 65535 or "/" in text:
        raise InvalidEntry(f"{raw.strip()!r} isn't a host name like api.example.com, *.example.com or example.com:8443")
    return Entry(name, port, subdomains)


def parse(values: Iterable[str], *, limit: int | None = MAX_ENTRIES) -> list[Entry]:
    """Entries as stored: deduplicated, in the order given. Blank values are skipped; a bad one raises InvalidEntry
    naming it, so a typo is reported rather than silently allowing nothing."""
    entries: list[Entry] = []
    for raw in values:
        if not raw.strip():
            continue
        entry = parse_entry(raw)
        if entry not in entries:
            entries.append(entry)
    if limit is not None and len(entries) > limit:
        raise InvalidEntry(f"At most {limit} hosts")
    return entries


def parse_text(value: str | None) -> list[Entry]:
    """Entries separated by commas or whitespace, as in the runner's `DOTRIX_CODING_NETWORK_ALLOW`."""
    return parse(re.split(r"[\s,]+", (value or "").strip()), limit=None)


def clean(values: Iterable[str]) -> list[str]:
    return [str(entry) for entry in parse(values)]


def expand(presets: Iterable[str], hosts: Iterable[str]) -> list[str]:
    """A preset's hosts, then the custom ones, deduplicated. Unknown presets are skipped."""
    out: list[str] = []
    for value in [h for p in presets if p in PRESETS for h in PRESETS[p][1]] + [str(e) for e in parse(hosts, limit=None)]:
        if value not in out:
            out.append(value)
    return out


def within(limit: Iterable[str], value: str) -> bool:
    entry = parse_entry(value)
    return any(parse_entry(rule).covers(entry) for rule in limit)


def narrow(entries: Iterable[str], limit: Iterable[str] | None) -> list[str]:
    """`entries` as far as `limit` allows. None is no limit."""
    entries = list(entries)
    if limit is None:
        return entries
    limit = list(limit)
    return [value for value in entries if within(limit, value)]


def permits(entries: Iterable[Entry], host: str, port: int) -> bool:
    host = host.lower().rstrip(".")
    return valid_host(host) and any(entry.permits(host, port) for entry in entries)


def digest(entries: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(entries)).encode()).hexdigest()[:16]
