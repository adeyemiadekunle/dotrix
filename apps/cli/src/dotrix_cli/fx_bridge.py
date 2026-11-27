"""Inside the native sandbox: relay two fixed HTTP services through a private host channel.

Standard library only: this file is run with Python inside the OS sandbox (Linux Bubblewrap,
macOS Seatbelt, or Windows AppContainer). The engine never inherits the relay descriptor or
the host's provider/browser credentials.
"""
import base64
import contextlib
import http.server
import json
import os
import queue
import socket
import struct
import subprocess
import sys
import threading

LIMIT = 24 * 1024 * 1024
# The engine versions native execution runs, exactly as each one's `--version` prints them. The Kai runtime's fx
# reports its whole release (`0.0.18-kai.2`), so one Kai release can't stand in for another. fx_native reads these.
KAI_FX_VERSION = '0.0.18-kai.2'
CLAUDE_CODE_VERSION = '2.1.296'


class _SocketChannel:
    def __init__(self, sock):
        self._sock = sock

    def read_exact(self, size):
        data = bytearray()
        while len(data) < size:
            part = self._sock.recv(size - len(data))
            if not part:
                raise EOFError()
            data.extend(part)
        return bytes(data)

    def write_all(self, data):
        self._sock.sendall(data)

    def close(self):
        self._sock.close()


