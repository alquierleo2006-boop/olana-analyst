"""Suivi en direct (mode Scalp) : market cap rafraîchie toutes les quelques secondes après une analyse.

- Token sur bonding curve Pump.fun : lecture directe du compte de la curve (on-chain, ~1 requête / tick).
- Token migré / sur DEX : DexScreener (limite gratuite respectée).
Lecture seule : aucune transaction. Les alertes sont des informations, pas des ordres.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque

from ..providers.solana import PUMPFUN_PROGRAM, WSOL_MINT, decode_pump_curve, find_pda, pubkey_bytes

MAX_WATCHES = 5
RUG_CODES = {"DEV_SOLD", "INSIDER_SELL", "INSIDER_DUMP", "LIQ_DROP"}


class Watch:
    def __init__(self, mint: str, info: dict, cfg: dict) -> None:
        self.mint = mint
        self.info = info  # name, symbol, supply, decimals, creator, curve_address, pair_address
        self.cfg = cfg
        self.started = time.time()
        self.points: deque = deque(maxlen=1200)  # (ts, mcap, liquidity, real_sol)
        self.alerts: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.targets = {"above": cfg.get("target_above"), "below": cfg.get("target_below")}
        self.fired: set[str] = set()
        self.high = None
        self.dev_initial = None
        self.insider_initial: dict[str, float] = {}
        self.state: dict = {}
        self.task: asyncio.Task | None = None
        self.stopped = False

    def publish(self, kind: str, data: dict) -> None:
        for q in list(self.subscribers):
            if not q.full():
                q.put_nowait({"type": kind, "data": data})

    def change(self, seconds: int) -> float | None:
        if len(self.points) < 2:
            return None
        now_ts, now_mc = self.points[-1][0], self.points[-1][1]
        ref = next((p for p in self.points if p[0] >= now_ts - seconds), None)
        if not ref or not ref[1] or ref[0] > now_ts - seconds * 0.6:
            return None
        return 100 * (now_mc / ref[1] - 1)

    def sol_flow(self, seconds: int) -> float | None:
        """Flux net de SOL dans la bonding curve (achats − ventes) sur la période."""
        pts = [p for p in self.points if p[3] is not None]
        if len(pts) < 2:
            return None
        ref = next((p for p in pts if p[0] >= pts[-1][0] - seconds), pts[0])
        return pts[-1][3] - ref[3]


def evaluate_alerts(w: Watch, mcap: float, liq: float | None) -> list[dict]:
    """Règles d'alerte de scalp. Retourne les nouvelles alertes (chaque règle ne sonne qu'une fois par niveau)."""
    out = []
    cfg = w.cfg

    def fire(key, level, msg):
        if key not in w.fired:
            w.fired.add(key)
            out.append({"ts": time.time(), "level": level, "code": key.split(":")[0], "message": msg})

    if w.high is None or mcap > w.high:
        w.high = mcap
        w.fired.discard("REVERSAL")
    rev = cfg.get("reversal_pct", 15)
    if w.high and len(w.points) > 3 and mcap <= w.high * (1 - rev / 100):
        start = w.points[0][1] if w.points else mcap
        if w.high > start * 1.05:  # retournement après une vraie montée
            fire("REVERSAL", "élevé", f"Retournement : −{100 * (1 - mcap / w.high):.0f}% depuis le plus haut "
                                      f"(${w.high:,.0f} → ${mcap:,.0f})")
    t = w.targets.get("above")
    if t and mcap >= t:
        fire(f"TARGET_UP:{t}", "info", f"Objectif atteint : market cap ≥ ${t:,.0f} (${mcap:,.0f})")
    s = w.targets.get("below")
    if s and mcap <= s:
        fire(f"STOP:{s}", "élevé", f"Niveau stop touché : market cap ≤ ${s:,.0f} (${mcap:,.0f})")
    ch1 = w.change(60)
    pump = cfg.get("pump_alert_pct", 25)
    if ch1 is not None and ch1 >= pump:
        fire(f"PUMP:{int(time.time() // 120)}", "info", f"Accélération : +{ch1:.0f}% en 1 minute")
    if liq is not None and len(w.points) > 3:
        liq0 = next((p[2] for p in w.points if p[2]), None)
        if liq0 and liq < liq0 * 0.7:
            if w.state.get("source") == "bonding curve (on-chain)":
                fire("SELL_PRESSURE", "élevé", f"Forte pression vendeuse : SOL de la curve ${liq0:,.0f} → ${liq:,.0f}")
            else:
                fire("LIQ_DROP", "critique", f"Liquidité en chute : ${liq0:,.0f} → ${liq:,.0f}")
    prog = w.state.get("curve_progress")
    if prog is not None and prog >= 90:
        fire("MIGRATION", "info", f"Bonding curve à {prog:.0f}% : migration imminente (forte volatilité possible)")
    return out


class LiveWatcher:
    def __init__(self, svc, notifier) -> None:
        self.svc, self.notifier = svc, notifier
        self.watches: dict[str, Watch] = {}
        self._sol = (0.0, None)

    async def sol_usd(self) -> float | None:
        ts, v = self._sol
        if v and time.time() - ts < 60:
            return v
        try:
            v = (await self.svc.jup.prices([WSOL_MINT])).get(WSOL_MINT)
            self._sol = (time.time(), v)
        except Exception:
            pass
        return v or self._sol[1]

    def list(self) -> list[dict]:
        return [self.snapshot(w) for w in self.watches.values()]

    def snapshot(self, w: Watch) -> dict:
        last = w.points[-1] if w.points else None
        return {"mint": w.mint, "name": w.info.get("name"), "symbol": w.info.get("symbol"),
                "started": w.started, "mcap": last[1] if last else None, "liquidity": last[2] if last else None,
                "high": w.high, "drawdown_pct": (100 * (last[1] / w.high - 1)) if last and w.high else None,
                "change": {"30s": w.change(30), "1m": w.change(60), "5m": w.change(300)},
                "change_since_start": (100 * (last[1] / w.points[0][1] - 1)) if last and w.points[0][1] else None,
                "sol_flow": {"1m": w.sol_flow(60), "5m": w.sol_flow(300)},
                "targets": w.targets, "alerts": w.alerts[-20:], "state": w.state,
                "points": [(p[0], p[1]) for p in list(w.points)[-300:]], "interval_s": w.cfg.get("interval_s"),
                "stopped": w.stopped}

    def start(self, mint: str, info: dict, overrides: dict | None = None) -> Watch:
        if mint in self.watches and not self.watches[mint].stopped:
            w = self.watches[mint]
            if overrides:
                w.targets.update({k: v for k, v in overrides.items() if k in ("above", "below")})
            return w
        active = [m for m, w in self.watches.items() if not w.stopped]
        if len(active) >= MAX_WATCHES:
            oldest = min(active, key=lambda m: self.watches[m].started)
            self.stop(oldest)
        cfg = dict(self.svc.settings.get("scalp", {}))
        if overrides and (overrides.get("above") or overrides.get("below")):
            cfg.update({"target_above": overrides.get("above"), "target_below": overrides.get("below")})
        else:
            cfg["auto_targets"] = True
        w = Watch(mint, info, cfg)
        self.watches[mint] = w
        w.task = asyncio.create_task(self._loop(w))
        return w

    def stop(self, mint: str) -> None:
        w = self.watches.get(mint)
        if w:
            w.stopped = True
            if w.task:
                w.task.cancel()
            w.publish("stopped", {"mint": mint})

    async def tick(self, w: Watch, n: int) -> None:
        svc = self.svc
        mcap = liq = real_sol = None
        source = None
        curve_addr = w.info.get("curve_address")
        if curve_addr and not w.state.get("migrated"):
            raw = await svc.rpc.account_bytes(curve_addr)
            curve = decode_pump_curve(raw[0]) if raw and raw[1] == PUMPFUN_PROGRAM else None
            sol = await self.sol_usd()
            if curve and not curve["complete"] and sol:
                price = curve["price_sol"] * sol
                mcap = price * (w.info.get("supply") or curve["token_total_supply"] / 1e6)
                real_sol = curve["real_sol_reserves"] / 1e9
                liq = real_sol * sol
                w.state["curve_progress"] = curve["progress_pct"]
                source = "bonding curve (on-chain)"
            elif curve and curve["complete"]:
                w.state["migrated"] = True
        if mcap is None and (n % max(1, round(5 / w.cfg.get("interval_s", 3))) == 0 or not w.points):
            pairs = await svc.dex.pairs([w.mint])
            pairs = [p for p in pairs if (p.get("baseToken") or {}).get("address") == w.mint]
            if pairs:
                main = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
                mcap = main.get("marketCap") or main.get("fdv")
                liq = sum((p.get("liquidity") or {}).get("usd") or 0 for p in pairs)
                tx = (main.get("txns") or {}).get("m5") or {}
                w.state["txns_5m"] = {"buys": tx.get("buys"), "sells": tx.get("sells")}
                w.state["volume_5m"] = (main.get("volume") or {}).get("m5")
                source = "DexScreener"
        if mcap is None:
            return
        if not w.points and w.cfg.get("auto_targets"):
            # Objectif / stop calculés sur la 1re valeur live (même source que les relevés suivants).
            sc = w.cfg
            tp = sc.get("take_profit_pct")
            mult = 1 + float(tp) / 100 if tp is not None else float(sc.get("target_multiple", 1.4))
            w.targets = {"above": round(float(mcap) * mult),
                         "below": round(float(mcap) * (1 - float(sc.get("stop_pct", 30)) / 100))}
        w.points.append((time.time(), float(mcap), liq, real_sol))
        w.state["source"] = source
        # Le développeur vend-il ? (toutes les ~15 s)
        creator = w.info.get("creator")
        if creator and n % max(1, round(15 / w.cfg.get("interval_s", 3))) == 0:
            try:
                bal = await svc.rpc.token_balance_of(creator, w.mint)
                if w.dev_initial is None:
                    w.dev_initial = bal
                elif bal < w.dev_initial * 0.5 and w.dev_initial > 0:
                    w.state["dev_sold"] = True
                    new = [{"ts": time.time(), "level": "critique", "code": "DEV_SOLD",
                            "message": "Le développeur a vendu plus de la moitié de ses tokens"}]
                    if "DEV_SOLD" not in w.fired:
                        w.fired.add("DEV_SOLD")
                        self._emit(w, new)
                w.state["dev_balance_raw"] = bal
            except Exception:
                pass
        if w.info.get("watched_accounts") and n % max(1, round(6 / w.cfg.get("interval_s", 3))) == 0:
            try:
                await self.check_insiders(w)
            except Exception:
                pass
        self._emit(w, evaluate_alerts(w, float(mcap), liq))
        w.publish("tick", self.snapshot(w))

    async def check_insiders(self, w: Watch) -> None:
        """Les gros holders / wallets du bundle vendent-ils pendant le trade ? (1 seule requête RPC)"""
        accts = w.info["watched_accounts"]
        res = await self.svc.rpc.multiple_accounts([a["token_account"] for a in accts])
        supply = w.info.get("supply") or 0
        sold_total = 0.0
        for a, acc in zip(accts, res):
            try:
                amt = float(acc["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"]) if acc else 0.0
            except (TypeError, KeyError, ValueError):
                continue
            key = a["token_account"]
            init = w.insider_initial.setdefault(key, amt)
            sold = max(0.0, init - amt)
            if supply:
                sold_total += 100 * sold / supply
            if init > 0 and amt < init * 0.5 and (a.get("pct") or 0) >= 1.5:
                code = f"INSIDER_SELL:{key}"
                if code not in w.fired:
                    w.fired.add(code)
                    self._emit(w, [{"ts": time.time(), "level": "élevé", "code": "INSIDER_SELL",
                                    "message": f"Un {a['label']} ({a.get('pct', 0):.1f}% du supply, {(a.get('owner') or '')[:6]}…) "
                                               f"a vendu {100 * sold / init:.0f}% de ses tokens"}])
        w.state["insiders"] = {"watched": len(accts), "sold_supply_pct": round(sold_total, 2)}
        if sold_total >= 5 and "INSIDER_DUMP" not in w.fired:
            w.fired.add("INSIDER_DUMP")
            self._emit(w, [{"ts": time.time(), "level": "critique", "code": "INSIDER_DUMP",
                            "message": f"Les gros holders surveillés ont vendu {sold_total:.1f}% du supply depuis ton entrée"}])

    def _emit(self, w: Watch, alerts: list[dict]) -> None:
        if w.cfg.get("rug_only", True):
            # Mode « anti-rug seulement » : pas d'alertes de prix (déjà sur le terminal de l'utilisateur).
            alerts = [a for a in alerts if a["code"] in RUG_CODES]
        for a in alerts:
            w.alerts.append(a)
            name = f"${w.info.get('symbol') or w.mint[:6]}"
            self.notifier.emit("scalp_alert", {"mint": w.mint, **a}, f"{name} — {a['message'][:60]}", a["message"])

    async def _loop(self, w: Watch) -> None:
        interval = max(1.5, float(w.cfg.get("interval_s", 3)))
        max_s = float(w.cfg.get("max_minutes", 60)) * 60
        n = 0
        try:
            while time.time() - w.started < max_s:
                try:
                    await self.tick(w, n)
                    w.state.pop("error", None)
                except Exception as exc:
                    w.state["error"] = str(exc)[:200]
                n += 1
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        w.stopped = True
        w.publish("stopped", {"mint": w.mint})


def watch_info_from_result(r: dict) -> dict:
    tok, m = r.get("token") or {}, r.get("market") or {}
    curve = (m.get("bonding_curve") or {}).get("address") or ((tok.get("launchpad") or {}).get("bonding_curve") or {}).get("address")
    if (tok.get("launchpad") or {}).get("bonding_curve", {}).get("complete"):
        curve = None
    bundle = {w for c in (r.get("clusters") or {}).get("clusters") or [] for w in c.get("wallets", [])}
    watched = []
    for h in (r.get("holders") or {}).get("top") or []:
        if h.get("kind") == "wallet" and h.get("token_account") and len(watched) < 15:
            label = "bundle (financement commun)" if h.get("owner") in bundle else \
                "nouveau wallet 🌱" if h.get("fresh") else (h.get("label") or "gros holder")
            watched.append({"token_account": h["token_account"], "owner": h.get("owner"), "pct": h.get("pct"), "label": label})
    return {"name": tok.get("name"), "symbol": tok.get("symbol"), "supply": (tok.get("supply") or {}).get("v"),
            "creator": (r.get("developer") or {}).get("address"), "curve_address": curve,
            "pair_address": (m.get("main_pair") or {}).get("address"), "watched_accounts": watched or None}


def curve_address(mint: str) -> str:
    return find_pda([b"bonding-curve", pubkey_bytes(mint)], PUMPFUN_PROGRAM)
