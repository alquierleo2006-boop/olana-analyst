"""API locale (127.0.0.1 uniquement) consommée par l'application desktop.

Sécurité : jeton de session obligatoire (généré par l'app au lancement), vérification de l'hôte,
CORS limité aux origines de l'application. Le backend est en lecture seule : aucune clé privée,
aucune signature, aucun transfert.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets as pysecrets
import time

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .config import SECRET_NAMES, Secrets, Settings, data_dir
from .db import DB
from .engines.context import Services
from .engines.live import LiveWatcher, curve_address
from .engines.narratives import NarrativeEngine
from .engines.smartmoney import evaluate_wallet, validate_wallet
from .engines.tracker import Tracker, backtest_report
from .http import Http
from .notify import Notifier
from .orchestrator import Analyzer
from .providers.llm import LLM
from .providers.market import DexScreener, GeckoTerminal, Jupiter, PumpFunAPI, RugCheck
from .providers.news import News
from .providers.solana import SolanaRPC
from .providers.web import Web
from .util import is_valid_mint_format

ALLOWED_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
                   "http://localhost:1420", "http://127.0.0.1:1420"]


class AnalyzeIn(BaseModel):
    mint: str = Field(..., max_length=64)


class WalletIn(BaseModel):
    address: str = Field(..., max_length=64)
    label: str | None = Field(None, max_length=60)


class LiveIn(BaseModel):
    above: float | None = None
    below: float | None = None


class SecretIn(BaseModel):
    value: str | None = Field(None, max_length=500)


class State:
    def __init__(self, transport=None, path=None) -> None:
        self.db = DB(path or (data_dir() / "analyst.sqlite3"))
        self.settings = Settings(self.db)
        self.secrets = Secrets()
        self.http = Http(transport)
        self.notifier = Notifier(self.http, self.settings, self.secrets)
        self.build()

    def build(self) -> None:
        s = self.settings.all()
        self.http.disabled = {k for k, on in s.get("providers", {}).items() if not on}
        h = self.http
        self.svc = Services(
            http=h, rpc=SolanaRPC(h, s["rpc_url"], self.secrets.get("helius_api_key")), dex=DexScreener(h),
            gecko=GeckoTerminal(h), jup=Jupiter(h), rug=RugCheck(h), pump=PumpFunAPI(h), web=Web(h), news=News(h),
            llm=LLM(h, s.get("llm"), self.secrets.get("llm_api_key")), db=self.db, settings=self.settings,
            secrets=self.secrets)
        if hasattr(self, "narratives"):
            self.narratives.dex = self.svc.dex
            self.analyzer.svc = self.svc
            self.tracker.svc = self.svc
            self.live.svc = self.svc
        else:
            self.narratives = NarrativeEngine(h, self.svc.news, self.svc.dex, self.db, self.settings,
                                              notify=lambda k, d: self.notifier.emit(
                                                  k, d, f"Narrative en accélération : {d.get('name')}", d.get("state", "")))
            self.live = LiveWatcher(self.svc, self.notifier)
            self.analyzer = Analyzer(self.svc, self.narratives, self.notifier, self.live)
            self.tracker = Tracker(self.svc)
        for name in ("helius",):
            if not self.secrets.get("helius_api_key"):
                h.mark(name, "non configuré")
        if not self.svc.llm.available:
            h.mark("llm", "non configuré")


def create_app(transport=None, db_path=None, start_background: bool = True) -> FastAPI:
    token = os.environ.get("ANALYST_TOKEN") or ""
    app = FastAPI(title="Solana AI Desktop Analyst", version=__version__)
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"],
                       allow_headers=["*"], allow_credentials=False)
    st = State(transport, db_path)
    app.state.st = st

    @app.on_event("startup")
    async def _startup():
        if start_background:
            st.narratives.start()
            st.tracker.start()

    def auth(request: Request):
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            raise HTTPException(403, "hôte non autorisé")
        if token and not pysecrets.compare_digest(request.headers.get("x-analyst-token", ""), token):
            raise HTTPException(401, "jeton de session invalide")

    def ws_ok(ws: WebSocket) -> bool:
        return not token or pysecrets.compare_digest(ws.query_params.get("token", ""), token)

    A = [Depends(auth)]

    @app.get("/api/health", dependencies=A)
    async def health():
        s = st.settings.all()
        return {"version": __version__, "time": time.time(), "read_only": True,
                "live_watches": len([w for w in st.live.watches.values() if not w.stopped]),
                "llm": {"available": st.svc.llm.available, "provider": s["llm"]["provider"]},
                "helius": bool(st.secrets.get("helius_api_key")),
                "narrative_engine": st.narratives.status, "tracker": st.tracker.status,
                "providers": st.http.snapshot()}

    @app.post("/api/analyze", dependencies=A)
    async def analyze(body: AnalyzeIn):
        mint = body.mint.strip()
        if not is_valid_mint_format(mint):
            raise HTTPException(400, "Adresse invalide : une adresse Solana fait 32 à 44 caractères base58 "
                                     "(sans 0, O, I ni l).")
        an = st.analyzer.start(mint)
        return {"analysis_id": an.id, "mint": mint}

    @app.get("/api/analyses/{aid}", dependencies=A)
    async def get_analysis(aid: int):
        if aid in st.analyzer.live:
            return st.analyzer.live[aid].result
        row = st.db.one("SELECT result_json, status FROM token_analyses WHERE id=?", (aid,))
        if not row:
            raise HTTPException(404, "analyse inconnue")
        if not row["result_json"]:
            return {"analysis_id": aid, "status": row["status"], "error": "analyse interrompue (redémarrage)"}
        res = json.loads(row["result_json"])
        res["performance"] = st.db.all("SELECT horizon, due_at, taken_at, delay_s, price_usd, mcap, liquidity, "
                                       "max_mcap, min_mcap, change_pct, status FROM historical_performance "
                                       "WHERE analysis_id=? ORDER BY due_at", (aid,))
        return res

    @app.websocket("/ws/analyses/{aid}")
    async def ws_analysis(ws: WebSocket, aid: int):
        if not ws_ok(ws):
            await ws.close(code=4401)
            return
        await ws.accept()
        an = st.analyzer.live.get(aid)
        if not an:
            row = st.db.one("SELECT result_json FROM token_analyses WHERE id=?", (aid,))
            data = json.loads(row["result_json"]) if row and row["result_json"] else None
            await ws.send_json({"type": "error" if not data or data.get("error") else "complete", "data": data})
            await ws.close()
            return
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        an.subscribers.add(q)
        try:
            await ws.send_json({"type": "snapshot", "data": json.loads(json.dumps(an.result, default=str))})
            if an.done.is_set():
                kind = "error" if an.result.get("error") else "complete"
                await ws.send_json({"type": kind, "data": json.loads(json.dumps(an.result, default=str))})
                return
            while True:
                ev = await q.get()
                await ws.send_text(json.dumps(ev, default=str))
                if ev["type"] in ("complete", "error"):
                    break
        except WebSocketDisconnect:
            pass
        finally:
            an.subscribers.discard(q)
            try:
                await ws.close()
            except Exception:
                pass

    @app.get("/api/history", dependencies=A)
    async def history(limit: int = 200, launchpad: str | None = None, verdict: str | None = None,
                      min_score: float | None = None, max_score: float | None = None,
                      date_from: float | None = None, date_to: float | None = None, q: str | None = None,
                      outcome: str | None = None):
        sql = ("SELECT id, mint, created_at, status, mode, launchpad, name, symbol, score, verdict, confidence, risk, "
               "mcap, liquidity, volume_24h, first_result_ms, total_ms FROM token_analyses WHERE 1=1")
        p: list = []
        for cond, val in (("launchpad=?", launchpad), ("verdict=?", verdict), ("score>=?", min_score),
                          ("score<=?", max_score), ("created_at>=?", date_from), ("created_at<=?", date_to)):
            if val is not None and val != "":
                sql += f" AND {cond}"; p.append(val)
        if q:
            sql += " AND (mint LIKE ? OR name LIKE ? OR symbol LIKE ?)"; p += [f"%{q}%"] * 3
        sql += " ORDER BY created_at DESC LIMIT ?"
        p.append(min(max(1, limit), 1000))
        rows = st.db.all(sql, p)
        for r in rows:
            perf = st.db.all("SELECT horizon, change_pct, status FROM historical_performance WHERE analysis_id=?", (r["id"],))
            r["performance"] = {x["horizon"]: x["change_pct"] for x in perf if x["status"] in ("done", "late")}
        if outcome in ("up", "down"):
            def last_change(r):
                for h in ("7j", "24h", "6h", "1h", "15m", "5m"):
                    if r["performance"].get(h) is not None:
                        return r["performance"][h]
                return None
            rows = [r for r in rows if (c := last_change(r)) is not None and ((c > 0) == (outcome == "up"))]
        return rows

    @app.get("/api/compare", dependencies=A)
    async def compare(ids: str):
        out = []
        for i in [int(x) for x in ids.split(",") if x.strip().isdigit()][:6]:
            row = st.db.one("SELECT result_json FROM token_analyses WHERE id=?", (i,))
            if row and row["result_json"]:
                r = json.loads(row["result_json"])
                out.append({"id": i, "token": {k: r.get("token", {}).get(k) for k in ("name", "symbol", "mint", "image")},
                            "scores": r.get("scores"), "market": {k: r.get("market", {}).get(k) for k in
                                                                  ("mcap", "liquidity_usd", "price_usd")},
                            "created_at": r.get("started_at")})
        return out

    @app.get("/api/narratives", dependencies=A)
    async def narratives():
        return {"items": st.narratives.latest()[:10], "status": st.narratives.status}

    @app.post("/api/narratives/refresh", dependencies=A)
    async def narratives_refresh():
        asyncio.create_task(st.narratives.refresh())
        return {"ok": True}

    @app.get("/api/wallets", dependencies=A)
    async def wallets():
        rows = st.db.all("SELECT * FROM wallets ORDER BY added_at DESC")
        for r in rows:
            r["stats"] = json.loads(r["stats"]) if r["stats"] else None
        return rows

    @app.post("/api/wallets", dependencies=A)
    async def add_wallet(body: WalletIn):
        if not validate_wallet(body.address.strip()):
            raise HTTPException(400, "adresse de wallet invalide")
        st.db.execute("INSERT INTO wallets(address, label, added_at) VALUES(?,?,?) ON CONFLICT(address) DO UPDATE "
                      "SET label=excluded.label, tracked=1", (body.address.strip(), body.label, time.time()))
        return {"ok": True}

    @app.delete("/api/wallets/{address}", dependencies=A)
    async def del_wallet(address: str):
        st.db.execute("DELETE FROM wallets WHERE address=?", (address,))
        return {"ok": True}

    @app.post("/api/wallets/{address}/evaluate", dependencies=A)
    async def eval_wallet(address: str):
        if not st.secrets.get("helius_api_key"):
            raise HTTPException(400, "Nécessite une clé Helius gratuite (Paramètres → Clés API).")
        try:
            return await evaluate_wallet(st.svc, address)
        except Exception as exc:
            raise HTTPException(502, f"Évaluation impossible : {exc}")

    @app.get("/api/performance", dependencies=A)
    async def performance():
        return backtest_report(st.db, st.settings.all())

    @app.get("/api/settings", dependencies=A)
    async def get_settings():
        return {"settings": st.settings.all(), "secrets": st.secrets.status()}

    @app.put("/api/settings", dependencies=A)
    async def put_settings(patch: dict):
        allowed = set(st.settings.all())
        bad = [k for k in patch if k not in allowed]
        if bad:
            raise HTTPException(400, f"paramètres inconnus : {bad}")
        new = st.settings.update(patch)
        st.build()
        from .config import active_weights
        st.db.current_model_version(active_weights(new), new["thresholds"])
        return {"settings": new}

    @app.put("/api/secrets/{name}", dependencies=A)
    async def put_secret(name: str, body: SecretIn):
        if name not in SECRET_NAMES:
            raise HTTPException(400, "secret inconnu")
        where = st.secrets.set(name, (body.value or "").strip() or None)
        st.build()
        return {"ok": True, "stored_in": where}

    # ---------------- suivi en direct (mode Scalp)
    @app.get("/api/live", dependencies=A)
    async def live_list():
        return st.live.list()

    @app.post("/api/live/{mint}", dependencies=A)
    async def live_start(mint: str, body: LiveIn):
        if not is_valid_mint_format(mint):
            raise HTTPException(400, "adresse invalide")
        w = st.live.watches.get(mint)
        if w and not w.stopped:
            w.targets.update({"above": body.above, "below": body.below})
            w.fired = {f for f in w.fired if not f.startswith(("TARGET_UP", "STOP"))}
            return st.live.snapshot(w)
        row = st.db.one("SELECT result_json FROM token_analyses WHERE mint=? AND result_json IS NOT NULL "
                        "ORDER BY id DESC LIMIT 1", (mint,))
        from .engines.live import watch_info_from_result
        info = watch_info_from_result(json.loads(row["result_json"])) if row else \
            {"curve_address": curve_address(mint) if mint.endswith("pump") else None}
        w = st.live.start(mint, info, {"above": body.above, "below": body.below})
        return st.live.snapshot(w)

    @app.delete("/api/live/{mint}", dependencies=A)
    async def live_stop(mint: str):
        st.live.stop(mint)
        return {"ok": True}

    @app.websocket("/ws/live/{mint}")
    async def ws_live(ws: WebSocket, mint: str):
        if not ws_ok(ws):
            await ws.close(code=4401)
            return
        await ws.accept()
        w = st.live.watches.get(mint)
        if not w:
            await ws.send_json({"type": "stopped", "data": {"mint": mint}})
            await ws.close()
            return
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        w.subscribers.add(q)
        try:
            await ws.send_text(json.dumps({"type": "tick", "data": st.live.snapshot(w)}, default=str))
            while True:
                ev = await q.get()
                await ws.send_text(json.dumps(ev, default=str))
                if ev["type"] == "stopped":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            w.subscribers.discard(q)

    @app.get("/api/notifications", dependencies=A)
    async def notifications():
        return st.notifier.recent

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket):
        if not ws_ok(ws):
            await ws.close(code=4401)
            return
        await ws.accept()
        q = st.notifier.subscribe()
        try:
            while True:
                ev = await q.get()
                await ws.send_text(json.dumps(ev, default=str))
        except WebSocketDisconnect:
            pass
        finally:
            st.notifier.unsubscribe(q)

    @app.on_event("shutdown")
    async def _shutdown():
        await st.http.close()

    return app
