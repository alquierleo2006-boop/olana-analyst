"""Orchestrateur : lance tous les modules en parallèle, diffuse les résultats au fil de l'eau,
recalcule le score à chaque nouvelle donnée et enregistre l'analyse complète."""
from __future__ import annotations

import asyncio
import json
import time
import traceback

from .engines import identify as ident
from .engines import market, onchain, originality, scoring, smartmoney, social, tracker
from .config import EDITION
from .engines.context import Ctx, InvalidAddress, TokenNotFound
from .engines.narratives import run_narrative

# Logiciel 100 % scalp : pas de fact-checking ni d'analyse de site (lents, poids nul en scalp).
LEVEL1 = ["launchpad", "market", "security", "holders", "liquidity"]
LEVEL2 = ["developer", "social", "clusters", "narrative", "smart_money", "momentum"]
TIMEOUTS = {1: 15, 2: 30, 3: 35}
FIRST_RESULT_TARGET_S = {"memecoin": 5, "projet": 15, "hybride": 15}
SCALP_FIRST_RESULT_S = 3


class Analysis:
    def __init__(self, aid: int, mint: str) -> None:
        self.id, self.mint = aid, mint
        self.result: dict = {"analysis_id": aid, "mint": mint, "status": "en cours", "provisional": True,
                             "modules": {}, "risks": [], "started_at": time.time()}
        self.subscribers: set[asyncio.Queue] = set()
        self.done = asyncio.Event()

    def publish(self, kind: str, payload) -> None:
        for q in list(self.subscribers):
            if not q.full():
                q.put_nowait({"type": kind, "data": payload})


