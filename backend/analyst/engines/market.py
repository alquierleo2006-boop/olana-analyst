"""Marché, momentum, volumes et liquidité. Market cap, FDV et liquidité ne sont jamais confondues."""
from __future__ import annotations

import asyncio
import math
import statistics
import time

from ..providers.solana import WSOL_MINT
from ..util import ESTIMATED, OBSERVED, dp, fnum


def _sum(pairs: list[dict], *path) -> float | None:
    vals = []
    for p in pairs:
        cur = p
        for k in path:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        if cur is not None:
            vals.append(float(cur))
    return sum(vals) if vals else None


async def run_market(ctx) -> None:
    svc, mint = ctx.svc, ctx.mint
    m = ctx.section("market")
    tok = ctx.section("token")
    dex_r, gecko_r, sol_r = await asyncio.gather(svc.dex.pairs([mint]), svc.gecko.pools(mint),
                                                 svc.jup.prices([WSOL_MINT]), return_exceptions=True)
    pairs = [p for p in (dex_r if isinstance(dex_r, list) else [])
             if (p.get("baseToken") or {}).get("address") == mint]
    pools = gecko_r if isinstance(gecko_r, list) else []
    sol_usd = sol_r.get(WSOL_MINT) if isinstance(sol_r, dict) else None
    m["sol_usd"] = dp(sol_usd, "Jupiter Price API") if sol_usd else None
    errors = [f"{n}: {r}" for n, r in (("DexScreener", dex_r), ("GeckoTerminal", gecko_r)) if isinstance(r, Exception)]
    if errors:
        m["source_errors"] = errors

    supply = (tok.get("supply") or {}).get("v")
    main = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0) if pairs else None
    if main:
        src = "DexScreener"
        bt = main.get("baseToken") or {}
        tok.setdefault("name", bt.get("name"))
        tok.setdefault("symbol", bt.get("symbol"))
        info = main.get("info") or {}
        if info.get("imageUrl"):
            tok.setdefault("image", info["imageUrl"])
        ctx.provide("dex_info", info)
        m["main_pair"] = {"address": main.get("pairAddress"), "dex": main.get("dexId"), "url": main.get("url"),
                          "quote": (main.get("quoteToken") or {}).get("symbol"), "labels": main.get("labels")}
        m["pairs_count"] = len(pairs)
        m["pair_addresses"] = [p.get("pairAddress") for p in pairs if p.get("pairAddress")]
        m["price_usd"] = dp(fnum(main.get("priceUsd")), src)
        m["mcap"] = dp(fnum(main.get("marketCap")), src)
        m["fdv"] = dp(fnum(main.get("fdv")), src)
        m["liquidity_usd"] = dp(_sum(pairs, "liquidity", "usd"), f"{src} (somme des {len(pairs)} paires)")
        m["volume"] = {k: dp(_sum(pairs, "volume", k), src) for k in ("m5", "h1", "h6", "h24")}
        m["txns"] = {k: {"buys": int(_sum(pairs, "txns", k, "buys") or 0),
                         "sells": int(_sum(pairs, "txns", k, "sells") or 0)} for k in ("m5", "h1", "h6", "h24")}
        m["price_change"] = {k: fnum((main.get("priceChange") or {}).get(k)) for k in ("m5", "h1", "h6", "h24")}
        created = min((p.get("pairCreatedAt") for p in pairs if p.get("pairCreatedAt")), default=None)
        m["first_pair_at"] = dp(created / 1000 if created else None, src)
    else:
        ctx.provide("dex_info", {})
        m["pair_addresses"] = []

    if pools:
        top = max(pools, key=lambda p: fnum(p.get("reserve_in_usd")) or 0)
        if main:
            top = next((p for p in pools if p.get("address") == main.get("pairAddress")), top)
        src = "GeckoTerminal"
        vol = top.get("volume_usd") or {}
        tx = top.get("transactions") or {}
        m.setdefault("volume", {})["m15"] = dp(fnum(vol.get("m15")), src)
        m["unique_traders"] = {k: {"buyers": (tx.get(k) or {}).get("buyers"), "sellers": (tx.get(k) or {}).get("sellers")}
                               for k in ("m5", "m15", "h1", "h24") if tx.get(k)}
        m["gecko_pool"] = top.get("address")
        m["gecko_txns"] = {k: tx.get(k) for k in ("m5", "m15", "m30", "h1") if tx.get(k)}
        if not main:
            m["price_usd"] = dp(fnum(top.get("base_token_price_usd")), src)
            m["mcap"] = dp(fnum(top.get("market_cap_usd")), src)
            m["fdv"] = dp(fnum(top.get("fdv_usd")), src)
            m["liquidity_usd"] = dp(fnum(top.get("reserve_in_usd")), src)
            m["volume"].update({k: dp(fnum(vol.get(k)), src) for k in ("m5", "h1", "h6", "h24")})
            m["main_pair"] = {"address": top.get("address"), "dex": top.get("dex")}
            m["pair_addresses"] = [p.get("address") for p in pools if p.get("address")]

    # Token encore sur bonding curve (pas de pool DEX) : prix lu on-chain.
    curve = await get_curve(ctx)
    if curve and not curve.get("complete"):
        m["bonding_curve"] = {"progress_pct": curve.get("progress_pct"),
                              "real_sol_reserves": curve["real_sol_reserves"] / 1e9, "address": curve.get("address")}
        if sol_usd and curve.get("price_sol") and (not main or not (m.get("price_usd") or {}).get("v")):
            price = curve["price_sol"] * sol_usd
            src = "Bonding curve Pump.fun (on-chain) × prix SOL Jupiter"
            m["price_usd"] = dp(price, src, ESTIMATED)
            m["fdv"] = dp(price * curve["token_total_supply"] / 1e6, src, ESTIMATED)
            m["mcap"] = dp(price * (supply or curve["token_total_supply"] / 1e6), src, ESTIMATED)
            m["liquidity_usd"] = dp(curve["real_sol_reserves"] / 1e9 * sol_usd,
                                    "Réserves SOL de la bonding curve (on-chain)", ESTIMATED)
        m.setdefault("pair_addresses", []).append(curve.get("address"))
        try:
            sigs = await svc.rpc.signatures(curve["address"], 300)
            now = time.time()
            recent = [x for x in sigs if x.get("blockTime") and now - x["blockTime"] <= 300]
            recent20 = [x for x in sigs if x.get("blockTime") and now - x["blockTime"] <= 1200]
            act = {"tx_per_min_5m": len(recent) / 5, "tx_per_min_20m": len(recent20) / 20,
                   "tx_20m_is_minimum": len(sigs) >= 300 and len(recent20) == len(sigs),
                   "source": "RPC Solana (transactions de la bonding curve)"}
            created = ((ctx.result.get("token") or {}).get("created_at") or {}).get("v")
            if created and curve.get("progress_pct") is not None and now - created > 30:
                act["progress_per_min"] = curve["progress_pct"] / ((now - created) / 60)
            m["curve_activity"] = act
        except Exception:
            pass

    if not (m.get("price_usd") or {}).get("v"):
        m["unavailable"] = "Aucune donnée de marché : token sans pool connu ni bonding curve lisible."
        ctx.risk("élevé", "NO_MARKET", "Aucun marché identifié pour ce token", "Marché")
    ctx.provide("market", m)

    m["organic"] = assess_organic(m)
    if m.get("mcap") and (m["mcap"].get("v") or 0) > 0:
        svc.db.execute("INSERT INTO market_snapshots(mint, ts, source, price_usd, mcap, fdv, liquidity, volume_24h)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (ctx.mint, time.time(), m["mcap"]["src"], (m.get("price_usd") or {}).get("v"),
                        m["mcap"].get("v"), (m.get("fdv") or {}).get("v"), (m.get("liquidity_usd") or {}).get("v"),
                        ((m.get("volume") or {}).get("h24") or {}).get("v")))


