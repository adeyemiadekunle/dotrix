"""Shared OS process boundary for fx and Claude Code. The host owns model/browser access.

- Linux: Bubblewrap (`bwrap`) with user/network/PID/mount namespaces and a Unix-socket relay.
- macOS: Seatbelt (`sandbox-exec`) denying default filesystem/network access outside the
  worktree, private profile, and Unix-socket / loopback relay.
- Windows: zero-capability AppContainer + Job Object (`win_sandbox.py`) with an inherited
  pipe relay.

No broad proxy, host filesystem mount, credential-bearing engine environment, or
unconfined fallback. Unsupported or unverifiable hosts fail closed.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import functools
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import bundled, fx_wsl, network_allow, win_sandbox
from .frozen_entry import BRIDGE_COMMAND
from .fx_bridge import CLAUDE_CODE_VERSION, KAI_FX_VERSION
from .web_mcp import ResearchMcp

FRAME_LIMIT = 24 * 1024 * 1024
SAFE_HEADERS = {'accept', 'content-type', 'mcp-session-id', 'mcp-protocol-version', 'last-event-id', 'anthropic-version', 'anthropic-beta'}


SYSTEM_DIRS = ('/usr', '/bin', '/lib', '/lib64')
# The public CA certificates, which a sandbox with an allowlist (network_allow) needs to check the hosts it reaches.
CERT_DIRS = ('/etc/ssl', '/etc/ca-certificates', '/etc/pki')


def filesystem_args(system_dirs: tuple[str, ...] | None = None) -> list[str]:
    """`system_dirs` are the ones that exist on the Linux that runs Bubblewrap; by default, this computer's."""
    argv = ['--unshare-all', '--die-with-parent', '--cap-drop', 'ALL']
    for name in system_dirs if system_dirs is not None else tuple(name for name in SYSTEM_DIRS if Path(name).exists()):
        argv += ['--ro-bind', name, name]
    return argv + ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']


def bridge_argv(helper: Path) -> list[str]:
    """How the macOS and Windows launchers start fx_bridge.py: with this Python from source, or, in the standalone
    CLI (which has no interpreter of its own), as the frozen program's `_bridge` command (frozen_entry)."""
    if getattr(sys, 'frozen', False):
        return [sys.executable, BRIDGE_COMMAND]
    return [sys.executable, str(helper)]


def bwrap_argv(*, system_dirs: tuple[str, ...] | None, relay: str, passwd: str, group: str, root: str, profile: str,
               binary: str, helper: str, git: str | None, git_pointer: str | None, worktree_git_is_dir: bool,
               anthropic: bool, cert_dirs: tuple[str, ...] = (), bwrap: str = 'bwrap') -> list[str]:
    """The Bubblewrap command for one native turn, in the paths of the Linux that runs it. `git` is the private
    metadata folder; a native worktree's .git points outside the worktree, so neither the source checkout nor its
    remotes, hooks or credentials are exposed: the runtime gets its own index. `git_pointer` is a file naming that
    folder, for a worktree whose .git is a file."""
    git_mounts = []
    if git is not None:
        git_mounts = ['--bind', git, '/opt/dotrix/repo.git']
        if worktree_git_is_dir:
            git_mounts += ['--bind', git, f'{root}/.git']
        elif git_pointer is not None:
            git_mounts += ['--ro-bind', git_pointer, f'{root}/.git']
    certs = [arg for name in cert_dirs for arg in ('--ro-bind', name, name)]
    argv = [bwrap, *filesystem_args(system_dirs), *certs, '--ro-bind', relay, '/opt/dotrix/relay.sock',
        '--ro-bind', passwd, '/etc/passwd', '--ro-bind', group, '/etc/group',
        '--bind', root, root, '--bind', profile, profile, *git_mounts,
        '--ro-bind', f'{profile}/auth-source.json', f'{profile}/auth-source.json',
        '--ro-bind', binary, '/opt/dotrix/fx', '--ro-bind', helper, '/opt/dotrix/bridge.py',
        '--remount-ro', '/', '--chdir', root, '--', '/usr/bin/python3', '/opt/dotrix/bridge.py', '/opt/dotrix/relay.sock', profile, '/opt/dotrix/fx']
    return [*argv, 'claude'] if anthropic else argv


