"""Sécurité technique, holders, clusters de wallets et profil du développeur."""
from __future__ import annotations

import asyncio
import json
import time

from ..providers.solana import (INCINERATOR, METAPLEX_PROGRAM, TOKEN_2022_PROGRAM, decode_metaplex_metadata,
                                find_pda, is_on_curve, pubkey_bytes)
from ..util import ESTIMATED, OBSERVED, UNAVAILABLE, VERIFIED, dp, fnum

PUMP_UPDATE_AUTHORITY = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"


# ------------------------------------------------------------------ sécurité
async def run_security(ctx) -> None:
    svc = ctx.svc
    S = ctx.section("security")
    tok = ctx.section("token")
    mint_acc = await ctx.need("mint_account", timeout=5) or {}
    info = mint_acc.get("info") or {}
    S["mint_authority"] = dp(info.get("mintAuthority"), "RPC Solana (compte mint)")
    S["freeze_authority"] = dp(info.get("freezeAuthority"), "RPC Solana (compte mint)")
    checks = []

    def check(name, ok, detail, level="élevé"):
        checks.append({"name": name, "ok": ok, "detail": detail, "source": "RPC Solana"})
        if ok is False:
            ctx.risk(level, name, detail, "Sécurité technique")

    check("MINT_AUTHORITY", info.get("mintAuthority") is None,
          "Mint authority révoquée" if info.get("mintAuthority") is None
          else f"Mint authority ACTIVE ({info['mintAuthority']}) : de nouveaux tokens peuvent être créés", "critique")
    check("FREEZE_AUTHORITY", info.get("freezeAuthority") is None,
          "Freeze authority révoquée" if info.get("freezeAuthority") is None
          else f"Freeze authority ACTIVE ({info['freezeAuthority']}) : les comptes des détenteurs peuvent être gelés",
          "critique")

    if mint_acc.get("owner") == TOKEN_2022_PROGRAM:
        exts = {e.get("extension"): e.get("state") or {} for e in info.get("extensions") or []}
        S["token2022_extensions"] = sorted(exts)
        if "transferFeeConfig" in exts:
            st = exts["transferFeeConfig"]
            bps = ((st.get("newerTransferFee") or {}).get("transferFeeBasisPoints")
                   or (st.get("olderTransferFee") or {}).get("transferFeeBasisPoints") or 0)
            S["transfer_fee_pct"] = dp(bps / 100, "RPC Solana (extension Token-2022)")
            check("TRANSFER_FEE", bps <= 100, f"Frais de transfert : {bps / 100:.2f}%",
                  "critique" if bps > 1000 else "élevé")
        if "transferHook" in exts and exts["transferHook"].get("programId"):
            check("TRANSFER_HOOK", False, f"Transfer hook actif (programme {exts['transferHook']['programId']}) : "
                  "un programme externe peut bloquer les transferts", "critique")
        if "permanentDelegate" in exts and exts["permanentDelegate"].get("delegate"):
            check("PERMANENT_DELEGATE", False, "Délégué permanent : une adresse peut déplacer ou brûler les tokens "
                  "de n'importe quel détenteur", "critique")
        if "nonTransferable" in exts:
            check("NON_TRANSFERABLE", False, "Token non transférable", "critique")
        if (exts.get("defaultAccountState") or {}).get("accountState") == "frozen":
            check("DEFAULT_FROZEN", False, "Les nouveaux comptes sont gelés par défaut", "critique")
        if "pausableConfig" in exts:
            check("PAUSABLE", False, "Les transferts peuvent être mis en pause par une autorité", "critique")
        if "mintCloseAuthority" in exts and exts["mintCloseAuthority"].get("closeAuthority"):
            check("MINT_CLOSE_AUTHORITY", False, "Autorité de fermeture du mint active", "moyen")

    # Métadonnées Metaplex
    try:
        md_pda = find_pda([b"metadata", pubkey_bytes(METAPLEX_PROGRAM), pubkey_bytes(ctx.mint)], METAPLEX_PROGRAM)
        raw = await svc.rpc.account_bytes(md_pda)
        md = decode_metaplex_metadata(raw[0]) if raw else None
    except Exception:
        md = None
    if md:
        tok.setdefault("name", md["name"])
        tok.setdefault("symbol", md["symbol"])
        tok.setdefault("metadata_uri", md["uri"])
        S["metadata"] = {"mutable": md["mutable"], "update_authority": md["update_authority"],
                         "source": "Compte Metaplex (on-chain)"}
        if md["mutable"] and md["update_authority"] != PUMP_UPDATE_AUTHORITY:
            check("MUTABLE_METADATA", False, "Métadonnées modifiables (nom, image, liens peuvent changer)", "moyen")
    ctx.provide("metadata_uri", tok.get("metadata_uri"))

    # RugCheck : 2e source indépendante
    try:
        rc = await svc.rug.report(ctx.mint)
    except Exception as exc:
        rc = None
        S["rugcheck_error"] = str(exc)
    ctx.provide("rugcheck", rc)
    if isinstance(rc, dict):
        S["rugcheck"] = {"score_normalised": rc.get("score_normalised"), "rugged": rc.get("rugged"),
                         "risks": [{"name": r.get("name"), "level": r.get("level"), "description": r.get("description"),
                                    "value": r.get("value")} for r in rc.get("risks") or []][:20],
                         "source": "RugCheck API"}
        if rc.get("rugged"):
            ctx.risk("critique", "RUGGED", "RugCheck signale ce token comme « rugged »", "RugCheck")
        for r in rc.get("risks") or []:
            if (r.get("level") or "").lower() == "danger":
                ctx.risk("élevé", f"RC_{(r.get('name') or '')[:30]}",
                         f"RugCheck : {r.get('name')} — {r.get('description') or ''}".strip(" —"), "RugCheck")
    S["checks"] = checks
    S["note"] = ("Ces contrôles réduisent certains risques techniques mais ne garantissent pas l'absence d'arnaque. "
                 "Sources : lecture directe de la blockchain" + (" + RugCheck." if rc else " (RugCheck indisponible)."))


