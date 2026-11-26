import json

import pytest

from dotrix_cli.fx_local import allowed, prepare_profile
from dotrix_cli.web_mcp import ResearchMcp


@pytest.mark.parametrize("endpoint", [None, "http://searxng:8080"])
async def test_native_research_catalog_and_public_address_boundary(endpoint):
    service = ResearchMcp(endpoint)
    try:
        def body(method, params=None):
            return json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()

        status, result = await service.request("POST", body("tools/list"))
        assert status == 200 and result is not None
        assert [tool["name"] for tool in result["result"]["tools"]] == (
            ["fetch_page", "web_search"] if endpoint else ["fetch_page"]
        )
        status, result = await service.request("POST", body("tools/call", {
            "name": "fetch_page", "arguments": {"url": "http://127.0.0.1"},
        }))
        assert status == 200 and result is not None and result["result"]["isError"]
        assert "public internet" in result["result"]["content"][0]["text"]
    finally:
        await service.aclose()


def test_local_research_permission_requires_the_configured_server(tmp_path):
    prepare_profile(tmp_path / "profile", {"HOME": str(tmp_path), "DOTRIX_CODING_WEB_TOOLS": "true"})
    profile = json.loads((tmp_path / "profile/.fx/settings.json").read_text())
    assert profile["permission"]["web_search"] == "deny"
    assert profile["permission"]["mcp_research_*"] == "ask"
    call = {"name": "mcp_research_fetch_page", "_meta": {"fx": {"toolCall": {"mcp": {"server": "research"}}}}}
    assert allowed(call, tmp_path, research=True)
    assert not allowed(call, tmp_path)
    assert not allowed({"name": "mcp_research_fetch_page"}, tmp_path, research=True)
