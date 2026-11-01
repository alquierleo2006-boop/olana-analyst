"""Identification : validité de l'adresse, existence du mint, programme token, launchpad réel, mode d'analyse."""
from __future__ import annotations

import asyncio

from ..providers.solana import (LAUNCHLAB_PROGRAM, PROGRAMS, PUMPFUN_PROGRAM, TOKEN_2022_PROGRAM,
                                TOKEN_PROGRAM, WSOL_MINT, decode_pump_curve, find_pda, pubkey_bytes)
from ..util import ESTIMATED, OBSERVED, VERIFIED, dp, is_valid_mint_format
from .context import Ctx, InvalidAddress, TokenNotFound

LAUNCHPAD_LABELS = {"pumpfun": "Pump.fun", "letsbonk": "LetsBonk", "launchlab": "Raydium LaunchLab",
                    "meteora_dbc": "Meteora DBC", "stonkfun": "Stonk.fun", "unknown": "Non identifié"}


async def identify(ctx: Ctx) -> None:
    """Étape bloquante : sans mint valide et existant, aucune analyse n'est lancée."""
    if not is_valid_mint_format(ctx.mint):
        raise InvalidAddress("Adresse Solana invalide (format base58 / 32 octets attendu).")
    acc = await ctx.svc.rpc.account_info(ctx.mint)
    if not acc:
        raise TokenNotFound("Aucun compte trouvé à cette adresse sur Solana mainnet.")
    data = acc.get("data")
    parsed = data.get("parsed") if isinstance(data, dict) else None
    if acc.get("owner") not in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM) or not parsed or parsed.get("type") != "mint":
        raise TokenNotFound("Cette adresse existe mais n'est pas un mint de token (wallet, programme ou autre compte).")
    info = parsed["info"]
    tok = ctx.section("token")
    tok["mint"] = ctx.mint
    tok["token_program"] = dp("Token-2022" if acc["owner"] == TOKEN_2022_PROGRAM else "SPL Token", "RPC Solana")
    tok["decimals"] = int(info.get("decimals", 0))
    tok["supply_raw"] = int(info.get("supply", 0))
    tok["supply"] = dp(int(info.get("supply", 0)) / 10 ** tok["decimals"], "RPC Solana")
    ctx.provide("mint_account", {"owner": acc["owner"], "info": info})
    # Métadonnées Token-2022 intégrées (si présentes)
    for ext in info.get("extensions") or []:
        if ext.get("extension") == "tokenMetadata":
            st = ext.get("state") or {}
            tok.setdefault("name", st.get("name"))
            tok.setdefault("symbol", st.get("symbol"))
            tok["metadata_uri"] = st.get("uri")