# ------------------------------------------------------------------ holders
async def run_holders(ctx) -> None:
    svc = ctx.svc
    H = ctx.section("holders")
    tok = ctx.result.get("token", {})
    dec = tok.get("decimals", 0)
    supply_raw = tok.get("supply_raw") or 0
    if not supply_raw:
        H["unavailable"] = "Supply nulle ou inconnue"
        return
    largest = await svc.rpc.largest_accounts(ctx.mint)
    accounts = await svc.rpc.multiple_accounts([a["address"] for a in largest])
    market = await ctx.need("market", timeout=6) or {}
    pools = set(a for a in market.get("pair_addresses") or [] if a)
    curve = await ctx.need("pump_curve", timeout=3)
    if curve and curve.get("address"):
        pools.add(curve["address"])  # la bonding curve détient les tokens non vendus : compte technique
    creator = (await ctx.need("creator", timeout=4)) or {}
    tracked = {w["address"]: w.get("label") for w in svc.db.all("SELECT address, label FROM wallets WHERE tracked=1")}
    rows = []
    for a, acc in zip(largest, accounts):
        owner = None
        try:
            owner = acc["data"]["parsed"]["info"]["owner"]
        except (TypeError, KeyError):
            pass
        amount = int(a["amount"])
        kind, label = "wallet", None
        if owner == INCINERATOR:
            kind, label = "burn", "Adresse de burn"
        elif owner in pools or a["address"] in pools:
            kind, label = "pool", "Pool de liquidité / bonding curve"
        elif owner and not is_on_curve(owner):
            kind, label = "program", "Compte de programme (PDA : pool, vault, curve…)"
        if owner and owner == creator.get("address"):
            label = "Développeur (créateur)"
        if owner in tracked:
            label = f"Wallet suivi : {tracked[owner] or owner[:6]}"
        rows.append({"token_account": a["address"], "owner": owner, "amount": amount / 10 ** dec,
                     "pct": 100 * amount / supply_raw, "kind": kind, "label": label})
    H["top"] = rows
    H["source"] = "RPC Solana getTokenLargestAccounts (20 plus gros comptes)"
    real = [r for r in rows if r["kind"] == "wallet"]

    def top(n, lst):
        return round(sum(r["pct"] for r in lst[:n]), 2)
    H["concentration_raw"] = {"top5": top(5, rows), "top10": top(10, rows), "top20": top(20, rows)}
    H["concentration_excl_technical"] = {"top5": top(5, real), "top10": top(10, real), "top20": top(20, real)}
    H["technical_pct"] = round(sum(r["pct"] for r in rows if r["kind"] != "wallet"), 2)

    # Nombre total de holders : Helius (clé gratuite) > RugCheck > indisponible
    total, src = None, None
    try:
        res = await svc.rpc.helius_holders(ctx.mint, max_pages=5)
        if res:
            accs, complete = res
            owners = {}
            for x in accs:
                if int(x.get("amount") or 0) > 0:
                    owners[x["owner"]] = owners.get(x["owner"], 0) + int(x["amount"])
            if complete:
                total, src = len(owners), "Helius DAS (comptage complet)"
                ranked = sorted(owners.items(), key=lambda kv: -kv[1])
                H["top50_pct_raw"] = round(100 * sum(v for _, v in ranked[:50]) / supply_raw, 2)
            else:
                total, src = len(owners), "Helius DAS (> 5 000 comptes : minimum)"
                H["holders_is_minimum"] = True
    except Exception as exc:
        H["helius_error"] = str(exc)
    if total is None:
        rc = await ctx.need("rugcheck", timeout=5)
        if isinstance(rc, dict) and rc.get("totalHolders"):
            total, src = int(rc["totalHolders"]), "RugCheck"
    H["total"] = dp(total, src or "aucune source gratuite disponible (ajoute une clé Helius gratuite)",
                    OBSERVED if total else UNAVAILABLE)
    prev = svc.db.one("SELECT holders, ts FROM holder_snapshots WHERE mint=? AND holders IS NOT NULL ORDER BY ts DESC LIMIT 1",
                      (ctx.mint,))
    if prev and total:
        H["evolution_since_last"] = {"previous": prev["holders"], "since_s": time.time() - prev["ts"],
                                     "delta": total - prev["holders"]}
    svc.db.execute("INSERT INTO holder_snapshots(mint, ts, top10_pct, top20_pct, holders, data) VALUES(?,?,?,?,?,?)",
                   (ctx.mint, time.time(), H["concentration_excl_technical"]["top10"],
                    H["concentration_excl_technical"]["top20"], total, json.dumps(rows)))
    c10 = H["concentration_excl_technical"]["top10"]
    if real and real[0]["pct"] > 15:
        ctx.risk("élevé", "WHALE", f"Un seul wallet détient {real[0]['pct']:.1f}% du supply", "Holders")
    if c10 > 45:
        ctx.risk("élevé", "CONCENTRATION", f"Top 10 (hors pools/burn) = {c10:.1f}% du supply", "Holders")
    ctx.provide("holders", H)


