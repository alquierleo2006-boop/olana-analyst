"""GLOBAL NARRATIVE INTELLIGENCE — moteur indépendant des analyses de tokens.

Collecte (gratuite) : GDELT, Google News RSS, flux crypto, Reddit RSS.
Les reprises d'une même dépêche sont regroupées en « histoires » (story_key) pour ne pas être comptées
plusieurs fois. Une narrative = groupe de termes qui apparaissent dans les mêmes histoires.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import defaultdict

from ..providers.news import GDELT_QUERIES, REDDIT_FEEDS, RSS_FEEDS
from ..util import ESTIMATED

STOP = set("""
a an the and or but if of to in on at by for with from as is are was were be been being it its this that these those
he she they we you i his her their our your my me him them us not no yes do does did done has have had will would can
could should may might must shall about after before over under into out up down off than then so such very more most
new news says said say report reports update updates live video watch today yesterday tomorrow week year years day days
first last next just now how what why who when where which while also amid via vs per new-york people man woman world
time times back still top big get gets got make makes made take takes one two three four five six seven eight nine ten
le la les un une des du de et ou mais si au aux en dans sur par pour avec sans est sont été être ce cet cette ces il
elle ils elles nous vous je tu son sa ses leur leurs plus moins très aussi après avant selon face contre entre comme
qui que quoi dont où quand alors donc ainsi cela ça pas ne fait faire dit dire nouveau nouvelle nouveaux an ans jour
jours semaine heure heures direct vidéo here there all any some many much other another every each own same both few
amp quot http https www com reddit comments submitted link post thread daily discussion
""".split())

CATEGORIES = {
    "Intelligence artificielle": ["ai", "openai", "chatgpt", "gpt", "llm", "agent", "agents", "anthropic", "claude",
                                  "gemini", "grok", "nvidia", "robot", "deepseek", "artificial", "intelligence"],
    "Crypto / Solana": ["crypto", "bitcoin", "btc", "ethereum", "solana", "sol", "memecoin", "token", "etf", "binance",
                        "coinbase", "defi", "stablecoin", "pump", "airdrop"],
    "Politique": ["trump", "election", "president", "senate", "congress", "biden", "macron", "government", "minister",
                  "vote", "war", "ukraine", "russia", "israel", "china", "tariff", "tariffs"],
    "Économie / Finance": ["market", "stocks", "inflation", "fed", "rates", "economy", "recession", "earnings", "dollar",
                           "gold", "oil", "bank"],
    "Personnalités": ["musk", "elon", "kanye", "swift", "beast", "zuckerberg", "bezos", "kardashian", "drake"],
    "Animaux viraux": ["dog", "cat", "monkey", "penguin", "hippo", "frog", "bear", "duck", "goat", "pig", "squirrel"],
    "Culture internet": ["meme", "viral", "tiktok", "trend", "trending", "internet", "youtube", "streamer"],
    "Technologie": ["apple", "google", "spacex", "tesla", "iphone", "microsoft", "quantum", "chip", "launch", "rocket"],
    "Sport": ["cup", "championship", "nba", "nfl", "football", "soccer", "olympics", "final", "match", "f1"],
}
POS = set("win wins won surge soars record rally boom breakthrough approve approved launch success gains rise rises "
          "historic love viral celebrates bullish pump jump jumps".split())
NEG = set("crash crashes dies dead death war attack lawsuit ban banned hack hacked scam fraud fall falls plunge "
          "plunges fear crisis collapse arrested bearish dump loss losses fire".split())

SHORT_OK = {"ai", "ia", "uk", "eu", "f1"}
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9$#][A-Za-zÀ-ÿ0-9'’\-]{1,30}")


def tokenize(title: str) -> list[str]:
    words = [w.lower().strip("'’-").lstrip("#") for w in WORD_RE.findall(title)]
    return [w for w in words if (len(w) >= 3 or w in SHORT_OK) and w not in STOP and not w.isdigit()]


def terms_of(title: str) -> list[str]:
    words = tokenize(title)
    bigrams = [f"{a} {b}" for a, b in zip(words, words[1:])]
    return list(dict.fromkeys(words + bigrams))


def story_key(title: str) -> str:
    return " ".join(sorted(set(tokenize(title)))[:8])


def categorize(terms: list[str]) -> str:
    best, n = "Actualités mondiales", 0
    flat = set(" ".join(terms).split())
    for cat, kws in CATEGORIES.items():
        k = len(flat & set(kws))
        if k > n:
            best, n = cat, k
    return best


def sentiment(titles: list[str]) -> dict:
    p = n = 0
    for t in titles:
        ws = set(tokenize(t))
        p += len(ws & POS)
        n += len(ws & NEG)
    tot = p + n
    val = (p - n) / tot if tot else 0.0
    label = "positif" if val > 0.2 else "négatif" if val < -0.2 else "neutre / mixte"
    return {"value": round(val, 2), "label": label, "method": "lexique simple (approximatif)"}


class NarrativeEngine:
    def __init__(self, http, news, dex, db, settings, notify=None) -> None:
        self.http, self.news, self.dex, self.db, self.settings = http, news, dex, db, settings
        self.notify = notify or (lambda *a, **k: None)
        self.status = {"state": "arrêté", "last_collect": None, "last_compute": None, "articles_48h": 0,
                       "errors": [], "sources_ok": 0, "sources_failed": 0}
        self._task: asyncio.Task | None = None
        self._first = True
        self._lock = asyncio.Lock()

    # -------------------------------------------------------------- collecte
    async def collect(self) -> int:
        prov = self.settings.get("providers", {})
        jobs: list = []
        if prov.get("rss", True):
            jobs += [self.news.rss(n) for n in RSS_FEEDS]
        if prov.get("reddit_rss", True):
            jobs += [self.news.reddit(s) for s in REDDIT_FEEDS]
        results = await asyncio.gather(*jobs, return_exceptions=True)
        if prov.get("gdelt", True):
            span = "24h" if self._first else "2h"
            for q in GDELT_QUERIES.values():  # séquentiel : limite GDELT ~1 requête / 5 s
                try:
                    results.append(await self.news.gdelt(q, timespan=span, maxrecords=150))
                except Exception as exc:
                    results.append(exc)
        ok = [r for r in results if isinstance(r, list)]
        errs = [str(r)[:150] for r in results if isinstance(r, Exception)]
        self.status.update(sources_ok=len(ok), sources_failed=len(errs), errors=errs[:8])
        n = 0
        now = time.time()
        rows = []
        for lst in ok:
            for a in lst:
                if not a.get("url") or not a.get("title"):
                    continue
                pub = min(a.get("published_at") or now, now)
                rows.append((a["url"][:800], a["title"], a.get("domain"), a.get("source_type"), pub, now,
                             a.get("country"), a.get("lang"), story_key(a["title"]), json.dumps(terms_of(a["title"]))))
        before = self.db.one("SELECT COUNT(*) c FROM news_articles")["c"]
        self.db.executemany("INSERT OR IGNORE INTO news_articles(url, title, domain, source_type, published_at, "
                            "fetched_at, country, lang, story_key, terms) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        n = self.db.one("SELECT COUNT(*) c FROM news_articles")["c"] - before
        self._first = False
        self.status["last_collect"] = now
        return n

    # -------------------------------------------------------------- calcul
    def compute_terms(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        arts = self.db.all("SELECT title, url, domain, source_type, published_at, country, story_key, terms "
                           "FROM news_articles WHERE published_at > ?", (now - 48 * 3600,))
        self.status["articles_48h"] = len(arts)
        stats: dict[str, dict] = defaultdict(lambda: {"recent": set(), "base": set(), "all": set(), "domains": set(),
                                                      "types": set(), "countries": set(), "first": now, "titles": []})
        for a in arts:
            age_h = (now - a["published_at"]) / 3600
            for t in json.loads(a["terms"] or "[]"):
                s = stats[t]
                if age_h <= 24:
                    s["all"].add(a["story_key"])
                    (s["recent"] if age_h <= 3 else s["base"]).add(a["story_key"])
                    if a["domain"]:
                        s["domains"].add(a["domain"])
                    s["types"].add(a["source_type"])
                    if a["country"]:
                        s["countries"].add(a["country"])
                    if len(s["titles"]) < 40:
                        s["titles"].append(a)
                s["first"] = min(s["first"], a["published_at"])
        out = []
        for term, s in stats.items():
            vol = len(s["all"])
            if vol < 3 or len(s["domains"]) < 2:
                continue
            rate_recent = len(s["recent"]) / 3
            rate_base = (len(s["base"]) + 0.5) / 21
            accel = rate_recent / rate_base
            crypto = 1 if ({"crypto", "social"} & s["types"]) else 0
            interest = (math.log1p(vol) * 1.0 + math.log(max(accel, 0.2)) * 1.4 +
                        math.log1p(len(s["domains"])) * 0.8 + 0.6 * crypto + (0.25 if " " in term else 0))
            out.append({"term": term, "volume": vol, "recent": len(s["recent"]), "acceleration": round(accel, 2),
                        "domains": len(s["domains"]), "countries": len(s["countries"]), "types": sorted(s["types"]),
                        "first_seen": s["first"], "stories": s["all"], "titles": s["titles"],
                        "interest": round(interest, 3)})
        out.sort(key=lambda x: -x["interest"])
        return out

    def group(self, terms: list[dict], limit: int = 30) -> list[dict]:
        narratives: list[dict] = []
        for t in terms[:400]:
            placed = False
            for n in narratives:
                inter = len(t["stories"] & n["stories"])
                if inter / max(1, min(len(t["stories"]), len(n["stories"]))) >= 0.6:
                    if len(n["keywords"]) < 8:
                        n["keywords"].append(t["term"])
                    n["stories"] |= t["stories"]
                    placed = True
                    break
            if not placed and len(narratives) < limit:
                narratives.append({**t, "keywords": [t["term"]], "stories": set(t["stories"])})
        return narratives

    @staticmethod
    def lifecycle(n: dict, tokens_24h: int | None) -> str:
        vol, acc = n["volume"], n["acceleration"]
        if tokens_24h is not None and tokens_24h >= 15 and acc < 2:
            return "SATURÉE"
        if acc >= 2 and vol < 8:
            return "ÉMERGENTE"
        if acc >= 1.6:
            return "EN ACCÉLÉRATION"
        if vol >= 20 and n["domains"] >= 8 and acc >= 0.9:
            return "VIRALE"
        if acc < 0.5:
            return "EN DÉCLIN"
        return "MATURE"

    async def compute(self) -> list[dict]:
        terms = self.compute_terms()
        groups = self.group(terms)
        now = time.time()
        ranked = []
        for i, n in enumerate(groups):
            name = next((k for k in n["keywords"] if " " in k), n["keywords"][0])
            titles = sorted(n["titles"], key=lambda a: a["published_at"])
            trigger = titles[0] if titles else None
            tokens, tokens_24h = [], None
            if i < 12:  # recherche de tokens Solana associés pour les narratives en tête
                try:
                    pairs = await self.dex.search(name)
                    seen = {}
                    for p in pairs:
                        a = (p.get("baseToken") or {}).get("address")
                        if a and a not in seen:
                            seen[a] = p
                    tokens_24h = sum(1 for p in seen.values()
                                     if p.get("pairCreatedAt") and now - p["pairCreatedAt"] / 1000 < 86400)
                    tokens = sorted(({"mint": a, "symbol": (p.get("baseToken") or {}).get("symbol"),
                                      "mcap": p.get("marketCap"), "volume_24h": (p.get("volume") or {}).get("h24"),
                                      "created_at": (p.get("pairCreatedAt") or 0) / 1000 or None}
                                     for a, p in seen.items()), key=lambda x: -(x["volume_24h"] or 0))[:5]
                except Exception:
                    tokens_24h = None
            state = self.lifecycle(n, tokens_24h)
            saturation = min(1.0, (tokens_24h or 0) / 20) if tokens_24h is not None else None
            cont = n["interest"] * (1.25 if state in ("ÉMERGENTE", "EN ACCÉLÉRATION") else
                                    0.6 if state in ("SATURÉE", "EN DÉCLIN") else 1.0)
            ranked.append({
                "name": name, "keywords": n["keywords"], "category": categorize(n["keywords"]),
                "description": f"{n['volume']} histoires distinctes en 24 h sur {n['domains']} sources ; "
                               f"{n['recent']} sur les 3 dernières heures.",
                "trigger": {"title": trigger["title"], "url": trigger["url"], "domain": trigger["domain"],
                            "published_at": trigger["published_at"]} if trigger else None,
                "sources": [{"title": a["title"], "url": a["url"], "domain": a["domain"]} for a in titles[-6:]],
                "first_seen": n["first_seen"], "volume_24h": n["volume"], "recent_3h": n["recent"],
                "acceleration": n["acceleration"], "unique_sources": n["domains"], "countries": n["countries"],
                "source_types": n["types"], "state": state, "saturation": saturation,
                "solana_tokens_24h": tokens_24h, "solana_tokens": tokens,
                "sentiment": sentiment([a["title"] for a in titles]),
                "continuation_score": round(cont, 2), "status": ESTIMATED,
            })
        ranked.sort(key=lambda r: -r["continuation_score"])
        self.db.execute("DELETE FROM narratives WHERE computed_at < ?", (now - 7 * 86400,))
        self.db.executemany("INSERT INTO narratives(computed_at, rank, name, data) VALUES(?,?,?,?)",
                            [(now, i + 1, r["name"], json.dumps(r)) for i, r in enumerate(ranked)])
        self._detect_changes(ranked)
        self.status["last_compute"] = now
        return ranked

    def _detect_changes(self, ranked: list[dict]) -> None:
        prev = self.latest(offset_batch=1)
        prev_state = {r["name"]: r["state"] for r in prev}
        for r in ranked[:10]:
            if r["state"] == "EN ACCÉLÉRATION" and prev_state.get(r["name"]) not in (None, "EN ACCÉLÉRATION"):
                self.notify("narrative_acceleration", {"name": r["name"], "state": r["state"]})

    def latest(self, offset_batch: int = 0) -> list[dict]:
        batches = self.db.all("SELECT DISTINCT computed_at FROM narratives ORDER BY computed_at DESC LIMIT 2")
        if len(batches) <= offset_batch:
            return []
        ts = batches[offset_batch]["computed_at"]
        return [json.loads(r["data"]) | {"rank": r["rank"], "computed_at": ts}
                for r in self.db.all("SELECT rank, data FROM narratives WHERE computed_at=? ORDER BY rank", (ts,))]

    async def refresh(self) -> list[dict]:
        async with self._lock:
            self.status["state"] = "collecte"
            try:
                await self.collect()
                self.status["state"] = "calcul"
                return await self.compute()
            finally:
                self.status["state"] = "actif"

    async def loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception as exc:  # le moteur ne doit jamais s'arrêter sur une erreur réseau
                self.status["errors"] = [str(exc)[:200]]
            await asyncio.sleep(max(2, int(self.settings.get("narrative_refresh_minutes", 10))) * 60)

    def start(self) -> None:
        if not self._task:
            self.status["state"] = "actif"
            self._task = asyncio.create_task(self.loop())


# ------------------------------------------------------------------ corrélation token ↔ narratives
STATE_VALUE = {"ÉMERGENTE": 8.5, "EN ACCÉLÉRATION": 9.0, "VIRALE": 7.5, "MATURE": 5.5, "SATURÉE": 3.5, "EN DÉCLIN": 3.0}


async def run_narrative(ctx, engine: NarrativeEngine) -> None:
    N = ctx.section("narrative")
    tok = ctx.result.get("token", {})
    name, symbol = tok.get("name") or "", tok.get("symbol") or ""
    desc = (tok.get("description") or {}).get("v") or ""
    if not desc:
        await ctx.need("social", timeout=6)
        desc = ((ctx.result.get("token", {}).get("description") or {}).get("v")) or ""
    token_terms = set(tokenize(f"{name} {symbol}")) | set(tokenize(desc)[:40])
    core_terms = set(tokenize(f"{name} {symbol}"))
    N["token_terms"] = sorted(core_terms)
    narratives = engine.latest()
    N["engine_status"] = {"last_compute": engine.status.get("last_compute"), "articles_48h": engine.status.get("articles_48h")}
    if not narratives:
        N["score"] = {"score": None, "confidence": 0.0, "reasons": ["moteur de narratives pas encore prêt (1re collecte en cours)"],
                      "available": False}
        return
    matches = []
    for n in narratives:
        kw = set(" ".join(n["keywords"]).split())
        core_hit = {t for t in core_terms for k in kw if _term_match(t, k)}
        desc_hit = {t for t in token_terms - core_terms for k in kw if _term_match(t, k)}
        strength = min(1.0, 0.7 * len(core_hit) + 0.2 * len(desc_hit))
        if strength >= 0.3:
            matches.append({"name": n["name"], "state": n["state"], "rank": n["rank"], "strength": round(strength, 2),
                            "matched_terms": sorted(core_hit | desc_hit), "acceleration": n["acceleration"],
                            "solana_tokens_24h": n.get("solana_tokens_24h"), "category": n["category"],
                            "trigger": n.get("trigger")})
    matches.sort(key=lambda m: -(m["strength"] * STATE_VALUE.get(m["state"], 5)))
    N["matches"] = matches[:5]

    # Concurrence : autres tokens Solana au même nom / ticker
    competitors = None
    if symbol or name:
        try:
            pairs = await ctx.svc.dex.search(symbol or name)
            same = {}
            for p in pairs:
                bt = p.get("baseToken") or {}
                if bt.get("address") != ctx.mint and (_eq(bt.get("symbol"), symbol) or _eq(bt.get("name"), name)):
                    same[bt["address"]] = p
            mine_created = (ctx.result.get("market", {}).get("first_pair_at") or {}).get("v")
            older = [p for p in same.values() if p.get("pairCreatedAt") and mine_created
                     and p["pairCreatedAt"] / 1000 < mine_created]
            competitors = {"count": len(same), "older_count": len(older),
                           "bigger_count": sum(1 for p in same.values()
                                               if (p.get("marketCap") or 0) > ((ctx.result.get("market", {}).get("mcap") or {}).get("v") or 0)),
                           "source": "DexScreener"}
        except Exception as exc:
            competitors = {"error": str(exc)}
    N["competitors"] = competitors

    reasons = []
    if matches:
        best = matches[0]
        base = STATE_VALUE.get(best["state"], 5) * (0.55 + 0.45 * best["strength"])
        reasons.append(f"correspond à la narrative « {best['name']} » ({best['state']}, rang {best['rank']})")
        conf = 0.55
    else:
        base = 3.0
        reasons.append("aucune narrative suivie (actualités / Reddit) ne correspond au nom du token")
        conf = 0.35
    if competitors and competitors.get("count"):
        pen = min(2.5, 0.25 * competitors["count"])
        if competitors.get("bigger_count"):
            pen += 0.5
            reasons.append(f"{competitors['bigger_count']} token(s) homonyme(s) plus gros : pas d'avantage narratif")
        base -= pen
        reasons.append(f"{competitors['count']} autre(s) token(s) Solana au même nom / ticker")
    elif competitors and competitors.get("count") == 0:
        reasons.append("aucun homonyme : identité narrative unique")
    N["score"] = {"score": round(max(0, min(10, base)), 1), "confidence": conf, "reasons": reasons,
                  "available": True, "status": ESTIMATED,
                  "coverage_note": "Couverture : médias, GDELT et Reddit. Les tendances nées uniquement sur X "
                                   "ne sont visibles qu'une fois reprises ailleurs (API X payante)."}


def _term_match(t: str, k: str) -> bool:
    """Égalité, ou préfixe commun pour les mots ≥ 4 lettres (robo ↔ robots, agent ↔ agents)."""
    if t == k:
        return True
    if len(t) >= 4 and len(k) >= 4:
        return k.startswith(t) or t.startswith(k)
    return False


def _eq(a, b) -> bool:
    return bool(a and b) and re.sub(r"\W", "", a.lower()) == re.sub(r"\W", "", b.lower())
