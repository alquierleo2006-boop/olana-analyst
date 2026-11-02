"""Checklist d'entrée de l'édition TECH : projets technologiques (IA, outils, infra) tenus de quelques minutes
à quelques heures. Reprend la sécurité anti-rug de l'édition scalp et ajoute la vérification du produit réel."""
from __future__ import annotations

from . import scalp as S
from .scalp import BAD, OK, WAIT, WARN, _c

TECH_CATEGORIES = ("Intelligence artificielle", "Technologie", "Crypto / Solana")


def checklist(r: dict, settings: dict) -> dict:
    base = S.checklist(r, settings)
    keep = ("Pièges techniques", "Bundle / snipers", "🌱 Fresh wallets", "Concentration", "Développeur", "Coût aller-retour", "Réseaux sociaux")
    checks = [c for c in base["checks"] if c["name"] in keep]
    mods = r.get("modules") or {}
    pending = lambda k: (mods.get(k) or {}).get("status") == "en cours"  # noqa: E731
    P, F, N, m = r.get("project") or {}, r.get("factcheck") or {}, r.get("narrative") or {}, r.get("market") or {}

    # Produit réel : le code existe-t-il, est-il original, est-il vivant ?
    g = P.get("github")
    if pending("project") or pending("social"):
        checks.append(_c("Produit réel (GitHub)", WAIT, "analyse du code en cours"))
    elif not g or g.get("error"):
        checks.append(_c("Produit réel (GitHub)", WARN, "aucun dépôt de code public trouvé"))
    elif g.get("fork"):
        checks.append(_c("Produit réel (GitHub)", BAD, f"le dépôt est une copie (fork) de {g.get('parent') or 'un autre projet'}"))
    elif g.get("archived"):
        checks.append(_c("Produit réel (GitHub)", WARN, "dépôt archivé (abandonné)"))
    elif g.get("created_for_launch"):
        checks.append(_c("Produit réel (GitHub)", WARN, "dépôt quasi vide créé au moment du lancement"))
    elif g.get("active"):
        checks.append(_c("Produit réel (GitHub)", OK, f"{g.get('repo')} actif (dernier commit {str(g.get('pushed_at'))[:10]})"
                                                    + (f", {g['stars']} étoiles" if g.get("stars") else "")))
    else:
        checks.append(_c("Produit réel (GitHub)", WARN, f"{g.get('repo')} inactif depuis plus de 30 jours"))

    # Site, documentation, domaine
    site = next((a for a in ((r.get("social") or {}).get("accounts") or {}).get("website", []) if a.get("final_url")), None)
    if pending("project") or pending("social"):
        checks.append(_c("Site & documentation", WAIT, "analyse du site en cours"))
    elif P.get("has_site") is False or not site:
        checks.append(_c("Site & documentation", BAD, "aucun site officiel : rare pour un vrai projet tech"))
    else:
        why, st = [], OK
        age = site.get("domain_age_days")
        if age is not None:
            why.append(f"domaine de {age:.0f} j")
            if age < 7:
                st = WARN
        if P.get("has_docs"):
            why.append("documentation")
        else:
            st = WARN; why.append("pas de documentation")
        if site.get("mentions_mint"):
            why.append("le site affiche l'adresse du token")
        elif st == OK:
            st = WARN; why.append("le site n'affiche pas l'adresse du token")
        checks.append(_c("Site & documentation", st, " · ".join(why)))

    # Affirmations vérifiées
    claims = F.get("claims") or []
    if pending("factcheck"):
        checks.append(_c("Affirmations", WAIT, "vérification des sources en cours"))
    elif any(c["status"] in ("CONTREDIT", "FAUX OU TROMPEUR") for c in claims):
        bad = next(c for c in claims if c["status"] in ("CONTREDIT", "FAUX OU TROMPEUR"))
        checks.append(_c("Affirmations", BAD, f"affirmation contredite : « {bad['text'][:80]} »"))
    elif any(c["status"] == "NON VÉRIFIÉ" for c in claims):
        n = sum(1 for c in claims if c["status"] == "NON VÉRIFIÉ")
        first = next(c for c in claims if c["status"] == "NON VÉRIFIÉ")
        checks.append(_c("Affirmations", WARN, f"{n} affirmation(s) sans source indépendante, ex. « {first['text'][:70]} »"))
    elif any(c["status"].startswith("CONFIRMÉ") for c in claims):
        checks.append(_c("Affirmations", OK, "au moins une affirmation confirmée par des sources indépendantes"))
    else:
        checks.append(_c("Affirmations", OK, "aucune affirmation douteuse détectée"))

    # Narrative tech
    matches = N.get("matches") or []
    if pending("narrative"):
        checks.append(_c("Narrative tech", WAIT, "corrélation en cours"))
    elif not matches:
        checks.append(_c("Narrative tech", WARN, "ne correspond à aucune tendance suivie"))
    else:
        best = matches[0]
        if best["state"] in ("SATURÉE", "EN DÉCLIN"):
            checks.append(_c("Narrative tech", WARN, f"« {best['name']} » : {best['state'].lower()}"))
        elif best.get("category") in TECH_CATEGORIES:
            checks.append(_c("Narrative tech", OK, f"« {best['name']} » ({best['state'].lower()}, {best['category']})"))
        else:
            checks.append(_c("Narrative tech", WARN, f"tendance « {best['name']} » hors thème tech"))

    # Momentum 20 min
    mom = m.get("momentum") or {}
    ch20 = (mom.get("change") or {}).get("20m")
    tx = (m.get("gecko_txns") or {}).get("m30") or {}
    src = "30 min"
    if not tx:
        tx, src = (m.get("txns") or {}).get("h1") or {}, "1 h"
    b, se = tx.get("buys") or 0, tx.get("sells") or 0
    why, st = [], None
    if ch20 is not None:
        why.append(f"prix {ch20:+.0f}% sur 20 min")
        st = BAD if ch20 < -25 else WARN if ch20 < -8 else OK
    if mom.get("volume_20m_trend") is not None:
        why.append(f"volume ×{mom['volume_20m_trend']:.1f} vs 20 min précédentes")
    if b + se >= 15:
        ratio = b / max(1, se)
        why.append(f"achats/ventes {src} : {b}/{se}")
        rs = OK if ratio >= 1.1 else WARN if ratio >= 0.75 else BAD
        st = rs if st is None else (BAD if BAD in (st, rs) else WARN if WARN in (st, rs) else OK)
    tpm = (m.get("curve_activity") or {}).get("tx_per_min_20m")
    if tpm is not None:
        why.append(f"{tpm:.0f} tx/min sur la curve")
    if st is None:
        st = WAIT if pending("momentum") or pending("market") else WARN
        why.append("pas assez de données sur 20 min" if st == WARN else "calcul en cours")
    checks.append(_c("Momentum 20 min", st, " · ".join(why)))

    # Originalité (recherche de projets similaires)
    O = r.get("originality") or {}
    if pending("originality"):
        checks.append(_c("Originalité", WAIT, "recherche de projets similaires en cours"))
    elif not O.get("verdict"):
        checks.append(_c("Originalité", WARN, O.get("unavailable") or "recherche indisponible"))
    else:
        checks.append(_c("Originalité", {"originale": OK, "peu originale": WARN, "copie probable": BAD}[O["verdict"]],
                         "; ".join(O.get("reasons", [])[:2]) or O["verdict"]))

    sc = settings.get("scalp") or {}
    decision, why = S.decide(checks)
    out = S.finish(checks, decision, why, (m.get("mcap") or {}).get("v"), float(sc.get("take_profit_pct", 50)),
                   float(sc.get("stop_pct", 25)), float(sc.get("position_sol", 0.25)), r.get("liquidity") or {})
    out["note"] = ("Checklist d'élimination des pièges et de vérification du produit, pas une prédiction. "
                   "Décide toujours toi-même.")
    return out