# ------------------------------------------------------------------ clusters
async def run_clusters(ctx) -> None:
    """Liens observés entre gros holders : même source de financement, création rapprochée.
    Ce sont des OBSERVATIONS ; une propriété commune n'est jamais affirmée."""
    svc = ctx.svc
    C = ctx.section("clusters")
    H = await ctx.need("holders", timeout=10)
    if not H:
        C["unavailable"] = "holders indisponibles"
        return
    wallets = [r["owner"] for r in H.get("top", []) if r["kind"] == "wallet" and r["owner"]][:15]
    sem = asyncio.Semaphore(4)

    async def funding(w):
        async with sem:
            try:
                sigs = await svc.rpc.signatures(w, 1000)
            except Exception:
                return w, None
            if not sigs or len(sigs) >= 1000:
                return w, {"old_wallet": True, "tx_count": len(sigs or [])}
            first = sigs[-1]
            try:
                tx = await svc.rpc.transaction(first["signature"])
            except Exception:
                tx = None
            funder = None
            for ix in ((tx or {}).get("transaction") or {}).get("message", {}).get("instructions", []):
                p = ix.get("parsed") if isinstance(ix, dict) else None
                if isinstance(p, dict) and p.get("type") in ("transfer", "transferWithSeed") \
                        and (p.get("info") or {}).get("destination") == w:
                    funder = p["info"].get("source")
                    break
            return w, {"first_tx_time": first.get("blockTime"), "tx_count": len(sigs), "funder": funder}

    res = dict(await asyncio.gather(*[funding(w) for w in wallets]))
    groups: dict[str, list[str]] = {}
    for w, info in res.items():
        if info and info.get("funder"):
            groups.setdefault(info["funder"], []).append(w)
    pct = {r["owner"]: r["pct"] for r in H.get("top", [])}
    clusters = [{"funder": f, "wallets": ws, "supply_pct": round(sum(pct.get(w, 0) for w in ws), 2),
                 "link": "financement commun observé (1re transaction)", "status": ESTIMATED}
                for f, ws in groups.items() if len(ws) >= 2]
    fresh = [w for w, i in res.items() if i and not i.get("old_wallet") and i.get("tx_count", 0) < 20]
    times = sorted(i["first_tx_time"] for i in res.values() if i and i.get("first_tx_time"))
    C["clusters"] = sorted(clusters, key=lambda c: -c["supply_pct"])
    C["fresh_wallets"] = {"count": len(fresh), "of": len(wallets),
                          "supply_pct": round(sum(pct.get(w, 0) for w in fresh), 2)}
    if len(times) >= 3:
        span = [times[i + 2] - times[i] for i in range(len(times) - 2)]
        C["min_creation_gap_3_wallets_s"] = min(span)
    rc = await ctx.need("rugcheck", timeout=2)
    if isinstance(rc, dict) and (rc.get("graphInsidersDetected") or rc.get("insiderNetworks")):
        C["rugcheck_insiders"] = {"detected": rc.get("graphInsidersDetected"),
                                  "networks": len(rc.get("insiderNetworks") or []), "source": "RugCheck"}
    C["method"] = ("Analyse des 15 plus gros wallets : source du premier financement en SOL et ancienneté. "
                   "Un financement commun est un lien observé, pas une preuve de propriété commune.")
    total_cluster = sum(c["supply_pct"] for c in clusters)
    if total_cluster > 15:
        ctx.risk("élevé", "CLUSTER", f"Wallets à financement commun détenant {total_cluster:.1f}% du supply (lien observé)",
                 "Clusters")
    if C["fresh_wallets"]["supply_pct"] > 25:
        ctx.risk("moyen", "FRESH_WALLETS", f"{C['fresh_wallets']['count']} wallets neufs détiennent "
                 f"{C['fresh_wallets']['supply_pct']:.1f}% du supply (bundle possible)", "Clusters")


