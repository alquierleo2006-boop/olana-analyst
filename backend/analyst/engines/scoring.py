"""Moteur de scoring et verdict. Le score est calculé par des règles explicites et versionnées ;
l'IA (si activée) explique le résultat mais ne le fabrique jamais."""
from __future__ import annotations

from ..util import clamp

CATS = ["onchain", "momentum", "narrative", "social", "credibility", "smart_money"]
LABELS = {"onchain": "On-chain & sécurité", "momentum": "Momentum & marché", "narrative": "Narrative & actualités",
          "social": "Réseaux sociaux", "credibility": "Qualité & crédibilité", "smart_money": "Smart money"}
INTERPRETATION = [(2, "potentiel très faible"), (4, "potentiel faible"), (6, "potentiel intermédiaire"),
                  (7, "intéressant sous conditions"), (8, "signaux favorables"), (9, "convergence de signaux très favorable"),
                  (10.01, "configuration exceptionnelle selon les indicateurs disponibles")]


def _s(score, conf, reasons, pos=None, neg=None):
    return {"score": None if score is None else round(clamp(score), 1), "confidence": round(conf, 2),
            "reasons": reasons, "positives": pos or [], "negatives": neg or [], "available": score is not None}


def score_onchain(r: dict) -> dict:
    sec, hol, clu, dev = r.get("security") or {}, r.get("holders") or {}, r.get("clusters") or {}, r.get("developer") or {}
    liq = (r.get("liquidity") or {}).get("risk_level") or {}
    if not sec.get("checks") and not hol.get("top"):
        return _s(None, 0, ["données on-chain en attente"])
    s, pos, neg, n = 7.0, [], [], 0
    for c in sec.get("checks") or []:
        n += 1
        if c["ok"] is False:
            critical = c["name"] in ("MINT_AUTHORITY", "FREEZE_AUTHORITY", "TRANSFER_HOOK", "PERMANENT_DELEGATE",
                                     "NON_TRANSFERABLE", "DEFAULT_FROZEN", "PAUSABLE")
            s -= 3.5 if critical else 1.0
            neg.append(c["detail"])
    if sec.get("checks") and all(c["ok"] for c in sec["checks"]):
        pos.append("autorités mint et freeze révoquées, pas d'extension dangereuse")
    conc = (hol.get("concentration_excl_technical") or {}).get("top10")
    if conc is not None:
        n += 1
        if conc < 20:
            s += 1.5; pos.append(f"supply bien distribué (top 10 hors pools : {conc:.0f}%)")
        elif conc > 45:
            s -= 2.5; neg.append(f"top 10 hors pools : {conc:.0f}% du supply")
        elif conc > 30:
            s -= 1.0; neg.append(f"concentration notable (top 10 : {conc:.0f}%)")
    cl = sum(c["supply_pct"] for c in clu.get("clusters") or [])
    if cl > 15:
        s -= 1.5; neg.append(f"wallets à financement commun : {cl:.0f}% du supply")
    rep = (dev.get("reputation") or {}).get("score")
    if rep is not None:
        n += 1
        s += (rep - 5) * 0.3
        label = dev["reputation"]["label"]
        if label == "bonne":
            pos.append("bonne réputation du développeur")
        elif label == "mauvaise":
            neg.append("mauvaise réputation du développeur")
    elif dev.get("status") == "NON IDENTIFIÉ":
        neg.append("développeur non identifié")
    if liq.get("score") is not None:
        n += 1
        s -= [0, 0.5, 1.5, 3.0][liq["score"]]
        if liq["score"] >= 2:
            neg.append(f"risque de liquidité {liq['level']}")
    rc = (sec.get("rugcheck") or {}).get("score_normalised")
    if rc is not None and rc > 60:
        s -= 1.0; neg.append(f"score de risque RugCheck élevé ({rc})")
    return _s(s, min(0.9, 0.3 + 0.12 * n), ["synthèse sécurité, holders, clusters, développeur, liquidité"], pos, neg)


