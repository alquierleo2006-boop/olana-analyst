"""Originalité d'un projet tech : est-ce une idée neuve, un concept saturé, ou une copie ?

Recherches (gratuites) :
- tokens Solana homonymes (même nom / ticker) : un homonyme plus ancien ET bien plus gros = copycat probable ;
- tokens Solana au concept similaire (mots-clés du projet) lancés récemment ;
- dépôts GitHub établis qui font déjà la même chose ;
- nom reprenant une marque connue.
Ce sont des indices : un concept existant n'interdit pas un bon projet, mais réduit son originalité.
"""
from __future__ import annotations

import re
import time
from collections import Counter

from .narratives import tokenize

GENERIC = {"token", "coin", "solana", "crypto", "community", "first", "project", "based", "platform", "built", "official",
           "world", "future", "powered", "launch", "launched", "meme", "memecoin", "pump", "holders", "join", "buy",
           "website", "telegram", "twitter", "chain", "blockchain", "web3", "defi", "best", "make", "using", "will",
           "your", "into", "more", "every", "everyone", "decentralized", "ecosystem", "users", "real", "fully", "next",
           # vocabulaire promotionnel (affirmations, pas concept)
           "partnership", "partner", "partners", "announced", "announce", "backed", "endorsed", "listed", "listing",
           "exclusive", "revolutionary", "innovative", "massive", "huge", "moon", "gem", "soon", "today", "now",
           "team", "roadmap", "tokenomics", "supply", "liquidity", "burned", "locked", "renounced"}
BRANDS = {"openai": "OpenAI", "chatgpt": "ChatGPT", "gpt": "GPT (OpenAI)", "grok": "Grok (xAI)", "xai": "xAI",
          "claude": "Claude (Anthropic)", "anthropic": "Anthropic", "gemini": "Gemini (Google)", "deepseek": "DeepSeek",
          "nvidia": "Nvidia", "tesla": "Tesla", "spacex": "SpaceX", "virtuals": "Virtuals", "ai16z": "ai16z",
          "eliza": "ElizaOS", "jupiter": "Jupiter", "apple": "Apple", "google": "Google", "microsoft": "Microsoft",
          "meta": "Meta", "neuralink": "Neuralink", "perplexity": "Perplexity", "mistral": "Mistral", "llama": "Llama (Meta)"}


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def keywords(*texts: str, exclude: set[str] = frozenset(), n: int = 3) -> list[str]:
    words = [w for t in texts for w in tokenize(t or "") if len(w) >= 4 and w not in GENERIC and w not in exclude
             and not w.startswith("$")]
    return [w for w, _ in Counter(words).most_common(n)]


