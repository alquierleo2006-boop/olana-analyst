"""Suivi des performances après analyse, backtesting et modèle de probabilités calibré.

Aucune probabilité n'est affichée tant que le modèle n'a pas passé la validation chronologique
(échantillon de test suffisant, meilleur que le taux de base, bien calibré).
"""
from __future__ import annotations

import asyncio
import json
import math
import time

HORIZONS = {"5m": 300, "15m": 900, "1h": 3600, "6h": 6 * 3600, "24h": 86400, "7j": 7 * 86400}
PROB_HORIZONS = ["15m", "1h", "6h", "24h", "7j"]
SCORE_BUCKETS = [(0, 4), (4, 6), (6, 7), (7, 8), (8, 10.01)]
FEES_ROUNDTRIP_PCT = 2.0  # hypothèse frais + slippage aller-retour, affichée


SCALP_WINDOW_S = 3600


def schedule_scalp(db, analysis_id: int, t0: float, r: dict, settings: dict) -> None:
    sc = settings.get("scalp") or {}
    chk = ((r.get("scores") or {}).get("scalp") or {})
    plan = chk.get("plan") or {}
    window = float(settings.get("outcome_window_min", 60)) * 60
    db.execute("INSERT OR IGNORE INTO scalp_outcomes(analysis_id, due_at, tp_pct, sl_pct, cost_pct, score, decision, window_s) "
               "VALUES(?,?,?,?,?,?,?,?)",
               (analysis_id, t0 + window, float(sc.get("take_profit_pct", 40)), float(sc.get("stop_pct", 20)),
                plan.get("cost_pct"), (r.get("scores") or {}).get("global"), chk.get("decision"), window))


