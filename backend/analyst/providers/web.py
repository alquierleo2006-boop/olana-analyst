"""Vérifications web et sociales SANS contournement : uniquement pages publiques et API ouvertes.

- Site web : téléchargé en texte brut (aucun JavaScript exécuté), taille limitée.
- RDAP : date d'enregistrement du domaine (protocole public officiel).
- X : oEmbed public (publish.twitter.com) — confirme l'existence/l'auteur d'un tweet ; aucun scraping.
- Telegram : page d'aperçu publique t.me (nombre de membres).
- Discord : endpoint public d'invitation (membres / en ligne).
- GitHub : API publique.
"""
from __future__ import annotations

import html as htmllib
import re
from urllib.parse import urlparse

from ..http import Http, ProviderError

HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#][^"']*)["']""", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
META_DESC_RE = re.compile(r"""<meta[^>]+name=["']description["'][^>]+content=["']([^"']*)""", re.I)
TAG_RE = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.I | re.S)


def domain_of(url: str) -> str | None:
    try:
        host = urlparse(url if "://" in url else f"https://{url}").hostname or ""
    except ValueError:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host or None


def registrable_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def classify_link(url: str) -> tuple[str, dict]:
    """Retourne (plateforme, détails) pour un lien social."""
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    p = urlparse(u)
    host = (p.hostname or "").lower().removeprefix("www.").removeprefix("mobile.")
    parts = [x for x in p.path.split("/") if x]
    if host in ("x.com", "twitter.com"):
        if len(parts) >= 3 and parts[1] == "status":
            return "x", {"kind": "tweet", "handle": parts[0].lower(), "id": parts[2], "url": u}
        if parts and parts[0] == "i" and len(parts) >= 3 and parts[1] == "communities":
            return "x", {"kind": "community", "id": parts[2], "url": u}
        if parts and parts[0] not in ("search", "hashtag", "i", "home", "intent"):
            return "x", {"kind": "profile", "handle": parts[0].lower(), "url": u}
        return "x", {"kind": "other", "url": u}
    if host in ("t.me", "telegram.me"):
        name = parts[0] if parts else ""
        return "telegram", {"kind": "private_invite" if name.startswith("+") or name == "joinchat" else "public",
                            "name": name, "url": u}
    if host in ("discord.gg", "discord.com", "discordapp.com"):
        code = parts[-1] if parts else ""
        return "discord", {"code": code, "url": u}
    if host == "github.com":
        return "github", {"owner": parts[0] if parts else None, "repo": parts[1] if len(parts) > 1 else None, "url": u}
    for plat, hosts in {"instagram": ("instagram.com",), "tiktok": ("tiktok.com",),
                        "youtube": ("youtube.com", "youtu.be"), "medium": ("medium.com",),
                        "reddit": ("reddit.com",)}.items():
        if host in hosts or host.endswith(tuple("." + h for h in hosts)):
            return plat, {"url": u, "name": parts[0] if parts else None}
    return "website", {"url": u, "domain": host}