# ------------------------------------------------------------------ développeur
async def run_developer(ctx) -> None:
    svc = ctx.svc
    D = ctx.section("developer")
    creator = await ctx.need("creator", timeout=10)
    if not creator:
        rc = await ctx.need("rugcheck", timeout=3)
        if isinstance(rc, dict) and rc.get("creator"):
            creator = {"address": rc["creator"], "source": "RugCheck", "status": OBSERVED}
    if not creator:
        D["identified"] = False
        D["status"] = "NON IDENTIFIÉ"
        D["reputation"] = None
        D["note"] = "Créateur non identifiable avec les données disponibles : aucune réputation attribuée."
        return
    addr = creator["address"]
    D.update(identified=True, address=addr, address_source=creator["source"], address_status=creator["status"])
    tok = ctx.result.get("token", {})
    dec, supply_raw = tok.get("decimals", 0), tok.get("supply_raw") or 0

    async def holding():
        bal = await svc.rpc.token_balance_of(addr, ctx.mint)
        return 100 * bal / supply_raw if supply_raw else None

    hold_r, sol_r, sigs_r, created_r = await asyncio.gather(
        holding(), svc.rpc.balance(addr), svc.rpc.signatures(addr, 1000),
        svc.pump.created_by(addr, 50), return_exceptions=True)
    if not isinstance(hold_r, Exception):
        D["current_holding_pct"] = dp(hold_r, "RPC Solana")
        if hold_r and hold_r > 10:
            ctx.risk("élevé", "DEV_HOLDING", f"Le développeur détient encore {hold_r:.1f}% du supply", "Développeur")
    if not isinstance(sol_r, Exception):
        D["sol_balance"] = dp(sol_r / 1e9, "RPC Solana")
    if not isinstance(sigs_r, Exception):
        D["tx_count"] = {"value": len(sigs_r), "is_minimum": len(sigs_r) >= 1000}
        if sigs_r and len(sigs_r) < 1000 and sigs_r[-1].get("blockTime"):
            D["wallet_first_seen"] = dp(sigs_r[-1]["blockTime"], "RPC Solana")
    prev = []
    if isinstance(created_r, list):
        prev = [c for c in created_r if c.get("mint") and c.get("mint") != ctx.mint]
        D["previous_tokens_source"] = "pump.fun (API publique non officielle) + DexScreener"
    else:
        D["previous_tokens_error"] = f"Historique de lancements indisponible : {created_r}"
    if prev:
        try:
            pairs = await svc.dex.pairs([c["mint"] for c in prev[:30]])
        except Exception:
            pairs = []
        liq = {}
        for p in pairs:
            a = (p.get("baseToken") or {}).get("address")
            liq[a] = max(liq.get(a, 0), (p.get("liquidity") or {}).get("usd") or 0)
        hist = []
        for c in prev[:30]:
            l = liq.get(c["mint"], 0)
            created = (c.get("created_timestamp") or 0) / 1000
            last = (c.get("last_trade_timestamp") or 0) / 1000
            hist.append({"mint": c["mint"], "symbol": c.get("symbol"), "name": c.get("name"),
                         "created_at": created or None, "migrated": bool(c.get("complete")),
                         "usd_market_cap": fnum(c.get("usd_market_cap")),
                         "liquidity_usd": l, "alive": l >= 10_000,
                         "lifetime_h": (last - created) / 3600 if last and created and last > created else None})
        D["previous_tokens"] = hist
        n = len(hist)
        migrated = sum(1 for h in hist if h["migrated"])
        alive = sum(1 for h in hist if h["alive"])
        lifetimes = sorted(h["lifetime_h"] for h in hist if h["lifetime_h"] is not None)
        D["history_stats"] = {"count": n, "count_is_minimum": len(created_r) >= 50 if isinstance(created_r, list) else False,
                              "migrated": migrated, "alive_now": alive, "dead_ratio": round(1 - alive / n, 2),
                              "median_lifetime_h": lifetimes[len(lifetimes) // 2] if lifetimes else None}
        if n >= 10 and alive / n < 0.1:
            ctx.risk("élevé", "SERIAL_LAUNCHER", f"Le créateur a lancé {n}+ tokens dont {n - alive} sont morts", "Développeur")
    D["reputation"] = developer_reputation(D)
    svc.db.execute("INSERT INTO developer_profiles(address, updated_at, data) VALUES(?,?,?) "
                   "ON CONFLICT(address) DO UPDATE SET updated_at=excluded.updated_at, data=excluded.data",
                   (addr, time.time(), json.dumps({k: v for k, v in D.items() if k != "previous_tokens"})))


def developer_reputation(D: dict) -> dict:
    reasons, score, known = [], 5.0, 0
    st = D.get("history_stats")
    if st:
        known += 1
        n = st["count"]
        if n == 0:
            reasons.append("aucun lancement précédent connu")
        else:
            if n >= 20:
                score -= 2.5; reasons.append(f"lanceur en série ({n}+ tokens)")
            elif n >= 5:
                score -= 1; reasons.append(f"{n} tokens lancés auparavant")
            if st["dead_ratio"] >= 0.9 and n >= 3:
                score -= 2; reasons.append(f"{st['dead_ratio'] * 100:.0f}% de ses anciens tokens sont morts")
            if st["migrated"] and st["migrated"] / n >= 0.2:
                score += 1.5; reasons.append(f"{st['migrated']} token(s) ont terminé leur bonding curve")
            if st["alive_now"] >= 2:
                score += 1; reasons.append(f"{st['alive_now']} ancien(s) token(s) encore liquides")
    hold = (D.get("current_holding_pct") or {}).get("v")
    if hold is not None:
        known += 1
        if hold > 10:
            score -= 1.5; reasons.append(f"détient encore {hold:.1f}% du supply")
        elif hold == 0:
            reasons.append("ne détient plus de tokens (vente ou transfert — neutre en soi)")
    fs = (D.get("wallet_first_seen") or {}).get("v")
    if fs and time.time() - fs < 3 * 86400:
        known += 1
        score -= 0.5; reasons.append("wallet créé il y a moins de 3 jours")
    if known == 0:
        return {"score": None, "label": "NON ÉVALUÉ", "reasons": ["données d'historique indisponibles"]}
    score = max(0.0, min(10.0, score))
    label = "bonne" if score >= 7 else "neutre" if score >= 4.5 else "mauvaise"
    return {"score": round(score, 1), "label": label, "reasons": reasons, "status": ESTIMATED,
            "completeness": "partielle" if known < 3 else "correcte"}