class _PipeChannel:
    def __init__(self, read_fd, write_fd):
        self._read_fd = read_fd
        self._write_fd = write_fd

    def read_exact(self, size):
        data = bytearray()
        while len(data) < size:
            part = os.read(self._read_fd, size - len(data))
            if not part:
                raise EOFError()
            data.extend(part)
        return bytes(data)

    def write_all(self, data):
        view = memoryview(data)
        total = 0
        while total < len(data):
            written = os.write(self._write_fd, view[total:])
            if written <= 0:
                raise OSError('Short write on relay pipe')
            total += written

    def close(self):
        for fd in (self._read_fd, self._write_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def _open_channel(spec):
    if spec.startswith('--pipe-fds='):
        read_raw, write_raw = spec.split('=', 1)[1].split(':', 1)
        read_val, write_val = int(read_raw), int(write_raw)
        if os.name == 'nt':
            import msvcrt
            read_fd = msvcrt.open_osfhandle(read_val, os.O_RDONLY)
            write_fd = msvcrt.open_osfhandle(write_val, os.O_WRONLY)
            return _PipeChannel(read_fd, write_fd)
        return _PipeChannel(read_val, write_val)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(spec)
    return _SocketChannel(sock)


def frame_read(channel):
    header = channel.read_exact(4)
    size = struct.unpack('!I', header)[0]
    if size > LIMIT:
        raise ValueError('Relay frame too large')
    return json.loads(channel.read_exact(size))


def require_kai_fx(binary):
    """Refuse an fx without the Kai runtime's `project_config` off. Upstream fx has no such setting, so it
    would read the repository's .fx.json, skills, .mcp.json and AGENTS.md; here the profile and
    FX_PROJECT_CONFIG=0 turn it off. This holds even for an fx whose version was made to read as Kai's."""
    setting = subprocess.run([binary, 'config', 'get', 'project_config'], capture_output=True, text=True, timeout=15)
    if setting.returncode != 0 or setting.stdout.strip() != 'false':
        raise ValueError("Native execution requires the Kai runtime's fx, which can ignore a repository's configuration")


def main():
    channel = _open_channel(sys.argv[1])
    profile, binary = sys.argv[2:4]
    claude = len(sys.argv) > 4 and sys.argv[4] == 'claude'
    pending, lock, sequence = {}, threading.Lock(), 0
    # The host lists hosts commands may reach (network_allow); without one, CONNECT is refused here too.
    tunnels = os.environ.pop('DOTRIX_NETWORK_TUNNELS', '') == '1'

    def reader():
        try:
            while True:
                value = frame_read(channel)
                with lock:
                    target = pending.get(value.get('id'))
                if target is not None:
                    target.put(value)
        except (EOFError, OSError, ValueError):
            with lock:
                for target in pending.values():
                    target.put({'end': True})

    threading.Thread(target=reader, daemon=True).start()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def handle_request(self):
            nonlocal sequence
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= 16 * 1024 * 1024:
                    self.send_error(413)
                    return
                body = self.rfile.read(size)
                with lock:
                    if len(pending) >= 8:
                        self.send_error(429)
                        return
                    sequence += 1
                    identity = sequence
                    result = queue.Queue(maxsize=16)
                    pending[identity] = result
                    request = json.dumps({'id': identity, 'path': self.path, 'method': self.command,
                        'headers': dict(self.headers), 'body': base64.b64encode(body).decode()}).encode()
                    channel.write_all(struct.pack('!I', len(request)) + request)
                started = False
                while True:
                    event = result.get(timeout=180)
                    if 'status' in event:
                        self.send_response(event['status'])
                        for key, value in event.get('headers', {}).items():
                            self.send_header(key, value)
                        self.send_header('Connection', 'close')
                        self.end_headers()
                        started = True
                    if event.get('data'):
                        self.wfile.write(base64.b64decode(event['data']))
                        self.wfile.flush()
                    if event.get('end'):
                        break
                if not started:
                    self.send_error(502)
            except (OSError, ValueError, queue.Empty):
                self.close_connection = True
            finally:
                with lock:
                    if 'identity' in locals():
                        pending.pop(identity, None)
                self.close_connection = True

        do_POST = do_GET = do_DELETE = handle_request

        def do_CONNECT(self):
            """An HTTPS tunnel for a command, which the host opens only to a host on its allowlist."""
            nonlocal sequence
            if not tunnels:
                self.send_error(403, 'This sandbox has no network')
                return
            with lock:
                if len(pending) >= 40:
                    self.send_error(429)
                    return
                sequence += 1
                identity = sequence
                result = queue.Queue(maxsize=64)
                pending[identity] = result
                request = json.dumps({'id': identity, 'tunnel': self.path}).encode()
                channel.write_all(struct.pack('!I', len(request)) + request)
            sock = self.connection
            try:
                opened = result.get(timeout=30)
                if opened.get('status') != 200:
                    self.send_error(403 if opened.get('status') == 403 else 502,
                                    'Dotrix allows only the hosts in DOTRIX_CODING_NETWORK_ALLOW')
                    return
                self.send_response(200, 'Connection Established')
                self.end_headers()
                self.wfile.flush()

                def outward():
                    try:
                        while data := sock.recv(65536):
                            frame = json.dumps({'id': identity, 'data': base64.b64encode(data).decode()}).encode()
                            with lock:
                                channel.write_all(struct.pack('!I', len(frame)) + frame)
                    except OSError:
                        pass
                    finally:
                        frame = json.dumps({'id': identity, 'end': True}).encode()
                        with lock, contextlib.suppress(OSError):
                            channel.write_all(struct.pack('!I', len(frame)) + frame)

                threading.Thread(target=outward, daemon=True).start()
                while True:
                    event = result.get(timeout=600)
                    if event.get('data'):
                        sock.sendall(base64.b64decode(event['data']))
                    if event.get('end'):
                        break
            except (OSError, ValueError, queue.Empty):
                pass
            finally:
                with lock:
                    pending.pop(identity, None)
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)
                self.close_connection = True

    # fx refuses to resume a session whose connection's base_url changed, so a later turn asks for the port the
    # session started on (DOTRIX_BRIDGE_PORT). Linux gives every sandbox its own network, so the port is free there;
    # elsewhere a taken port falls back to a new one and that turn starts a fresh session.
    requested = os.environ.pop('DOTRIX_BRIDGE_PORT', '')
    port = int(requested) if requested.isdigit() and 1024 <= int(requested) <= 65535 else 0

    class Server(http.server.ThreadingHTTPServer):
        # On Windows, SO_REUSEADDR lets a bind share a port another program listens on; a requested port must fail.
        allow_reuse_address = os.name != 'nt'

    try:
        server = Server(('127.0.0.1', port), Handler)
    except OSError:
        server = Server(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if tunnels:
        # Commands find the allowlist's tunnels as an ordinary HTTPS proxy; the bridge's own address stays direct.
        proxy = f'http://127.0.0.1:{server.server_port}'
        for name in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy'):
            os.environ[name] = proxy
        os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost'
    if not claude:
        path = os.path.join(profile, '.fx', 'settings.json')
        with open(path) as stream:
            settings = json.load(stream)
        provider = settings['provider']
        settings['providers'][provider]['base_url'] = f'http://127.0.0.1:{server.server_port}/model'
        with open(path, 'w') as stream:
            json.dump(settings, stream)
    else:
        with open(os.path.join(profile, 'command.json')) as stream:
            configured = json.load(stream)
        os.environ.update(ANTHROPIC_BASE_URL=f'http://127.0.0.1:{server.server_port}/model',
            ANTHROPIC_API_KEY='dotrix-relay-placeholder', ANTHROPIC_MODEL=configured['model'],
            CLAUDE_CONFIG_DIR=os.path.join(profile, '.claude'), DISABLE_AUTOUPDATER='1',
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', CLAUDE_CODE_DISABLE_CLAUDE_MDS='1')
    git_dir = os.environ.get('DOTRIX_SANDBOX_GIT_DIR') or '/opt/dotrix/repo.git'
    if os.path.isdir(git_dir):
        root = os.getcwd()
        def git(*args):
            subprocess.run(['git', '-c', f'core.hooksPath={os.devnull}', *args], check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        git('init', '--bare', '--template=', git_dir)
        git(f'--git-dir={git_dir}', 'config', 'core.bare', 'false')
        git(f'--git-dir={git_dir}', 'config', 'core.worktree', root)
        git(f'--git-dir={git_dir}', 'add', '-A')
        git(f'--git-dir={git_dir}', '-c', 'user.name=Dotrix', '-c', 'user.email=dotrix@localhost',
            'commit', '--allow-empty', '--no-verify', '-qm', 'Sandbox baseline')
    version = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=15, check=True).stdout.strip()
    expected = CLAUDE_CODE_VERSION if claude else KAI_FX_VERSION
    if version.split()[0] != expected:
        name = 'Claude Code' if claude else "the Kai runtime's fx"
        raise ValueError(f'Native execution requires {name} {expected}, not {version.split()[0] if version else "an unknown version"}')
    if not claude:
        require_kai_fx(binary)
    print(json.dumps({'bridge_ready': True, 'port': server.server_port, 'version': expected}), flush=True)
    # Do not pass the relay descriptor to fx. Exiting kills leftover commands via the OS sandbox boundary.
    raise SystemExit(subprocess.call([binary, *configured['argv']] if claude else [binary, 'acp'], close_fds=True))


if __name__ == '__main__':
    main()
