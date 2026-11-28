"""The network policy's one format (network_policy): entries, presets, the workspace limit and its checks."""
import pytest

from dotrix_engine import network_policy as np


def test_entries_are_names_with_an_optional_port_and_443_is_the_default():
    assert np.clean([" API.Example.com. ", "api.example.com:443", "*.example.com", "registry.example.com:8443"]) == [
        "api.example.com", "*.example.com", "registry.example.com:8443"]
    assert np.parse_entry("*.example.com:8443") == np.Entry("example.com", 8443, True)


@pytest.mark.parametrize("bad", ["https://example.com", "10.0.0.1", "[::1]:443", "*.com", "localhost", "example.com:0",
                                 "example.com:x", "example.com/path", "exa mple.com"])
def test_anything_else_is_refused(bad):
    with pytest.raises(np.InvalidEntry):
        np.parse_entry(bad)


def test_presets_expand_first_and_duplicates_go():
    assert np.expand(["npm", "nope"], ["registry.npmjs.org", "x.example.com"]) == [
        "registry.npmjs.org", "registry.yarnpkg.com", "x.example.com"]


def test_a_limit_covers_what_its_entries_allow_on_the_same_port():
    limit = ["*.example.com", "pypi.org", "registry.example.org:8443"]
    assert np.within(limit, "api.example.com") and np.within(limit, "*.ci.example.com")
    assert np.within(limit, "*.example.com") and not np.within(limit, "example.com")
    assert not np.within(limit, "api.example.com:8443")  # another port
    assert np.within(limit, "pypi.org") and not np.within(limit, "*.pypi.org")
    assert not np.within(limit, "registry.example.org") and np.within(limit, "registry.example.org:8443")
    assert np.narrow(["api.example.com", "evil.org"], limit) == ["api.example.com"]
    assert np.narrow(["evil.org"], None) == ["evil.org"]  # no limit
    assert np.narrow(["evil.org"], []) == []  # a limit with nothing in it


def test_permits_checks_host_and_port():
    entries = np.parse(["*.example.com", "pypi.org"])
    assert np.permits(entries, "A.Example.com.", 443) and not np.permits(entries, "example.com", 443)
    assert not np.permits(entries, "pypi.org", 80)
