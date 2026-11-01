"""Checklist d'entrée scalp : adaptée à une stratégie « entrée 6-15 k$ de market cap, sortie +30-50 %, petite taille ».

Chaque contrôle : ok / attention / bloquant / en attente, avec sa raison. Décision :
- un contrôle bloquant → NE PAS ENTRER
- 3 « attention » ou plus → ATTENDRE
- sinon → ENTRÉE POSSIBLE
Ce n'est pas une prédiction : la checklist élimine les pièges et vérifie que le contexte est porteur.
"""
from __future__ import annotations

import time

OK, WARN, BAD, WAIT = "ok", "attention", "bloquant", "en attente"
PLATFORM_FEE_PCT = 1.0  # frais de plateforme par sens (hypothèse affichée)


def _c(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def checklist(r: dict, settings: dict) -> dict:
    sc = settings.get("scalp") or {}
    lo, hi = float(sc.get("entry_mcap_min", 6000)), float(sc.get("entry_mcap_max", 15000))
    tp = float(sc.get("take_profit_pct", 40))
    sl = float(sc.get("stop_pct", 20))
    pos = float(sc.get("position_sol", 0.25))
    m, sec, H = r.get("market") or {}, r.get("security") or {}, r.get("holders") or {}
    C, D, S, L = r.get("clusters") or {}, r.get("developer") or {}, r.get("social") or {}, r.get("liquidity") or {}
    mods = r.get("modules") or {}
    pending = lambda k: (mods.get(k) or {}).get("status") == "en cours"  # noqa: E731
    checks = []

    # 1. Zone de market cap
    mcap = (m.get("mcap") or {}).get("v")
    if mcap is None:
        checks.append(_c("Zone de market cap", WAIT if pending("market") else BAD, "market cap inconnue"))
    elif mcap < lo:
        checks.append(_c("Zone de market cap", WARN, f"${mcap:,.0f} : sous ta zone (${lo:,.0f}–${hi:,.0f}), très tôt = plus risqué"))
    elif mcap > hi:
        checks.append(_c("Zone de market cap", WARN, f"${mcap:,.0f} : au-dessus de ta zone (${lo:,.0f}–${hi:,.0f})"))
    else:
        checks.append(_c("Zone de market cap", OK, f"${mcap:,.0f} : dans ta zone (${lo:,.0f}–${hi:,.0f})"))

    # 2. Pièges techniques
    crit = [x for x in r.get("risks") or [] if x["level"] == "critique"]
    if pending("security") and not sec.get("checks"):
        checks.append(_c("Pièges techniques", WAIT, "contrôles en cours"))
    elif crit:
        checks.append(_c("Pièges techniques", BAD, crit[0]["message"]))
    else:
        checks.append(_c("Pièges techniques", OK, "mint/freeze révoqués, pas d'extension dangereuse détectée"))

    # 3. Bundle / snipers
    if not C or pending("clusters"):
        checks.append(_c("Bundle / snipers", WAIT, "analyse des wallets en cours"))
    elif C.get("unavailable"):
        checks.append(_c("Bundle / snipers", WARN, "analyse des wallets indisponible"))
    else:
        fresh = (C.get("fresh_wallets") or {}).get("supply_pct") or 0
        clus = sum(c["supply_pct"] for c in C.get("clusters") or [])
        tot = max(fresh, clus)
        st = OK if tot < 15 else WARN if tot < 30 else BAD
        checks.append(_c("Bundle / snipers", st, f"wallets neufs {fresh:.0f}% · financement commun {clus:.0f}% du supply"))

    # 4. Concentration
    top10 = (H.get("concentration_excl_technical") or {}).get("top10")
    if top10 is None:
        checks.append(_c("Concentration", WAIT if pending("holders") else WARN, "holders indisponibles"))
    else:
        biggest = max([x["pct"] for x in H.get("top", []) if x["kind"] == "wallet"] or [0])
        st = BAD if top10 > 40 or biggest > 12 else WARN if top10 > 25 or biggest > 6 else OK
        checks.append(_c("Concentration", st, f"top 10 hors curve/pools {top10:.0f}% · plus gros wallet {biggest:.1f}%"))

    # 5. Développeur
    if pending("developer"):
        checks.append(_c("Développeur", WAIT, "profil en cours"))
    elif not D.get("identified"):
        checks.append(_c("Développeur", WARN, "non identifié"))
    else:
        hold = (D.get("current_holding_pct") or {}).get("v")
        rep = D.get("reputation") or {}
        st, why = OK, []
        if hold is not None:
            why.append(f"détient {hold:.1f}%")
            st = BAD if hold > 15 else WARN if hold > 5 else st
        if rep.get("label") == "mauvaise":
            st = BAD
        elif rep.get("label") == "neutre" and st == OK and (D.get("history_stats") or {}).get("count", 0) >= 5:
            st = WARN
        if rep.get("reasons"):
            why.append(rep["reasons"][0])
        checks.append(_c("Développeur", st, " · ".join(why) or "aucune donnée"))

    # 6. Momentum
    tx5 = (m.get("txns") or {}).get("m5") or {}
    b, s_ = tx5.get("buys") or 0, tx5.get("sells") or 0
    act = m.get("curve_activity") or {}
    why, st = [], WAIT if pending("market") else WARN
    if b + s_ >= 10:
        ratio = b / max(1, s_)
        why.append(f"achats/ventes 5 min : {b}/{s_}")
        st = OK if ratio >= 1.3 else WARN if ratio >= 0.8 else BAD
    if act.get("tx_per_min_5m") is not None:
        why.append(f"{act['tx_per_min_5m']:.0f} tx/min sur la curve")
        if act["tx_per_min_5m"] < 2 and st != BAD:
            st = WARN
            why.append("activité faible")
    if act.get("progress_per_min") is not None:
        why.append(f"curve +{act['progress_per_min']:.2f} %/min")
    checks.append(_c("Momentum", st if why else (WAIT if pending("market") else WARN),
                     " · ".join(why) or "pas assez de transactions récentes pour juger"))

    # 7. Coût aller-retour vs objectif
    t = next((x for x in L.get("impact_tests") or [] if abs(x["size_sol"] - pos) < 1e-9), None)
    cost = None
    if t and t.get("buy_impact_pct") is not None and t.get("sell_impact_pct") is not None:
        cost = t["buy_impact_pct"] + t["sell_impact_pct"] + 2 * PLATFORM_FEE_PCT
        st = OK if cost < tp * 0.15 else WARN if cost < tp * 0.3 else BAD
        checks.append(_c("Coût aller-retour", st, f"≈ {cost:.1f}% pour {pos:g} SOL (impact + ~{PLATFORM_FEE_PCT:g}% de frais par sens) "
                                                    f"vs objectif +{tp:g}%"))
    else:
        checks.append(_c("Coût aller-retour", WAIT if pending("liquidity") else WARN, "impact non mesuré"))

    # 8. Réseaux sociaux
    if pending("social"):
        checks.append(_c("Réseaux sociaux", WAIT, "vérification en cours"))
    else:
        accs = [a for v in (S.get("accounts") or {}).values() for a in v]
        if any(a.get("status") == "USURPATION PROBABLE" for a in accs):
            checks.append(_c("Réseaux sociaux", BAD, "usurpation probable d'un compte connu"))
        elif any(a.get("status") in ("AUTHENTIQUE VÉRIFIÉ", "PROBABLEMENT AUTHENTIQUE") for a in accs):
            checks.append(_c("Réseaux sociaux", OK, "au moins un compte cohérent avec le token"))
        else:
            checks.append(_c("Réseaux sociaux", WARN, "aucun compte vérifiable (fréquent à ce stade)"))

    decision, why = decide(checks)
    return finish(checks, decision, why, mcap, tp, sl, pos, L)


def decide(checks: list[dict]) -> tuple[str, str]:
    bads = [c for c in checks if c["status"] == BAD]
    warns = [c for c in checks if c["status"] == WARN]
    waits = [c for c in checks if c["status"] == WAIT]
    if bads:
        decision, why = "NE PAS ENTRER", f"bloquant : {bads[0]['name'].lower()} — {bads[0]['detail']}"
    elif len(warns) >= 3:
        decision, why = "ATTENDRE", f"{len(warns)} points d'attention : " + ", ".join(c["name"].lower() for c in warns)
    elif waits:
        decision, why = "EN COURS", "contrôles encore en cours : " + ", ".join(c["name"].lower() for c in waits)
    else:
        decision, why = "ENTRÉE POSSIBLE", "aucun blocage" + (f", {len(warns)} point(s) d'attention" if warns else "")
    return decision, why


def cost_for(L: dict, pos: float) -> float | None:
    t = next((x for x in L.get("impact_tests") or [] if abs(x["size_sol"] - pos) < 1e-9), None)
    if t and t.get("buy_impact_pct") is not None and t.get("sell_impact_pct") is not None:
        return t["buy_impact_pct"] + t["sell_impact_pct"] + 2 * PLATFORM_FEE_PCT
    return None


def finish(checks, decision, why, mcap, tp, sl, pos, L) -> dict:
    cost = cost_for(L, pos)
    plan = None
    if mcap:
        net_tp = tp - (cost or 0)
        net_sl = -sl - (cost or 0)
        plan = {"entry_mcap": mcap, "target_mcap": mcap * (1 + tp / 100), "stop_mcap": mcap * (1 - sl / 100),
                "position_sol": pos, "take_profit_pct": tp, "stop_pct": sl, "cost_pct": cost,
                "gain_sol": pos * net_tp / 100, "loss_sol": pos * net_sl / 100,
                "breakeven_winrate": (abs(net_sl) / (net_tp + abs(net_sl))) if net_tp > 0 else None}
    return {"decision": decision, "reason": why, "checks": checks, "plan": plan, "computed_at": time.time(),
            "note": "Checklist d'élimination des pièges, pas une prédiction. Décide toujours toi-même."}