def sandbox_env(home: str, port: int | None, network: bool = False) -> dict[str, str]:
    """The environment of the Linux sandbox: no host variables, credentials or proxies."""
    env = {'SHELL': '/bin/bash', 'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': home, 'FX_HOME': f'{home}/.fx',
           'LANG': 'C.UTF-8', 'NO_COLOR': '1', 'FX_AUTO_UPGRADE': '0', 'FX_PROJECT_CONFIG': '0', 'FX_DISABLE_KEYCHAIN': '1',
           'FX_NO_OPEN_BROWSER': '1', 'GIT_CONFIG_SYSTEM': '/dev/null', 'GIT_CONFIG_GLOBAL': '/dev/null', 'DOTRIX_FX_BROKER_KEY': 'dotrix-relay-placeholder'}
    if port:
        env['DOTRIX_BRIDGE_PORT'] = str(port)
    if network:
        env['DOTRIX_NETWORK_TUNNELS'] = '1'
    return env


@functools.lru_cache(maxsize=1)
def _linux_bwrap() -> str | None:
    """The first Bubblewrap (bundled.bwrap_candidates) that makes the sandbox on this machine, or None."""
    if not Path('/usr/bin/python3').is_file() or not Path('/bin/bash').is_file():
        return None
    for binary in bundled.bwrap_candidates():
        try:
            result = subprocess.run([binary, *filesystem_args(), '--', '/bin/true'],
                env={'PATH': '/usr/bin:/bin'}, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return binary
    return None


def _linux_available() -> bool:
    return _linux_bwrap() is not None


@functools.lru_cache(maxsize=1)
def _macos_available() -> bool:
    if not Path('/usr/bin/sandbox-exec').is_file() or not Path('/bin/bash').is_file():
        return False
    try:
        result = subprocess.run(
            ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)', '/usr/bin/true'],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@functools.lru_cache(maxsize=1)
def _windows_available() -> bool:
    return win_sandbox.available()


def fx_available() -> bool:
    """Whether native fx can run here. On Windows it runs in WSL, so this is whether WSL has what it needs."""
    if sys.platform == 'win32':
        return fx_wsl.status().ok
    return available()


def fx_refusal() -> str | None:
    """Why native fx can't run here and how to fix it, for a person, naming only Kai; None when it can. Only Windows
    says how. What the engine itself lacks goes to the worker's log (stderr), never to the person."""
    if sys.platform == 'win32':
        found = fx_wsl.status()
        if found.ok:
            return None
        if found.detail:
            print(f'dotrix: {found.detail}', file=sys.stderr, flush=True)
        return found.message()
    return None


@functools.lru_cache(maxsize=1)
def available() -> bool:
    if sys.platform == 'linux':
        return _linux_available()
    if sys.platform == 'darwin':
        return _macos_available()
    if sys.platform == 'win32':
        return _windows_available()
    return False


def _sbpl_quote(path: Path | str) -> str:
    text = str(path)
    if any(ch in text for ch in ('"', '\\', '\n', '\r', '\0')):
        raise ValueError(f'Path cannot be represented safely in macOS Seatbelt profile: {text!r}')
    return f'"{text}"'


def _parent_git_dir(root: Path) -> Path | None:
    dot_git = root / '.git'
    if not dot_git.is_file():
        return None
    try:
        content = dot_git.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    if not content.startswith('gitdir:'):
        return None
    raw = content.partition(':')[2].strip()
    if not raw:
        return None
    target = (root / raw).resolve()
    # A worktree's gitdir is <repo>/.git/worktrees/<name>; block the whole parent .git dir.
    if target.parent.name == 'worktrees' and target.parent.parent.name == '.git':
        return target.parent.parent
    return target


def macos_sandbox_profile(
    root: Path,
    profile: Path,
    temp_dir: Path,
    relay_sock: Path,
    binary: Path,
    helper: Path,
    python_exe: Path | None = None,
    real_home: Path | None = None,
) -> str:
    """Build a fail-closed macOS Seatbelt (SBPL) profile for a native coding session.

    In SBPL, the last matching rule wins: we deny default, allow system read roots,
    explicitly deny the user's real $HOME and any parent repository .git directory, then
    re-allow read/write strictly on the worktree, private profile, and relay temp dir.
    """
    resolved_root = root.resolve()
    resolved_profile = profile.resolve()
    resolved_temp = temp_dir.resolve()
    resolved_sock = relay_sock.resolve()
    resolved_binary = binary.resolve()
    resolved_helper = helper.resolve()
    resolved_python = (python_exe or Path(sys.executable)).resolve()
    home_dir = (real_home or Path.home()).resolve()

    system_read_roots = [
        '/usr', '/bin', '/sbin', '/Library', '/System', '/private/var/db',
        '/private/etc', '/etc', '/private/preboot', '/dev', '/opt/homebrew', '/usr/local',
    ]
    extra_read_roots = list(dict.fromkeys([
        str(Path(sys.base_prefix).resolve()),
        str(Path(sys.prefix).resolve()),
        str(resolved_python.parent),
        str(resolved_binary.parent),
        str(resolved_helper.parent),
    ]))

    lines = [
        '(version 1)',
        '(deny default)',
        '(allow process-exec process-fork signal sysctl-read mach-lookup)',
        '(allow file-read-metadata file-map-executable)',
        '(allow file-read* (literal "/"))',
    ]
    for entry in system_read_roots:
        lines.append(f'(allow file-read* (subpath {_sbpl_quote(entry)}))')

    # Never expose host credentials or personal config under the user's real home directory.
    lines.append(f'(deny file-read* (subpath {_sbpl_quote(home_dir)}))')

    # Allow the Python runtime, helper, and coding binary even when installed under $HOME (e.g. uv/venv).
    for entry in extra_read_roots:
        lines.append(f'(allow file-read* (subpath {_sbpl_quote(entry)}))')

    # Hide any parent checkout's .git directory referenced by a worktree gitfile.
    parent_git = _parent_git_dir(resolved_root)
    if parent_git is not None:
        lines.append(f'(deny file-read* (subpath {_sbpl_quote(parent_git)}))')

    # Allow read and write strictly inside the worktree, private profile, and relay temp folder.
    for rw in (resolved_root, resolved_profile, resolved_temp):
        q = _sbpl_quote(rw)
        lines.append(f'(allow file-read* (subpath {q}))')
        lines.append(f'(allow file-write* (subpath {q}))')

    lines.extend([
        f'(allow file-read* (literal {_sbpl_quote(resolved_binary)}) (literal {_sbpl_quote(resolved_helper)}))',
        '(allow file-write* (literal "/dev/null") (literal "/dev/tty") (literal "/dev/dtracehelper"))',
        # Network: allow ONLY the private relay Unix socket and loopback HTTP for fx <-> bridge.
        f'(allow network-outbound (remote unix-socket (path-literal {_sbpl_quote(resolved_sock)})))',
        '(allow network-bind (local ip "localhost:*"))',
        '(allow network-inbound (local ip "localhost:*"))',
        '(allow network-outbound (remote ip "localhost:*"))',
    ])
    return '\n'.join(lines) + '\n'


class Relay:
    def __init__(
        self,
        channel: socket.socket | None,
        model_url: str,
        key: str,
        model: str,
        browser: dict | None,
        protocol: str = 'openai',
        *,
        pipe_fds: tuple[int, int] | None = None,
        research: ResearchMcp | None = None,
        network: tuple[network_allow.Rule, ...] = (),
    ):
        self.channel, self.model_url, self.key, self.model, self.browser = channel, model_url, key, model, browser
        self.pipe_fds = pipe_fds
        self.research = research
        # HTTPS tunnels the sandbox's commands opened (network_allow), by request id: what the sandbox sends on each.
        self.network = network
        self.tunnels: dict[int, asyncio.Queue] = {}
        self.lock = asyncio.Lock()
        self.protocol = protocol
        self.work: set[asyncio.Task] = set()

    async def send(self, value):
        encoded = json.dumps(value).encode()
        frame = struct.pack('!I', len(encoded)) + encoded
        async with self.lock:
            if self.pipe_fds is not None:
                _, write_fd = self.pipe_fds
                await asyncio.to_thread(self._write_fd_all, write_fd, frame)
            else:
                await asyncio.get_running_loop().sock_sendall(self.channel, frame)

    @staticmethod
    def _write_fd_all(fd: int, data: bytes) -> None:
        view = memoryview(data)
        total = 0
        while total < len(data):
            written = os.write(fd, view[total:])
            if written <= 0:
                raise OSError('Short write on relay pipe')
            total += written

    @staticmethod
    def _read_fd_exact(fd: int, size: int) -> bytes:
        output = bytearray()
        while len(output) < size:
            chunk = os.read(fd, size - len(output))
            if not chunk:
                raise EOFError()
            output.extend(chunk)
        return bytes(output)

    async def receive(self, size):
        if self.pipe_fds is not None:
            read_fd, _ = self.pipe_fds
            return await asyncio.to_thread(self._read_fd_exact, read_fd, size)
        output = bytearray()
        while len(output) < size:
            data = await asyncio.get_running_loop().sock_recv(self.channel, size - len(output))
            if not data:
                raise EOFError()
            output.extend(data)
        return bytes(output)

    async def run(self):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=20), follow_redirects=False) as client:
                while True:
                    size = struct.unpack('!I', await self.receive(4))[0]
                    if size > FRAME_LIMIT:
                        raise ValueError('Relay frame too large')
                    request = json.loads(await self.receive(size))
                    if request.get('id') in self.tunnels:
                        self.tunnels[request['id']].put_nowait(request)
                        continue
                    if 'path' not in request and 'tunnel' not in request:
                        continue  # what the sandbox still sent on a tunnel that has closed
                    if 'tunnel' in request:
                        if not self.network or len(self.tunnels) >= 32:
                            await self.send({'id': request['id'], 'status': 403, 'end': True})
                            continue
                        self.tunnels[request['id']] = asyncio.Queue()
                        task = asyncio.create_task(self.tunnel(request))
                        self.work.add(task)
                        task.add_done_callback(self.completed)
                        continue
                    if len(self.work) - len(self.tunnels) >= 8:
                        await self.send({'id': request['id'], 'status': 429, 'end': True})
                        continue
                    task = asyncio.create_task(self.forward(client, request))
                    self.work.add(task)
                    task.add_done_callback(self.completed)
        except (EOFError, OSError, ValueError, asyncio.CancelledError):
            pass
        finally:
            for task in list(self.work):
                task.cancel()
            await asyncio.gather(*self.work, return_exceptions=True)

    def completed(self, task):
        self.work.discard(task)
        if not task.cancelled():
            task.exception()  # A disconnected sandbox must not log request contents.

    async def tunnel(self, request):
        """One HTTPS tunnel a sandboxed command asked for, opened only to a host network_allow permits."""
        identity = request['id']
        inbound = self.tunnels[identity]
        writer = None
        try:
            try:
                host, port = network_allow.split_target(str(request['tunnel']))
                reader, writer = await network_allow.connect(self.network, host, port)
            except PermissionError:
                await self.send({'id': identity, 'status': 403})
                return
            except (OSError, ValueError, TimeoutError):
                await self.send({'id': identity, 'status': 502})
                return
            await self.send({'id': identity, 'status': 200})

            async def outward():
                while True:
                    item = await inbound.get()
                    if item.get('data'):
                        writer.write(base64.b64decode(item['data'], validate=True))
                        await writer.drain()
                    if item.get('end'):
                        with contextlib.suppress(OSError):
                            writer.write_eof()
                        return

            sending = asyncio.create_task(outward())
            try:
                while chunk := await reader.read(65536):
                    await self.send({'id': identity, 'data': base64.b64encode(chunk).decode()})
            finally:
                sending.cancel()
                await asyncio.gather(sending, return_exceptions=True)
        except (OSError, ValueError):
            pass
        finally:
            self.tunnels.pop(identity, None)
            if writer is not None:
                writer.close()
            await self.send({'id': identity, 'end': True})

    async def forward(self, client, request):
        identity = request['id']
        started = False
        try:
            body = base64.b64decode(request.get('body', ''), validate=True)
            if len(body) > 16 * 1024 * 1024:
                raise ValueError('Request too large')
            headers = {k: v for k, v in request.get('headers', {}).items() if k.lower() in SAFE_HEADERS}
            if request['path'] == '/research' and self.research is not None:
                status, content = await self.research.request(request['method'], body)
                await self.send({'id': identity, 'status': status, 'headers': {'content-type': 'application/json'}})
                started = True
                if content is not None:
                    data = base64.b64encode(json.dumps(content).encode()).decode()
                    await self.send({'id': identity, 'data': data})
                return
            if self.protocol == 'anthropic' and request['path'] in ('/model/v1/messages', '/model/v1/messages?beta=true',
                    '/model/v1/messages/count_tokens', '/model/v1/messages/count_tokens?beta=true') and request['method'] == 'POST':
                if json.loads(body).get('model') != self.model:
                    raise ValueError('Model changed')
                target = self.model_url.rstrip('/') + request['path'].removeprefix('/model')
                headers['x-api-key'] = self.key
            elif self.protocol == 'openai' and request['path'] == '/model/chat/completions' and request['method'] == 'POST':
                if json.loads(body).get('model') != self.model:
                    raise ValueError('Model changed')
                target = self.model_url.rstrip('/') + '/chat/completions'
                headers['Authorization'] = 'Bearer ' + self.key
            elif request['path'] == '/browser' and self.browser and request['method'] in ('POST', 'GET', 'DELETE'):
                target = self.browser['url']
                headers.update(self.browser['headers'])
            else:
                raise ValueError('Endpoint refused')
            async with client.stream(request['method'], target, content=body, headers=headers) as response:
                await self.send({'id': identity, 'status': response.status_code,
                    'headers': {k: v for k, v in response.headers.items() if k.lower() in SAFE_HEADERS}})
                started = True
                async for chunk in response.aiter_bytes():
                    await self.send({'id': identity, 'data': base64.b64encode(chunk).decode()})
        except (ValueError, KeyError, TypeError, AttributeError, httpx.HTTPError):
            if not started:
                await self.send({'id': identity, 'status': 502})
        finally:
            await self.send({'id': identity, 'end': True})


