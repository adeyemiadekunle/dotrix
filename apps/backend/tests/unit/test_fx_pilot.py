"""The fx pilot uses fixed providers and the requesting person's credentials."""
import pytest

from dotrix_backend.modules.agents.fx_pilot import _connection
from dotrix_backend.modules.agents.llm import ModelUnavailable


def test_fx_pilot_resolves_a_fixed_openai_endpoint_without_exposing_the_key():
    connection = _connection("openai:example-model", {"openai": "private-test-key"})
    assert connection.model == "example-model"
    assert connection.base_url == "https://api.openai.com/v1"
    assert connection.api_key == "private-test-key"
    assert "private-test-key" not in repr(connection)


@pytest.mark.parametrize("model,keys", [
    ("openai:example-model", {"anthropic": "other-provider-key"}),
    ("anthropic:example-model", {"anthropic": "personal-key"}),
    ("https://example.test/v1:model", {"https": "personal-key"}),
])
def test_fx_pilot_rejects_missing_keys_or_unapproved_provider_endpoints(model, keys):
    with pytest.raises(ModelUnavailable):
        _connection(model, keys)
