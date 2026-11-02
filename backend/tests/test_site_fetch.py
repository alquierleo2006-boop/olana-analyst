import asyncio

import pytest

from analyst.http import Http
from analyst.providers.web import SiteUnreadable, Web

from .fakes import MINT, Fake


def _web():
    return Web(Http(Fake().transport()))


def test_javascript_site_read_through_its_bundle():
    site = asyncio.run(_web().fetch_site("spa.example"))
    assert site["javascript_site"] and site["js_files_read"] == 1
    assert MINT in site["raw"]
    assert any("x.com/robocatsol" in l for l in site["links"]) and any("github.com/robocat/agent" in l for l in site["links"])
    assert site["description"] == "Autonomous AI agent cat"


@pytest.mark.parametrize("url,reason", [
    ("blocked.example", "protégé contre les robots"),
    ("challenge.example", "Cloudflare"),
    ("dead.example", "injoignable"),
])
def test_unreadable_sites_explain_why(url, reason):
    with pytest.raises(SiteUnreadable) as e:
        asyncio.run(_web().fetch_site(url))
    assert reason in e.value.reason


def test_browser_like_headers():
    seen = {}

    class T(Fake):
        def handle(self, req):
            seen["ua"] = req.headers.get("user-agent", "")
            return super().handle(req)
    asyncio.run(Web(Http(T().transport())).fetch_site("robocat.example"))
    assert seen["ua"].startswith("Mozilla/5.0")