def score_momentum(r: dict) -> dict:
    """Momentum très court terme (scalp) : 5 min, activité de la bonding curve, traders uniques."""
    m = r.get("market") or {}
    if not (m.get("price_usd") or {}).get("v"):
        return _s(None, 0, ["aucune donnée de marché"])
    s, pos, neg, n = 5.0, [], [], 0
    pc = m.get("price_change") or {}
    ch5 = pc.get("m5")
    if ch5 is not None:
        n += 1
        if ch5 > 15:
            s += 1.2; pos.append(f"+{ch5:.0f}% sur 5 min")
        elif ch5 > 3:
            s += 0.6
        elif ch5 < -15:
            s -= 1.8; neg.append(f"{ch5:.0f}% sur 5 min")
        elif ch5 < -5:
            s -= 0.8
    tx = (m.get("txns") or {}).get("m5") or {}
    b, se = tx.get("buys") or 0, tx.get("sells") or 0
    if b + se >= 10:
        n += 1
        ratio = b / max(1, se)
        if ratio >= 2:
            s += 1.8; pos.append(f"forte pression acheteuse (5 min : {b} achats / {se} ventes)")
        elif ratio >= 1.3:
            s += 0.9; pos.append(f"acheteurs dominants (5 min : {b}/{se})")
        elif ratio < 0.7:
            s -= 2.0; neg.append(f"vendeurs dominants (5 min : {b}/{se})")
        elif ratio < 0.9:
            s -= 0.8
    act = m.get("curve_activity") or {}
    tpm = act.get("tx_per_min_5m")
    if tpm is not None:
        n += 1
        if tpm >= 20:
            s += 1.0; pos.append(f"curve très active ({tpm:.0f} tx/min)")
        elif tpm >= 8:
            s += 0.5
        elif tpm < 2:
            s -= 1.0; neg.append("curve quasi inactive")
    ppm = act.get("progress_per_min")
    if ppm is not None and ppm >= 1:
        s += 0.6; pos.append(f"curve se remplit vite (+{ppm:.1f} %/min)")
    ut = (m.get("unique_traders") or {}).get("m5") or {}
    if ut.get("buyers"):
        n += 1
        if ut["buyers"] >= 25:
            s += 0.6; pos.append(f"{ut['buyers']} acheteurs uniques en 5 min")
        elif ut["buyers"] < 5:
            s -= 0.6; neg.append("très peu d'acheteurs uniques sur 5 min")
    mom = m.get("momentum") or {}
    acc = mom.get("volume_acceleration")
    if acc is not None:
        n += 1
        if acc > 2:
            s += 0.8; pos.append(f"volume en accélération (×{acc:.1f})")
        elif acc < 0.4:
            s -= 0.8; neg.append("volume en net ralentissement")
    dd = mom.get("drawdown_from_high_pct")
    if dd is not None and dd < -40:
        s -= 1.0; neg.append(f"{dd:.0f}% sous le plus haut récent")
    org = m.get("organic") or {}
    if org.get("level") == "suspect":
        s -= 1.5; neg.append("activité possiblement artificielle : " + "; ".join(org.get("flags", [])[:2]))
    return _s(s, min(0.9, 0.35 + 0.12 * n), ["5 min, activité de la curve, traders uniques, volume"], pos, neg)


def score_momentum_20m(r: dict) -> dict:
    """Édition tech : momentum sur 20 minutes (prix, volume vs 20 min précédentes, achats/ventes 30 min, curve)."""
    m = r.get("market") or {}
    if not (m.get("price_usd") or {}).get("v"):
        return _s(None, 0, ["aucune donnée de marché"])
    s, pos, neg, n = 5.0, [], [], 0
    mom = m.get("momentum") or {}
    ch = (mom.get("change") or {}).get("20m")
    if ch is not None:
        n += 1
        if ch > 25:
            s += 1.5; pos.append(f"+{ch:.0f}% sur 20 min")
        elif ch > 5:
            s += 0.8
        elif ch < -25:
            s -= 2.0; neg.append(f"{ch:.0f}% sur 20 min")
        elif ch < -8:
            s -= 0.8
    tr = mom.get("volume_20m_trend")
    if tr is not None:
        n += 1
        if tr > 1.5:
            s += 1.0; pos.append(f"volume des 20 dernières min ×{tr:.1f} vs les 20 précédentes")
        elif tr < 0.5:
            s -= 1.0; neg.append("volume en net recul sur 20 min")
    tx = (m.get("gecko_txns") or {}).get("m30") or (m.get("txns") or {}).get("h1") or {}
    b, se = tx.get("buys") or 0, tx.get("sells") or 0
    if b + se >= 15:
        n += 1
        ratio = b / max(1, se)
        if ratio >= 1.5:
            s += 1.2; pos.append(f"acheteurs dominants ({b}/{se})")
        elif ratio < 0.75:
            s -= 1.5; neg.append(f"vendeurs dominants ({b}/{se})")
    tpm = (m.get("curve_activity") or {}).get("tx_per_min_20m")
    if tpm is not None:
        n += 1
        if tpm >= 10:
            s += 0.6; pos.append(f"curve active ({tpm:.0f} tx/min sur 20 min)")
        elif tpm < 1:
            s -= 0.8; neg.append("curve quasi inactive sur 20 min")
    org = m.get("organic") or {}
    if org.get("level") == "suspect":
        s -= 1.5; neg.append("activité possiblement artificielle")
    return _s(s, min(0.9, 0.35 + 0.13 * n), ["20 min : prix, volume, achats/ventes, activité de la curve"], pos, neg)