def connection(profile: Path, environ: dict[str, str]):
    path = profile / '.fx/settings.json'
    settings = json.loads(path.read_text())
    provider = settings.get('provider')
    configured = settings.get('providers', {}).get(provider, {})
    auth = configured.get('auth', {})
    address = urlsplit(configured.get('base_url', ''))
    model = settings.get('models', {}).get(provider)
    key = environ.get(auth.get('env', ''))
    if (configured.get('protocol') != 'openai-chat-completions' or auth.get('type') != 'bearer'
            or not key or not isinstance(model, str) or not model or address.username or address.password
            or address.query or address.fragment or not address.hostname
            or (address.scheme != 'https' and not (address.scheme == 'http' and address.hostname in ('127.0.0.1', 'localhost')))):
        raise ValueError('Native execution requires a custom Chat Completions API-key connection; use cloud coding for other sign-ins')
    target = configured['base_url']
    # The sandbox receives neither other provider settings nor saved OAuth credentials.
    for name in ('auth.json', 'chatgpt-auth.json', 'grok-auth.json', 'api-key'):
        (profile / '.fx' / name).unlink(missing_ok=True)
    settings['providers'] = {provider: {'protocol': 'openai-chat-completions', 'base_url': 'http://127.0.0.1:0/model',
        'auth': {'type': 'bearer', 'env': 'DOTRIX_FX_BROKER_KEY'}, 'model_metadata': {model: {'supports_tool_use': True}}}}
    settings.pop('credential_source', None)
    settings.update(cache_warming=False, session_titles=False, sound=False)
    # API-key-only native sessions cannot refresh a person's OAuth files. Shells
    # can edit the private home, so never trust its credential write-back metadata.
    (profile / 'auth-source.json').write_text(json.dumps({'source': str(profile), 'originals': {}}))
    path.write_text(json.dumps(settings))
    return target, key, model


