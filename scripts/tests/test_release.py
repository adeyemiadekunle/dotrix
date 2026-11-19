import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_affected import load

release = load('release')


class Releases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for component, group in release.GROUPS.items():
            for folder in group['json']:
                path = self.root / folder / 'package.json'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'version': '0.2.0'}))
            for folder in group['python']:
                path = self.root / folder / 'pyproject.toml'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('[project]\nversion = "0.2.0"\n')
            log = self.root / group['changelog']
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('## [Unreleased]\n\nChanges for ' + component + '\n\n## [0.2.0]\n\nOld notes\n')
        api = self.root / release.API_VERSION
        api.parent.mkdir(parents=True, exist_ok=True)
        api.write_text('API_VERSION = "0.2.0"\n')
        subprocess.run(['git', 'init', str(self.root)], capture_output=True, check=True)
        for key, value in [('user.name', 'Test'), ('user.email', 'test@localhost')]:
            subprocess.run(['git', '-C', str(self.root), 'config', key, value], check=True)
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'commit', '-m', 'initial'], capture_output=True, check=True)

    def test_desktop_bump_does_not_change_api_cli_or_shared_versions(self):
        with patch.object(release.subprocess, 'run') as run:
            release.bump('0.3.0', 'desktop', self.root)
        run.assert_not_called()
        self.assertEqual(release.current('desktop', self.root), '0.3.0')
        self.assertEqual(release.current('platform', self.root), '0.2.0')
        self.assertEqual(release.current('cli', self.root), '0.2.0')
        self.assertEqual(release.notes('0.3.0', 'desktop', self.root), 'Changes for desktop\n')
        release.check(self.root)

    def test_cli_bump_locks_python_metadata_but_leaves_desktop_and_platform(self):
        with patch.object(release.subprocess, 'run') as run:
            release.bump('0.2.1', 'cli', self.root)
        run.assert_called_once_with(['uv', 'lock'], cwd=self.root, check=True)
        self.assertEqual(release.current('cli', self.root), '0.2.1')
        self.assertEqual(release.current('desktop', self.root), '0.2.0')
        self.assertEqual(release.current('platform', self.root), '0.2.0')

    def test_legacy_tag_is_not_republished_as_new_component_releases(self):
        subprocess.run(['git', '-C', str(self.root), 'tag', 'v0.2.0'], check=True)
        self.assertEqual(release.plan(self.root), [])
        with patch.object(release.subprocess, 'run'):
            release.bump('0.2.1', 'cli', self.root)
        self.assertEqual(release.plan(self.root), [{'component': 'cli', 'version': '0.2.1', 'tag': 'cli-v0.2.1', 'latest': False, 'prerelease': False}])

    def test_mismatched_platform_versions_and_missing_notes_are_rejected(self):
        (self.root / 'apps/web/package.json').write_text('{"version":"1.0.0"}')
        with self.assertRaises(ValueError):
            release.check(self.root)
        with self.assertRaises(ValueError):
            release.bump('invalid', 'desktop', self.root)

    def test_publishing_cli_does_not_touch_latest_or_build_desktop(self):
        subprocess.run(['git', '-C', str(self.root), 'tag', 'v0.2.0'], check=True)
        with patch.object(release.subprocess, 'run'):
            release.bump('0.2.1', 'cli', self.root)
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'commit', '-m', 'CLI release'], capture_output=True, check=True)
        head = subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD'], text=True).strip()
        real_run = release.subprocess.run
        published = []
        def run(argv, **kwargs):
            if argv[0] == 'gh':
                published.append(argv)
                return subprocess.CompletedProcess(argv, 0)
            return real_run(argv, **kwargs)
        with patch.dict(release.os.environ, {'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': head}), patch.object(release.subprocess, 'run', side_effect=run):
            builds = release.publish(self.root)
        self.assertEqual(builds, {'cli_tag': 'cli-v0.2.1'})
        self.assertEqual(len(published), 1)
        self.assertIn('--latest=false', published[0])
        self.assertEqual(published[0][3], 'cli-v0.2.1')
        # Asset retries still select the existing tag at this release commit.
        subprocess.run(['git', '-C', str(self.root), 'tag', 'cli-v0.2.1'], check=True)
        with patch.dict(release.os.environ, {'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': head}), patch.object(release.subprocess, 'run', side_effect=run):
            self.assertEqual(release.publish(self.root), builds)
        self.assertEqual(len(published), 1)

    def test_platform_publication_does_not_build_clients_or_replace_latest(self):
        subprocess.run(['git', '-C', str(self.root), 'tag', 'v0.2.0'], check=True)
        with patch.object(release.subprocess, 'run'):
            release.bump('0.3.0', 'platform', self.root)
        self.assertIn('API_VERSION = "0.3.0"', (self.root / release.API_VERSION).read_text())
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'commit', '-m', 'Platform release'], capture_output=True, check=True)
        head = subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD'], text=True).strip()
        real_run = release.subprocess.run
        calls = []
        def run(argv, **kwargs):
            if argv[0] == 'gh':
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0)
            return real_run(argv, **kwargs)
        with patch.dict(release.os.environ, {'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': head}), patch.object(release.subprocess, 'run', side_effect=run):
            self.assertEqual(release.publish(self.root), {})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][3], 'platform-v0.3.0')
        self.assertIn('--latest=false', calls[0])

    def test_publish_requires_main_and_never_publishes_from_a_pr(self):
        with patch.dict(release.os.environ, {'GITHUB_REF': 'refs/pull/1/merge', 'GITHUB_SHA': 'a' * 40}):
            with self.assertRaises(ValueError), patch.object(release.subprocess, 'run') as run:
                release.publish(self.root)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
