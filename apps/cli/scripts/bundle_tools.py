"""Put the programs native local Code needs beside the standalone CLI, for machines whose OS lacks them:
`python apps/cli/scripts/bundle_tools.py --out apps/desktop/resources/dotrix`.

- The Kai runtime's fx (every platform with a Kai build: Linux and macOS), from GitHub Packages at the version
  and per-platform SHA-256 of `bundled-tools.json`. It needs a token with read:packages in NODE_AUTH_TOKEN
  (or KAI_PACKAGES_TOKEN).
- Bubblewrap (Linux), built static from its pinned release in a pinned Alpine container, so it runs on any
  distribution. macOS's Seatbelt and Windows's AppContainer come with the OS.

Each lands in `<out>/bin/` with its license under `<out>/bin/licenses/`, where `dotrix_cli.bundled` finds it.
A download whose SHA-256 differs from its pin stops the build. Run it on the platform it builds for.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PINS = json.loads((Path(__file__).with_name("bundled-tools.json")).read_text(encoding="utf-8"))


def host_platform() -> str:
    system = {"linux": "linux", "darwin": "darwin"}.get(sys.platform)
    machine = platform.machine().lower()
    cpu = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if system is None or cpu is None:
        raise SystemExit(f"No bundled tools for {sys.platform}/{machine}: Kai's fx is built for Linux and macOS")
    return f"{system}-{cpu}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(path: Path, expected: str, what: str) -> None:
    got = sha256(path)
    if got != expected:
        raise SystemExit(f"{what}: SHA-256 {got} is not the pinned {expected}")


def safe_extract(archive: Path, dest: Path) -> None:
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter="data")


def bundle_fx(target: str, out: Path, work: Path) -> None:
    pin = PINS["kai_fx"]
    expected = pin["sha256"].get(target)
    if expected is None:
        raise SystemExit(f"Kai's fx has no pinned build for {target}")
    token = os.environ.get("NODE_AUTH_TOKEN") or os.environ.get("KAI_PACKAGES_TOKEN")
    if not token:
        raise SystemExit("Set NODE_AUTH_TOKEN (or KAI_PACKAGES_TOKEN) to a token with read:packages")
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm is needed to fetch Kai's fx from GitHub Packages")
    package = pin["package"].format(platform=target)
    registry = pin["registry"]
    npmrc = work / ".npmrc"
    host = registry.removeprefix("https://")
    npmrc.write_text(f"@kunemi-group:registry={registry}\n//{host}/:_authToken=${{NODE_AUTH_TOKEN}}\n", encoding="utf-8")
    packed = subprocess.run([npm, "pack", f"{package}@{pin['version']}", "--userconfig", str(npmrc), "--ignore-scripts",
                             "--silent", "--pack-destination", str(work)], cwd=work, check=True, capture_output=True,
                            text=True, env={**os.environ, "NODE_AUTH_TOKEN": token}).stdout.strip().splitlines()[-1]
    unpacked = work / "fx-package"
    unpacked.mkdir()
    safe_extract(work / packed, unpacked)
    binary = unpacked / "package/bin/fx"
    check(binary, expected, f"{package}@{pin['version']} bin/fx")
    (out / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, out / "bin/fx")
    (out / "bin/fx").chmod(0o755)
    licenses = out / "bin/licenses/kai-fx"
    licenses.mkdir(parents=True, exist_ok=True)
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        if (unpacked / "package" / name).is_file():
            shutil.copyfile(unpacked / "package" / name, licenses / name)
    reported = subprocess.run([str(out / "bin/fx"), "--version"], capture_output=True, text=True, timeout=30,
                              env={**os.environ, "FX_AUTO_UPGRADE": "0"}).stdout.strip()
    if reported != pin["version"]:
        raise SystemExit(f"The bundled fx reports {reported!r}, not {pin['version']}")
    print(f"bundled fx {reported} ({target})")


BUILD_BWRAP = r"""
set -eu
apk add --no-cache build-base meson ninja pkgconf libcap-dev libcap-static linux-headers bash-completion >/dev/null
# Build in the container's own /tmp: only the program and its license come back, owned by the caller.
cd /tmp && tar -xJf /work/bubblewrap.tar.xz && cd bubblewrap-*
LDFLAGS=-static meson setup build --prefer-static -Ddefault_library=static -Dselinux=disabled -Dman=disabled \
  -Dtests=false -Dbash_completion=disabled -Dzsh_completion=disabled >/dev/null
ninja -C build bwrap >/dev/null
strip build/bwrap
cp build/bwrap /work/bwrap
cp COPYING /work/COPYING
chown "$HOST_UID:$HOST_GID" /work/bwrap /work/COPYING
"""


def bundle_bwrap(target: str, out: Path, work: Path) -> None:
    pin = PINS["bubblewrap"]
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("Docker is needed to build a static bwrap")
    source = work / "bubblewrap.tar.xz"
    with urllib.request.urlopen(pin["url"], timeout=60) as response, source.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    check(source, pin["sha256"], f"bubblewrap {pin['version']} source")
    arch = {"linux-x64": "linux/amd64", "linux-arm64": "linux/arm64"}[target]
    subprocess.run([docker, "run", "--rm", "--platform", arch, "-v", f"{work}:/work",
                    "-e", f"HOST_UID={os.getuid()}", "-e", f"HOST_GID={os.getgid()}", pin["builder_image"],
                    "sh", "-c", BUILD_BWRAP], check=True)
    built = work / "bwrap"
    described = subprocess.run(["file", str(built)], capture_output=True, text=True).stdout
    if "statically linked" not in described and "static-pie" not in described:
        raise SystemExit(f"The built bwrap is not static: {described.strip()}")
    (out / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(built, out / "bin/bwrap")
    (out / "bin/bwrap").chmod(0o755)
    licenses = out / "bin/licenses/bubblewrap"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(work / "COPYING", licenses / "COPYING")
    (licenses / "SOURCE").write_text(f"bubblewrap {pin['version']}: {pin['url']} (sha256 {pin['sha256']})\n",
                                     encoding="utf-8")
    print(f"bundled bwrap {pin['version']} ({target})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[3] / "apps/desktop/resources/dotrix")
    parser.add_argument("--skip-bwrap", action="store_true", help="Linux only: leave bwrap to the system")
    args = parser.parse_args()
    target = host_platform()
    out = args.out.resolve()
    with tempfile.TemporaryDirectory(prefix="dotrix-bundle-") as scratch:
        work = Path(scratch)
        bundle_fx(target, out, work)
        if target.startswith("linux") and not args.skip_bwrap:
            bundle_bwrap(target, out, work)


if __name__ == "__main__":
    main()