CURVE_LAUNCHPADS = ("pumpfun", "letsbonk", "launchlab", "meteora_dbc")
AMM_DEXES = ("pumpswap", "raydium", "orca", "meteora", "fluxbeam")
PRESUMED_CURVE_MAX_MCAP = 60_000


async def get_curve(ctx) -> dict | None:
    """Bonding curve Pump.fun : valeur du module launchpad, sinon UNE relecture partagée entre les modules."""
    curve = await ctx.need("pump_curve", timeout=4)
    if curve:
        return curve
    task = getattr(ctx, "_curve_task", None)
    if task is None:
        task = asyncio.ensure_future(_read_curve(ctx))
        ctx._curve_task = task
    return await asyncio.shield(task)


async def _read_curve(ctx) -> dict | None:
    from ..providers.solana import PUMPFUN_PROGRAM, decode_pump_curve, find_pda, pubkey_bytes
    pda = find_pda([b"bonding-curve", pubkey_bytes(ctx.mint)], PUMPFUN_PROGRAM)
    for attempt in range(2):
        try:
            raw = await ctx.svc.rpc.account_bytes(pda)
            if raw and raw[1] == PUMPFUN_PROGRAM:
                c = decode_pump_curve(raw[0])
                if c:
                    c["address"] = pda
                return c
            return None  # pas de curve Pump.fun pour ce token
        except Exception:
            await asyncio.sleep(0.4 * (attempt + 1))
    return None


