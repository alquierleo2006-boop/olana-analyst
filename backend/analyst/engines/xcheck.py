"""Vérification d'un projet à partir de son lien X (Twitter) — édition Tech.

À partir d'un tweet ou d'un profil : CA publié, site du projet, cohérence CA (X ↔ site ↔ blockchain ↔ adresse saisie),
liens croisés site ↔ compte X, âge du domaine, documentation. Verdict CLEAN / À VÉRIFIER / SUSPECT.
Aucun contournement : uniquement les endpoints publics d'intégration de X. Le contenu externe est traité comme
des données non fiables.
"""
from __future__ import annotations

import re
import time
from datetime import datetime

from ..providers.solana import TOKEN_2022_PROGRAM, TOKEN_PROGRAM
from ..providers.web import classify_link, domain_of
from ..util import is_valid_mint_format

CA_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
SOCIAL_HOSTS = ("x.com", "twitter.com", "t.me", "telegram.me", "discord.gg", "discord.com", "instagram.com", "tiktok.com",
                "youtube.com", "youtu.be", "github.com", "dexscreener.com", "pump.fun", "birdeye.so", "solscan.io",
                "jup.ag", "raydium.io", "medium.com", "linktr.ee", "gmgn.ai", "photon-sol.tinyastro.io", "axiom.trade")
OK, WARN, BAD, INFO = "ok", "attention", "bloquant", "info"


def _c(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def find_cas(text: str) -> list[str]:
    return list(dict.fromkeys(c for c in CA_RE.findall(text or "") if is_valid_mint_format(c)))


async def is_token_mint(svc, address: str) -> bool:
    try:
        acc = await svc.rpc.account_info(address)
    except Exception:
        return False
    data = (acc or {}).get("data")
    return bool(acc and acc.get("owner") in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM)
                and isinstance(data, dict) and (data.get("parsed") or {}).get("type") == "mint")


async def tokens_declaring_handle(svc, handle: str | None) -> list[dict]:
    """Tokens Solana dont la fiche DexScreener déclare ce compte X (lien x.com/<handle>), du plus ancien au plus récent."""
    if not handle:
        return []
    try:
        pairs = await svc.dex.search(handle)
    except Exception:
        return []
    found: dict[str, dict] = {}
    for p in pairs:
        info = p.get("info") or {}
        socials = [s.get("url") for s in info.get("socials") or [] if s.get("url")]
        hit = False
        for u in socials:
            plat, d = classify_link(u)
            if plat == "x" and (d.get("handle") or "").lower() == handle.lower():
                hit = True
        if not hit:
            continue
        bt = p.get("baseToken") or {}
        a = bt.get("address")
        liq = (p.get("liquidity") or {}).get("usd") or 0
        cur = found.get(a)
        created = (p.get("pairCreatedAt") or 0) / 1000 or None
        if not cur or liq > cur["liquidity"]:
            found[a] = {"mint": a, "symbol": bt.get("symbol"), "name": bt.get("name"), "liquidity": liq,
                        "mcap": p.get("marketCap") or p.get("fdv"), "created_at": created,
                        "websites": [w.get("url") for w in info.get("websites") or [] if w.get("url")]}
    return sorted(found.values(), key=lambda d: d["created_at"] or 9e18)


