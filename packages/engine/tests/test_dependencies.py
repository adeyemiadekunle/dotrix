"""Dependencies from manifests and lockfiles: what each manifest declares, and what its lockfile pins."""
import json
from pathlib import Path

from dotrix_engine.dependencies import read_dependencies


def _write(root: Path, files: dict[str, str]) -> list[str]:
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    return list(files)


def _by(found, manifest):
    return {d.name: d for d in found.dependencies if d.manifest == manifest}


def test_a_pnpm_workspace_pins_each_package_s_dependencies(tmp_path: Path) -> None:
    paths = _write(tmp_path, {
        "package.json": json.dumps({"devDependencies": {"prettier": "^3.3.0"}}),
        "apps/web/package.json": json.dumps({"dependencies": {"react": "^19.0.0"}, "peerDependencies": {"vite": "*"}}),
        "pnpm-lock.yaml": "lockfileVersion: '9.0'\nimporters:\n  .:\n    devDependencies:\n      prettier:\n"
                          "        specifier: ^3.3.0\n        version: 3.3.3\n  apps/web:\n    dependencies:\n"
                          "      react:\n        specifier: ^19.0.0\n        version: 19.1.0(react-dom@19.1.0)\n",
    })
    found = read_dependencies(tmp_path, paths)
    assert _by(found, "package.json")["prettier"].locked == "3.3.3"
    web = _by(found, "apps/web/package.json")
    assert web["react"].locked == "19.1.0" and web["react"].scope == "runtime" and web["react"].lockfile == "pnpm-lock.yaml"
    assert web["vite"].scope == "peer" and web["vite"].locked is None and not found.unread


def test_npm_and_yarn_lockfiles(tmp_path: Path) -> None:
    paths = _write(tmp_path, {
        "a/package.json": json.dumps({"dependencies": {"left-pad": "^1.3.0"}}),
        "a/package-lock.json": json.dumps({"lockfileVersion": 3, "packages": {
            "": {}, "node_modules/left-pad": {"version": "1.3.0"},
            "node_modules/x/node_modules/left-pad": {"version": "0.1.0"}}}),
        "b/package.json": json.dumps({"dependencies": {"lodash": "^4.17.0"}}),
        "b/yarn.lock": '# yarn lockfile v1\n\n"lodash@^4.17.0", lodash@^4.17.21:\n  version "4.17.21"\n',
    })
    found = read_dependencies(tmp_path, paths)
    assert _by(found, "a/package.json")["left-pad"].locked == "1.3.0"
    assert _by(found, "b/package.json")["lodash"].locked == "4.17.21"


def test_python_cargo_and_go(tmp_path: Path) -> None:
    paths = _write(tmp_path, {
        "pyproject.toml": '[project]\nname = "x"\ndependencies = ["FastAPI>=0.115", "pydantic[email]~=2.9; python_version>\'3.10\'"]\n'
                          '[dependency-groups]\ndev = ["pytest>=8"]\n',
        "uv.lock": '[[package]]\nname = "fastapi"\nversion = "0.115.6"\n\n[[package]]\nname = "pytest"\nversion = "8.3.4"\n',
        "tools/requirements-dev.txt": "ruff==0.8.4  # lint\n-e .\n",
        "crates/core/Cargo.toml": '[dependencies]\nserde = { version = "1", features = ["derive"] }\n[dev-dependencies]\ninsta = "1.40"\n',
        "Cargo.lock": '[[package]]\nname = "serde"\nversion = "1.0.217"\n',
        "svc/go.mod": "module x\n\ngo 1.23\n\nrequire (\n\tgithub.com/a/b v1.2.3\n\tgithub.com/c/d v0.1.0 // indirect\n)\n",
        "Gemfile": "source 'https://rubygems.org'\n",
    })
    found = read_dependencies(tmp_path, paths)
    py = _by(found, "pyproject.toml")
    assert py["FastAPI"].locked == "0.115.6" and py["FastAPI"].declared == ">=0.115"
    assert py["pydantic"].locked is None and py["pydantic"].declared == "~=2.9"
    assert py["pytest"].scope == "dev" and py["pytest"].locked == "8.3.4"
    ruff = _by(found, "tools/requirements-dev.txt")["ruff"]
    assert ruff.locked == "0.8.4" and ruff.scope == "dev"
    crate = _by(found, "crates/core/Cargo.toml")
    assert crate["serde"].locked == "1.0.217" and crate["insta"].scope == "dev"
    assert list(_by(found, "svc/go.mod")) == ["github.com/a/b"]  # indirect ones aren't direct
    assert found.unread == [("Gemfile", "No reader for this manifest yet")]


def test_a_file_that_doesn_t_parse_is_reported_not_guessed(tmp_path: Path) -> None:
    paths = _write(tmp_path, {"package.json": "{not json", "pnpm-lock.yaml": "a: [unclosed\n"})
    found = read_dependencies(tmp_path, paths)
    assert found.dependencies == []
    assert sorted(p for p, _ in found.unread) == ["package.json", "pnpm-lock.yaml"]