def _validate_browser(browser: dict | None) -> None:
    if browser:
        url = urlsplit(browser['url'])
        if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password:
            raise ValueError('The desktop browser must use its authenticated loopback connection')


@asynccontextmanager
async def _launch_linux(
    profile: Path, binary: str, root: Path, browser: dict | None,
    target: str, key: str, model: str, expected_version: str, anthropic: bool,
    research: ResearchMcp | None = None, port: int | None = None, network: tuple = (),
):
    temporary = tempfile.TemporaryDirectory(prefix='dotrix-fx-relay-')
    address = str(Path(temporary.name) / 'relay.sock')
    passwd = Path(temporary.name) / 'passwd'
    group = Path(temporary.name) / 'group'
    passwd.write_text(f'dotrix:x:{os.getuid()}:{os.getgid()}:Dotrix:{profile}:/bin/bash\n')
    group.write_text(f'dotrix:x:{os.getgid()}:\n')
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(address)
    os.chmod(address, 0o600)
    listener.listen(1)
    listener.setblocking(False)
    parent = task = None
    helper = Path(__file__).with_name('fx_bridge.py')
    metadata = pointer = None
    if (root / '.git').exists():
        metadata = profile / '.sandbox-git'
        metadata.mkdir(mode=0o700, exist_ok=True)
        if not (root / '.git').is_dir():
            pointer = Path(temporary.name) / 'git-pointer'
            pointer.write_text('gitdir: /opt/dotrix/repo.git\n')
    argv = bwrap_argv(system_dirs=None, relay=address, passwd=str(passwd), group=str(group), root=str(root),
        profile=str(profile), binary=binary, helper=str(helper), git=str(metadata) if metadata else None,
        git_pointer=str(pointer) if pointer else None, worktree_git_is_dir=(root / '.git').is_dir(), anthropic=anthropic,
        cert_dirs=tuple(name for name in CERT_DIRS if Path(name).is_dir()) if network else (),
        bwrap=_linux_bwrap() or 'bwrap')
    env = sandbox_env(str(profile), port, bool(network))
    process = None
    try:
        process = await asyncio.create_subprocess_exec(*argv, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None,
            limit=16 * 1024 * 1024)
        parent, _ = await asyncio.wait_for(asyncio.get_running_loop().sock_accept(listener), 10)
        listener.close()
        parent.setblocking(False)
        relay = Relay(parent, target, key, model, browser, protocol='anthropic' if anthropic else 'openai', research=research,
                      network=network)
        task = asyncio.create_task(relay.run())
        line = await asyncio.wait_for(process.stdout.readline(), 20)
        ready = json.loads(line)
        if not ready.get('bridge_ready') or ready.get('version') != expected_version:
            raise ValueError('The native isolation helper did not start')
        yield process, ready['port']
    finally:
        listener.close()
        if process and process.returncode is None:
            process.kill()
        if process:
            await process.wait()
        if task:
            task.cancel()
        if parent:
            parent.close()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        temporary.cleanup()