async def run_originality(ctx) -> None:
    svc = ctx.svc
    O = ctx.section("originality")
    gh = await ctx.need("github", timeout=15)
    await ctx.need("site", timeout=5)
    tok = ctx.result.get("token") or {}
    name, symbol = tok.get("name") or "", tok.get("symbol") or ""
    desc = ((tok.get("description") or {}).get("v")) or ""
    site_desc = next((a.get("title") or "" for a in ((ctx.result.get("social") or {}).get("accounts") or {}).get("website", [])
                      if a.get("final_url")), "")
    own_names = set(tokenize(f"{name} {symbol}")) | set(BRANDS)
    kws = keywords(desc, (gh or {}).get("description") or "", site_desc, exclude=own_names)
    O["keywords"] = kws
    reasons, verdict, score = [], "originale", 8.0
    my_mcap = ((ctx.result.get("market") or {}).get("mcap") or {}).get("v") or 0
    my_created = ((ctx.result.get("market") or {}).get("first_pair_at") or {}).get("v") \
        or ((tok.get("created_at") or {}).get("v"))

    # 1. Marque connue dans le nom
    brand = next((label for k, label in BRANDS.items() if k in _norm(name) or k == _norm(symbol)), None)
    if brand:
        O["brand"] = brand
        reasons.append(f"le nom reprend la marque {brand} (aucun lien officiel présumé)")
        verdict, score = "peu originale", score - 2

    # 2. Homonymes : même nom / ticker
    homonyms = []
    try:
        for p in await svc.dex.search(symbol or name):
            bt = p.get("baseToken") or {}
            if bt.get("address") == ctx.mint:
                continue
            if _norm(bt.get("symbol")) == _norm(symbol) or (name and _norm(bt.get("name")) == _norm(name)):
                homonyms.append({"mint": bt.get("address"), "symbol": bt.get("symbol"), "name": bt.get("name"),
                                 "mcap": p.get("marketCap") or p.get("fdv"),
                                 "created_at": (p.get("pairCreatedAt") or 0) / 1000 or None})
    except Exception as exc:
        O["homonyms_error"] = str(exc)[:150]
    uniq = {h["mint"]: h for h in homonyms if h["mint"]}
    homonyms = sorted(uniq.values(), key=lambda h: -(h["mcap"] or 0))[:8]
    O["homonyms"] = homonyms
    copied = [h for h in homonyms if h["created_at"] and my_created and h["created_at"] < my_created
              and (h["mcap"] or 0) >= max(5 * my_mcap, 50_000)]
    if copied:
        h = copied[0]
        reasons.insert(0, f"un token plus ancien et bien plus gros porte déjà ce nom (${h['symbol']}, "
                          f"market cap ${h['mcap']:,.0f}) : copycat probable")
        verdict, score = "copie probable", min(score, 2.0)
    elif len(homonyms) >= 3:
        reasons.append(f"{len(homonyms)} autres tokens Solana portent le même nom / ticker")
        score -= 1.5
        if verdict == "originale":
            verdict = "peu originale"

    # 3. Concept similaire sur Solana (7 derniers jours)
    similar = {}
    now = time.time()
    for kw in kws[:2]:
        try:
            for p in await svc.dex.search(kw):
                bt = p.get("baseToken") or {}
                a = bt.get("address")
                if a and a != ctx.mint and kw in (bt.get("name") or "").lower() + " " + (bt.get("symbol") or "").lower():
                    similar[a] = {"mint": a, "symbol": bt.get("symbol"), "name": bt.get("name"), "keyword": kw,
                                  "mcap": p.get("marketCap") or p.get("fdv"),
                                  "created_at": (p.get("pairCreatedAt") or 0) / 1000 or None}
        except Exception:
            continue
    recent = [x for x in similar.values() if x["created_at"] and now - x["created_at"] < 7 * 86400]
    O["similar_tokens"] = sorted(similar.values(), key=lambda x: -(x["mcap"] or 0))[:8]
    O["similar_recent_7d"] = len(recent)
    if len(recent) >= 5:
        reasons.append(f"{len(recent)} tokens au concept similaire ({', '.join(kws[:2])}) lancés cette semaine")
        score -= 1.5
        if verdict == "originale":
            verdict = "peu originale"

    # 4. Projets open source établis qui font la même chose
    if kws:
        try:
            repos = await svc.web.github_search(" ".join(kws[:2]), svc.secrets.get("github_token"))
            mine = ((gh or {}).get("repo") or "").lower()
            repos = [x for x in repos if (x["repo"] or "").lower() != mine]
            O["similar_repos"] = repos[:5]
            big = [x for x in repos if (x["stars"] or 0) >= 1000]
            if big:
                reasons.append(f"concept déjà couvert par des projets établis (ex. {big[0]['repo']}, {big[0]['stars']} étoiles)")
                score -= 1.0
                if verdict == "originale":
                    verdict = "peu originale"
        except Exception as exc:
            O["similar_repos_error"] = str(exc)[:150]
    if (gh or {}).get("fork"):
        reasons.insert(0, f"le code est une copie (fork) de {gh.get('parent')}")
        verdict, score = "copie probable", min(score, 2.0)
    if not kws and not brand and not homonyms:
        O["unavailable"] = "pas assez d'informations (description, site, GitHub) pour juger l'originalité"
        return
    if verdict == "originale":
        reasons.append("aucun homonyme gênant ni concept saturé trouvé")
    O.update(verdict=verdict, reasons=reasons, score=max(0.0, min(10.0, round(score, 1))),
             method="Recherches DexScreener (homonymes, concepts similaires 7 j) et GitHub (projets établis).")