def presumed_curve(ctx, m: dict) -> bool:
    """Token de launchpad très probablement pas encore migré, même si la curve n'a pas pu être lue."""
    lp = ((ctx.result.get("token") or {}).get("launchpad") or {}).get("id")
    hinted = lp in CURVE_LAUNCHPADS or ctx.mint.lower().endswith(("pump", "bonk"))
    mcap = (m.get("mcap") or {}).get("v")
    dex = ((m.get("main_pair") or {}).get("dex") or "").lower()
    on_amm = any(dex.startswith(d) for d in AMM_DEXES) and "launch" not in dex and "dbc" not in dex
    return hinted and (mcap is None or mcap < PRESUMED_CURVE_MAX_MCAP) and not on_amm


async def run_momentum(ctx) -> None:
    """Bougies 1 min (GeckoTerminal, limité à 1 requête / 2 s) : hors du chemin critique de la 1re fiche."""
    m = await ctx.need("market", timeout=10)
    if not m:
        return
    pool = (m.get("main_pair") or {}).get("address") or m.get("gecko_pool")
    if not pool:
        m["momentum"] = {"unavailable": "aucun pool connu"}
        return
    supply = ((ctx.result.get("token") or {}).get("supply") or {}).get("v")
    try:
        candles = await ctx.svc.gecko.ohlcv(pool, "minute", 1, 120)
        m["momentum"] = analyse_candles(candles, supply)
        if candles:
            m.setdefault("volume", {})["m1"] = dp(candles[-1][5], "GeckoTerminal (dernière bougie 1 min)")
    except Exception as exc:
        m["momentum"] = {"unavailable": f"Bougies indisponibles : {exc}"}
    m["organic"] = assess_organic(m)