@asynccontextmanager
async def _launch_macos(
    profile: Path, binary: str, root: Path, browser: dict | None,
    target: str, key: str, model: str, expected_version: str, anthropic: bool,
    research: ResearchMcp | None = None, port: int | None = None, network: tuple = (),
):
    temporary = tempfile.TemporaryDirectory(prefix='dotrix-fx-relay-')
    temp_path = Path(temporary.name)
    address = temp_path / 'relay.sock'
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(address))
    os.chmod(address, 0o600)
    listener.listen(1)
    listener.setblocking(False)
    parent = task = None
    helper = Path(__file__).with_name('fx_bridge.py').resolve()
    binary_path = Path(binary).resolve()
    sbpl_path = temp_path / 'sandbox.sb'
    sbpl_path.write_text(
        macos_sandbox_profile(root, profile, temp_path, address, binary_path, helper),
        encoding='utf-8',
    )
    env = {
        'SHELL': '/bin/bash',
        'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
        'HOME': str(profile),
        'TMPDIR': str(temp_path),
        'FX_HOME': str(profile / '.fx'),
        'LANG': 'C.UTF-8',
        'NO_COLOR': '1',
        'FX_AUTO_UPGRADE': '0',
        'FX_PROJECT_CONFIG': '0',
        'FX_DISABLE_KEYCHAIN': '1',
        'FX_NO_OPEN_BROWSER': '1',
        'GIT_CONFIG_SYSTEM': '/dev/null',
        'GIT_CONFIG_GLOBAL': '/dev/null',
        'DOTRIX_FX_BROKER_KEY': 'dotrix-relay-placeholder',
    }
    if port:
        env['DOTRIX_BRIDGE_PORT'] = str(port)
    if network:
        env['DOTRIX_NETWORK_TUNNELS'] = '1'
    if (root / '.git').exists():
        metadata = profile / '.sandbox-git'
        metadata.mkdir(mode=0o700, exist_ok=True)
        env['DOTRIX_SANDBOX_GIT_DIR'] = str(metadata)
        env['GIT_DIR'] = str(metadata)
        env['GIT_WORK_TREE'] = str(root.resolve())

    argv = [
        '/usr/bin/sandbox-exec', '-f', str(sbpl_path),
        *bridge_argv(helper), str(address), str(profile), str(binary_path),
    ]
    if anthropic:
        argv.append('claude')
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=str(root), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None,
            limit=16 * 1024 * 1024,
        )
        parent, _ = await asyncio.wait_for(asyncio.get_running_loop().sock_accept(listener), 10)
        listener.close()
        parent.setblocking(False)
        relay = Relay(parent, target, key, model, browser, protocol='anthropic' if anthropic else 'openai', research=research,
                      network=network)
        task = asyncio.create_task(relay.run())
        line = await asyncio.wait_for(process.stdout.readline(), 20)
        ready = json.loads(line)
        if not ready.get('bridge_ready') or ready.get('version') != expected_version:
            raise ValueError('The native isolation helper did not start')
        yield process, ready['port']
    finally:
        listener.close()
        if process and process.returncode is None:
            process.kill()
        if process:
            await process.wait()
        if task:
            task.cancel()
        if parent:
            parent.close()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        temporary.cleanup()