async def detect_launchpad(ctx: Ctx) -> None:
    """Détection par les comptes on-chain : bonding curve Pump.fun, pool LaunchLab, puis transaction de création."""
    rpc = ctx.svc.rpc
    tok = ctx.section("token")
    lp = {"id": "unknown", "label": LAUNCHPAD_LABELS["unknown"], "status": "non identifié", "evidence": []}

    pump_pda = find_pda([b"bonding-curve", pubkey_bytes(ctx.mint)], PUMPFUN_PROGRAM)
    lab_pda = find_pda([b"pool", pubkey_bytes(ctx.mint), pubkey_bytes(WSOL_MINT)], LAUNCHLAB_PROGRAM)
    pump_acc, lab_acc = await asyncio.gather(rpc.account_bytes(pump_pda), rpc.account_bytes(lab_pda),
                                             return_exceptions=True)
    curve = None
    if isinstance(pump_acc, tuple) and pump_acc[1] == PUMPFUN_PROGRAM:
        curve = decode_pump_curve(pump_acc[0])
        lp.update(id="pumpfun", label="Pump.fun", status="vérifié on-chain")
        lp["evidence"].append(f"Bonding curve Pump.fun trouvée ({pump_pda})")
        if curve:
            curve["address"] = pump_pda
            lp["bonding_curve"] = {"progress_pct": curve["progress_pct"], "complete": curve["complete"],
                                   "address": pump_pda}
            if curve["creator"]:
                ctx.provide("creator", {"address": curve["creator"], "source": "bonding curve Pump.fun (on-chain)",
                                        "status": VERIFIED})
    elif isinstance(lab_acc, tuple) and lab_acc[1] == LAUNCHLAB_PROGRAM:
        lp.update(id="launchlab", label="Raydium LaunchLab", status="vérifié on-chain")
        lp["evidence"].append(f"Pool Raydium LaunchLab trouvé ({lab_pda})")
        lp["pool"] = lab_pda
        if ctx.mint.lower().endswith("bonk"):
            lp.update(id="letsbonk", label="LetsBonk (via Raydium LaunchLab)")
            lp["evidence"].append("Plateforme LetsBonk : estimée (suffixe 'bonk' de l'adresse) — LaunchLab vérifié")
    ctx.provide("pump_curve", curve)

    # Transaction de création : date, créateur, programme réellement utilisé.
    creation = await creation_transaction(ctx)
    if creation:
        tok["created_at"] = dp(creation["block_time"], "RPC Solana (1re transaction du mint)", VERIFIED)
        progs = creation["programs"]
        if lp["id"] == "unknown":
            for pid in progs:
                if pid in PROGRAMS and PROGRAMS[pid][0] in ("pumpfun", "launchlab", "meteora_dbc"):
                    key, label = PROGRAMS[pid]
                    lp.update(id=key, label=label, status="vérifié on-chain")
                    lp["evidence"].append(f"Programme {label} appelé dans la transaction de création")
                    if key == "launchlab" and ctx.mint.lower().endswith("bonk"):
                        lp.update(id="letsbonk", label="LetsBonk (via Raydium LaunchLab)")
                    break
        if creation.get("fee_payer"):
            ctx.provide("creator", {"address": creation["fee_payer"],
                                    "source": "payeur de la transaction de création (on-chain)", "status": OBSERVED})
    else:
        tok["created_at"] = dp(None, "RPC Solana", "indisponible")
        lp["evidence"].append("Historique trop long pour remonter à la création dans le budget de temps")

    if lp["id"] == "unknown":
        m = ctx.mint.lower()
        hint = "pumpfun" if m.endswith("pump") else "letsbonk" if m.endswith("bonk") else None
        if hint:
            lp["hint"] = LAUNCHPAD_LABELS[hint]
            lp["evidence"].append(f"Indice non vérifié : suffixe de l'adresse évoque {LAUNCHPAD_LABELS[hint]}")
            lp["status"] = "indice seulement"
    tok["launchpad"] = lp
    ctx.provide("launchpad", lp)


async def creation_transaction(ctx: Ctx) -> dict | None:
    rpc = ctx.svc.rpc
    try:
        sigs, reached = await rpc.oldest_signatures(ctx.mint, max_pages=3)
    except Exception:
        return None
    if not reached or not sigs:
        return None
    first = sigs[-1]
    try:
        tx = await rpc.transaction(first["signature"])
    except Exception:
        return {"block_time": first.get("blockTime"), "programs": [], "fee_payer": None,
                "signature": first["signature"]}
    if not tx:
        return None
    msg = tx["transaction"]["message"]
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in msg.get("accountKeys", [])]
    programs = [ix.get("programId") for ix in msg.get("instructions", [])]
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        programs += [ix.get("programId") for ix in inner.get("instructions", [])]
    return {"block_time": tx.get("blockTime") or first.get("blockTime"), "programs": [p for p in programs if p],
            "fee_payer": keys[0] if keys else None, "signature": first["signature"]}


def classify_mode(result: dict) -> dict:
    """MEMECOIN / PROJET / HYBRIDE à partir d'éléments objectifs. Un site web seul ne suffit pas."""
    proj = result.get("project") or {}
    social = result.get("social") or {}
    lp = (result.get("token") or {}).get("launchpad") or {}
    reasons, points = [], 0
    if proj.get("has_docs"):
        points += 2; reasons.append("documentation / whitepaper trouvée")
    if proj.get("github_active"):
        points += 2; reasons.append("dépôt GitHub actif")
    if proj.get("team_page"):
        points += 1; reasons.append("page équipe présente")
    if proj.get("product_signals"):
        points += 1; reasons.append("fonctionnalités / produit décrits")
    if proj.get("roadmap"):
        points += 1; reasons.append("roadmap présente")
    if not (social.get("links") or {}).get("website"):
        reasons.append("pas de site officiel déclaré")
    if lp.get("id") in ("pumpfun", "letsbonk", "launchlab", "meteora_dbc"):
        reasons.append(f"lancé via {lp.get('label')} (bonding curve typique des memecoins)")
    if points >= 4:
        mode, certainty = "projet", min(0.9, 0.5 + points * 0.08)
    elif points >= 2:
        mode, certainty = "hybride", 0.5
    else:
        mode, certainty = "memecoin", 0.8 if lp.get("id") != "unknown" else 0.6
    status = ESTIMATED if certainty < 0.75 else OBSERVED
    return {"value": mode, "certainty": round(certainty, 2), "reasons": reasons, "status": status}