def analyse_candles(c: list[list], supply: float | None) -> dict:
    """c = [[ts, o, h, l, close, volume], …] trié par temps."""
    if len(c) < 3:
        return {"unavailable": "historique trop court"}
    closes = [x[4] for x in c if x[4]]
    vols = [x[5] or 0 for x in c]
    last = closes[-1]
    out: dict = {"source": "GeckoTerminal OHLCV 1 min", "candles": len(c),
                 "window_minutes": int((c[-1][0] - c[0][0]) / 60) + 1}

    def change(minutes: int):
        cutoff = c[-1][0] - minutes * 60
        ref = next((x[1] for x in c if x[0] >= cutoff), None)
        return 100 * (last / ref - 1) if ref else None

    out["change"] = {"5m": change(5), "15m": change(15), "20m": change(20), "60m": change(60)}
    if len(vols) >= 40:
        v20, prev20 = sum(vols[-20:]), sum(vols[-40:-20])
        out["volume_20m"] = v20
        out["volume_20m_trend"] = (v20 / prev20) if prev20 else None
    hi = max(x[2] for x in c)
    out["high_window"] = hi
    out["drawdown_from_high_pct"] = 100 * (last / hi - 1) if hi else None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]
    out["volatility_1m_pct"] = 100 * statistics.pstdev(rets[-60:]) if len(rets) > 5 else None
    v5 = sum(vols[-5:])
    avg5 = sum(vols[-65:-5]) / 12 if len(vols) >= 20 else None
    out["volume_acceleration"] = (v5 / avg5) if avg5 else None
    last30 = closes[-30:]
    rng = (max(last30) / min(last30) - 1) * 100 if min(last30) > 0 else None
    out["consolidating"] = rng is not None and rng < 15 and len(last30) >= 20
    out["range_30m_pct"] = rng
    tot = sum(vols)
    out["top3_candles_volume_share"] = (sum(sorted(vols)[-3:]) / tot) if tot else None
    if supply:
        out["mcap_high_window"] = hi * supply
        out["mcap_open_window"] = c[0][1] * supply
    return out


def assess_organic(m: dict) -> dict:
    """Signaux d'activité artificielle. Ce sont des indices, pas des preuves."""
    flags, notes = [], []
    tx = (m.get("txns") or {}).get("h1") or {}
    vol_h1 = ((m.get("volume") or {}).get("h1") or {}).get("v")
    n = (tx.get("buys") or 0) + (tx.get("sells") or 0)
    if n and vol_h1:
        avg = vol_h1 / n
        notes.append(f"taille moyenne d'une transaction (1 h) : ${avg:,.0f}")
    ut = (m.get("unique_traders") or {}).get("h1") or {}
    uniq = (ut.get("buyers") or 0) + (ut.get("sellers") or 0)
    if n and uniq:
        ratio = n / uniq
        notes.append(f"{ratio:.1f} transactions par trader unique (1 h)")
        if ratio > 6:
            flags.append("beaucoup de transactions pour peu de traders uniques (bots / volume répétitif possible)")
    mom = m.get("momentum") or {}
    share = mom.get("top3_candles_volume_share")
    if share and share > 0.6 and (mom.get("candles") or 0) > 60:
        flags.append(f"{share * 100:.0f}% du volume concentré sur 3 minutes (pics isolés)")
    if tx.get("buys") and tx.get("sells") == 0 and tx["buys"] > 30:
        flags.append("aucune vente sur 1 h malgré de nombreux achats (vente peut-être impossible)")
    level = "suspect" if len(flags) >= 2 else "à surveiller" if flags else ("plutôt organique" if notes else "inconnu")
    return {"level": level, "flags": flags, "notes": notes, "status": ESTIMATED}


