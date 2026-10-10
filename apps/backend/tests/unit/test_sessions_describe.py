"""What a signed-in browser or app is called in Settings → Devices, from its User-Agent."""
import pytest

from dotrix_backend.modules.auth.models import SessionClient
from dotrix_backend.modules.auth.sessions import describe

CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
EDGE_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.0 Mobile/15E148 Safari/604.1"
)
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
DESKTOP_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "dotrix/0.1.0 Chrome/138.0.0.0 Electron/37.2.0 Safari/537.36"
)


@pytest.mark.parametrize(
    ("user_agent", "client", "device"),
    [
        (CHROME_MAC, SessionClient.WEB, "Chrome on macOS"),
        (EDGE_WINDOWS, SessionClient.WEB, "Edge on Windows"),
        (SAFARI_IPHONE, SessionClient.WEB, "Safari on iOS"),
        (FIREFOX_LINUX, SessionClient.WEB, "Firefox on Linux"),
        (DESKTOP_MAC, SessionClient.DESKTOP, "Desktop app on macOS"),
        ("python-httpx/0.28", SessionClient.OTHER, "Unknown app"),
        ("", SessionClient.OTHER, "Unknown app"),
    ],
)
def test_describe(user_agent: str, client: SessionClient, device: str) -> None:
    assert describe(user_agent) == (client, device)