def scalp_outcome(candles: list[list], t0: float, tp: float, sl: float, window_s: float = SCALP_WINDOW_S) -> dict | None:
    """Rejoue le trade minute par minute : l'objectif (+tp %) est-il touché avant le stop (−sl %) ?
    Entrée = ouverture de la 1re bougie après l'analyse. Si les deux sont touchés dans la même minute,
    l'issue est comptée comme perdante (hypothèse prudente)."""
    start = int(t0 // 60) * 60
    win = [c for c in candles if start <= c[0] <= t0 + window_s]
    if not win or not win[0][1]:
        return None
    entry = win[0][1]
    up, down = entry * (1 + tp / 100), entry * (1 - sl / 100)
    hi = lo = entry
    for c in win:
        hi, lo = max(hi, c[2]), min(lo, c[3])
        hit_tp, hit_sl = c[2] >= up, c[3] <= down
        if hit_tp or hit_sl:
            outcome = "ambiguous" if hit_tp and hit_sl else "win" if hit_tp else "loss"
            return {"outcome": outcome, "minutes": (c[0] - start) / 60, "entry_price": entry,
                    "max_gain_pct": 100 * (hi / entry - 1), "max_drawdown_pct": 100 * (lo / entry - 1),
                    "final_change_pct": 100 * (c[4] / entry - 1)}
    return {"outcome": "open", "minutes": None, "entry_price": entry, "max_gain_pct": 100 * (hi / entry - 1),
            "max_drawdown_pct": 100 * (lo / entry - 1), "final_change_pct": 100 * (win[-1][4] / entry - 1)}


def scalp_pnl(o: dict, tp: float, sl: float, cost: float | None) -> float:
    cost = 3.0 if cost is None else cost
    if o["outcome"] == "win":
        return tp - cost
    if o["outcome"] in ("loss", "ambiguous"):
        return -sl - cost
    return o["final_change_pct"] - cost


def schedule(db, analysis_id: int, t0: float) -> None:
    db.executemany("INSERT OR IGNORE INTO historical_performance(analysis_id, horizon, due_at) VALUES(?,?,?)",
                   [(analysis_id, h, t0 + s) for h, s in HORIZONS.items()])


class Tracker:
    def __init__(self, svc) -> None:
        self.svc = svc
        self._task = None
        self.status = {"state": "arrêté", "last_run": None, "pending": 0}

    async def run_once(self) -> int:
        db = self.svc.db
        now = time.time()
        due = db.all("SELECT p.id, p.analysis_id, p.horizon, p.due_at, a.mint, a.mcap, a.price_usd, a.created_at "
                     "FROM historical_performance p JOIN token_analyses a ON a.id=p.analysis_id "
                     "WHERE p.status='pending' AND p.due_at<=? ORDER BY p.due_at LIMIT 60", (now,))
        self.status["pending"] = db.one("SELECT COUNT(*) c FROM historical_performance WHERE status='pending'")["c"]
        if not due:
            return 0
        mints = list({d["mint"] for d in due})
        try:
            pairs = await self.svc.dex.pairs(mints)
        except Exception:
            return 0
        best: dict[str, dict] = {}
        for p in pairs:
            a = (p.get("baseToken") or {}).get("address")
            if a and ((p.get("liquidity") or {}).get("usd") or 0) >= ((best.get(a) or {}).get("liquidity") or {}).get("usd", -1):
                best[a] = p
        for d in due:
            p = best.get(d["mint"])
            delay = now - d["due_at"]
            tolerance = max(120, HORIZONS[d["horizon"]] * 0.25)
            status = "done" if delay <= tolerance else "late"
            if not p:
                db.execute("UPDATE historical_performance SET taken_at=?, delay_s=?, status=? WHERE id=?",
                           (now, delay, "no_data", d["id"]))
                continue
            price = float(p.get("priceUsd") or 0) or None
            mcap = p.get("marketCap") or p.get("fdv")
            liq = (p.get("liquidity") or {}).get("usd")
            ref = d["price_usd"]
            change = 100 * (price / ref - 1) if price and ref else None
            mx = mn = None
            pool = p.get("pairAddress")
            if pool and d["horizon"] in ("1h", "6h", "24h", "7j"):
                try:
                    tf, agg, lim = ("minute", 5, 300) if d["horizon"] in ("1h", "6h") else ("hour", 1, 200)
                    candles = await self.svc.gecko.ohlcv(pool, tf, agg, lim)
                    win = [c for c in candles if d["created_at"] <= c[0] <= now]
                    if win and ref and price:
                        ratio = (mcap or 0) / price if mcap else None
                        mx = max(c[2] for c in win) * ratio if ratio else None
                        mn = min(c[3] for c in win) * ratio if ratio else None
                except Exception:
                    pass
            db.execute("UPDATE historical_performance SET taken_at=?, delay_s=?, price_usd=?, mcap=?, liquidity=?, "
                       "max_mcap=?, min_mcap=?, change_pct=?, status=? WHERE id=?",
                       (now, delay, price, mcap, liq, mx, mn, change, status, d["id"]))
        self.status["last_run"] = now
        return len(due)

    async def run_scalp_once(self) -> int:
        db = self.svc.db
        due = db.all("SELECT s.analysis_id, s.tp_pct, s.sl_pct, s.cost_pct, s.window_s, a.created_at, a.result_json FROM scalp_outcomes s "
                     "JOIN token_analyses a ON a.id = s.analysis_id WHERE s.status='pending' AND s.due_at <= ? "
                     "ORDER BY s.due_at LIMIT 10", (time.time(),))
        for d in due:
            r = json.loads(d["result_json"] or "{}")
            pool = ((r.get("market") or {}).get("main_pair") or {}).get("address") or (r.get("market") or {}).get("gecko_pool")
            o = None
            if pool:
                try:
                    w = d["window_s"] or SCALP_WINDOW_S
                    # 1 min jusqu'à 5 h de fenêtre ; au-delà, bougies de 5 min.
                    agg = 1 if w <= 5 * 3600 else 5
                    o = scalp_outcome(await self.svc.gecko.ohlcv(pool, "minute", agg, 1000 if agg > 1 else 300),
                                      d["created_at"], d["tp_pct"], d["sl_pct"], w)
                except Exception:
                    o = None
            if not o:
                # Données absentes : on réessaie plus tard, puis on abandonne après 24 h.
                late = time.time() - d["created_at"] > 86400
                db.execute("UPDATE scalp_outcomes SET status=?, due_at=? WHERE analysis_id=?",
                           ("no_data" if late else "pending", time.time() + 600, d["analysis_id"]))
                continue
            db.execute("UPDATE scalp_outcomes SET status='done', outcome=?, minutes=?, entry_price=?, max_gain_pct=?, "
                       "max_drawdown_pct=?, final_change_pct=?, pnl_pct=?, evaluated_at=? WHERE analysis_id=?",
                       (o["outcome"], o["minutes"], o["entry_price"], o["max_gain_pct"], o["max_drawdown_pct"],
                        o["final_change_pct"], scalp_pnl(o, d["tp_pct"], d["sl_pct"], d["cost_pct"]), time.time(),
                        d["analysis_id"]))
        return len(due)

    async def loop(self) -> None:
        while True:
            try:
                if self.svc.settings.get("tracking_enabled", True):
                    await self.run_once()
                    await self.run_scalp_once()
                self.prune()
            except Exception as exc:
                self.status["error"] = str(exc)[:200]
            await asyncio.sleep(60)

    def prune(self) -> None:
        """Durée de conservation de l'historique (paramètre utilisateur)."""
        days = int(self.svc.settings.get("history_retention_days", 365) or 0)
        if days <= 0:
            return
        cutoff = time.time() - days * 86400
        db = self.svc.db
        old = "SELECT id FROM token_analyses WHERE created_at < ?"
        for table in ("historical_performance", "risk_events", "token_narratives", "fact_checks", "smart_money_events"):
            db.execute(f"DELETE FROM {table} WHERE analysis_id IN ({old})", (cutoff,))
        db.execute("DELETE FROM token_analyses WHERE created_at < ?", (cutoff,))
        for table in ("market_snapshots", "holder_snapshots"):
            db.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
        db.execute("DELETE FROM news_articles WHERE fetched_at < ?", (time.time() - 14 * 86400,))

    def start(self) -> None:
        if not self._task:
            self.status["state"] = "actif"
            self._task = asyncio.create_task(self.loop())


# ------------------------------------------------------------------ backtesting
def _samples(db, horizon: str) -> list[dict]:
    return db.all("SELECT a.id, a.created_at, a.score, a.verdict, a.launchpad, a.mcap AS mcap0, p.change_pct, "
                  "p.max_mcap, p.min_mcap, p.liquidity FROM historical_performance p JOIN token_analyses a "
                  "ON a.id=p.analysis_id WHERE p.horizon=? AND p.status='done' AND p.change_pct IS NOT NULL "
                  "AND a.score IS NOT NULL ORDER BY a.created_at", (horizon,))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d, (c + m) / d


def bucket_of(score: float) -> int:
    return next(i for i, (lo, hi) in enumerate(SCORE_BUCKETS) if lo <= score < hi)


def fit_probability_model(samples: list[dict], rise_pct: float, min_test: int) -> dict:
    n = len(samples)
    hits = [1 if (s["change_pct"] - FEES_ROUNDTRIP_PCT) >= rise_pct else 0 for s in samples]
    n_train = int(n * 0.6)
    n_val = int(n * 0.2)
    test_idx = range(n_train + n_val, n)
    if len(test_idx) < min_test:
        return {"usable": False, "reason": "DONNÉES INSUFFISANTES POUR UNE PROBABILITÉ FIABLE",
                "observations": n, "test_needed": min_test, "test_available": len(test_idx)}
    fit = range(0, n_train + n_val)  # entraînement + validation (chronologiquement antérieurs)
    counts = [[0, 0] for _ in SCORE_BUCKETS]
    for i in fit:
        b = bucket_of(samples[i]["score"])
        counts[b][0] += hits[i]; counts[b][1] += 1
    base = sum(hits[i] for i in fit) / max(1, len(fit))
    probs = [(k + base * 2) / (m + 2) for k, m in counts]  # lissage vers le taux de base
    brier = sum((probs[bucket_of(samples[i]["score"])] - hits[i]) ** 2 for i in test_idx) / len(test_idx)
    brier_base = sum((base - hits[i]) ** 2 for i in test_idx) / len(test_idx)
    ece, tot = 0.0, len(test_idx)
    for b in range(len(SCORE_BUCKETS)):
        idx = [i for i in test_idx if bucket_of(samples[i]["score"]) == b]
        if idx:
            ece += len(idx) / tot * abs(probs[b] - sum(hits[i] for i in idx) / len(idx))
    usable = brier < brier_base and ece < 0.1
    return {"usable": usable, "observations": n, "test_size": tot, "brier": round(brier, 4),
            "brier_base_rate": round(brier_base, 4), "ece": round(ece, 4), "base_rate": round(base, 3),
            "buckets": [{"range": f"{lo}–{min(hi, 10):g}", "probability": round(probs[b], 3), "n": counts[b][1],
                         "ci95": [round(x, 3) for x in wilson(counts[b][0], counts[b][1])]}
                        for b, (lo, hi) in enumerate(SCORE_BUCKETS)],
            "reason": None if usable else "modèle non validé (pas meilleur que le taux de base ou mal calibré)"}


def _scalp_samples(db) -> list[dict]:
    rows = db.all("SELECT s.score AS score, s.outcome AS outcome FROM scalp_outcomes s JOIN token_analyses a ON a.id = s.analysis_id "
                  "WHERE s.status='done' AND s.score IS NOT NULL ORDER BY a.created_at")
    # change_pct fictif : 100 si objectif touché avant le stop, sinon −100 (réutilise le modèle calibré).
    return [{"score": r["score"], "change_pct": 100.0 if r["outcome"] == "win" else -100.0} for r in rows]


def probabilities_for(db, score: float | None, settings: dict) -> dict:
    rise = settings.get("rise_definition_pct", 20.0)
    min_test = settings.get("probability_min_test_samples", 100)
    sc = settings.get("scalp") or {}
    out = {"definition": f"hausse ≥ {rise:g}% du prix depuis l'analyse, après {FEES_ROUNDTRIP_PCT:g}% de frais estimés",
           "horizons": {}}
    model = fit_probability_model(_scalp_samples(db), 0, min_test)
    win_h = float(settings.get("outcome_window_min", 60)) / 60
    key = f"objectif +{sc.get('take_profit_pct', 40):g}% avant stop −{sc.get('stop_pct', 20):g}% ({win_h:g} h)"
    if model["usable"] and score is not None:
        b = model["buckets"][bucket_of(score)]
        out["scalp"] = {"label": key, "available": True, "probability": b["probability"], "ci95": b["ci95"],
                        "comparable_observations": b["n"], "brier": model["brier"], "ece": model["ece"]}
    else:
        out["scalp"] = {"label": key, "available": False, "message": "DONNÉES INSUFFISANTES POUR UNE PROBABILITÉ FIABLE",
                        "observations": model["observations"], "detail": model.get("reason")}
    for h in PROB_HORIZONS:
        model = fit_probability_model(_samples(db, h), rise, min_test)
        if not model["usable"] or score is None:
            out["horizons"][h] = {"available": False, "message": "DONNÉES INSUFFISANTES POUR UNE PROBABILITÉ FIABLE",
                                  "observations": model["observations"], "detail": model.get("reason")}
        else:
            b = model["buckets"][bucket_of(score)]
            out["horizons"][h] = {"available": True, "probability": b["probability"], "ci95": b["ci95"],
                                  "comparable_observations": b["n"], "brier": model["brier"], "ece": model["ece"]}
    return out


def backtest_report(db, settings: dict) -> dict:
    rise = settings.get("rise_definition_pct", 20.0)
    min_test = settings.get("probability_min_test_samples", 100)
    report = {"rise_definition_pct": rise, "fees_assumption_pct": FEES_ROUNDTRIP_PCT, "horizons": {}}
    for h in HORIZONS:
        S = _samples(db, h)
        if not S:
            report["horizons"][h] = {"observations": 0}
            continue

        def agg(rows):
            ch = sorted(r["change_pct"] - FEES_ROUNDTRIP_PCT for r in rows)
            hits = sum(1 for c in ch if c >= rise)
            dd = [100 * (r["min_mcap"] / r["mcap0"] - 1) for r in rows if r["min_mcap"] and r["mcap0"]]
            mx = [100 * (r["max_mcap"] / r["mcap0"] - 1) for r in rows if r["max_mcap"] and r["mcap0"]]
            return {"n": len(rows), "median_change_after_fees": round(ch[len(ch) // 2], 1),
                    "hit_rate": round(hits / len(rows), 3), "ci95": [round(x, 3) for x in wilson(hits, len(rows))],
                    "avg_max_gain": round(sum(mx) / len(mx), 1) if mx else None,
                    "avg_drawdown": round(sum(dd) / len(dd), 1) if dd else None}
        by_bucket = {}
        for lo, hi in SCORE_BUCKETS:
            rows = [r for r in S if lo <= r["score"] < hi]
            if rows:
                by_bucket[f"{lo}–{min(hi, 10):g}"] = agg(rows)
        by_verdict = {v: agg([r for r in S if r["verdict"] == v]) for v in ("BUY SETUP", "WATCH", "AVOID")
                      if any(r["verdict"] == v for r in S)}
        by_lp = {lp or "inconnu": agg([r for r in S if r["launchpad"] == lp]) for lp in {r["launchpad"] for r in S}}
        caps = [("< 100 k$", 0, 1e5), ("100 k–1 M$", 1e5, 1e6), ("1–10 M$", 1e6, 1e7), ("> 10 M$", 1e7, 1e30)]
        by_cap = {lbl: agg(rows) for lbl, lo, hi in caps
                  if (rows := [r for r in S if r["mcap0"] and lo <= r["mcap0"] < hi])}
        tp = sum(1 for r in S if r["verdict"] == "BUY SETUP" and r["change_pct"] - FEES_ROUNDTRIP_PCT >= rise)
        fp = sum(1 for r in S if r["verdict"] == "BUY SETUP" and r["change_pct"] - FEES_ROUNDTRIP_PCT < rise)
        fn = sum(1 for r in S if r["verdict"] != "BUY SETUP" and r["change_pct"] - FEES_ROUNDTRIP_PCT >= rise)
        report["horizons"][h] = {
            "observations": len(S), "overall": agg(S), "by_score": by_bucket, "by_verdict": by_verdict,
            "by_launchpad": by_lp, "by_mcap": by_cap,
            "buy_setup": {"precision": round(tp / (tp + fp), 3) if tp + fp else None,
                          "recall": round(tp / (tp + fn), 3) if tp + fn else None, "false_positives": fp},
            "probability_model": fit_probability_model(S, rise, min_test) if h in PROB_HORIZONS else None,
        }
    report["scalp"] = scalp_report(db)
    report["note"] = ("Biais de sélection : seuls les tokens que tu as choisi d'analyser sont inclus. "
                      "Les pondérations ne sont jamais modifiées automatiquement ; chaque changement crée une nouvelle "
                      "version du modèle.")
    report["model_versions"] = [dict(r, weights=json.loads(r["weights"]), thresholds=json.loads(r["thresholds"]))
                                for r in db.all("SELECT * FROM model_versions ORDER BY id DESC LIMIT 20")]
    return report


def scalp_report(db) -> dict:
    rows = db.all("SELECT s.*, a.launchpad, a.mcap FROM scalp_outcomes s JOIN token_analyses a ON a.id = s.analysis_id "
                  "WHERE s.status='done'")
    pending = db.one("SELECT COUNT(*) c FROM scalp_outcomes WHERE status='pending'")["c"]

    def agg(rs):
        n = len(rs)
        wins = sum(1 for r in rs if r["outcome"] == "win")
        losses = sum(1 for r in rs if r["outcome"] in ("loss", "ambiguous"))
        pnl = [r["pnl_pct"] for r in rs if r["pnl_pct"] is not None]
        mins = sorted(r["minutes"] for r in rs if r["outcome"] == "win" and r["minutes"] is not None)
        return {"n": n, "wins": wins, "losses": losses, "open": n - wins - losses,
                "win_rate": round(wins / n, 3) if n else None, "ci95": [round(x, 3) for x in wilson(wins, n)],
                "avg_pnl_pct": round(sum(pnl) / len(pnl), 2) if pnl else None,
                "median_minutes_to_target": mins[len(mins) // 2] if mins else None}
    by_score = {}
    for lo, hi in SCORE_BUCKETS:
        rs = [r for r in rows if r["score"] is not None and lo <= r["score"] < hi]
        if rs:
            by_score[f"{lo}–{min(hi, 10):g}"] = agg(rs)
    by_decision = {d: agg([r for r in rows if r["decision"] == d]) for d in {r["decision"] for r in rows} if d}
    return {"observations": len(rows), "pending": pending, "overall": agg(rows) if rows else None,
            "by_score": by_score, "by_decision": by_decision,
            "definition": "Trade rejoué minute par minute pendant la fenêtre de suivi après l'analyse : gagnant si l'objectif est touché "
                          "avant le stop ; si les deux le sont dans la même minute, compté perdant. PnL moyen après coût "
                          "aller-retour estimé."}