@asynccontextmanager
async def _launch_windows(
    profile: Path, binary: str, root: Path, browser: dict | None,
    target: str, key: str, model: str, expected_version: str, anthropic: bool,
    research: ResearchMcp | None = None, port: int | None = None, network: tuple = (),
):
    temporary = tempfile.TemporaryDirectory(prefix='dotrix-fx-relay-')
    temp_path = Path(temporary.name)
    helper = Path(__file__).with_name('fx_bridge.py').resolve()
    binary_path = Path(binary).resolve()
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    env = {
        'SystemRoot': system_root,
        'COMSPEC': os.environ.get('COMSPEC', os.path.join(system_root, 'System32', 'cmd.exe')),
        'PATH': f"{Path(sys.executable).resolve().parent};{os.path.join(system_root, 'System32')};{system_root}",
        'HOME': str(profile),
        'USERPROFILE': str(profile),
        'TEMP': str(temp_path),
        'TMP': str(temp_path),
        'FX_HOME': str(profile / '.fx'),
        'NO_COLOR': '1',
        'FX_AUTO_UPGRADE': '0',
        'FX_PROJECT_CONFIG': '0',
        'FX_DISABLE_KEYCHAIN': '1',
        'FX_NO_OPEN_BROWSER': '1',
        'GIT_CONFIG_SYSTEM': os.devnull,
        'GIT_CONFIG_GLOBAL': os.devnull,
        'DOTRIX_FX_BROKER_KEY': 'dotrix-relay-placeholder',
    }
    if port:
        env['DOTRIX_BRIDGE_PORT'] = str(port)
    if network:
        env['DOTRIX_NETWORK_TUNNELS'] = '1'
    if (root / '.git').exists():
        metadata = profile / '.sandbox-git'
        metadata.mkdir(exist_ok=True)
        env['DOTRIX_SANDBOX_GIT_DIR'] = str(metadata)
        env['GIT_DIR'] = str(metadata)
        env['GIT_WORK_TREE'] = str(root.resolve())

    process = None
    task = None
    try:
        process = win_sandbox.launch_appcontainer(
            python_exe=sys.executable,
            helper=helper,
            bridge=bridge_argv(helper),
            profile=profile,
            binary=binary_path,
            root=root,
            temp_dir=temp_path,
            env=env,
            extra_args=['claude'] if anthropic else None,
        )
        relay = Relay(
            None, target, key, model, browser,
            protocol='anthropic' if anthropic else 'openai',
            pipe_fds=(process.relay_read_fd, process.relay_write_fd), research=research, network=network,
        )
        task = asyncio.create_task(relay.run())
        line = await asyncio.wait_for(process.stdout.readline(), 20)
        ready = json.loads(line)
        if not ready.get('bridge_ready') or ready.get('version') != expected_version:
            raise ValueError('The native isolation helper did not start')
        yield process, ready['port']
    finally:
        if process and process.returncode is None:
            process.kill()
        if process:
            await process.wait()
        if task:
            task.cancel()
        if process:
            process.cleanup()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        temporary.cleanup()


