"""Known vulnerabilities in a repository's dependencies, from OSV (faked here: no network)."""
import json

import httpx

from dotrix_backend.modules.repo_knowledge import advisories as adv
from dotrix_engine.dependencies import Dependency


def _dep(name: str, eco: str = "pypi", declared: str | None = None, locked: str | None = None, scope: str = "runtime"):
    return Dependency(eco, name, declared, locked, scope, "requirements.txt" if eco == "pypi" else "package.json", None)


def _osv(asked: list):
    advisory = {
        "id": "GHSA-462w-v97r-4m45", "aliases": ["CVE-2019-10906"], "summary": "Jinja2 sandbox escape",
        "database_specific": {"severity": "HIGH"},
        "affected": [{"package": {"ecosystem": "PyPI", "name": "jinja2"},
                      "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.10.1"}]}]}],
    }

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/querybatch"):
            queries = json.loads(request.content)["queries"]
            asked.extend(queries)
            return httpx.Response(200, json={"results": [
                {"vulns": [{"id": advisory["id"]}]} if q["package"]["name"] == "jinja2" else {} for q in queries]})
        return httpx.Response(200, json=advisory)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def test_only_exact_versions_are_checked() -> None:
    assert adv.exact_version(_dep("a", locked="1.2.3")) == "1.2.3"
    assert adv.exact_version(_dep("a", declared="==2.10")) == "2.10"
    assert adv.exact_version(_dep("a", eco="npm", declared="4.17.21")) == "4.17.21"
    assert adv.exact_version(_dep("a", declared=">=2,<3")) is None  # a range: not guessed
    assert adv.exact_version(_dep("a", eco="npm", declared="^19.0.0")) is None


async def test_vulnerable_versions_come_back_with_severity_and_the_fix() -> None:
    adv._ids.clear()
    adv._details.clear()
    asked: list = []
    deps = [_dep("jinja2", declared="==2.10"), _dep("fastapi", locked="0.115.6"),
            _dep("react", eco="npm", declared="^19.0.0")]
    async with _osv(asked) as client:
        report = await adv.advisories(deps, client=client)
    assert {q["package"]["ecosystem"] for q in asked} == {"PyPI"} and len(asked) == 2  # react's range isn't asked
    assert report["checked"] == 2
    [hit] = report["vulnerable"]
    assert (hit["package"], hit["version"]) == ("jinja2", "2.10")
    assert hit["advisories"] == [{"id": "GHSA-462w-v97r-4m45", "aliases": ["CVE-2019-10906"],
                                  "summary": "Jinja2 sandbox escape", "severity": "HIGH", "fixed_in": ["2.10.1"]}]
    assert report["unchecked"]["count"] == 1 and "react" in report["unchecked"]["examples"][0]
    # Asked again: from the cache, OSV isn't called.
    async with _osv(asked) as client:
        await adv.advisories(deps, client=client)
    assert len(asked) == 2
