"""Authenticité sociale, crédibilité du projet et vérification des affirmations.

Règle : une donnée qui ne peut pas être vérifiée avec un accès autorisé est affichée NON VÉRIFIÉ.
Aucun contournement des protections des plateformes (pas de scraping de X, Instagram, TikTok).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime

from ..providers.web import classify_link, domain_of, registrable_domain
from ..util import ESTIMATED, dp

AUTH_VERIFIED = "AUTHENTIQUE VÉRIFIÉ"
AUTH_PROBABLE = "PROBABLEMENT AUTHENTIQUE"
SUSPECT = "SUSPECT"
IMPERSONATION = "USURPATION PROBABLE"
NOT_VERIFIED = "NON VÉRIFIÉ"
NOT_FOUND = "NON TROUVÉ"

# Comptes de personnalités / marques : un token qui les déclare comme « son » compte ne prouve rien.
FAMOUS_HANDLES = {
    "elonmusk", "realdonaldtrump", "potus", "whitehouse", "cz_binance", "vitalikbuterin", "saylor", "kanyewest",
    "kimkardashian", "mrbeast", "sama", "openai", "nasa", "spacex", "tesla", "binance", "coinbase", "solana",
    "aeyakovenko", "rajgokal", "pumpdotfun", "jupiterexchange", "raydiumprotocol", "x", "twitter", "google",
    "apple", "nvidia", "microsoft", "cnn", "bbcworld", "nytimes", "reuters", "billgates", "barackobama",
    "taylorswift13", "cristiano", "kingjames", "snoopdogg", "jack", "naval", "a16z", "blackrock", "anthropicai",
    "grok", "xai", "metaai", "zuck", "jeffbezos", "markcuban", "justinsuntron", "melaniatrump", "donaldjtrumpjr",
}
CLAIM_PATTERNS = re.compile(
    r"([^.!?\n]{0,160}\b(partner(?:ed|ship)?s?|partenaire|partenariat|backed by|soutenu par|endorsed|official(?:ly)?|"
    r"officiel(?:le)?|collaborat\w+|in collaboration with|listed on|listing|supported by|affiliated|incubated|"
    r"invested|investors?|approved by|launched by|created by|fondé par|founded by)\b[^.!?\n]{0,160})", re.I)


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


async def run_social(ctx) -> None:
    svc = ctx.svc
    S = ctx.section("social")
    tok = ctx.section("token")
    dex_info = await ctx.need("dex_info", timeout=6) or {}
    uri = await ctx.need("metadata_uri", timeout=4)
    meta_r, pump_r = await asyncio.gather(svc.web.metadata_json(uri) if uri else _none(),
                                          svc.pump.coin(ctx.mint), return_exceptions=True)
    meta = meta_r if isinstance(meta_r, dict) else {}
    pump = pump_r if isinstance(pump_r, dict) else {}

    links: dict[str, dict] = {}

    def add(url, source):
        if not url or not isinstance(url, str) or len(url) > 500:
            return
        plat, det = classify_link(url)
        key = det.get("url", url).rstrip("/").lower()
        entry = links.setdefault(key, {"platform": plat, **det, "declared_by": []})
        if source not in entry["declared_by"]:
            entry["declared_by"].append(source)

    for w in dex_info.get("websites") or []:
        add(w.get("url"), "DexScreener")
    for s in dex_info.get("socials") or []:
        add(s.get("url"), "DexScreener")
    for k in ("website", "twitter", "telegram", "discord"):
        add(meta.get(k) or (meta.get("extensions") or {}).get(k), "métadonnées on-chain (déclarées par le créateur)")
        add(pump.get(k), "pump.fun")
    descs = [d.strip() for d in (meta.get("description"), pump.get("description")) if isinstance(d, str) and d.strip()]
    desc = "\n".join(dict.fromkeys(descs))
    if desc:
        tok["description"] = dp(desc[:2000], "métadonnées du token (déclaratif, non fiable)", "non vérifié")
    if meta.get("image") or pump.get("image_uri"):
        tok.setdefault("image", meta.get("image") or pump.get("image_uri"))

    name, symbol = tok.get("name") or "", tok.get("symbol") or ""
    accounts = list(links.values())
    S["links_count"] = len(accounts)
    site_info: dict = {}

    async def verify(acc):
        try:
            return await asyncio.wait_for(_verify(svc, acc, ctx.mint, name, symbol, site_info), 8)
        except Exception as exc:
            acc.update(status=NOT_VERIFIED, reasons=[f"vérification impossible : {type(exc).__name__}"])
            return acc

    # Le site d'abord (ses liens servent à recouper les autres comptes).
    sites = [a for a in accounts if a["platform"] == "website"]
    others = [a for a in accounts if a["platform"] != "website"]
    await asyncio.gather(*[verify(a) for a in sites])
    await asyncio.gather(*[verify(a) for a in others])

    # Liens réutilisés par d'autres tokens déjà analysés : signal de copie.
    for a in accounts:
        rows = svc.db.all("SELECT DISTINCT mint FROM social_accounts WHERE url=? AND mint<>?", (a["url"], ctx.mint))
        if rows and a["platform"] in ("website", "x", "telegram"):
            a.setdefault("reasons", []).append(f"lien déjà déclaré par {len(rows)} autre(s) token(s) analysé(s)")
            if a.get("status") in (AUTH_PROBABLE, NOT_VERIFIED):
                a["status"] = SUSPECT
    for a in accounts:
        svc.db.execute("INSERT INTO social_accounts(mint, platform, url, status, reasons, checked_at) VALUES(?,?,?,?,?,?)",
                       (ctx.mint, a["platform"], a["url"], a.get("status"), json.dumps(a.get("reasons", [])), time.time()))

    by_platform = {}
    for plat in ("x", "telegram", "discord", "website", "github", "instagram", "tiktok", "youtube", "medium", "reddit"):
        found = [a for a in accounts if a["platform"] == plat]
        by_platform[plat] = found or [{"platform": plat, "status": NOT_FOUND,
                                       "reasons": ["aucun lien déclaré par le token sur DexScreener / métadonnées / pump.fun"]}]
    S["accounts"] = by_platform
    S["links"] = {p: [a["url"] for a in v if a.get("url")] for p, v in by_platform.items()}
    S["limitations"] = [
        "Audience, croissance et engagement sur X non mesurés : l'API X est payante. Seule l'existence d'un tweet "
        "ou d'un compte est vérifiée via oEmbed public.",
        "Instagram et TikTok : pas d'accès public autorisé pour vérifier les comptes.",
        "Telegram : seules les données publiques de la page d'aperçu (membres, en ligne) sont lues.",
    ]
    S["score"] = social_score(by_platform)
    ctx.provide("site", site_info)
    ctx.provide("social", S)


async def _none():
    return None


async def _verify(svc, a: dict, mint: str, name: str, symbol: str, site_info: dict) -> dict:
    plat = a["platform"]
    reasons: list[str] = []
    a["reasons"] = reasons
    declared_onchain = any("on-chain" in d for d in a["declared_by"])
    if declared_onchain:
        reasons.append("déclaré dans les métadonnées du token (contrôlées par le créateur)")
    if plat == "website":
        site = await svc.web.fetch_site(a["url"])
        dom = domain_of(site["final_url"]) or a.get("domain")
        reg = await svc.web.domain_registration(dom) if dom else None
        a.update(title=site.get("title"), final_url=site["final_url"], domain=dom, https=site["https"])
        mentions_mint = mint in site["text"] or any(mint in l for l in site["links"])
        a["mentions_mint"] = mentions_mint
        if reg and reg.get("registration"):
            a["domain_registered"] = reg["registration"]
            try:
                age_d = (time.time() - datetime.fromisoformat(reg["registration"].replace("Z", "+00:00")).timestamp()) / 86400
                a["domain_age_days"] = round(age_d, 1)
                reasons.append(f"domaine enregistré il y a {age_d:.0f} jour(s) (RDAP)")
            except ValueError:
                pass
        else:
            reasons.append("date d'enregistrement du domaine indisponible")
        low = site["text"].lower()
        if any(x in low for x in ("lorem ipsum", "coming soon", "under construction")):
            reasons.append("contenu de remplissage détecté (lorem ipsum / coming soon)")
        site_info.update(text=site["text"], links=site["links"], domain=dom, title=site.get("title"),
                         description=site.get("description"), domain_age_days=a.get("domain_age_days"))
        if mentions_mint:
            reasons.append("le site affiche l'adresse exacte du token (lien bidirectionnel)")
            a["status"] = AUTH_VERIFIED
        elif symbol and (_norm(symbol) in _norm(site["text"][:5000]) or _norm(name) in _norm(site.get("title"))):
            reasons.append("le site mentionne le nom / ticker mais pas l'adresse du token")
            a["status"] = AUTH_PROBABLE
        else:
            reasons.append("le site ne mentionne ni l'adresse ni le ticker du token")
            a["status"] = SUSPECT
        return a

    site_links = [l.lower() for l in site_info.get("links", [])]
    if plat == "x":
        handle = a.get("handle")
        if handle and handle in FAMOUS_HANDLES:
            a["status"] = IMPERSONATION
            reasons.append(f"@{handle} est le compte d'une personnalité / marque connue, pas un compte du token")
            return a
        if a.get("kind") == "tweet":
            emb = await svc.web.x_oembed(a["url"])
            if emb and emb.get("not_found"):
                a["status"] = SUSPECT; reasons.append("tweet introuvable (supprimé ou inexistant)")
                return a
            text = re.sub(r"<[^>]+>", " ", (emb or {}).get("html", ""))
            a["tweet_author"] = (emb or {}).get("author_name")
            a["tweet_excerpt"] = re.sub(r"\s+", " ", text)[:280]
            if mint in text or (symbol and f"${symbol.lower()}" in text.lower()):
                a["status"] = AUTH_PROBABLE; reasons.append("le tweet existe et mentionne le token (oEmbed public)")
            else:
                a["status"] = NOT_VERIFIED
                reasons.append("le lien X pointe vers un tweet (souvent la source de la narrative), pas vers un compte officiel")
            return a
        if a.get("kind") == "community":
            a["status"] = NOT_VERIFIED; reasons.append("communauté X : contenu non accessible sans l'API X payante")
            return a
        emb = await svc.web.x_oembed(a["url"]) if handle else None
        if emb and emb.get("not_found"):
            a["status"] = SUSPECT; reasons.append("compte X introuvable via oEmbed (suspendu ou inexistant)")
            return a
        on_site = handle and any(f"x.com/{handle}" in l or f"twitter.com/{handle}" in l for l in site_links)
        if on_site and site_info.get("text") and mint in site_info["text"]:
            a["status"] = AUTH_PROBABLE
            reasons.append("compte lié depuis le site officiel qui affiche l'adresse du token")
        elif on_site:
            a["status"] = AUTH_PROBABLE; reasons.append("compte lié depuis le site déclaré")
        else:
            a["status"] = NOT_VERIFIED
        if handle and symbol and _norm(symbol) not in _norm(handle) and _norm(name)[:6] not in _norm(handle):
            reasons.append("le nom du compte ne correspond pas au nom / ticker du token")
        reasons.append("ancienneté, audience et engagement non mesurés (API X payante)")
        return a
    if plat == "telegram":
        if a.get("kind") == "private_invite":
            a["status"] = NOT_VERIFIED; reasons.append("lien d'invitation privé : aucune donnée publique")
            return a
        tg = await svc.web.telegram_public(a["name"])
        a["telegram"] = tg
        if not tg.get("exists"):
            a["status"] = NOT_FOUND; reasons.append("groupe / canal Telegram introuvable")
            return a
        if tg.get("members") is not None:
            reasons.append(f"{tg['members']:,} membres".replace(",", " ")
                           + (f", {tg['online']:,} en ligne".replace(",", " ") if tg.get("online") is not None else ""))
        if tg.get("members") and tg.get("online") is not None and tg["members"] > 500:
            ratio = tg["online"] / tg["members"]
            a["online_ratio"] = round(ratio, 3)
            if ratio < 0.01:
                reasons.append("très peu de membres en ligne par rapport au total (membres gonflés possible)")
        title = _norm(tg.get("title")) + _norm(tg.get("description"))
        matches = (symbol and _norm(symbol) in title) or (name and _norm(name)[:8] in title) or mint in (tg.get("description") or "")
        on_site = any(f"t.me/{a['name'].lower()}" in l for l in site_links)
        if matches and (on_site or a["declared_by"]):
            a["status"] = AUTH_PROBABLE
            reasons.append("nom du groupe cohérent avec le token" + (" et lié depuis le site" if on_site else ""))
        else:
            a["status"] = SUSPECT if not matches else NOT_VERIFIED
            if not matches:
                reasons.append("le nom / la description du groupe ne correspond pas au token")
        reasons.append("activité des messages non mesurée (nécessite d'être membre du groupe)")
        return a
    if plat == "discord":
        d = await svc.web.discord_invite(a.get("code", ""))
        a["discord"] = d
        if not d or d.get("not_found"):
            a["status"] = NOT_FOUND; reasons.append("invitation Discord invalide ou expirée")
            return a
        reasons.append(f"serveur « {d.get('guild')} » : {d.get('members')} membres, {d.get('online')} en ligne")
        ok = symbol and (_norm(symbol) in _norm(d.get("guild")) or _norm(name)[:8] in _norm(d.get("guild")))
        a["status"] = AUTH_PROBABLE if ok else NOT_VERIFIED
        return a
    if plat == "github":
        gh = await svc.web.github(a.get("owner") or "", a.get("repo"), svc.secrets.get("github_token"))
        a["github"] = gh
        if not gh or gh.get("not_found"):
            a["status"] = NOT_FOUND; reasons.append("dépôt / compte GitHub introuvable")
            return a
        a["status"] = AUTH_PROBABLE if any("github.com/" + (a.get("owner") or "").lower() in l for l in site_links) else NOT_VERIFIED
        for k in ("created_at", "pushed_at"):
            if gh.get(k):
                reasons.append(f"{k} : {gh[k][:10]}")
        return a
    a["status"] = NOT_VERIFIED
    reasons.append("plateforme sans accès public autorisé pour vérifier le compte")
    return a


def social_score(by_platform: dict) -> dict:
    weights = {AUTH_VERIFIED: 10, AUTH_PROBABLE: 7, NOT_VERIFIED: 4, SUSPECT: 1.5, IMPERSONATION: 0, NOT_FOUND: None}
    vals, reasons, verified_points = [], [], 0
    for plat, accs in by_platform.items():
        for a in accs:
            w = weights.get(a.get("status"))
            if w is None:
                continue
            vals.append(w)
            if a.get("status") in (AUTH_VERIFIED, AUTH_PROBABLE):
                verified_points += 1
            if a.get("status") in (SUSPECT, IMPERSONATION):
                reasons.append(f"{plat} : {a['status']}")
    present = sum(1 for p in ("x", "telegram", "website") if any(a.get("status") != NOT_FOUND for a in by_platform.get(p, [])))
    if not vals:
        return {"score": 1.0, "confidence": 0.5, "reasons": ["aucun réseau social ni site déclaré"], "status": ESTIMATED}
    base = sum(vals) / len(vals)
    base += 0.5 * (present - 1)
    tg = next((a for a in by_platform.get("telegram", []) if a.get("telegram")), None)
    if tg and (tg["telegram"].get("members") or 0) > 300 and (tg.get("online_ratio") or 0) >= 0.03:
        base += 0.5; reasons.append("Telegram avec une part de membres en ligne crédible")
    if any(a.get("status") == IMPERSONATION for accs in by_platform.values() for a in accs):
        base = min(base, 2.5); reasons.append("usurpation probable d'identité")
    measured = verified_points + sum(1 for accs in by_platform.values() for a in accs if a.get("telegram") or a.get("discord"))
    confidence = min(0.8, 0.25 + 0.12 * measured)  # plafonnée : pas d'accès à l'audience X
    return {"score": round(max(0, min(10, base)), 1), "confidence": round(confidence, 2),
            "reasons": reasons or [f"{verified_points} compte(s) authentifié(s) par recoupement"], "status": ESTIMATED}


# ------------------------------------------------------------------ crédibilité du projet
async def run_project(ctx) -> None:
    svc = ctx.svc
    P = ctx.section("project")
    site = await ctx.need("site", timeout=12) or {}
    social = await ctx.need("social", timeout=2) or {}
    if not site.get("text"):
        ctx.provide("github", None)
        P["has_site"] = False
        P["score"] = {"score": 1.5, "confidence": 0.6, "reasons": ["aucun site web analysable"], "status": ESTIMATED}
        return
    text, links = site["text"].lower(), [l.lower() for l in site.get("links", [])]
    P["has_site"] = True
    P["has_docs"] = any(k in l for l in links for k in ("docs.", "/docs", "gitbook", "whitepaper", "litepaper", ".pdf"))
    P["team_page"] = any(k in l for l in links for k in ("/team", "/about")) or "our team" in text or "notre équipe" in text
    P["roadmap"] = "roadmap" in text or "feuille de route" in text
    P["product_signals"] = any(k in text for k in ("launch app", "open app", "dashboard", "dapp", "testnet", "mainnet",
                                                   "sdk", "api ", "protocol"))
    P["tokenomics"] = "tokenomics" in text
    P["word_count"] = len(text.split())
    P["github"] = await analyse_github(ctx, social, links)
    ctx.provide("github", P["github"])
    P["github_active"] = bool(P["github"] and P["github"].get("active"))
    reasons, score = [], 3.0
    for key, pts, label in (("has_docs", 1.5, "documentation"), ("team_page", 1.0, "page équipe"),
                            ("roadmap", 0.5, "roadmap"), ("product_signals", 1.0, "produit / application décrit"),
                            ("github_active", 2.0, "GitHub actif (< 90 j)"), ("tokenomics", 0.5, "tokenomics")):
        if P.get(key):
            score += pts; reasons.append(label)
    age = site.get("domain_age_days")
    if age is not None:
        if age < 7:
            score -= 1.0; reasons.append(f"domaine très récent ({age:.0f} j)")
        elif age > 180:
            score += 1.0; reasons.append(f"domaine ancien ({age:.0f} j)")
    if P["word_count"] < 150:
        score -= 1.0; reasons.append("site très pauvre en contenu")
    g = P["github"] or {}
    if g.get("fork"):
        score -= 2.5; reasons.append(f"le GitHub est une copie (fork) de {g.get('parent') or 'un autre projet'}")
    if g.get("created_for_launch"):
        score -= 1.0; reasons.append("dépôt GitHub créé au moment du lancement du token")
    if g.get("stars") and g["stars"] >= 50:
        score += 0.5; reasons.append(f"{g['stars']} étoiles GitHub")
    P["note"] = "Un site web ne suffit pas à rendre un projet sérieux : ces éléments sont des indices de sérieux."
    P["score"] = {"score": round(max(0, min(10, score)), 1), "confidence": 0.55 if age is not None else 0.45,
                  "reasons": reasons, "status": ESTIMATED}


def _ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


async def analyse_github(ctx, social: dict, site_links: list[str]) -> dict | None:
    """Dépôt GitHub du projet (déclaré ou lié depuis le site) : activité réelle, copie, création opportuniste."""
    from ..providers.web import classify_link
    svc = ctx.svc
    cands: list[tuple[str, str | None]] = []
    for a in (social.get("accounts") or {}).get("github", []):
        if a.get("owner"):
            cands.append((a["owner"], a.get("repo")))
    for l in site_links:
        if "github.com/" in l:
            plat, det = classify_link(l)
            if plat == "github" and det.get("owner") and det["owner"] not in ("features", "sponsors", "orgs", "about"):
                cands.append((det["owner"], det.get("repo")))
    cands = list(dict.fromkeys(cands))
    if not cands:
        return None
    token = svc.secrets.get("github_token")
    for owner, repo in cands[:2]:
        try:
            info = await (svc.web.github(owner, repo, token) if repo else svc.web.github_top_repo(owner, token))
        except Exception:
            info = None
        if not info or info.get("not_found") or "pushed_at" not in info:
            continue
        pushed, created = _ts(info.get("pushed_at")), _ts(info.get("created_at"))
        tok_created = ((ctx.result.get("token") or {}).get("created_at") or {}).get("v")
        out = {"repo": info.get("full_name") or f"{owner}/{repo}", "url": info.get("html_url"),
               "stars": info.get("stargazers_count"), "fork": bool(info.get("fork")), "parent": info.get("parent"),
               "language": info.get("language"), "created_at": info.get("created_at"), "pushed_at": info.get("pushed_at"),
               "archived": info.get("archived"), "size_kb": info.get("size"),
               "active": bool(pushed and time.time() - pushed < 30 * 86400),
               "created_for_launch": bool(created and tok_created and abs(created - tok_created) < 3 * 86400
                                          and (info.get("size") or 0) < 500),
               "source": "API publique GitHub"}
        return out
    return {"error": "dépôt GitHub introuvable ou inaccessible"}


# ------------------------------------------------------------------ fact-checking
def extract_claims_rules(text: str, limit: int = 6) -> list[str]:
    out = []
    for m in CLAIM_PATTERNS.finditer(text or ""):
        c = re.sub(r"\s+", " ", m.group(1)).strip(" -–:;,")
        if 25 <= len(c) <= 300 and c not in out:
            out.append(c)
        if len(out) >= limit:
            break
    return out


ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z0-9&]+(?:\s+[A-Z][a-zA-Z0-9&]+){0,3})\b")
STOP_ENTITIES = {"The", "We", "Our", "This", "Token", "Official", "Partner", "Partnership", "Solana", "Join", "Buy",
                 "In", "With", "And", "By", "Backed", "Listed", "Launched", "Created", "Founded", "Supported"}


async def run_factcheck(ctx) -> None:
    svc = ctx.svc
    F = ctx.section("factcheck")
    site = await ctx.need("site", timeout=12) or {}
    tok = ctx.result.get("token", {})
    desc = ((tok.get("description") or {}).get("v")) or ""
    name, symbol = tok.get("name") or "", tok.get("symbol") or ""
    corpus = f"{desc}\n{site.get('description') or ''}\n{(site.get('text') or '')[:6000]}"
    claims: list[dict] = []
    if svc.llm.available:
        try:
            out = await svc.llm.json(
                "Extrais au maximum 6 affirmations factuelles vérifiables faites par ce token / projet "
                "(partenariats, soutiens, associations à une personnalité ou entreprise, listings, équipe, "
                "événement d'actualité invoqué). Format : {\"claims\":[{\"text\":..., \"entity\":...}]}. "
                "Ne garde que ce qui est explicitement écrit.", corpus, timeout=12)
            for c in (out or {}).get("claims", [])[:6]:
                if isinstance(c, dict) and c.get("text"):
                    claims.append({"text": str(c["text"])[:300], "entity": str(c.get("entity") or "")[:80],
                                   "extracted_by": "IA"})
        except Exception as exc:
            F["llm_error"] = str(exc)
    if not claims:
        for c in extract_claims_rules(corpus):
            ents = [e for e in ENTITY_RE.findall(c) if e.split()[0] not in STOP_ENTITIES
                    and _norm(e) not in (_norm(name), _norm(symbol))]
            claims.append({"text": c, "entity": ents[0] if ents else "", "extracted_by": "règles"})
    own = registrable_domain(site["domain"]) if site.get("domain") else None
    results = []
    for c in claims[:6]:
        results.append(await verify_claim(svc, c, name, symbol, own))
    F["claims"] = results
    F["method"] = ("Recherche des sources indépendantes (Google News RSS + GDELT) citant à la fois l'entité "
                   "et le token. Sans source fiable : NON VÉRIFIÉ.")
    if not claims:
        F["note"] = "Aucune affirmation vérifiable détectée dans la description ou le site."
    for r in results:
        svc.db.execute("INSERT INTO fact_checks(mint, claim, origin, status, confidence, sources, checked_at) "
                       "VALUES(?,?,?,?,?,?,?)", (ctx.mint, r["text"], r["origin"], r["status"], r["confidence"],
                                                 json.dumps(r["sources"]), time.time()))
        if r["status"] in ("CONTREDIT", "FAUX OU TROMPEUR"):
            ctx.risk("élevé", "FALSE_CLAIM", f"Affirmation contredite : « {r['text'][:120]} »", "Fact-check")


async def verify_claim(svc, c: dict, name: str, symbol: str, own_domain: str | None) -> dict:
    entity = c.get("entity") or ""
    res = {"text": c["text"], "entity": entity, "origin": "description / site du token (déclaratif)",
           "extracted_by": c["extracted_by"], "sources": [], "status": "NON VÉRIFIÉ", "confidence": 0.0,
           "date": time.time()}
    if not entity:
        res["reason"] = "aucune entité identifiable à rechercher"
        return res
    token_terms = [t for t in (_norm(name), _norm(symbol)) if len(t) >= 3]
    query = f'"{entity}" {name or symbol} crypto'
    articles = []
    for coro in (svc.news.google_news_search(query), svc.news.gdelt(f'"{entity}" "{name or symbol}"', timespan="3m", maxrecords=50)):
        try:
            articles += await coro
        except Exception as exc:
            res.setdefault("search_errors", []).append(str(exc))
    hits, domains = [], set()
    for a in articles:
        t = _norm(a["title"])
        dom = registrable_domain(a.get("domain") or domain_of(a["url"]) or "")
        if own_domain and dom == own_domain:
            continue
        if _norm(entity) in t and any(tt in t for tt in token_terms):
            hits.append({"title": a["title"], "url": a["url"], "domain": dom, "published_at": a.get("published_at")})
            domains.add(dom)
    res["sources"] = hits[:8]
    if len(domains) >= 2:
        res.update(status="CONFIRMÉ PAR PLUSIEURS SOURCES", confidence=0.7)
    elif len(domains) == 1:
        res.update(status="PARTIELLEMENT CONFIRMÉ", confidence=0.4)
    else:
        res["reason"] = "aucune source indépendante trouvée citant l'entité et le token"
    res["note"] = "Statut basé sur les titres d'articles ; ouvrir les liens pour vérifier le contenu."
    return res
