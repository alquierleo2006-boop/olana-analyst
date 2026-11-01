import asyncio

from fastapi.testclient import TestClient

from analyst.app import create_app
from analyst.engines.live import Watch, evaluate_alerts

from .fakes import CREATOR, CURVE, MINT, Fake


def test_live_curve_tracking_and_alerts():
    # La market cap monte (30 → 45 SOL virtuels) puis retombe (→ 36) : objectif puis retournement.
    fake = Fake(curve_seq=[30, 33, 38, 45, 45, 36, 36])
    app = create_app(transport=fake.transport(), db_path=":memory:", start_background=False)
    st = app.state.st
    with TestClient(app) as c:
        def run():
            async def go():
                from analyst.engines.live import Watch
                w = Watch(MINT, {"symbol": "RCAT", "supply": 1e9, "creator": CREATOR, "curve_address": CURVE},
                          {"interval_s": 3, "reversal_pct": 15, "pump_alert_pct": 1000})
                mc0 = None
                for n in range(7):
                    if n == 5:
                        fake.dev_balance = 10**12  # le dev vend 80 % de ses tokens
                    await st.live.tick(w, n * 5)  # n*5 : force la vérification du dev à chaque tick
                    if mc0 is None:
                        mc0 = w.points[0][1]
                        w.targets = {"above": mc0 * 1.4, "below": mc0 * 0.5}
                return w
            return asyncio.run(go()) if False else c.portal.call(go)
        w = run()
    snap = st.live.snapshot(w)
    codes = [a["code"] for a in w.alerts]
    assert snap["state"]["source"] == "bonding curve (on-chain)"
    assert len(w.points) == 7 and snap["high"] > w.points[0][1]
    assert "TARGET_UP" in codes, codes
    assert "REVERSAL" in codes, codes
    assert "DEV_SOLD" in codes, codes
    assert snap["sol_flow"]["5m"] is not None


def test_alert_rules_fire_once():
    w = Watch("m", {}, {"reversal_pct": 10})
    import time
    t = time.time()
    for i, mc in enumerate([100, 130, 150, 150]):
        w.points.append((t + i, mc, 1000, None))
        evaluate_alerts(w, mc, 1000)
    w.points.append((t + 5, 120, 1000, None))
    a1 = evaluate_alerts(w, 120, 1000)
    a2 = evaluate_alerts(w, 119, 1000)
    assert [x["code"] for x in a1] == ["REVERSAL"] and a2 == []


def test_scalp_mode_weights_and_auto_watch():
    fake = Fake()
    app = create_app(transport=fake.transport(), db_path=":memory:", start_background=False)
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["settings"]["trading_mode"] == "scalp"
        aid = c.post("/api/analyze", json={"mint": MINT}).json()["analysis_id"]
        st = app.state.st
        c.portal.call(st.analyzer.live[aid].done.wait)
        r = c.get(f"/api/analyses/{aid}").json()
        assert r["scores"]["trading_mode"] == "scalp"
        assert r["scores"]["categories"]["momentum"]["weight"] == 40
        assert r["live_watch"]["active"] is True
        lst = c.get("/api/live").json()
        assert lst and lst[0]["mint"] == MINT
        assert c.delete(f"/api/live/{MINT}").json()["ok"]
        c.put("/api/settings", json={"trading_mode": "hold"})
        aid2 = c.post("/api/analyze", json={"mint": MINT}).json()["analysis_id"]
        c.portal.call(st.analyzer.live[aid2].done.wait)
        r2 = c.get(f"/api/analyses/{aid2}").json()
        assert r2["scores"]["categories"]["credibility"]["weight"] == 25


def test_auto_targets_use_first_live_value():
    fake = Fake(curve_seq=[30, 31, 32])
    app = create_app(transport=fake.transport(), db_path=":memory:", start_background=False)
    st = app.state.st
    with TestClient(app) as c:
        async def go():
            w = Watch(MINT, {"curve_address": CURVE, "supply": 1e9}, {"auto_targets": True, "target_multiple": 2, "stop_pct": 30})
            await st.live.tick(w, 1)
            return w
        w = c.portal.call(go)
    mc = w.points[0][1]
    assert w.targets["above"] == round(mc * 2) and w.targets["below"] == round(mc * 0.7)
    assert not w.alerts  # aucun stop déclenché à tort au démarrage
