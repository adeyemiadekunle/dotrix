"""Independent platform, desktop and CLI releases from one source repository.

python scripts/release.py check
python scripts/release.py version [--component platform|desktop|cli]
python scripts/release.py notes [VERSION] [--component platform|desktop|cli]
python scripts/release.py bump VERSION [--component platform|desktop|cli]
python scripts/release.py plan

Platform contains the API and its shared packages/browser clients. Desktop and CLI
have separate versions/changelogs. Desktop keeps vX.Y.Z for existing updaters;
platform-vX.Y.Z and cli-vX.Y.Z must never replace the desktop's latest release.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "platform": {
        "json": ["apps/web", "apps/site", "apps/admin", "packages/ui", "packages/api-client"],
        "python": ["apps/backend", "packages/engine"], "changelog": "CHANGELOG.md", "prefix": "platform-v",
    },
    "desktop": {"json": ["apps/desktop"], "python": [], "changelog": "apps/desktop/CHANGELOG.md", "prefix": "v"},
    "cli": {"json": [], "python": ["apps/cli"], "changelog": "apps/cli/CHANGELOG.md", "prefix": "cli-v"},
}
# v0.2.0 and earlier used a coordinated release. Don't republish the existing
# 0.2.0 components just because they acquire separate release tags in this change.
LEGACY_VERSION = "0.2.0"
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
PY_VERSION = re.compile(r'^(version\s*=\s*")([^"]+)(")', re.M)
API = re.compile(r'^(API_VERSION\s*=\s*")([^"]+)(")', re.M)
API_VERSION = "apps/backend/src/dotrix_backend/main.py"
UNRELEASED = "## [Unreleased]"


def versions(component: str = "platform", root: Path = ROOT) -> dict[str, str]:
    group = GROUPS[component]
    found = {}
    for folder in group['json']:
        filename = folder + '/package.json'
        found[filename] = json.loads((root / filename).read_text())['version']
    for folder in group['python']:
        filename = folder + '/pyproject.toml'
        match = PY_VERSION.search((root / filename).read_text())
        found[filename] = match.group(2) if match else '(none)'
    if component == 'platform':
        match = API.search((root / API_VERSION).read_text())
        found[API_VERSION] = match.group(2) if match else '(none)'
    return found


def current(component: str = "platform", root: Path = ROOT) -> str:
    found = versions(component, root)
    values = set(found.values())
    if len(values) != 1 or not SEMVER.fullmatch(next(iter(values))):
        raise ValueError(f'{component} packages must agree on a valid version: {found}')
    return values.pop()


def notes(version: str, component: str = "platform", root: Path = ROOT) -> str:
    text = (root / GROUPS[component]['changelog']).read_text()
    match = re.search(rf'^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)', text, re.M | re.S)
    if not match:
        raise ValueError(f'{component} changelog has no section for {version}')
    return match.group(1).strip() + '\n'


def check(root: Path = ROOT) -> None:
    for component, group in GROUPS.items():
        version = current(component, root)
        notes(version, component, root)
        if UNRELEASED not in (root / group['changelog']).read_text():
            raise ValueError(f'{component} changelog needs {UNRELEASED}')
        print(f'{component} {version}: versions and changelog agree')


def bump(version: str, component: str = "platform", root: Path = ROOT) -> None:
    if not SEMVER.fullmatch(version):
        raise ValueError('Use a version like 1.2.3 or 1.2.3-rc.1')
    old = current(component, root)
    if old == version:
        raise ValueError(f'Already at {component} {version}')
    group = GROUPS[component]
    changelog = root / group['changelog']
    head, sep, rest = changelog.read_text().partition(UNRELEASED + '\n')
    if not sep:
        raise ValueError(f'{changelog} needs {UNRELEASED}')
    body, _, tail = rest.partition('\n## [')
    if not body.strip():
        raise ValueError(f'Write the {component} release notes under {UNRELEASED} first')
    tail = ('\n## [' + tail) if tail else ''
    text = f'{head}{UNRELEASED}\n\n## [{version}] - {datetime.date.today().isoformat()}\n\n{body.strip()}\n{tail}'
    prefix = group['prefix']
    text = re.sub(r'^\[Unreleased\]: (\S+)/compare/\S+?\.\.\.(\S+)$',
        rf'[Unreleased]: \g<1>/compare/{prefix}{version}...\g<2>\n[{version}]: \g<1>/releases/tag/{prefix}{version}', text, count=1, flags=re.M)
    changelog.write_text(text)
    for folder in group['json']:
        path = root / folder / 'package.json'
        path.write_text(re.sub(r'("version":\s*")[^"]+(\")', rf'\g<1>{version}\g<2>', path.read_text(), count=1))
    for folder in group['python']:
        path = root / folder / 'pyproject.toml'
        path.write_text(PY_VERSION.sub(rf'\g<1>{version}\g<3>', path.read_text(), count=1))
    if component == 'platform':
        path = root / API_VERSION
        path.write_text(API.sub(rf'\g<1>{version}\g<3>', path.read_text(), count=1))
    if group['python']:
        subprocess.run(['uv', 'lock'], cwd=root, check=True)
    print(f'{component}: {old} -> {version}. Open a PR into stage; release after stage merges into main.')


def plan(root: Path = ROOT) -> list[dict]:
    result = []
    for component, group in GROUPS.items():
        version = current(component, root)
        tag = group['prefix'] + version
        exists = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', 'refs/tags/' + tag], cwd=root,
                                capture_output=True).returncode == 0
        if not exists and component != 'desktop' and version == LEGACY_VERSION:
            exists = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', 'refs/tags/v' + LEGACY_VERSION],
                                    cwd=root, capture_output=True).returncode == 0
        if not exists:
            result.append({'component': component, 'version': version, 'tag': tag,
                           'latest': component == 'desktop', 'prerelease': '-' in version})
    return result


def publish(root: Path = ROOT) -> dict[str, str]:
    """Called only by the protected main-branch release workflow, never by CI checks."""
    if os.environ.get('GITHUB_REF') != 'refs/heads/main' or not re.fullmatch(r'[0-9a-f]{40}', os.environ.get('GITHUB_SHA', '')):
        raise ValueError('Publishing requires the main-branch release workflow')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip()
    if head != os.environ['GITHUB_SHA'] or dirty:
        raise ValueError('Publish only the clean checked-out release commit')
    check(root)
    builds = {}
    for item in plan(root):
        with tempfile.TemporaryDirectory(prefix='dotrix-notes-') as temporary:
            path = Path(temporary) / 'notes.md'
            path.write_text(notes(item['version'], item['component'], root))
            argv = ['gh', 'release', 'create', item['tag'], '--target', os.environ['GITHUB_SHA'],
                    '--title', f"dotrix {item['component']} {item['version']}", '--notes-file', str(path),
                    '--latest=' + ('true' if item['latest'] and not item['prerelease'] else 'false')]
            if item['prerelease']:
                argv.append('--prerelease')
            subprocess.run(argv, cwd=root, check=True)
            if item['component'] in ('desktop', 'cli'):
                builds[item['component'] + '_tag'] = item['tag']
    # Explicit workflow_call builds are necessary: releases created with
    # GITHUB_TOKEN do not trigger another workflow's release event. Retrying an
    # asset job must also work after its tag was already created by this run.
    for component in ('desktop', 'cli'):
        tag = GROUPS[component]['prefix'] + current(component, root)
        target = subprocess.run(['git', 'rev-list', '-n', '1', 'refs/tags/' + tag], cwd=root, capture_output=True, text=True)
        if target.returncode == 0 and target.stdout.strip() == os.environ['GITHUB_SHA']:
            builds[component + '_tag'] = tag
    return builds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'version', 'notes', 'bump', 'plan', 'publish'])
    parser.add_argument('version', nargs='?')
    parser.add_argument('--github-output', type=Path)
    parser.add_argument('--component', choices=list(GROUPS), default='platform')
    args = parser.parse_args()
    try:
        if args.command == 'check':
            check()
        elif args.command == 'version':
            print(current(args.component))
        elif args.command == 'notes':
            print(notes((args.version or current(args.component)).removeprefix('v'), args.component), end='')
        elif args.command == 'bump':
            if not args.version:
                parser.error('bump requires a version')
            bump(args.version.removeprefix('v'), args.component)
        elif args.command == 'plan':
            print(json.dumps(plan(), indent=2))
        elif args.command == 'publish':
            builds = publish()
            if args.github_output:
                with args.github_output.open('a') as output:
                    for component in ('desktop', 'cli'):
                        output.write(component + '_tag=' + builds.get(component + '_tag', '') + '\n')
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