async def run_liquidity(ctx) -> None:
    """Impact réel d'entrée / sortie mesuré par devis Jupiter (aucune transaction exécutée)."""
    svc = ctx.svc
    L = ctx.section("liquidity")
    m = await ctx.need("market", timeout=12) or {}
    tok = ctx.result.get("token", {})
    sol_usd = (m.get("sol_usd") or {}).get("v")
    price = (m.get("price_usd") or {}).get("v")
    liq = (m.get("liquidity_usd") or {}).get("v")
    mcap = (m.get("mcap") or {}).get("v")
    L["total_usd"] = m.get("liquidity_usd")
    if liq and mcap:
        L["liq_to_mcap_pct"] = 100 * liq / mcap
    tests = []
    pos = float((svc.settings.get("scalp") or {}).get("position_sol", 0.5) or 0.5)
    sizes = sorted({round(pos, 3), 2.0, 10.0})
    L["position_sol"] = pos
    curve = await get_curve(ctx)
    if curve and not curve.get("complete") and curve.get("virtual_sol_reserves"):
        ctx.result.setdefault("token", {})["on_bonding_curve"] = True
        # Bonding curve : liquidité détenue par le programme (non retirable), impact calculé exactement.
        L["mode"] = "bonding_curve"
        L["impact_tests"] = [curve_impact(curve, s_) for s_ in sizes]
        L["impact_source"] = "Calcul exact sur la bonding curve (produit constant, hors frais de plateforme)"
        if sol_usd:
            L["curve_depth_usd"] = curve["virtual_sol_reserves"] / 1e9 * sol_usd
        L["note"] = ("Token encore sur bonding curve : la liquidité ne peut pas être retirée par le créateur et la "
                     "revente est toujours possible. Le risque se mesure par l'impact de prix pour ta taille de position.")
        L["risk_level"] = curve_liquidity_risk(L["impact_tests"], pos)
        _liquidity_risk_events(ctx, L["risk_level"])
        return
    presumed = presumed_curve(ctx, m)
    L["mode"] = "bonding_curve_presumed" if presumed else "dex"
    if presumed:
        ctx.result.setdefault("token", {})["on_bonding_curve"] = True
        L["note"] = ("Token de launchpad pas encore migré (curve non lue directement) : la liquidité en dollars n'est pas "
                     "un critère pertinent ; seul l'impact de prix pour ta taille de position est utilisé.")
    if sol_usd and price:
        dec = tok.get("decimals", 6)
        async def q_buy(s):
            return await svc.jup.quote(WSOL_MINT, ctx.mint, int(s * 1e9))
        async def q_sell(s):
            raw = int(s * sol_usd / price * 10 ** dec)
            return await svc.jup.quote(ctx.mint, WSOL_MINT, raw) if raw > 0 else None
        res = await asyncio.gather(*[q_buy(s) for s in sizes], *[q_sell(s) for s in sizes], return_exceptions=True)
        for i, s in enumerate(sizes):
            b, sl = res[i], res[i + len(sizes)]
            tests.append({"size_sol": s,
                          "buy_impact_pct": _impact(b), "sell_impact_pct": _impact(sl),
                          "buy_route": _route(b), "sell_route": _route(sl),
                          "buy_error": str(b) if isinstance(b, Exception) else None,
                          "sell_error": str(sl) if isinstance(sl, Exception) else None})
        L["impact_tests"] = tests
        L["impact_source"] = "Devis Jupiter (simulation, aucune transaction)"
        sell_ok = [t for t in tests if t["sell_impact_pct"] is not None]
        if tests and not sell_ok and not any(t["sell_error"] for t in tests):
            ctx.risk("critique", "NO_SELL_ROUTE", "Aucune route de vente trouvée par Jupiter : sortie potentiellement impossible",
                     "Liquidité")
    rc = await ctx.need("rugcheck", timeout=6)
    if isinstance(rc, dict):
        locks = []
        for mk in rc.get("markets") or []:
            lp = mk.get("lp") or {}
            if lp.get("lpLockedPct") is not None:
                locks.append({"market": mk.get("marketType"), "pubkey": mk.get("pubkey"),
                              "locked_pct": fnum(lp.get("lpLockedPct")), "locked_usd": fnum(lp.get("lpLockedUSD"))})
        if locks:
            L["lp_locks"] = locks
            L["lp_locks_source"] = "RugCheck"
    if presumed:
        tests_ok = [t for t in L.get("impact_tests") or [] if t.get("buy_impact_pct") is not None]
        L["risk_level"] = curve_liquidity_risk(tests_ok, pos) if tests_ok else \
            {"level": "inconnu", "score": None, "reasons": ["impact non mesuré"], "status": ESTIMATED}
        if L["risk_level"].get("score") is not None:
            _liquidity_risk_events(ctx, L["risk_level"])
        return
    L["risk_level"] = liquidity_risk(L, m, pos)
    _liquidity_risk_events(ctx, L["risk_level"])


