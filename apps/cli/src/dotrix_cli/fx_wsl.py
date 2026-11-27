"""Kai's fx on Windows: the Linux fx, in the same Bubblewrap sandbox as on Linux, inside a WSL 2 distribution.

fx has no Windows build, so a Windows runner reaches the Linux one through `wsl.exe`. Each turn:

- The private profile, `fx_bridge.py` and a relay pump are staged in a private folder on the distribution's own
  filesystem. fx ignores a settings file that others can write, and a Windows drive mounted in WSL reports every
  file as writable by all.
- The worktree stays on the Windows drive, seen from WSL at its `/mnt/<drive>/...` path, and is bound into the
  sandbox there.
- The sandbox's model/browser relay socket is carried to this host's `Relay` over a second `wsl.exe` process's
  pipes, so credentials stay on Windows, as they stay on the host on Linux.
- When the turn ends, the profile is copied back, apart from the files the host owns, and the folder is removed.

`status()` says what is missing and how to install it, for the runner to show.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .fx_bridge import KAI_FX_VERSION

DISTRO_ENV = 'DOTRIX_WSL_DISTRO'
# Files in the profile that the host writes and trusts; a turn's copy never replaces them.
HOST_OWNED = ('.fx/dotrix-session.json', 'auth-source.json')
COPY_BACK_LIMIT = 512 * 1024 * 1024
INSTALL_WSL = 'Open PowerShell as administrator, run `wsl --install`, and restart Windows.'

# Runs in the distribution, with its own python3, outside the sandbox: listens on the relay socket the sandbox
# connects to, says it is ready with one byte, then copies between that connection and its stdin/stdout.
PUMP = r'''
import os, socket, sys, threading
path = sys.argv[1]
listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
listener.bind(path)
os.chmod(path, 0o600)
listener.listen(1)
os.write(1, b"R")
listener.settimeout(60)
connection, _ = listener.accept()
listener.close()
connection.settimeout(None)
def inward():
    try:
        while True:
            data = os.read(0, 65536)
            if not data:
                break
            connection.sendall(data)
    except OSError:
        pass
    try:
        connection.shutdown(socket.SHUT_WR)
    except OSError:
        pass
threading.Thread(target=inward, daemon=True).start()
while True:
    data = connection.recv(65536)
    if not data:
        break
    view = memoryview(data)
    while view:
        view = view[os.write(1, view):]
'''

# Runs in the distribution: what native fx needs there, as JSON.
PROBE = r'''
found() { command -v "$1" >/dev/null 2>&1; }
missing=""
for name in python3 git bwrap; do found "$name" || missing="$missing $name"; done
[ -x /usr/bin/python3 ] || missing="$missing python3"
[ -x /bin/bash ] || missing="$missing bash"
namespaces=false
if found bwrap && bwrap --unshare-all --die-with-parent --ro-bind / / /bin/true 2>/dev/null; then namespaces=true; fi
fx="${DOTRIX_WSL_FX:-$(bash -lc 'command -v fx' 2>/dev/null)}"
[ -n "$fx" ] && fx="$(readlink -f "$fx" 2>/dev/null || echo "$fx")"
version=""
[ -n "$fx" ] && [ -x "$fx" ] && version="$("$fx" --version 2>/dev/null | head -n 1 | cut -d ' ' -f 1)"
dirs=""
for name in /usr /bin /lib /lib64; do [ -e "$name" ] && dirs="$dirs $name"; done
certs=""
for name in /etc/ssl /etc/ca-certificates /etc/pki; do [ -d "$name" ] && certs="$certs $name"; done
printf '{"missing":"%s","namespaces":%s,"fx":"%s","version":"%s","dirs":"%s","certs":"%s"}\n' "$missing" "$namespaces" "$fx" "$version" "$dirs" "$certs"
'''


@dataclass(frozen=True)
class Status:
    """Whether native fx can run here through WSL. When it can't, `problem` says what is missing and `fix` how to
    install it, in words for a person."""
    distro: str | None = None
    fx: str | None = None
    system_dirs: tuple[str, ...] = ()
    cert_dirs: tuple[str, ...] = ()
    problem: str | None = None
    fix: str | None = None

    @property
    def ok(self) -> bool:
        return self.problem is None

    def message(self) -> str:
        return f'{self.problem} {self.fix}' if self.fix else str(self.problem)


def _wsl_exe() -> str | None:
    found = shutil.which('wsl.exe') or shutil.which('wsl')
    if found:
        return found
    system = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'wsl.exe'
    return str(system) if system.is_file() else None


def _run(args: list[str], *, input: bytes | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    exe = _wsl_exe()
    if exe is None:
        raise FileNotFoundError('wsl.exe')
    return subprocess.run([exe, *args], input=input, capture_output=True, timeout=timeout,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def _text(raw: bytes) -> str:
    """wsl.exe writes its own messages in UTF-16."""
    if raw[:2] in (b'\xff\xfe',) or (len(raw) > 1 and raw[1:2] == b'\x00'):
        return raw.decode('utf-16-le', errors='replace').replace('\x00', '')
    return raw.decode('utf-8', errors='replace')


def distributions() -> list[tuple[str, int, bool]]:
    """(name, WSL version, whether it is the default) for each installed distribution; empty when WSL is not
    installed or has none."""
    try:
        listed = _run(['--list', '--verbose'], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if listed.returncode != 0:
        return []
    found = []
    for line in _text(listed.stdout).splitlines()[1:]:
        default = line.lstrip().startswith('*')
        parts = line.replace('*', ' ').split()
        if len(parts) >= 3 and parts[-1].isdigit():
            found.append((' '.join(parts[:-2]), int(parts[-1]), default))
    return found


_ready: Status | None = None


def status() -> Status:
    """What native fx needs through WSL, checked each call until it is all there (so installing WSL or a package
    takes effect on the next turn) and then kept."""
    global _ready
    if _ready is not None:
        return _ready
    found = _status()
    if found.ok:
        _ready = found
    return found


def _status() -> Status:
    if _wsl_exe() is None:
        return Status(problem="Kai's local coding on Windows runs in WSL, which isn't installed.", fix=INSTALL_WSL)
    distros = [item for item in distributions() if not item[0].lower().startswith('docker-desktop')]
    if not distros:
        return Status(problem="Kai's local coding on Windows runs in WSL, which has no Linux distribution yet.",
                      fix='Run `wsl --install -d Ubuntu` in PowerShell, then open Ubuntu once to finish its setup.')
    wanted = os.environ.get(DISTRO_ENV)
    chosen = next((item for item in distros if item[0] == wanted), None) if wanted else (
        next((item for item in distros if item[2]), None) or distros[0])
    if chosen is None:
        return Status(problem=f'The WSL distribution {wanted!r} set in {DISTRO_ENV} is not installed.',
                      fix='Run `wsl --list --verbose` to see the installed ones.')
    name, version, _ = chosen
    if version != 2:
        return Status(distro=name, problem=f'{name} runs on WSL 1, which has no Linux namespaces for the sandbox.',
                      fix=f'Run `wsl --set-version {name} 2` in PowerShell.')
    try:
        # wsl.exe passes no Windows variables, so a chosen fx (its path in the distribution) is given explicitly.
        chosen_fx = [f'DOTRIX_WSL_FX={os.environ["DOTRIX_WSL_FX"]}'] if os.environ.get('DOTRIX_WSL_FX') else []
        probed = _run(['--distribution', name, '--exec', '/usr/bin/env', *chosen_fx, '/bin/sh', '-c', PROBE], timeout=90)
        facts = json.loads(probed.stdout.decode('utf-8', errors='replace').strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return Status(distro=name, problem=f"Couldn't start the WSL distribution {name}.",
                      fix=f'Open {name} once from the Start menu to finish its setup, then try again.')
    missing = sorted(set(facts.get('missing', '').split()))
    if missing:
        packages = ' '.join('bubblewrap' if item == 'bwrap' else item for item in missing)
        return Status(distro=name, problem=f'{name} is missing {", ".join(missing)}, which the sandbox needs.',
                      fix=f'In {name}, run `sudo apt install {packages}`.')
    if not facts.get('namespaces'):
        return Status(distro=name, problem=f"Bubblewrap can't create Linux namespaces in {name}.",
                      fix='Update WSL with `wsl --update`, then restart it with `wsl --shutdown`.')
    if not facts.get('fx') or facts.get('version') != KAI_FX_VERSION:
        have = f' (it has {facts["version"]})' if facts.get('version') else ''
        return Status(distro=name, problem=f"{name} doesn't have the Kai runtime's fx {KAI_FX_VERSION}{have}.",
                      fix=f"Install the Kai runtime's fx {KAI_FX_VERSION} for Linux in {name}, on its PATH.")
    return Status(distro=name, fx=facts['fx'], system_dirs=tuple(facts.get('dirs', '').split()),
                  cert_dirs=tuple(facts.get('certs', '').split()))


def _tar(files: dict[str, bytes], profile: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o600
            archive.addfile(info, io.BytesIO(data))

        def private(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
            if info.issym() or info.islnk():
                return None
            info.mode = 0o700 if info.isdir() else 0o600
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            return info

        archive.add(str(profile), arcname='profile', filter=private)
    return buffer.getvalue()


def copy_back(archive: bytes, profile: Path) -> None:
    """Writes the turn's profile over the host's, except the files the host owns. Only regular files and folders
    inside the profile are taken."""
    if len(archive) > COPY_BACK_LIMIT:
        raise ValueError('The local profile grew too large to keep')
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r') as source:
        members = []
        for member in source.getmembers():
            name = PurePosixPath(member.name)
            relative = PurePosixPath(*name.parts[1:]) if name.parts[:1] == ('.',) else name
            if (not (member.isfile() or member.isdir()) or relative.is_absolute() or '..' in relative.parts
                    or str(relative) in HOST_OWNED or str(relative) == '.'):
                continue
            member.name = str(relative)
            members.append(member)
        source.extractall(profile, members=members, filter='data')


@asynccontextmanager
async def launch(profile: Path, root: Path, browser: dict | None, target: str, key: str, model: str,
                 expected_version: str, research=None, port: int | None = None, network: tuple = ()):
    """Starts the bridge in Bubblewrap in WSL. Yields the process, the bridge's port, and the worktree's path in WSL,
    which is the path fx names files by."""
    from .fx_native import Relay, bwrap_argv, sandbox_env

    found = status()
    if not found.ok or found.distro is None or found.fx is None:
        raise ValueError(found.message())
    distro = found.distro
    stage_files = {
        'bridge.py': Path(__file__).with_name('fx_bridge.py').read_bytes(),
        'pump.py': PUMP.encode(),
        'git-pointer': b'gitdir: /opt/dotrix/repo.git\n',
    }
    stage = await asyncio.to_thread(_run, [
        '--distribution', distro, '--exec', '/bin/sh', '-c',
        'set -e; umask 077; t="$(mktemp -d /tmp/dotrix-fx-XXXXXXXX)"; tar -x -C "$t" --no-same-owner; '
        'mkdir -p "$t/profile/.sandbox-git"; u="$(id -u)"; g="$(id -g)"; '
        'printf "dotrix:x:%s:%s:Dotrix:%s:/bin/bash\\n" "$u" "$g" "$t/profile" > "$t/passwd"; '
        'printf "dotrix:x:%s:\\n" "$g" > "$t/group"; r="$(wslpath -a -u "$1")"; '
        'test -d "$r" || { echo "unreachable"; exit 3; }; printf "%s\\n%s\\n" "$t" "$r"',
        'sh', str(root.resolve()),
    ], input=_tar(stage_files, profile), timeout=120)
    lines = stage.stdout.decode('utf-8', errors='replace').split()
    if stage.returncode == 3:
        raise ValueError(f"The worktree isn't reachable from {distro}; check that its drive is mounted in WSL")
    if stage.returncode != 0 or len(lines) < 2:
        raise ValueError(f"Couldn't prepare the sandbox in {distro}")
    folder, linux_root = lines[0], lines[1]
    linux_profile = f'{folder}/profile'
    relay_process = sandbox = task = None
    try:
        relay_process = subprocess.Popen(
            [_wsl_exe(), '--distribution', distro, '--exec', '/usr/bin/python3', f'{folder}/pump.py', f'{folder}/relay.sock'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ready = await asyncio.wait_for(asyncio.to_thread(relay_process.stdout.read, 1), 60)
        if ready != b'R':
            raise ValueError(f"The relay in {distro} didn't start")
        git = (root / '.git').exists()
        argv = bwrap_argv(system_dirs=found.system_dirs, relay=f'{folder}/relay.sock', passwd=f'{folder}/passwd',
            group=f'{folder}/group', root=linux_root, profile=linux_profile, binary=found.fx, helper=f'{folder}/bridge.py',
            git=f'{linux_profile}/.sandbox-git' if git else None, git_pointer=f'{folder}/git-pointer' if git else None,
            worktree_git_is_dir=(root / '.git').is_dir(), anthropic=False, cert_dirs=found.cert_dirs if network else ())
        env = sandbox_env(linux_profile, port, bool(network))
        sandbox = await asyncio.create_subprocess_exec(
            _wsl_exe(), '--distribution', distro, '--exec', '/usr/bin/env', '-i',
            *(f'{name}={value}' for name, value in env.items()), *argv,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None, limit=16 * 1024 * 1024,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        relay = Relay(None, target, key, model, browser, protocol='openai',
                      pipe_fds=(relay_process.stdout.fileno(), relay_process.stdin.fileno()), research=research,
                      network=network)
        task = asyncio.create_task(relay.run())
        line = await asyncio.wait_for(sandbox.stdout.readline(), 60)
        started = json.loads(line)
        if not started.get('bridge_ready') or started.get('version') != expected_version:
            raise ValueError('The native isolation helper did not start')
        yield sandbox, started['port'], linux_root
    finally:
        if sandbox and sandbox.returncode is None:
            sandbox.kill()
        if sandbox:
            await sandbox.wait()
        if relay_process:
            with contextlib.suppress(OSError):
                relay_process.kill()
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if relay_process:
            await asyncio.to_thread(relay_process.wait)
        await asyncio.to_thread(_finish, distro, folder, profile)


def _finish(distro: str, folder: str, profile: Path) -> None:
    """Stops what the turn left running in WSL, keeps the profile, and removes the turn's folder."""
    # The patterns name the sandbox's and the pump's own command lines, which this script's does not contain.
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        _run(['--distribution', distro, '--exec', '/bin/sh', '-c',
              'pkill -KILL -f "/opt/dotrix/bridge.py /opt/dotrix/relay.sock $1/profile"; '
              'pkill -KILL -f "pump.py $1/relay.sock"; exit 0', 'sh', folder], timeout=60)
    try:
        archive = _run(['--distribution', distro, '--exec', '/bin/tar', '-C', f'{folder}/profile', '-cf', '-', '.'],
                       timeout=300)
        if archive.returncode == 0:
            copy_back(archive.stdout, profile)
    finally:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            _run(['--distribution', distro, '--exec', '/bin/rm', '-rf', '--', folder], timeout=120)
