"""Shared Linux process boundary for fx and Claude Code. The host owns model/browser access.

No broad proxy, host filesystem mount, credential-bearing engine environment, or
unconfined fallback. Other operating systems remain unavailable.
"""
from __future__ import annotations

import asyncio
import base64
import functools
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx

FRAME_LIMIT = 24 * 1024 * 1024
SAFE_HEADERS = {'accept', 'content-type', 'mcp-session-id', 'mcp-protocol-version', 'last-event-id', 'anthropic-version', 'anthropic-beta'}


def filesystem_args() -> list[str]:
    argv = ['--unshare-all', '--die-with-parent', '--cap-drop', 'ALL']
    for name in ('/usr', '/bin', '/lib', '/lib64'):
        if Path(name).exists():
            argv += ['--ro-bind', name, name]
    return argv + ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']


@functools.lru_cache(maxsize=1)
def available() -> bool:
    if sys.platform != 'linux' or not shutil.which('bwrap') or (not Path('/usr/bin/python3').is_file() or not Path('/bin/bash').is_file()):
        return False
    try:
        result = subprocess.run(['bwrap', *filesystem_args(), '--', '/bin/true'],
            env={'PATH': '/usr/bin:/bin'}, capture_output=True, timeout=10)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Relay:
    def __init__(self, channel: socket.socket, model_url: str, key: str, model: str, browser: dict | None, protocol: str = 'openai'):
        self.channel, self.model_url, self.key, self.model, self.browser = channel, model_url, key, model, browser
        self.lock = asyncio.Lock()
        self.protocol = protocol
        self.work: set[asyncio.Task] = set()

    async def send(self, value):
        encoded = json.dumps(value).encode()
        async with self.lock:
            await asyncio.get_running_loop().sock_sendall(self.channel, struct.pack('!I', len(encoded)) + encoded)

    async def receive(self, size):
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
                    if len(self.work) >= 8:
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
            task.exception()  # A disconnected namespace must not log request contents.

    async def forward(self, client, request):
        identity = request['id']
        started = False
        try:
            body = base64.b64decode(request.get('body', ''), validate=True)
            if len(body) > 16 * 1024 * 1024:
                raise ValueError('Request too large')
            headers = {k: v for k, v in request.get('headers', {}).items() if k.lower() in SAFE_HEADERS}
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
    # The namespace receives neither other provider settings nor saved OAuth credentials.
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


@asynccontextmanager
async def launch(profile: Path, binary: str, root: Path, browser: dict | None, *, anthropic: tuple[str, str, str] | None = None):
    if not available():
        raise ValueError('Native isolation is unavailable: Linux Bubblewrap with working user/network namespaces is required')
    target, key, model = anthropic if anthropic else connection(profile, dict(os.environ))
    expected_version = '2.1.296' if anthropic else '0.0.17'
    if browser:
        url = urlsplit(browser['url'])
        if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password:
            raise ValueError('The desktop browser must use its authenticated loopback connection')
    temporary = tempfile.TemporaryDirectory(prefix="dotrix-fx-relay-")
    address = str(Path(temporary.name) / "relay.sock")
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
    git_mounts = []
    if (root / '.git').exists():
        # A native worktree's .git points outside the worktree. Do not expose the
        # source checkout, remotes, hooks or credentials; give the runtime its own index.
        metadata = profile / '.sandbox-git'
        metadata.mkdir(mode=0o700, exist_ok=True)
        git_mounts = ['--bind', str(metadata), '/opt/dotrix/repo.git']
        if (root / '.git').is_dir():
            git_mounts += ['--bind', str(metadata), str(root / '.git')]
        else:
            pointer = Path(temporary.name) / 'git-pointer'
            pointer.write_text('gitdir: /opt/dotrix/repo.git\n')
            git_mounts += ['--ro-bind', str(pointer), str(root / '.git')]

    argv = ['bwrap', *filesystem_args(), '--ro-bind', address, '/opt/dotrix/relay.sock',
        '--ro-bind', str(passwd), '/etc/passwd', '--ro-bind', str(group), '/etc/group',
        '--bind', str(root), str(root), '--bind', str(profile), str(profile), *git_mounts,
        '--ro-bind', str(profile / 'auth-source.json'), str(profile / 'auth-source.json'),
        '--ro-bind', binary, '/opt/dotrix/fx', '--ro-bind', str(helper), '/opt/dotrix/bridge.py',
        '--remount-ro', '/', '--chdir', str(root), '--', '/usr/bin/python3', '/opt/dotrix/bridge.py', '/opt/dotrix/relay.sock', str(profile), '/opt/dotrix/fx']
    if anthropic:
        argv.append('claude')
    env = {'SHELL': '/bin/bash', 'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(profile), 'FX_HOME': str(profile / '.fx'),
           'LANG': 'C.UTF-8', 'NO_COLOR': '1', 'FX_AUTO_UPGRADE': '0', 'FX_DISABLE_KEYCHAIN': '1',
           'FX_NO_OPEN_BROWSER': '1', 'GIT_CONFIG_SYSTEM': '/dev/null', 'GIT_CONFIG_GLOBAL': '/dev/null', 'DOTRIX_FX_BROKER_KEY': 'dotrix-relay-placeholder'}
    process = None
    try:
        process = await asyncio.create_subprocess_exec(*argv, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None,
            limit=16 * 1024 * 1024)
        parent, _ = await asyncio.wait_for(asyncio.get_running_loop().sock_accept(listener), 10)
        listener.close()
        parent.setblocking(False)
        relay = Relay(parent, target, key, model, browser, protocol='anthropic' if anthropic else 'openai')
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
