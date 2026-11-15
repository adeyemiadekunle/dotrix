"""Enforce Python workspace dependency direction and application-only config ownership."""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANNED = {
    "packages/engine": {"apps", "dotrix_backend", "dotrix_cli", "fastapi", "typer"},
    "apps/cli": {"apps", "dotrix_backend"},
    "apps/backend": {"apps", "dotrix_cli"},
}


def violations(source: str, banned: set[str]) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(source)):
        modules = []
        if isinstance(node, ast.Import):
            modules = [name.name for name in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            function = node.func
            if (isinstance(function, ast.Name) and function.id == "__import__") or (
                isinstance(function, ast.Attribute) and function.attr == "import_module"):
                modules = [node.args[0].value] if isinstance(node.args[0].value, str) else []
        found.extend((node.lineno, name) for name in modules if name.split(".")[0] in banned)
    return found


def main() -> int:
    failures = []
    for folder, banned in BANNED.items():
        manifest = tomllib.loads((ROOT / folder / 'pyproject.toml').read_text())
        blocked = {name.replace('_', '-') for name in banned}
        for dependency in manifest['project'].get('dependencies', []):
            name = re.split(r'[\s\[<>=!~;]', dependency, maxsplit=1)[0].lower().replace('_', '-')
            if name in blocked:
                failures.append(f'{folder}/pyproject.toml: forbidden dependency {name}')
        for path in sorted((ROOT / folder / "src").rglob("*.py")):
            for line, name in violations(path.read_text(), banned):
                failures.append(f"{path.relative_to(ROOT)}:{line}: forbidden dependency {name}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Python workspace boundaries passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
