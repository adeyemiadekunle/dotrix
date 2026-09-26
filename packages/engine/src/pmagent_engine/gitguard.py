"""Keep `.pmagent/` out of git.

Project knowledge (requirements, architecture, ADRs, research, tasks) never
goes to GitHub/GitLab. Until the hosted platform exists it lives only on the
local machine; once the platform ships, the local folder becomes a synced
mirror of the platform copy. Either way, the code host sees code only.

Three layers, so no single mistake leaks it:

1. `.pmagent/.gitignore` containing `*`. Git ignores everything in the folder,
   including that file itself, so `git add .` / `git add -A` never pick it up.
   Works even if the hooks below are missing.
2. `.git/info/exclude` entries for `/.pmagent/` and the generated hand-off
   files. Local to this clone, never committed, and never shows up as a
   change in anyone's working tree.
3. A pre-commit hook that refuses any commit staging a `.pmagent/` path, or a
   hand-off file carrying pmagent's managed section. This catches
   `git add -f`. (`git commit --no-verify` can still bypass it; `pmagent
   protect` reports anything that slipped through.)
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

PMAGENT_DIR = ".pmagent"
HANDOFF_FILES = ("AGENTS.md", "CLAUDE.md")
MARKER = "pmagent:start"  # must match handoff.START
EXCLUDE_HEADER = "# pmagent: project knowledge stays local / on the platform"
EXCLUDE_LINES = [f"/{PMAGENT_DIR}/", *(f"/{f}" for f in HANDOFF_FILES)]
HOOK_TAG = "# pmagent-guard"
CHAINED_HOOK = "pre-commit.pre-pmagent"

HOOK_SCRIPT = f"""#!/bin/sh
{HOOK_TAG}: refuses commits that include pmagent project knowledge.
# Installed by `pmagent protect`. Safe to delete if you stop using pmagent.

staged=$(git diff --cached --name-only --diff-filter=ACMR)

if printf '%s\\n' "$staged" | grep -qE '^\\{PMAGENT_DIR}(/|$)'; then
  echo "pmagent: refusing to commit {PMAGENT_DIR}/ (project knowledge never goes to the code repo)." >&2
  echo "         Unstage it with: git restore --staged {PMAGENT_DIR}" >&2
  exit 1
fi

for f in {' '.join(HANDOFF_FILES)}; do
  if printf '%s\\n' "$staged" | grep -qx "$f"; then
    if git show ":$f" 2>/dev/null | grep -q "{MARKER}"; then
      echo "pmagent: refusing to commit $f: it contains pmagent's generated hand-off section." >&2
      echo "         Unstage it with: git restore --staged $f" >&2
      exit 1
    fi
  fi
done

# Run whatever pre-commit hook existed before pmagent's, if any.
hook_dir=$(dirname "$0")
if [ -x "$hook_dir/{CHAINED_HOOK}" ]; then
  exec "$hook_dir/{CHAINED_HOOK}" "$@"
fi
exit 0
"""


def _git(root: str, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", root, *args], capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.strip()


def is_git_repo(root: str) -> bool:
    return _git(root, "rev-parse", "--is-inside-work-tree") == "true"


def _git_path(root: str, rel: str) -> Path:
    """Resolve a path inside .git, correct for worktrees and submodules."""
    p = _git(root, "rev-parse", "--git-path", rel)
    path = Path(p)
    return path if path.is_absolute() else Path(root) / path


def _hooks_dir(root: str) -> Path:
    custom = _git(root, "config", "--get", "core.hooksPath")
    if custom:
        p = Path(os.path.expanduser(custom))
        return p if p.is_absolute() else Path(root) / p
    return _git_path(root, "hooks")


def write_folder_gitignore(pmagent_dir: str) -> None:
    Path(pmagent_dir).mkdir(parents=True, exist_ok=True)
    (Path(pmagent_dir) / ".gitignore").write_text(
        "# Everything in .pmagent/ stays out of git, including this file.\n*\n"
    )


def _ensure_exclude(root: str) -> bool:
    path = _git_path(root, "info/exclude")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else ""
    missing = [line for line in EXCLUDE_LINES if line not in text.splitlines()]
    if not missing:
        return False
    block = ("\n" if text and not text.endswith("\n") else "") + (
        f"{EXCLUDE_HEADER}\n" if EXCLUDE_HEADER not in text else ""
    ) + "\n".join(missing) + "\n"
    path.write_text(text + block)
    return True


def _ensure_hook(root: str) -> str:
    hooks = _hooks_dir(root)
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    if hook.exists():
        current = hook.read_text(errors="ignore")
        if HOOK_TAG in current:
            if current == HOOK_SCRIPT:
                return "present"
            hook.write_text(HOOK_SCRIPT)
            return "updated"
        chained = hooks / CHAINED_HOOK
        if chained.exists():
            raise RuntimeError(
                f"Both {hook} and {chained} exist; merge them by hand, then re-run `pmagent protect`."
            )
        hook.rename(chained)  # keep the user's hook; ours runs it afterwards
    hook.write_text(HOOK_SCRIPT)
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return "installed (existing hook chained)" if (hooks / CHAINED_HOOK).exists() else "installed"


def tracked_leaks(root: str) -> list[str]:
    """Files git already tracks that shouldn't be there (committed before
    protection existed). Excludes don't affect tracked files, so these need
    `git rm --cached`."""
    leaks = (_git(root, "ls-files", "--", PMAGENT_DIR) or "").splitlines()
    for f in HANDOFF_FILES:
        if _git(root, "ls-files", "--", f):
            content = _git(root, "show", f"HEAD:{f}") or ""
            if MARKER in content:
                leaks.append(f)
    return [f for f in leaks if f]


def is_tracked(root: str, rel_path: str) -> bool:
    return bool(_git(root, "ls-files", "--", rel_path))


def protect(root: str, pmagent_dir: str) -> dict:
    """Apply all three layers. Idempotent. Returns a report for the CLI."""
    write_folder_gitignore(pmagent_dir)
    report = {"folder_gitignore": "written", "git_repo": is_git_repo(root)}
    if not report["git_repo"]:
        report["note"] = ("Not a git repo: only the folder .gitignore was written. "
                          "Run `pmagent protect` again after `git init`.")
        return report
    report["exclude"] = "added" if _ensure_exclude(root) else "present"
    report["hook"] = _ensure_hook(root)
    report["tracked_leaks"] = tracked_leaks(root)
    return report