async def run_xcheck(svc, url: str, mint_hint: str | None = None) -> dict:
    t0 = time.monotonic()
    u = url.strip()
    if re.fullmatch(r"@?[A-Za-z0-9_]{1,15}", u):  # « @pseudo » ou « pseudo » seul
        u = "https://x.com/" + u.lstrip("@")
    url = u
    plat, det = classify_link(url)
    if plat != "x" or det.get("kind") not in ("tweet", "profile"):
        return {"error": "Colle le lien d'un tweet (x.com/compte/status/…) ou d'un profil X (x.com/compte)."}
    out: dict = {"input": url, "kind": det["kind"], "handle": det.get("handle"), "checks": [], "limits": []}
    texts, urls = [], []

    # 1. Lecture du tweet / du profil
    if det["kind"] == "tweet":
        tw = await svc.web.x_tweet(det["id"])
        if not tw:
            emb = await svc.web.x_oembed(det["url"])
            if emb and not emb.get("not_found"):
                html = emb.get("html", "")
                text = re.sub(r"<[^>]+>", " ", html)
                tw = {"text": re.sub(r"\s+", " ", text).strip(), "urls": re.findall(r'href="(https?://[^"]+)"', html),
                      "author": (emb.get("author_url") or "").rstrip("/").split("/")[-1] or det.get("handle"),
                      "source": "oEmbed (texte seulement)"}
        if not tw:
            out["checks"].append(_c("Compte / tweet X", BAD, "tweet introuvable (supprimé, privé ou lien invalide)"))
        else:
            out["tweet"] = tw
            out["handle"] = (tw.get("author") or det.get("handle") or "").lower() or None
            texts.append(tw["text"])
            urls += tw.get("urls") or []
            out["checks"].append(_c("Compte / tweet X", OK, f"tweet de @{out['handle']} lu"
                                    + (f" ({str(tw.get('created_at'))[:10]})" if tw.get("created_at") else "")))
    prof = await svc.web.x_profile(out["handle"]) if out.get("handle") else None
    if prof:
        out["profile"] = {k: prof.get(k) for k in ("handle", "name", "bio", "followers", "created_at", "bio_urls")}
        texts.append(prof.get("bio") or "")
        texts += [t["text"] for t in prof.get("tweets", [])]
        urls += prof.get("bio_urls") or []
        for t in prof.get("tweets", []):
            urls += t.get("urls") or []
        if det["kind"] == "profile":
            out["checks"].append(_c("Compte / tweet X", OK, f"profil @{prof['handle']} lu ({len(prof.get('tweets', []))} tweets récents)"))
        if prof.get("created_at"):
            try:
                created = datetime.strptime(prof["created_at"], "%a %b %d %H:%M:%S %z %Y").timestamp()
                days = (time.time() - created) / 86400
                out["account_age_days"] = round(days)
                out["checks"].append(_c("Ancienneté du compte X", OK if days > 30 else WARN,
                                        f"compte créé il y a {days:.0f} jour(s)"))
            except ValueError:
                pass
    elif det["kind"] == "profile":
        emb = await svc.web.x_oembed(det["url"])
        if emb and emb.get("not_found"):
            out["checks"].append(_c("Compte / tweet X", BAD, "compte X introuvable (suspendu ou inexistant)"))
        else:
            out["checks"].append(_c("Compte / tweet X", INFO, "compte trouvé ; son contenu n'est pas lisible gratuitement "
                                                            "(vérification via DexScreener et le site)"))
            out["limits"].append("X restreint la lecture des profils : le CA et le site sont retrouvés via les tokens qui "
                                 "déclarent ce compte sur DexScreener. Un lien de tweet du CA donne une vérification plus complète.")

    # 1 bis. Tokens qui déclarent ce compte X comme réseau officiel (DexScreener) — fonctionne sans lire X.
    declared = await tokens_declaring_handle(svc, out.get("handle"))
    out["declared_tokens"] = declared
    for d in declared[:3]:
        urls += d.get("websites") or []

    # 2. CA publié
    cas_x = []
    for c in find_cas(" ".join(texts) + " " + " ".join(urls)):
        if await is_token_mint(svc, c):
            cas_x.append(c)
    out["cas_on_x"] = cas_x
    if len(cas_x) == 1:
        out["checks"].append(_c("CA publié sur X", OK, f"{cas_x[0][:6]}…{cas_x[0][-4:]} (token vérifié on-chain)"))
    elif len(cas_x) > 1:
        out["checks"].append(_c("CA publié sur X", WARN, f"{len(cas_x)} CA différents publiés : vérifie lequel est officiel"))
    elif texts:
        out["checks"].append(_c("CA publié sur X", WARN, "aucun CA trouvé dans le contenu lu"))

    # 3. Site du projet
    resolved = []
    for u in dict.fromkeys(urls):
        if "t.co/" in u:
            u = await svc.web.resolve_url(u)
        resolved.append(u)
    sites = [u for u in resolved if (domain_of(u) or "") and not any((domain_of(u) or "").endswith(h) for h in SOCIAL_HOSTS)]
    out["links"] = resolved[:20]
    site_ok = None
    if not sites:
        out["checks"].append(_c("Site du projet", WARN if texts else INFO, "aucun site trouvé dans les liens lus"))
    else:
        site_url = sites[0]
        try:
            site = await svc.web.fetch_site(site_url)
        except Exception as exc:
            site = None
            out["checks"].append(_c("Site du projet", BAD, f"site injoignable ({type(exc).__name__})"))
        if site:
            dom = domain_of(site["final_url"])
            reg = await svc.web.domain_registration(dom) if dom else None
            age = None
            if reg and reg.get("registration"):
                try:
                    age = (time.time() - datetime.fromisoformat(reg["registration"].replace("Z", "+00:00")).timestamp()) / 86400
                except ValueError:
                    pass
            links_low = [l.lower() for l in site["links"]]
            h = (out.get("handle") or "").lower()
            back = bool(h) and any(f"x.com/{h}" in l or f"twitter.com/{h}" in l for l in links_low)
            cas_site = [c for c in find_cas(site["text"] + " " + " ".join(site["links"]))]
            has_docs = any(k in l for l in links_low for k in ("docs.", "/docs", "gitbook", "whitepaper", "litepaper"))
            out["site"] = {"url": site["final_url"], "title": site.get("title"), "domain": dom,
                           "domain_age_days": round(age) if age is not None else None, "links_back_to_x": back,
                           "cas": cas_site, "has_docs": has_docs, "https": site["https"]}
            why = [f"{dom}"]
            st = OK
            if age is not None:
                why.append(f"domaine de {age:.0f} j")
                if age < 7:
                    st = WARN
            why.append("documentation" if has_docs else "pas de documentation")
            if not has_docs:
                st = WARN
            out["checks"].append(_c("Site du projet", st, " · ".join(why)))
            out["checks"].append(_c("Lien site → compte X", OK if back else WARN,
                                    "le site renvoie bien vers ce compte X" if back
                                    else "le site ne renvoie pas vers ce compte X (compte non officiel ?)"))
            site_ok = site

    # 4. Cohérence des CA
    cas_site = (out.get("site") or {}).get("cas") or []
    ref = [c for c in (cas_x[:1] + ([mint_hint] if mint_hint else [])) if c]
    if cas_x and cas_site:
        if set(cas_x) & set(cas_site):
            out["checks"].append(_c("CA identique X ↔ site", OK, "le même CA est publié sur X et sur le site"))
        else:
            out["checks"].append(_c("CA identique X ↔ site", BAD, "le CA du site est DIFFÉRENT de celui publié sur X"))
    elif site_ok and cas_x and not cas_site:
        out["checks"].append(_c("CA identique X ↔ site", WARN, "le site n'affiche pas de CA"))
    if mint_hint:
        known = set(cas_x) | set(cas_site) | {d["mint"] for d in declared[:1]}
        if not known:
            out["checks"].append(_c("CA saisi", WARN, "impossible de confirmer ton CA : aucun CA trouvé sur X ni sur le site"))
        elif mint_hint in known:
            out["checks"].append(_c("CA saisi", OK, "ton CA correspond à celui publié par le projet"))
        else:
            out["checks"].append(_c("CA saisi", BAD, "ton CA NE correspond PAS à celui publié par le projet (faux token ?)"))
    # Tokens déclarant ce compte X : un seul = cohérent ; plusieurs = copies probables.
    dmints = [d["mint"] for d in declared]
    if declared:
        orig = declared[0]  # le plus ancien
        if len(declared) == 1:
            out["checks"].append(_c("Token lié à ce compte X", OK, f"${orig['symbol']} déclare ce compte X sur DexScreener"))
        else:
            out["checks"].append(_c("Token lié à ce compte X", WARN,
                                    f"{len(declared)} tokens déclarent ce compte X : le plus ancien est ${orig['symbol']} "
                                    f"({orig['mint'][:6]}…), les autres sont probablement des copies"))
        if cas_x and not set(cas_x) & set(dmints):
            out["checks"].append(_c("CA publié vs DexScreener", WARN,
                                    "le CA publié sur X n'est pas encore relié à ce compte sur DexScreener"))
        if cas_site and not set(cas_site) & set(dmints) and not cas_x:
            out["checks"].append(_c("CA identique site ↔ DexScreener", BAD,
                                    "le CA affiché sur le site est différent du token qui déclare ce compte X"))
        elif cas_site and set(cas_site) & set(dmints) and not cas_x:
            out["checks"].append(_c("CA identique site ↔ DexScreener", OK, "le site affiche bien le CA du token lié à ce compte"))
    elif out.get("handle"):
        out["checks"].append(_c("Token lié à ce compte X", WARN if not cas_x else INFO,
                                "aucun token ne déclare ce compte X sur DexScreener"))
    if mint_hint and declared and mint_hint not in dmints and not (set(cas_x) | set(cas_site)):
        out["checks"].append(_c("CA saisi", BAD, "ton CA n'est pas le token qui déclare ce compte X (copie ?)"))
    out["ca"] = (cas_x[0] if len(cas_x) == 1 else None) or (mint_hint if mint_hint and await is_token_mint(svc, mint_hint) else None) \
        or (declared[0]["mint"] if declared else None) \
        or (cas_site[0] if len(cas_site) == 1 and await is_token_mint(svc, cas_site[0]) else None)
    if not ref and not cas_site:
        out["limits"].append("Sans CA publié, l'outil ne peut pas relier ce compte X à un token.")

    # 5. Verdict
    bad = [c for c in out["checks"] if c["status"] == BAD]
    warn = [c for c in out["checks"] if c["status"] == WARN]
    if bad:
        out["verdict"], out["reason"] = "SUSPECT", f"{bad[0]['name']} : {bad[0]['detail']}"
    elif warn or not out.get("ca"):
        out["verdict"] = "À VÉRIFIER"
        out["reason"] = (", ".join(c["name"].lower() for c in warn) if warn else "aucun CA confirmé")
    else:
        out["verdict"], out["reason"] = "CLEAN", "compte, site et CA cohérents"
    if svc.llm.available:
        try:
            import json as _json
            res = await svc.llm.json(
                "Résume en 2 phrases en français si ce projet semble cohérent (compte X, site, CA). N'invente rien, "
                "base-toi uniquement sur les contrôles fournis. Format : {\"summary\": \"...\"}",
                _json.dumps({"verdict": out["verdict"], "checks": out["checks"]}, ensure_ascii=False), timeout=12)
            out["summary"] = (res or {}).get("summary")
        except Exception:
            pass
    out["ms"] = int((time.monotonic() - t0) * 1000)
    out["note"] = "Contrôles de cohérence, pas une garantie. Le contenu de X et des sites est déclaratif."
    return out