def _liquidity_risk_events(ctx, lvl: dict) -> None:
    if lvl["score"] == 3:
        ctx.risk("critique", "LIQUIDITY", "Liquidité critique : sortie difficile ou très coûteuse (" +
                 "; ".join(lvl["reasons"]) + ")", "Liquidité")
    elif lvl["score"] == 2:
        ctx.risk("élevé", "LIQUIDITY", "Liquidité faible : " + "; ".join(lvl["reasons"]), "Liquidité")


def curve_impact(curve: dict, size_sol: float) -> dict:
    """Impact de prix exact d'un achat / d'une vente de `size_sol` SOL sur une bonding curve à produit constant."""
    vsol, vtok = curve["virtual_sol_reserves"] / 1e9, curve["virtual_token_reserves"] / 1e6
    k, p0 = vsol * vtok, vsol / vtok
    out = vtok - k / (vsol + size_sol)
    buy = 100 * ((size_sol / out) / p0 - 1) if out > 0 else None
    t = size_sol / p0
    sol_out = vsol - k / (vtok + t)
    sell = 100 * (1 - (sol_out / t) / p0) if t > 0 else None
    exceeds = out > curve.get("real_token_reserves", 0) / 1e6 if curve.get("real_token_reserves") else False
    return {"size_sol": size_sol, "buy_impact_pct": buy, "sell_impact_pct": sell,
            "buy_route": "bonding curve", "sell_route": "bonding curve", "buy_error": None, "sell_error": None,
            "note": "achat > tokens restants : déclenche la migration" if exceeds else None}


def curve_liquidity_risk(tests: list[dict], pos: float) -> dict:
    t = min(tests, key=lambda x: abs(x["size_sol"] - pos))
    imp = max(t.get("buy_impact_pct") or 0, t.get("sell_impact_pct") or 0)
    level = 0 if imp < 3 else 1 if imp < 8 else 2 if imp < 15 else 3
    reasons = [f"impact pour {pos:g} SOL : {imp:.1f}%", "liquidité non retirable (bonding curve)"]
    return {"level": ["faible", "modéré", "élevé", "critique"][level], "score": level, "reasons": reasons,
            "status": ESTIMATED}


def _impact(q) -> float | None:
    if not isinstance(q, dict) or q.get("priceImpactPct") is None:
        return None
    return abs(float(q["priceImpactPct"])) * 100


def _route(q) -> str | None:
    if not isinstance(q, dict):
        return None
    return " → ".join((r.get("swapInfo") or {}).get("label", "?") for r in q.get("routePlan") or [])


def liquidity_risk(L: dict, m: dict, pos: float = 2.0) -> dict:
    liq = (L.get("total_usd") or {}).get("v")
    reasons = []
    level = 0
    if liq is None:
        reasons.append("liquidité non mesurée")
        if not L.get("impact_tests"):
            return {"level": "inconnu", "score": None, "reasons": reasons, "status": ESTIMATED}
    elif liq < 5_000:
        level = 3; reasons.append("liquidité < 5 000 $")
    elif liq < 20_000:
        level = 2; reasons.append("liquidité < 20 000 $")
    elif liq < 75_000:
        level = 1; reasons.append("liquidité modérée")
    t2 = next((t for t in L.get("impact_tests") or [] if t["size_sol"] == round(pos, 3)), None)
    if t2 and t2.get("sell_impact_pct") is not None:
        imp = t2["sell_impact_pct"]
        reasons.append(f"vente de {pos:g} SOL : impact {imp:.1f}%")
        if imp > 15:
            level = max(level, 3)
        elif imp > 5:
            level = max(level, 2)
    for lk in L.get("lp_locks") or []:
        if lk["locked_pct"] is not None and lk["locked_pct"] < 50 and lk.get("market", "").startswith("raydium"):
            level = max(level, 2); reasons.append(f"LP {lk['market']} verrouillée/brûlée à seulement {lk['locked_pct']:.0f}%")
    if (L.get("liq_to_mcap_pct") or 100) < 3:
        level = max(level, 2); reasons.append("liquidité très faible par rapport à la market cap")
    label = ["faible", "modéré", "élevé", "critique"][level]
    return {"level": label, "score": level, "reasons": reasons, "status": ESTIMATED}
