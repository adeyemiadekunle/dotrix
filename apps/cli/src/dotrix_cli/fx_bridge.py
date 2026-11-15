"""Inside the native namespace: relay two fixed HTTP services through a private Unix socket.

Standard library only: this file is mounted read-only and run with the system Python.
The engine never inherits the relay descriptor or the host's provider/browser credentials.
"""
import base64
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


def frame_read(sock):
    def read(size):
        data = bytearray()
        while len(data) < size:
            part = sock.recv(size - len(data))
            if not part:
                raise EOFError()
            data.extend(part)
        return bytes(data)
    size = struct.unpack('!I', read(4))[0]
    if size > LIMIT:
        raise ValueError('Relay frame too large')
    return json.loads(read(size))


def main():
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    channel.connect(sys.argv[1])
    profile, binary = sys.argv[2:4]
    claude = len(sys.argv) > 4 and sys.argv[4] == 'claude'
    pending, lock, sequence = {}, threading.Lock(), 0

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
                    channel.sendall(struct.pack('!I', len(request)) + request)
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

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 31820), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
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
    if os.path.isdir('/opt/dotrix/repo.git'):
        root = os.getcwd()
        def git(*args):
            subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *args], check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        git('init', '--bare', '--template=', '/opt/dotrix/repo.git')
        git('--git-dir=/opt/dotrix/repo.git', 'config', 'core.bare', 'false')
        git('--git-dir=/opt/dotrix/repo.git', 'config', 'core.worktree', root)
        git('--git-dir=/opt/dotrix/repo.git', 'add', '-A')
        git('--git-dir=/opt/dotrix/repo.git', '-c', 'user.name=Dotrix', '-c', 'user.email=dotrix@localhost',
            'commit', '--allow-empty', '--no-verify', '-qm', 'Sandbox baseline')
    version = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=15, check=True).stdout.strip()
    expected = '2.1.296' if claude else '0.0.17'
    if version.split()[0] != expected:
        raise ValueError('Native execution requires the tested coding runtime')
    print(json.dumps({'bridge_ready': True, 'port': server.server_port, 'version': expected}), flush=True)
    # Do not pass the relay descriptor to fx. Namespace PID 1 exiting kills leftover commands.
    raise SystemExit(subprocess.call([binary, *configured['argv']] if claude else [binary, 'acp'], close_fds=True))


if __name__ == '__main__':
    main()
