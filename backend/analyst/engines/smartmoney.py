"""Smart money : wallets publics suivis, performance historique (PnL, win rate) et présence sur un token.

Prudence : un wallet actif n'est pas forcément rentable ; < 20 positions clôturées = non fiable.
Calcul basé sur les transactions enrichies Helius (clé gratuite).
"""
from __future__ import annotations

import asyncio
import json
import time

from ..providers.solana import WSOL_MINT
from ..util import ESTIMATED, is_valid_mint_format

MIN_RELIABLE_TRADES = 20


def compute_wallet_stats(wallet: str, txs: list[dict], prices: dict[str, float] | None = None,
                         sol_usd: float | None = None) -> dict:
    """txs : format Helius enhanced transactions. Positions agrégées par mint (coût moyen)."""
    pos: dict[str, dict] = {}
    fees = 0.0
    for tx in sorted(txs, key=lambda t: t.get("timestamp") or 0):
        if tx.get("transactionError"):
            continue
        sol_change = 0.0
        tok_changes: dict[str, float] = {}
        for ad in tx.get("accountData") or []:
            if ad.get("account") == wallet:
                sol_change += (ad.get("nativeBalanceChange") or 0) / 1e9
            for tb in ad.get("tokenBalanceChanges") or []:
                if tb.get("userAccount") == wallet and tb.get("mint") != WSOL_MINT:
                    raw = tb.get("rawTokenAmount") or {}
                    amt = int(raw.get("tokenAmount") or 0) / 10 ** int(raw.get("decimals") or 0)
                    tok_changes[tb["mint"]] = tok_changes.get(tb["mint"], 0) + amt
            for tb in ad.get("tokenBalanceChanges") or []:  # WSOL wrappé compte comme SOL
                if tb.get("userAccount") == wallet and tb.get("mint") == WSOL_MINT:
                    raw = tb.get("rawTokenAmount") or {}
                    sol_change += int(raw.get("tokenAmount") or 0) / 1e9
        if tx.get("feePayer") == wallet:
            fees += (tx.get("fee") or 0) / 1e9
        if len(tok_changes) != 1 or abs(sol_change) < 1e-6:
            continue  # pas un swap simple token ↔ SOL
        mint, qty = next(iter(tok_changes.items()))
        p = pos.setdefault(mint, {"bought": 0.0, "sold": 0.0, "sol_in": 0.0, "sol_out": 0.0,
                                  "first": tx.get("timestamp"), "last": tx.get("timestamp")})
        p["last"] = tx.get("timestamp")
        if qty > 0 and sol_change < 0:
            p["bought"] += qty; p["sol_in"] += -sol_change
        elif qty < 0 and sol_change > 0:
            p["sold"] += -qty; p["sol_out"] += sol_change
    closed, open_ = [], []
    for mint, p in pos.items():
        if p["bought"] <= 0:
            continue
        frac = min(1.0, p["sold"] / p["bought"])
        cost_sold = p["sol_in"] * frac
        realized = p["sol_out"] - cost_sold
        rec = {"mint": mint, "realized_sol": realized, "roi": realized / cost_sold if cost_sold else None,
               "sold_fraction": frac, "first": p["first"], "last": p["last"], "sol_in": p["sol_in"]}
        if frac >= 0.9:
            closed.append(rec)
        else:
            rem = p["bought"] - p["sold"]
            if prices and sol_usd and prices.get(mint):
                rec["unrealized_sol"] = rem * prices[mint] / sol_usd - (p["sol_in"] - cost_sold)
            open_.append(rec)
    wins = [c for c in closed if c["realized_sol"] > 0]
    now = time.time()

    def period(days):
        sub = [c for c in closed if (c["last"] or 0) > now - days * 86400]
        return {"trades": len(sub), "pnl_sol": round(sum(c["realized_sol"] for c in sub), 3),
                "win_rate": round(len([c for c in sub if c["realized_sol"] > 0]) / len(sub), 2) if sub else None}
    rois = sorted(c["roi"] for c in closed if c["roi"] is not None)
    unreal = [o["unrealized_sol"] for o in open_ if "unrealized_sol" in o]
    return {
        "closed_positions": len(closed), "open_positions": len(open_),
        "win_rate": round(len(wins) / len(closed), 2) if closed else None,
        "realized_pnl_sol": round(sum(c["realized_sol"] for c in closed), 3),
        "unrealized_pnl_sol": round(sum(unreal), 3) if unreal else None,
        "median_roi": round(rois[len(rois) // 2], 3) if rois else None,
        "fees_sol": round(fees, 4), "periods": {"7j": period(7), "30j": period(30)},
        "transactions_analysed": len(txs),
        "reliable": len(closed) >= MIN_RELIABLE_TRADES,
        "performant": len(closed) >= MIN_RELIABLE_TRADES and (len(wins) / len(closed)) >= 0.5
                      and sum(c["realized_sol"] for c in closed) > 0,
        "method": "PnL réalisé = SOL reçus − coût moyen des tokens vendus (frais réseau inclus via variation de solde). "
                  "Slippage inclus implicitement. Positions < 90 % vendues = ouvertes.",
        "status": ESTIMATED, "computed_at": now,
    }


async def evaluate_wallet(svc, address: str, max_tx: int = 500) -> dict:
    txs, before = [], None
    while len(txs) < max_tx:
        page = await svc.rpc.helius_transactions(address, 100, before)
        if not page:
            break
        txs += page
        before = page[-1].get("signature")
        if len(page) < 100:
            break
    stats = compute_wallet_stats(address, txs)
    svc.db.execute("UPDATE wallets SET stats=?, stats_updated=? WHERE address=?", (json.dumps(stats), time.time(), address))
    return stats


async def run_smart_money(ctx) -> None:
    svc = ctx.svc
    SM = ctx.section("smart_money")
    wallets = svc.db.all("SELECT address, label, stats FROM wallets WHERE tracked=1")
    if not wallets:
        SM["score"] = {"score": None, "available": False, "confidence": 0,
                       "reasons": ["aucun wallet suivi : ajoute des wallets dans l'onglet Smart Money"]}
        return
    supply_raw = ctx.result.get("token", {}).get("supply_raw") or 0
    sem = asyncio.Semaphore(5)

    async def check(w):
        async with sem:
            try:
                return w, await svc.rpc.token_balance_of(w["address"], ctx.mint)
            except Exception:
                return w, None
    res = await asyncio.gather(*[check(w) for w in wallets])
    holders = []
    for w, bal in res:
        if bal:
            st = json.loads(w["stats"]) if w["stats"] else None
            holders.append({"address": w["address"], "label": w["label"],
                            "supply_pct": round(100 * bal / supply_raw, 3) if supply_raw else None,
                            "performant": bool(st and st.get("performant")), "reliable": bool(st and st.get("reliable")),
                            "win_rate": (st or {}).get("win_rate"), "closed_positions": (st or {}).get("closed_positions")})
            svc.db.execute("INSERT INTO smart_money_events(mint, wallet, kind, data, ts) VALUES(?,?,?,?,?)",
                           (ctx.mint, w["address"], "holding", json.dumps({"raw": bal}), time.time()))
    SM["tracked_count"] = len(wallets)
    SM["holders"] = holders
    perf = [h for h in holders if h["performant"]]
    SM["note"] = "Présence détectée = le wallet détient le token maintenant (lecture on-chain)."
    if not holders:
        SM["score"] = {"score": None, "available": False, "confidence": 0.3,
                       "reasons": [f"aucun des {len(wallets)} wallets suivis ne détient ce token"]}
        return
    score = {0: 5.5, 1: 7.0, 2: 8.3}.get(len(perf), 9.0)
    reasons = [f"{len(holders)} wallet(s) suivi(s) détiennent le token, dont {len(perf)} historiquement performant(s)"]
    if len(perf) >= 2:
        ctx.result.setdefault("alerts", []).append({"kind": "smart_money", "message": reasons[0]})
    SM["score"] = {"score": score, "available": True, "confidence": 0.6 if perf else 0.4, "reasons": reasons,
                   "status": ESTIMATED}


def validate_wallet(address: str) -> bool:
    return is_valid_mint_format(address)