@asynccontextmanager
async def launch(profile: Path, binary: str, root: Path, browser: dict | None, *, anthropic: tuple[str, str, str] | None = None,
                 research_enabled: bool = False, port: int | None = None):
    """Start the sandboxed helper. Yields the process, the bridge's port, and the worktree's path as the engine sees
    it (in WSL, its `/mnt/...` path). `port` asks its local bridge for the port an earlier turn used, so a resumed
    session's connection is unchanged (fx refuses a resume when its base_url differs). On Windows, fx runs in WSL
    (fx_wsl) and `binary` is unused: the distribution's own fx runs."""
    wsl = sys.platform == 'win32' and not anthropic
    if not (fx_available() if not anthropic else available()):
        raise ValueError(fx_refusal() if wsl else (
            'Native isolation is unavailable: Linux Bubblewrap, macOS Seatbelt (sandbox-exec), '
            'or Windows AppContainer is required'
        ))
    target, key, model = anthropic if anthropic else connection(profile, dict(os.environ))
    expected_version = CLAUDE_CODE_VERSION if anthropic else KAI_FX_VERSION
    _validate_browser(browser)
    # Hosts the sandbox's commands may reach through the relay; none unless the person lists them (network_allow).
    network = network_allow.from_environment()
    endpoint = os.environ.get("DOTRIX_SEARXNG_URL") if os.environ.get("DOTRIX_SEARCH_PROVIDER", "auto") in ("auto", "searxng") else None
    if wsl:
        research = ResearchMcp(endpoint) if research_enabled else None
        try:
            async with fx_wsl.launch(profile, root, browser, target, key, model, expected_version, research, port=port,
                                     network=network) as result:
                yield result
        finally:
            if research is not None:
                await research.aclose()
        return
    if sys.platform == 'linux':
        launcher = _launch_linux
    elif sys.platform == 'darwin':
        launcher = _launch_macos
    elif sys.platform == 'win32':
        launcher = _launch_windows
    else:
        raise ValueError('Native isolation is unavailable on this operating system')
    research = ResearchMcp(endpoint) if research_enabled else None
    try:
        async with launcher(profile, binary, root, browser, target, key, model, expected_version, bool(anthropic), research, port=port,
                            network=network) as (process, bridge_port):
            yield process, bridge_port, str(root)
    finally:
        if research is not None:
            await research.aclose()