def score_from_section(r: dict, key: str) -> dict:
    sc = ((r.get(key) or {}).get("score")) or {}
    if not sc or sc.get("score") is None:
        return _s(None, 0, sc.get("reasons") or ["en attente"])
    pos = [x for x in sc.get("reasons", []) if sc["score"] >= 6]
    neg = [x for x in sc.get("reasons", []) if sc["score"] < 4.5]
    return _s(sc["score"], sc.get("confidence", 0.4), sc.get("reasons", []), pos, neg)


def score_credibility(r: dict) -> dict:
    proj = (r.get("project") or {}).get("score")
    fc = (r.get("factcheck") or {}).get("claims") or []
    if not proj and not fc:
        return _s(None, 0, ["en attente"])
    s = proj["score"] if proj else 4.0
    pos, neg = [], []
    if proj:
        (pos if s >= 6 else neg if s < 4 else []).extend(proj.get("reasons", [])[:2])
    conf_claims = [c for c in fc if c["status"].startswith("CONFIRMÉ")]
    bad = [c for c in fc if c["status"] in ("CONTREDIT", "FAUX OU TROMPEUR")]
    unv = [c for c in fc if c["status"] == "NON VÉRIFIÉ"]
    s += 0.8 * len(conf_claims) - 2.5 * len(bad) - 0.3 * min(3, len(unv))
    if conf_claims:
        pos.append(f"{len(conf_claims)} affirmation(s) confirmée(s) par des sources indépendantes")
    if unv:
        neg.append(f"{len(unv)} affirmation(s) promotionnelle(s) non vérifiée(s)")
    o = r.get("originality") or {}
    if o.get("verdict") == "copie probable":
        s -= 3.0; neg.append("copie probable d'un autre projet")
    elif o.get("verdict") == "peu originale":
        s -= 1.0; neg.append("projet peu original")
    elif o.get("verdict") == "originale":
        s += 0.5; pos.append("projet original (pas de copie ni de concept saturé trouvé)")
    return _s(s, (proj or {}).get("confidence", 0.4), ["site, documentation, GitHub, fact-checking"], pos, neg)


def risk_score(r: dict) -> dict:
    risks = r.get("risks") or []
    w = {"critique": 4.0, "élevé": 1.8, "moyen": 0.8, "info": 0}
    s = sum(w.get(x["level"], 0) for x in risks)
    liq = ((r.get("liquidity") or {}).get("risk_level") or {}).get("score") or 0
    s += (liq or 0) * 0.7
    crit = [x for x in risks if x["level"] == "critique"]
    label = "critique" if crit else "élevé" if s >= 5 else "modéré" if s >= 2 else "faible"
    return {"score": round(clamp(s), 1), "label": label, "critical": crit,
            "count": len(risks), "note": "Score de risque séparé du potentiel (10 = risque maximal)."}


