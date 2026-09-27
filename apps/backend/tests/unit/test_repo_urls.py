import pytest

from pmagent_backend.modules.projects.repo_urls import normalize_repo_url


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/acme/kunemi",
        "https://github.com/acme/kunemi.git",
        "https://github.com/acme/kunemi/",
        "https://ada:ghp_token@github.com/acme/kunemi.git",
        "http://GitHub.com/acme/kunemi",
        "git@github.com:acme/kunemi.git",
        "ssh://git@github.com:22/acme/kunemi.git",
        "git+ssh://git@github.com/acme/kunemi",
    ],
)
def test_same_repo_same_url(raw: str) -> None:
    assert normalize_repo_url(raw) == "https://github.com/acme/kunemi"


def test_self_hosted_and_nested_paths() -> None:
    assert normalize_repo_url("git@gitlab.acme.io:team/sub/app.git") == "https://gitlab.acme.io/team/sub/app"


@pytest.mark.parametrize("raw", ["", "not a url", "ftp://host/x", "https://github.com/", "https://github.com/../etc"])
def test_rejects_non_repo_urls(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_repo_url(raw)
