"""Actualités gratuites : GDELT (DOC 2.0), Google News RSS, flux RSS crypto, Reddit RSS."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from ..http import Http
from .web import domain_of

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"

RSS_FEEDS = {
    # (url, type)
    "gnews_world_en": ("https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en", "news"),
    "gnews_tech_en": ("https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en", "news"),
    "gnews_business_en": ("https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en", "news"),
    "gnews_ent_en": ("https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=en-US&gl=US&ceid=US:en", "news"),
    "gnews_top_fr": ("https://news.google.com/rss?hl=fr&gl=FR&ceid=FR:fr", "news"),
    "cointelegraph": ("https://cointelegraph.com/rss", "crypto"),
    "decrypt": ("https://decrypt.co/feed", "crypto"),
    "coindesk": ("https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto"),
    "theblock": ("https://www.theblock.co/rss.xml", "crypto"),
}
REDDIT_FEEDS = ["CryptoCurrency", "solana", "memecoins", "worldnews", "technology", "artificial",
                "popular", "OutOfTheLoop"]

GDELT_QUERIES = {
    "ia": '("artificial intelligence" OR "AI agent" OR OpenAI OR chatbot)',
    "crypto": "(crypto OR bitcoin OR solana OR memecoin)",
    "politique": "(election OR president OR government OR senate)",
    "economie": '(economy OR inflation OR "stock market" OR tariffs)',
    "viral": '(viral OR meme OR trending OR "goes viral")',
    "celebrites": "(celebrity OR billionaire OR \"Elon Musk\" OR Trump)",
    "sport": "(championship OR final OR \"world cup\" OR olympics)",
    "tech": "(technology OR startup OR robot OR SpaceX OR Apple OR Google)",
}


def _ts_rss(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_feed(xml_text: str, source_type: str, feed_name: str) -> list[dict]:
    """Parse RSS 2.0 et Atom. Les données de flux sont traitées comme non fiables (texte uniquement)."""
    out = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return out
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//a:entry", ns)
    for it in items[:150]:
        title = (it.findtext("title") or it.findtext("a:title", namespaces=ns) or "").strip()
        link = it.findtext("link") or ""
        if not link:
            le = it.find("a:link", ns)
            link = le.get("href") if le is not None else ""
        pub = it.findtext("pubDate") or it.findtext("a:updated", namespaces=ns) or it.findtext("a:published", namespaces=ns)
        src_el = it.find("source")
        domain = domain_of(src_el.get("url")) if src_el is not None and src_el.get("url") else domain_of(link)
        if feed_name.startswith("gnews") and " - " in title:
            title, src_name = title.rsplit(" - ", 1)
            domain = domain or src_name.lower()
        if not title or not link:
            continue
        out.append({"url": link.strip(), "title": re.sub(r"\s+", " ", title)[:300], "domain": domain,
                    "published_at": _ts_rss(pub) or time.time(), "source_type": source_type,
                    "feed": feed_name, "lang": "fr" if feed_name.endswith("_fr") else "en", "country": None})
    return out


class News:
    def __init__(self, http: Http) -> None:
        self.http = http

    async def gdelt(self, query: str, timespan: str = "6h", maxrecords: int = 150) -> list[dict]:
        data = await self.http.get_json("gdelt", GDELT, params={
            "query": query, "mode": "ArtList", "format": "json", "maxrecords": maxrecords,
            "timespan": timespan, "sort": "DateDesc"}, timeout=12)
        out = []
        for a in (data or {}).get("articles") or []:
            seen = a.get("seendate")
            try:
                ts = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").timestamp() if seen else time.time()
            except ValueError:
                ts = time.time()
            out.append({"url": a.get("url"), "title": (a.get("title") or "").strip()[:300],
                        "domain": a.get("domain"), "published_at": ts, "source_type": "news",
                        "feed": "gdelt", "lang": (a.get("language") or "")[:2].lower() or None,
                        "country": a.get("sourcecountry")})
        return [x for x in out if x["url"] and x["title"]]

    async def rss(self, name: str) -> list[dict]:
        url, typ = RSS_FEEDS[name]
        text = await self.http.get_text("rss", url, timeout=8)
        return parse_feed(text, typ, name)

    async def reddit(self, sub: str) -> list[dict]:
        text = await self.http.get_text("reddit_rss", f"https://www.reddit.com/r/{sub}/hot/.rss?limit=50", timeout=8)
        items = parse_feed(text, "social", f"reddit_{sub}")
        for i in items:
            i["domain"] = f"reddit.com/r/{sub}"
        return items

    async def google_news_search(self, query: str, lang: str = "en") -> list[dict]:
        gl, ceid = ("FR", "FR:fr") if lang == "fr" else ("US", "US:en")
        url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={lang}&gl={gl}&ceid={ceid}"
        text = await self.http.get_text("rss", url, timeout=8)
        return parse_feed(text, "news", f"gnews_search_{lang}")
