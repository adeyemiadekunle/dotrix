import pytest

from pmagent_engine.layout import AGENTS
from pmagent_engine.permissions import Access, access, can_create_issue, can_edit_issues, can_write

R, W, P, T = Access.READ, Access.WRITE, Access.PROPOSE, Access.TIDY
AGENT_ORDER = ("project-manager", "product", "architecture", "research", "reviewer", "documentation", "coding")

# The PRD table, row by row: a sample path, then access for
# PM, Product, Architecture, Research, Reviewer, Documentation, Coding.
MATRIX = [
    ("project.md", (R, R, R, R, R, W, R)),
    ("docs/README.md", (R, R, R, R, R, W, R)),
    ("vision.md", (R, W, R, R, R, T, R)),
    ("roadmap.md", (W, P, R, R, R, T, R)),
    ("current-state.md", (W, P, R, R, R, T, R)),
    ("requirements/modules/drivers.md", (R, W, P, R, R, T, R)),
    ("architecture/database.md", (R, R, W, R, R, T, R)),
    ("research/postcodes.md", (R, R, R, W, R, T, R)),
    ("reviews/pr-12.md", (R, R, R, R, W, T, R)),
    ("decisions/ADR-014.md", (P, P, P, P, P, W, R)),
    ("progress/blocked.md", (W, R, R, R, R, T, R)),
    ("issues/KUN-1.md", (W, R, R, R, R, R, R)),
    ("sprints/sprint-1.md", (W, R, R, R, R, R, R)),
    ("agent-rules/base.md", (R, R, R, R, R, R, R)),
    ("somewhere-else.md", (R, R, R, R, R, R, R)),
]


def test_agent_order_matches_layout() -> None:
    assert AGENT_ORDER == AGENTS


@pytest.mark.parametrize(("path", "expected"), MATRIX)
def test_matrix(path: str, expected: tuple[Access, ...]) -> None:
    assert tuple(access(agent, path) for agent in AGENT_ORDER) == expected


def test_can_write_allows_write_and_tidy_only() -> None:
    assert can_write("product", "requirements/product.md")
    assert can_write("documentation", "requirements/product.md")  # tidy
    assert not can_write("architecture", "requirements/product.md")  # propose
    assert not can_write("reviewer", "requirements/product.md")  # read
    assert not can_write("coding", "architecture/overview.md")
    assert not any(can_write(agent, "agent-rules/base.md") for agent in AGENTS)


def test_unknown_agent_is_read_only() -> None:
    assert access("someone", "requirements/product.md") is Access.READ


@pytest.mark.parametrize(
    ("agent", "allowed"),
    [
        ("project-manager", {"epic", "story", "task", "bug", "spike", "sub-task"}),
        ("product", {"epic", "story"}),
        ("architecture", {"task"}),
        ("research", {"spike"}),
        ("reviewer", {"bug"}),
        ("documentation", set()),
        ("coding", set()),
    ],
)
def test_issue_types_each_agent_may_create(agent: str, allowed: set[str]) -> None:
    for issue_type in ("epic", "story", "task", "bug", "spike", "sub-task"):
        assert can_create_issue(agent, issue_type) is (issue_type in allowed), (agent, issue_type)


def test_only_the_pm_edits_issues() -> None:
    assert can_edit_issues("project-manager")
    assert not any(can_edit_issues(a) for a in AGENTS if a != "project-manager")
