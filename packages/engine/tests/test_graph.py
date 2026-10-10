from dotrix_engine.graph import (
    AFFECTS,
    DECIDED_BY,
    IMPLEMENTS,
    MENTIONS,
    SUPERSEDES,
    Reference,
    find_references,
)

PATHS = ["requirements/auth.md", "requirements/billing.md", "decisions/ADR-001-sessions.md",
         "decisions/ADR-002.md", "architecture/overview.md"]


def test_a_document_s_references() -> None:
    text = """# ADR-002: Tokens in cookies

- Status: Accepted
- Affected modules: `auth`, web proxy and sessions
- Supersedes: ADR-1

Context: [the requirement](../requirements/auth.md) and /dotrix/architecture/overview.md.
Work: KUN-4, KUN-12 (and KUN-4 again). Not a key: KUNX-3. Not there: ../nope.md

## Affected modules
- Billing
- none
"""
    refs = set(find_references(text, source="decisions/ADR-002.md", project_key="KUN", paths=PATHS))
    assert refs == {
        Reference("module:auth", AFFECTS, "auth"),
        Reference("module:web proxy", AFFECTS, "web proxy"),
        Reference("module:sessions", AFFECTS, "sessions"),
        Reference("module:billing", AFFECTS, "Billing"),
        Reference("decisions/ADR-001-sessions.md", SUPERSEDES),
        Reference("requirements/auth.md", MENTIONS),
        Reference("architecture/overview.md", MENTIONS),
        Reference("KUN-4", MENTIONS),
        Reference("KUN-12", MENTIONS),
    }


def test_an_issue_implements_requirements_and_follows_decisions() -> None:
    text = "Build login per requirements/auth.md (and requirements/auth.md again), ADR-2. Blocked by KUN-3. Later: requirements/sso.md"
    refs = find_references(text, source="KUN-9", project_key="KUN", paths=PATHS, is_issue=True)
    assert set(refs) == {
        Reference("requirements/auth.md", IMPLEMENTS),
        Reference("decisions/ADR-002.md", DECIDED_BY),
        Reference("KUN-3", MENTIONS),
        Reference("requirements/sso.md", IMPLEMENTS),  # not written yet
    }
    assert find_references("See KUN-9", source="KUN-9", project_key="KUN", paths=PATHS) == []  # not itself