def compute(r: dict, settings: dict, final: bool = False) -> dict:
    from ..config import active_weights
    weights = active_weights(settings)
    th = dict(settings.get("thresholds", {}))
    # Niveau de risque accepté : ajuste uniquement le risque maximal toléré pour un BUY SETUP.
    th["max_risk_buy"] = {"prudent": 3.5, "normal": th.get("max_risk_buy", 5.0), "agressif": 6.5}.get(
        settings.get("risk_tolerance", "normal"), th.get("max_risk_buy", 5.0))
    from ..config import EDITION as _ED
    cats = {"onchain": score_onchain(r), "momentum": score_momentum_20m(r) if _ED == "tech" else score_momentum(r),
            "narrative": score_from_section(r, "narrative"), "social": score_from_section(r, "social"),
            "credibility": score_credibility(r), "smart_money": score_from_section(r, "smart_money")}
    tot_w = sum(weights.get(c, 0) for c in CATS) or 1
    avail = [(c, cats[c]) for c in CATS if cats[c]["available"] and weights.get(c, 0) > 0]
    aw = sum(weights[c] for c, _ in avail)
    glob = sum(weights[c] * x["score"] for c, x in avail) / aw if aw else None
    confidence = sum(weights[c] * x["confidence"] for c, x in avail) / tot_w if avail else 0.0
    risk = risk_score(r)
    pos = [p for c in CATS for p in cats[c]["positives"]]
    neg = [n for c in CATS for n in cats[c]["negatives"]]
    neg = [x["message"] for x in risk["critical"]] + [n for n in neg if n not in [x["message"] for x in risk["critical"]]]

    if glob is None:
        verdict, why = "AVOID", "données insuffisantes pour évaluer le token"
    elif risk["critical"]:
        verdict, why = "AVOID", "risque critique identifié : " + risk["critical"][0]["message"]
    elif glob < th.get("avoid_below", 4):
        verdict, why = "AVOID", f"score global faible ({glob:.1f}/10)"
    elif confidence < th.get("min_confidence", 0.35):
        verdict, why = ("AVOID" if final else "WATCH"), f"confiance trop faible ({confidence * 100:.0f}%) : données insuffisantes"
    elif glob >= th.get("buy_setup_min", 7) and confidence >= th.get("min_confidence_buy", 0.6) \
            and risk["score"] <= th.get("max_risk_buy", 5):
        verdict, why = "BUY SETUP", "convergence de signaux favorables sans risque critique identifié"
    else:
        missing = []
        if glob < th.get("buy_setup_min", 7):
            missing.append(f"score {glob:.1f} < {th.get('buy_setup_min', 7)}")
        if confidence < th.get("min_confidence_buy", 0.6):
            missing.append(f"confiance {confidence * 100:.0f}% insuffisante")
        if risk["score"] > th.get("max_risk_buy", 5):
            missing.append(f"risque {risk['score']}/10")
        verdict, why = "WATCH", "intéressant mais à confirmer : " + ", ".join(missing)
    scalp = None
    if True:
        from ..config import EDITION
        if EDITION == "tech":
            from .tech import checklist
        else:
            from .scalp import checklist
        scalp = checklist(r, settings)
        # En mode Scalp, la checklist d'entrée prime : un blocage interdit BUY SETUP.
        if scalp["decision"] == "NE PAS ENTRER" and verdict != "AVOID":
            verdict, why = "AVOID", "checklist : " + scalp["reason"]
        elif scalp["decision"] in ("ATTENDRE", "EN COURS") and verdict == "BUY SETUP":
            verdict, why = "WATCH", "checklist : " + scalp["reason"]
    interp = next(lbl for lim, lbl in INTERPRETATION if glob is not None and glob < lim) if glob is not None else "—"
    if glob is not None and confidence < th.get("min_confidence", 0.35):
        interp = "non qualifiable (confiance trop faible)" if final else "provisoire — en attente de données"
    explanation = []
    for c, x in avail:
        explanation.append(f"{LABELS[c]} {x['score']}/10 × {weights[c]}%")
    missing_cats = [LABELS[c] for c in CATS if weights.get(c, 0) > 0 and not cats[c]["available"]]
    return {
        "global": None if glob is None else round(glob, 1), "confidence": round(confidence, 2),
        "categories": {c: {**cats[c], "label": LABELS[c], "weight": weights.get(c, 0)} for c in CATS},
        "risk": risk, "verdict": verdict, "verdict_reason": why, "interpretation": interp,
        "positives": list(dict.fromkeys(pos))[:5], "negatives": list(dict.fromkeys(neg))[:5],
        "explanation": "Moyenne pondérée : " + " ; ".join(explanation) +
                       (f". Non disponibles (exclues, confiance réduite) : {', '.join(missing_cats)}." if missing_cats else "."),
        "scalp": scalp,
        "disclaimer": "Évaluation du potentiel selon les indicateurs disponibles. Ce n'est ni une probabilité ni un "
                      "conseil financier ; aucun ordre n'est passé.",
    }