class Analyzer:
    def __init__(self, svc, narratives, notifier, live=None) -> None:
        self.svc, self.narratives, self.notifier, self.watcher = svc, narratives, notifier, live
        self.live: dict[int, Analysis] = {}

    def start(self, mint: str, site: str | None = None) -> Analysis:
        aid = self.svc.db.execute("INSERT INTO token_analyses(mint, created_at, status) VALUES(?,?,?)",
                                  (mint, time.time(), "en cours"))
        an = Analysis(aid, mint)
        if site:
            an.result["user_site"] = site  # site fourni par l'utilisateur, analysé avec le CA
        self.live[aid] = an
        asyncio.create_task(self._run_safe(an))
        return an

    async def _run_safe(self, an: Analysis) -> None:
        try:
            await self._run(an)
        except Exception as exc:  # garde-fou : une analyse ne reste jamais bloquée « en cours »
            traceback.print_exc()
            if not an.done.is_set():
                self._fail(an, f"Erreur interne pendant l'analyse : {type(exc).__name__}: {exc}", "erreur")

    def _modules(self, ctx: Ctx) -> dict:
        return {
            "launchpad": (1, ident.detect_launchpad), "market": (1, market.run_market),
            "security": (1, onchain.run_security), "holders": (1, onchain.run_holders),
            "liquidity": (1, market.run_liquidity), "developer": (2, onchain.run_developer),
            "social": (2, social.run_social), "clusters": (2, onchain.run_clusters),
            "narrative": (2, lambda c: run_narrative(c, self.narratives)),
            "smart_money": (2, smartmoney.run_smart_money), "momentum": (2, market.run_momentum),
            **({"project": (3, social.run_project), "factcheck": (3, social.run_factcheck),
                "originality": (3, originality.run_originality)} if EDITION == "tech" else {}),
        }

    async def _run(self, an: Analysis) -> None:
        t0 = time.monotonic()
        r = an.result
        ctx = Ctx(an.mint, self.svc, r)
        settings = self.svc.settings.all()
        try:
            await ident.identify(ctx)
        except (InvalidAddress, TokenNotFound) as exc:
            return self._fail(an, str(exc), "introuvable" if isinstance(exc, TokenNotFound) else "invalide")
        except Exception as exc:
            return self._fail(an, f"Identification impossible (fournisseur Solana indisponible ?) : {exc}", "erreur")
        an.publish("section", {"token": r.get("token")})

        mods = self._modules(ctx)
        for name in mods:
            r["modules"][name] = {"status": "en cours", "level": mods[name][0]}
        first_sent = asyncio.Event()

        async def run_mod(name):
            level, fn = mods[name]
            m0 = time.monotonic()
            try:
                await asyncio.wait_for(fn(ctx), TIMEOUTS[level])
                r["modules"][name].update(status="terminé")
            except asyncio.TimeoutError:
                r["modules"][name].update(status="délai dépassé")
            except Exception as exc:
                r["modules"][name].update(status="erreur", error=f"{type(exc).__name__}: {exc}"[:300])
                traceback.print_exc()
            r["modules"][name]["ms"] = int((time.monotonic() - m0) * 1000)
            r["scores"] = scoring.compute(r, settings)
            section = name if name != "launchpad" else "token"
            an.publish("section", {section: r.get(section), "modules": r["modules"], "scores": r["scores"],
                                   "risks": r["risks"]})
            if not first_sent.is_set() and all(r["modules"][m]["status"] != "en cours" for m in LEVEL1):
                self._first_result(an, t0)
                first_sent.set()

        async def deadline():
            await asyncio.sleep(SCALP_FIRST_RESULT_S if EDITION == "scalp" else FIRST_RESULT_TARGET_S["memecoin"])
            if not first_sent.is_set():
                self._first_result(an, t0, partial=True)
                first_sent.set()

        dl = asyncio.create_task(deadline())
        await asyncio.gather(*[run_mod(n) for n in mods])
        dl.cancel()

        if EDITION == "tech":
            r["mode"] = ident.classify_mode(r)
            target = FIRST_RESULT_TARGET_S["projet"]
        else:
            r["mode"] = {"value": "memecoin", "certainty": 1.0, "reasons": ["logiciel dédié au scalp de memecoins"]}
            target = SCALP_FIRST_RESULT_S
        r["timing"]["target_s"] = target
        r["timing"]["first_result_within_target"] = r["timing"]["first_result_ms"] <= target * 1000
        r["scores"] = scoring.compute(r, settings, final=True)
        r["probabilities"] = tracker.probabilities_for(self.svc.db, r["scores"]["global"], settings)
        await self._ai_summary(r)
        r["timing"]["total_ms"] = int((time.monotonic() - t0) * 1000)
        failed = [n for n, m in r["modules"].items() if m["status"] != "terminé"]
        r["status"] = "complète" if not failed else "partielle"
        r["incomplete_modules"] = failed
        r["provisional"] = False
        r["finished_at"] = time.time()
        from .config import active_weights
        r["model_version_id"] = self.svc.db.current_model_version(
            active_weights(settings), settings["thresholds"])
        if self.watcher and an.mint in self.watcher.watches:
            from .engines.live import watch_info_from_result
            self.watcher.watches[an.mint].info.update({k: v for k, v in watch_info_from_result(r).items() if v})
        self._save(an)
        an.publish("complete", r)
        an.done.set()
        self._notifications(r)
        asyncio.get_event_loop().call_later(600, self.live.pop, an.id, None)

    def _first_result(self, an: Analysis, t0: float, partial: bool = False) -> None:
        ms = int((time.monotonic() - t0) * 1000)
        an.result["timing"] = {"first_result_ms": ms, "first_result_partial": partial}
        an.publish("first_result", {"ms": ms, "partial": partial, "scores": an.result.get("scores")})
        self._maybe_watch(an)

    def _maybe_watch(self, an: Analysis) -> None:
        """Mode Scalp : le suivi en direct démarre dès la première fiche, sans attendre la fin de l'analyse."""
        s = self.svc.settings.all()
        if not self.watcher or not (s.get("scalp") or {}).get("auto_watch", True):
            return
        from .engines.live import watch_info_from_result
        r = an.result
        mcap = ((r.get("market") or {}).get("mcap") or {}).get("v")
        if not mcap:
            return
        try:
            w = self.watcher.start(an.mint, watch_info_from_result(r), None)  # objectif/stop fixés au 1er relevé live
            r["live_watch"] = {"active": True, "targets": w.targets}
        except Exception as exc:
            r["live_watch"] = {"active": False, "error": str(exc)[:200]}

    async def _ai_summary(self, r: dict) -> None:
        sc = r["scores"]
        llm = self.svc.llm
        summary = None
        if llm.available:
            facts = {"token": {k: r.get("token", {}).get(k) for k in ("name", "symbol")},
                     "score": sc["global"], "verdict": sc["verdict"], "raison": sc["verdict_reason"],
                     "confiance": sc["confidence"], "positifs": sc["positives"], "negatifs": sc["negatives"],
                     "risques": [x["message"] for x in r.get("risks", [])][:8],
                     "categories": {k: v["score"] for k, v in sc["categories"].items()}}
            try:
                out = await llm.json("Rédige en français une conclusion synthétique (3 à 5 phrases) expliquant ce "
                                     "verdict à un trader. N'ajoute aucun fait absent des données, ne modifie ni le "
                                     "score ni le verdict, ne donne aucune probabilité. Format : {\"summary\": \"...\"}",
                                     json.dumps(facts, ensure_ascii=False), timeout=20)
                summary = (out or {}).get("summary")
            except Exception as exc:
                r["ai_error"] = str(exc)[:200]
        if not summary:
            g = sc["global"]
            summary = (f"Score {g}/10 ({sc['interpretation']}), verdict {sc['verdict']} : {sc['verdict_reason']}. "
                       + (f"Points forts : {'; '.join(sc['positives'][:3])}. " if sc["positives"] else "")
                       + (f"Points faibles : {'; '.join(sc['negatives'][:3])}. " if sc["negatives"] else "")
                       + f"Confiance {sc['confidence'] * 100:.0f}%.") if g is not None else sc["verdict_reason"]
            r["summary_source"] = "règles"
        else:
            r["summary_source"] = "IA (" + (llm.cfg.get("model") or llm.provider) + ")"
        r["summary"] = summary

    def _fail(self, an: Analysis, message: str, kind: str) -> None:
        an.result.update(status=kind, error=message, provisional=False, finished_at=time.time())
        self.svc.db.execute("UPDATE token_analyses SET status=?, finished_at=?, result_json=? WHERE id=?",
                            (kind, time.time(), json.dumps(an.result, default=str), an.id))
        an.publish("error", {"message": message, "kind": kind})
        an.done.set()
        asyncio.get_event_loop().call_later(600, self.live.pop, an.id, None)

    def _save(self, an: Analysis) -> None:
        r, db = an.result, self.svc.db
        tok, m, sc = r.get("token", {}), r.get("market", {}), r["scores"]
        v = lambda d: (d or {}).get("v") if isinstance(d, dict) else None  # noqa: E731
        lp = (tok.get("launchpad") or {}).get("id")
        db.execute("UPDATE token_analyses SET finished_at=?, status=?, mode=?, launchpad=?, name=?, symbol=?, score=?, "
                   "verdict=?, confidence=?, risk=?, mcap=?, liquidity=?, volume_24h=?, price_usd=?, first_result_ms=?, "
                   "total_ms=?, model_version_id=?, result_json=? WHERE id=?",
                   (r["finished_at"], r["status"], r["mode"]["value"], lp, tok.get("name"), tok.get("symbol"),
                    sc["global"], sc["verdict"], sc["confidence"], sc["risk"]["score"], v(m.get("mcap")),
                    v(m.get("liquidity_usd")), v((m.get("volume") or {}).get("h24")), v(m.get("price_usd")),
                    r["timing"]["first_result_ms"], r["timing"]["total_ms"], r["model_version_id"],
                    json.dumps(r, default=str), an.id))
        prev = db.one("SELECT last_analysis_id FROM tokens WHERE mint=?", (an.mint,))
        db.execute("INSERT INTO tokens(mint, name, symbol, launchpad, decimals, created_at, first_seen, last_analysis_id) "
                   "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(mint) DO UPDATE SET name=excluded.name, symbol=excluded.symbol, "
                   "launchpad=excluded.launchpad, last_analysis_id=excluded.last_analysis_id",
                   (an.mint, tok.get("name"), tok.get("symbol"), lp, tok.get("decimals"),
                    v(tok.get("created_at")), time.time(), an.id))
        for x in r.get("risks", []):
            db.execute("INSERT INTO risk_events(analysis_id, mint, level, code, message, source, ts) VALUES(?,?,?,?,?,?,?)",
                       (an.id, an.mint, x["level"], x["code"], x["message"], x["source"], time.time()))
        for mt in (r.get("narrative") or {}).get("matches", []):
            db.execute("INSERT INTO token_narratives(analysis_id, mint, narrative, score, data) VALUES(?,?,?,?,?)",
                       (an.id, an.mint, mt["name"], mt["strength"], json.dumps(mt)))
        db.execute("UPDATE fact_checks SET analysis_id=? WHERE mint=? AND analysis_id IS NULL", (an.id, an.mint))
        if v(m.get("price_usd")):
            tracker.schedule(db, an.id, r["started_at"])
            tracker.schedule_scalp(db, an.id, r["started_at"], r, self.svc.settings.all())
        r["previous_analysis_id"] = prev["last_analysis_id"] if prev else None

    def _notifications(self, r: dict) -> None:
        cfg = self.svc.settings.get("notifications", {})
        sc, tok = r["scores"], r.get("token", {})
        name = f"{tok.get('name') or '?'} (${tok.get('symbol') or '?'})"
        if sc["global"] is not None and sc["global"] >= cfg.get("score_above", 8):
            self.notifier.emit("score_above", {"id": r["analysis_id"]}, f"{name} : {sc['global']}/10",
                               f"Verdict {sc['verdict']}")
        if sc["risk"]["critical"] and cfg.get("critical_risk", True):
            self.notifier.emit("critical_risk", {"id": r["analysis_id"]}, f"Risque critique — {name}",
                               sc["risk"]["critical"][0]["message"])
        for a in r.get("alerts", []):
            self.notifier.emit("smart_money", {"id": r["analysis_id"]}, f"Smart money — {name}", a["message"])
        prev_id = r.get("previous_analysis_id")
        if prev_id:
            prev = self.svc.db.one("SELECT score, result_json FROM token_analyses WHERE id=?", (prev_id,))
            if prev and prev["score"] is not None and sc["global"] is not None \
                    and abs(sc["global"] - prev["score"]) >= cfg.get("score_change", 1.5):
                self.notifier.emit("score_change", {"id": r["analysis_id"]}, f"Score modifié — {name}",
                                   f"{prev['score']} → {sc['global']}")
            if prev and prev["result_json"]:
                old = {c["text"]: c["status"] for c in (json.loads(prev["result_json"]).get("factcheck") or {}).get("claims", [])}
                for c in (r.get("factcheck") or {}).get("claims", []):
                    if old.get(c["text"]) == "NON VÉRIFIÉ" and c["status"].startswith("CONFIRMÉ"):
                        self.notifier.emit("claim_confirmed", {"id": r["analysis_id"]}, f"Information confirmée — {name}",
                                           c["text"][:200])