class Web:
    def __init__(self, http: Http) -> None:
        self.http = http

    async def fetch_site(self, url: str) -> dict:
        if "://" not in url:
            url = "https://" + url
        r = await self.http.request("website", "GET", url, timeout=5, max_bytes=1_500_000, retries=0,
                                    headers={"Accept": "text/html"})
        body = r.text[:1_500_000]
        title = TITLE_RE.search(body)
        desc = META_DESC_RE.search(body)
        text = htmllib.unescape(TAG_RE.sub(" ", body))
        text = re.sub(r"\s+", " ", text).strip()
        links = sorted({htmllib.unescape(h) for h in HREF_RE.findall(body)})
        return {"final_url": str(r.url), "status": r.status_code,
                "title": htmllib.unescape(title.group(1).strip())[:200] if title else None,
                "description": htmllib.unescape(desc.group(1))[:500] if desc else None,
                "text": text[:20000], "links": links[:400], "https": str(r.url).startswith("https://")}

    async def domain_registration(self, domain: str) -> dict | None:
        try:
            data = await self.http.get_json("rdap", f"https://rdap.org/domain/{registrable_domain(domain)}", timeout=6)
        except ProviderError:
            return None
        out = {}
        for ev in data.get("events") or []:
            if ev.get("eventAction") in ("registration", "expiration", "last changed"):
                out[ev["eventAction"]] = ev.get("eventDate")
        return out

    async def x_oembed(self, url: str) -> dict | None:
        try:
            return await self.http.get_json("x_oembed", "https://publish.twitter.com/oembed",
                                            params={"url": url, "omit_script": "1", "dnt": "true"}, timeout=5)
        except ProviderError as exc:
            if exc.status == 404:
                return {"not_found": True}
            raise

    async def telegram_public(self, name: str) -> dict:
        body = await self.http.get_text("telegram_public", f"https://t.me/{name}", timeout=5)
        title = re.search(r'<div class="tgme_page_title"[^>]*>\s*<span[^>]*>(.*?)</span>', body, re.S)
        extra = re.search(r'<div class="tgme_page_extra">(.*?)</div>', body, re.S)
        desc = re.search(r'<div class="tgme_page_description[^"]*"[^>]*>(.*?)</div>', body, re.S)
        info = {"exists": bool(title), "title": htmllib.unescape(title.group(1)).strip() if title else None,
                "raw_extra": None, "members": None, "online": None, "kind": None,
                "description": htmllib.unescape(TAG_RE.sub(" ", desc.group(1))).strip()[:500] if desc else None}
        if extra:
            raw = htmllib.unescape(TAG_RE.sub(" ", extra.group(1))).strip()
            info["raw_extra"] = raw
            num = lambda s: int(re.sub(r"[^\d]", "", s)) if s else None  # noqa: E731
            m = re.search(r"([\d\s.,]+)\s*(members|subscribers)", raw)
            if m:
                info["members"], info["kind"] = num(m.group(1)), "group" if m.group(2) == "members" else "channel"
            o = re.search(r"([\d\s.,]+)\s*online", raw)
            if o:
                info["online"] = num(o.group(1))
        return info

    async def discord_invite(self, code: str) -> dict | None:
        try:
            data = await self.http.get_json("discord_public", f"https://discord.com/api/v9/invites/{code}",
                                            params={"with_counts": "true"}, timeout=5)
        except ProviderError as exc:
            if exc.status == 404:
                return {"not_found": True}
            raise
        g = data.get("guild") or {}
        return {"guild": g.get("name"), "guild_id": g.get("id"),
                "members": data.get("approximate_member_count"), "online": data.get("approximate_presence_count"),
                "expires_at": data.get("expires_at")}

    async def github(self, owner: str, repo: str | None, token: str | None = None) -> dict | None:
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        path = f"repos/{owner}/{repo}" if repo else f"users/{owner}"
        try:
            d = await self.http.get_json("github", f"https://api.github.com/{path}", headers=headers, timeout=6)
        except ProviderError as exc:
            if exc.status == 404:
                return {"not_found": True}
            raise
        keys = ("created_at", "updated_at", "pushed_at", "stargazers_count", "forks_count", "public_repos",
                "followers", "description", "archived", "fork", "size", "language", "full_name", "html_url")
        out = {k: d.get(k) for k in keys if k in d}
        if d.get("parent"):
            out["parent"] = d["parent"].get("full_name")
        return out

    async def github_search(self, query: str, token: str | None = None, limit: int = 5) -> list[dict]:
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        d = await self.http.get_json("github", "https://api.github.com/search/repositories",
                                     params={"q": query, "sort": "stars", "order": "desc", "per_page": limit},
                                     headers=headers, timeout=6)
        return [{"repo": i.get("full_name"), "url": i.get("html_url"), "stars": i.get("stargazers_count"),
                 "description": (i.get("description") or "")[:200], "created_at": i.get("created_at"),
                 "fork": i.get("fork")} for i in (d or {}).get("items") or []]

    async def github_top_repo(self, owner: str, token: str | None = None) -> dict | None:
        """Pour un lien vers un compte/organisation : le dépôt le plus récemment modifié."""
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for kind in ("orgs", "users"):
            try:
                repos = await self.http.get_json("github", f"https://api.github.com/{kind}/{owner}/repos",
                                                 params={"sort": "pushed", "per_page": 5}, headers=headers, timeout=6)
            except ProviderError:
                continue
            if isinstance(repos, list) and repos:
                best = max(repos, key=lambda r: (not r.get("fork"), r.get("pushed_at") or ""))
                return await self.github(owner, best["name"], token)
        return None

    async def metadata_json(self, uri: str) -> dict | None:
        if not uri:
            return None
        if uri.startswith("ipfs://"):
            uri = "https://ipfs.io/ipfs/" + uri[7:]
        try:
            data = await self.http.get_json("metadata", uri, timeout=5, max_bytes=300_000, retries=0)
            return data if isinstance(data, dict) else None
        except ProviderError:
            return None
