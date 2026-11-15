import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


affected = load('affected')
boundaries = load('check_boundaries')


class AffectedTests(unittest.TestCase):
    def test_engine_reaches_python_dependants_and_bundled_desktop(self):
        result = affected.select(['packages/engine/src/dotrix_engine/agent.py'])
        self.assertEqual(result['components'], ['backend', 'cli', 'desktop', 'engine'])
        self.assertTrue(result['e2e'])
        self.assertTrue(result['contract'])

    def test_ui_reaches_all_consumers_but_not_python_or_desktop(self):
        result = affected.select(['packages/ui/src/components/button.tsx'])
        self.assertEqual(result['components'], ['admin', 'site', 'ui', 'web'])
        self.assertFalse(result['python'])
        self.assertFalse(result['desktop'])
        self.assertTrue(result['e2e'])

    def test_single_apps_do_not_rebuild_unrelated_consumers(self):
        result = affected.select(['apps/site/src/App.tsx'])
        self.assertEqual(result['node_packages'], ['@dotrix/site'])
        self.assertFalse(result['python'])
        self.assertFalse(result['e2e'])
        self.assertFalse(result['cli'])

    def test_backend_runs_contract_and_browser_but_no_node_app_units(self):
        result = affected.select(['apps/backend/src/dotrix_backend/main.py'])
        self.assertTrue(result['e2e'])
        self.assertTrue(result['contract'])
        self.assertEqual(result['python_paths'], ['apps/backend/tests'])
        self.assertFalse(result['node'])

    def test_cli_reaches_desktop_without_server_or_browser(self):
        result = affected.select(['apps/cli/src/dotrix_cli/cli.py'])
        self.assertEqual(result['components'], ['cli', 'desktop'])
        self.assertFalse(result['e2e'])
        self.assertFalse(result['contract'])

    def test_docs_only_still_have_guards_but_no_app_suites(self):
        result = affected.select(['AGENTS.md', 'docs/monorepo.md', 'CHANGELOG.md'])
        self.assertEqual(result['components'], [])
        self.assertFalse(result['python'])
        self.assertFalse(result['node'])

    def test_locks_workflows_unknown_paths_and_missing_history_fail_open(self):
        all_components = affected.select(None)['components']
        for files in (['.github/workflows/ci.yml'], ['new-tool.config'], ['new-resource.svg'], None):
            self.assertEqual(affected.select(files)['components'], all_components)
        self.assertEqual(affected.select(['uv.lock'])['components'], ['backend', 'cli', 'desktop', 'engine'])
        node_lock = affected.select(['pnpm-lock.yaml'])
        self.assertTrue(node_lock['node'])
        self.assertFalse(node_lock['python'])
        self.assertTrue(node_lock['e2e'])

    def test_contract_changes_reach_clients(self):
        result = affected.select(['packages/api-client/openapi.json'])
        self.assertEqual(result['components'], ['api-client', 'web'])
        self.assertTrue(result['contract'])
        self.assertFalse(result['python'])

    def test_git_diff_includes_deletions_and_all_branch_commits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()
            git('init')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@localhost')
            (root / 'old.txt').write_text('old')
            (root / 'move.txt').write_text('exact renamed contents')
            git('add', '.')
            git('commit', '-m', 'base')
            base = git('rev-parse', 'HEAD')
            (root / 'old.txt').unlink()
            (root / 'move.txt').rename(root / 'renamed.txt')
            (root / 'new.txt').write_text('new')
            git('add', '-A')
            git('commit', '-m', 'one')
            (root / 'later.txt').write_text('later')
            git('add', '.')
            git('commit', '-m', 'two')
            self.assertEqual(set(affected.changed(base, 'HEAD', root)), {'old.txt', 'new.txt', 'later.txt', 'move.txt', 'renamed.txt'})
            self.assertIsNone(affected.changed('missing-commit', 'HEAD', root))


class BoundaryTests(unittest.TestCase):
    def test_imports_and_dynamic_imports_are_checked_but_data_is_not(self):
        source = 'from fastapi import FastAPI\nimport dotrix_backend.core\n__import__("typer")\nimportlib.import_module("dotrix_cli.cli")\nmessage = "import fastapi"\n'
        self.assertEqual([name for _, name in boundaries.violations(source, {'fastapi', 'dotrix_backend', 'typer', 'dotrix_cli'})],
                         ['fastapi', 'dotrix_backend.core', 'typer', 'dotrix_cli.cli'])
        self.assertEqual(boundaries.violations('from dotrix_engine import agent', {'dotrix_backend'}), [])


class LocalUpdates(unittest.TestCase):
    def test_updates_have_no_dependency_restarts_and_migrate_before_backend(self):
        updates = load('update_local')
        backend = updates.commands('backend')
        self.assertEqual([argv[len(updates.COMPOSE)] for argv in backend], ['build', 'run', 'up'])
        self.assertIn('migrate', backend[1])
        self.assertEqual(backend[-1][-2:], ['api', 'worker'])
        self.assertIn('--no-deps', backend[-1])
        self.assertEqual(updates.commands('site')[0][-1], 'site')
        with self.assertRaises(ValueError):
            updates.commands('database')


if __name__ == '__main__':
    unittest.main()
