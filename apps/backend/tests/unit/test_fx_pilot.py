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


def test_fx_pilot_reaches_anthropic_through_its_openai_compatible_endpoint():
    connection = _connection("anthropic:claude-haiku-5-5", {"anthropic": "private-test-key"})
    assert (connection.model, connection.base_url) == ("claude-haiku-5-5", "https://api.anthropic.com/v1")


@pytest.mark.parametrize("model,keys", [
    ("openai:example-model", {"anthropic": "other-provider-key"}),
    ("google_genai:example-model", {"google_genai": "personal-key"}),
    ("https://example.test/v1:model", {"https": "personal-key"}),
])
def test_fx_pilot_rejects_missing_keys_or_unapproved_provider_endpoints(model, keys):
    with pytest.raises(ModelUnavailable):
        _connection(model, keys)


def test_fx_bindings_name_the_pinned_artifact_and_keep_todays_upgrades():
    from dotrix_backend.modules.agents import fx_pilot

    assert fx_pilot._VERSION == f"libfx-{fx_pilot._LIBFX}-chat-3"
    assert fx_pilot._DURABLE_VERSION == f"libfx-{fx_pilot._LIBFX}-delegation-3"
    assert fx_pilot._earlier_bindings("0.0.16") == {
        "libfx-0.0.15-pilot-1": True, "libfx-0.0.15-delegation-1": True,
        "libfx-0.0.16-pilot-2": False, "libfx-0.0.16-delegation-2": False,
    }


def test_the_kai_runtime_resumes_bindings_made_on_fx_0_0_16():
    from dotrix_backend.modules.agents import fx_pilot

    assert fx_pilot._earlier_bindings("0.0.17-kai.1") == {
        "libfx-0.0.15-pilot-1": True, "libfx-0.0.15-delegation-1": True,
        "libfx-0.0.16-pilot-2": False, "libfx-0.0.16-delegation-2": False,
        "libfx-0.0.16-chat-3": False, "libfx-0.0.16-delegation-3": False,
    }


def test_kai_2_resumes_bindings_made_on_kai_1_and_on_fx_0_0_16():
    from dotrix_backend.modules.agents import fx_pilot

    assert fx_pilot._earlier_bindings("0.0.17-kai.2") == {
        "libfx-0.0.15-pilot-1": True, "libfx-0.0.15-delegation-1": True,
        "libfx-0.0.16-pilot-2": False, "libfx-0.0.16-delegation-2": False,
        "libfx-0.0.16-chat-3": False, "libfx-0.0.16-delegation-3": False,
        "libfx-0.0.17-kai.1-chat-3": False, "libfx-0.0.17-kai.1-delegation-3": False,
    }


def test_a_later_artifact_upgrades_only_the_bindings_it_was_shown_to_resume(monkeypatch):
    from dotrix_backend.modules.agents import fx_pilot
    from dotrix_engine.runtimes import fx as fx_module

    monkeypatch.setitem(fx_module.LIBFX_ARTIFACTS, "0.0.17-test", ("0.0.16",))
    monkeypatch.setitem(fx_module.LIBFX_ARTIFACTS, "0.0.18-test", ())
    later = fx_pilot._earlier_bindings("0.0.17-test")
    assert later["libfx-0.0.16-chat-3"] is False and later["libfx-0.0.16-delegation-3"] is False
    assert later["libfx-0.0.16-pilot-2"] is False and later["libfx-0.0.15-pilot-1"] is True
    assert "libfx-0.0.17-test-chat-3" not in later  # its own version is current, not earlier
    # Without 0.0.16 in its list, a 0.0.16 binding is not upgraded: it fails closed for a compatible reader.
    assert not any(name.startswith("libfx-0.0.16") for name in fx_pilot._earlier_bindings("0.0.18-test"))
