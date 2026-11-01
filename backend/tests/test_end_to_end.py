import asyncio
import os

import pytest
from fastapi.testclient import TestClient

os.environ.pop("ANALYST_TOKEN", None)
from analyst.app import create_app  # noqa: E402

from .fakes import CREATOR, MINT, Fake  # noqa: E402


def run_analysis(fake, prepare_narratives=True):
    app = create_app(transport=fake.transport(), db_path=":memory:", start_background=False)
    st = app.state.st
    with TestClient(app) as c:
        if prepare_narratives:
            c.portal.call(st.narratives.refresh)
        r = c.post("/api/analyze", json={"mint": MINT})
        assert r.status_code == 200, r.text
        aid = r.json()["analysis_id"]
        events = []
        with c.websocket_connect(f"/ws/analyses/{aid}") as ws:
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev["type"] in ("complete", "error"):
                    break
        full = c.get(f"/api/analyses/{aid}").json()
        return c, full, events, st


def test_full_analysis_pumpfun():
    fake = Fake()
    app = create_app(transport=fake.transport(), db_path=":memory:", start_background=False)
    st = app.state.st
    with TestClient(app) as c:
        c.portal.call(st.narratives.refresh)
        aid = c.post("/api/analyze", json={"mint": MINT}).json()["analysis_id"]
        events = []
        with c.websocket_connect(f"/ws/analyses/{aid}") as ws:
            while True:
                ev = ws.receive_json(); events.append(ev)
                if ev["type"] in ("complete", "error"):
                    break
        r = c.get(f"/api/analyses/{aid}").json()
        hist = c.get("/api/history").json()
        perf = c.get("/api/performance").json()
        nar = c.get("/api/narratives").json()
    types = [e["type"] for e in events]
    assert "first_result" in types and types[-1] == "complete", types
    assert r["status"] == "complète", r["modules"]
    tok = r["token"]
    assert tok["launchpad"]["id"] == "pumpfun" and tok["launchpad"]["status"] == "vérifié on-chain"
    assert tok["name"] == "Robo Cat" and tok["symbol"] == "RCAT"
    assert r["developer"]["address"] == CREATOR and r["developer"]["address_status"] == "vérifié"
    assert r["market"]["mcap"]["v"] == 420000 and r["market"]["fdv"]["src"] == "DexScreener"
    assert r["market"]["volume"]["m15"]["v"] == 30000.0 and r["market"]["volume"]["m1"]["v"] > 0
    h = r["holders"]
    assert h["top"][0]["kind"] == "pool" and h["top"][0]["label"].startswith("Pool")  # la bonding curve n'est pas comptée comme holder
    assert h["concentration_excl_technical"]["top10"] == pytest.approx(10.0)  # 40+30+25+5 milliards / 1 000 milliards
    assert h["total"]["v"] == 1834 and h["total"]["src"] == "RugCheck"
    cl = r["clusters"]["clusters"]
    assert cl and cl[0]["wallets"] and len(cl[0]["wallets"]) == 2, r["clusters"]
    soc = r["social"]["accounts"]
    assert soc["website"][0]["status"] == "AUTHENTIQUE VÉRIFIÉ"
    assert soc["x"][0]["status"] == "PROBABLEMENT AUTHENTIQUE"
    assert soc["telegram"][0]["status"] == "PROBABLEMENT AUTHENTIQUE"
    assert soc["instagram"][0]["status"] == "NON TROUVÉ"
    claims = r["factcheck"]["claims"]
    assert any("OpenAI" in c["text"] for c in claims)
    assert all(c["status"] in ("NON VÉRIFIÉ", "PARTIELLEMENT CONFIRMÉ", "CONFIRMÉ PAR PLUSIEURS SOURCES") for c in claims)
    assert r["narrative"]["score"]["available"] is True
    assert any(m["matched_terms"] for m in r["narrative"]["matches"]), r["narrative"]
    sc = r["scores"]
    assert 0 <= sc["global"] <= 10 and sc["verdict"] in ("BUY SETUP", "WATCH", "AVOID")
    assert set(sc["categories"]) >= {"onchain", "momentum", "narrative", "social", "credibility", "smart_money"}
    assert r["probabilities"]["horizons"]["1h"]["message"] == "DONNÉES INSUFFISANTES POUR UNE PROBABILITÉ FIABLE"
    assert r["timing"]["first_result_ms"] < 5000
    assert r["summary"]
    assert hist[0]["id"] == aid and hist[0]["score"] == sc["global"]
    assert perf["horizons"]["1h"]["observations"] == 0
    assert nar["items"], nar
    print("\nSCORE", sc["global"], sc["verdict"], sc["verdict_reason"])
    print("first result ms", r["timing"]["first_result_ms"], "total", r["timing"]["total_ms"])


def test_critical_risks_force_avoid():
    c, r, ev, st = run_analysis(Fake(mint_auth="Auth1111111111111111111111111111111111111111", no_sell=True), False)
    codes = {x["code"] for x in r["risks"]}
    assert "MINT_AUTHORITY" in codes and "NO_SELL_ROUTE" in codes
    assert r["scores"]["verdict"] == "AVOID"
    assert r["scores"]["risk"]["label"] == "critique"


def test_thin_liquidity_is_critical():
    c, r, ev, st = run_analysis(Fake(thin=True), False)
    assert r["liquidity"]["risk_level"]["level"] == "critique"
    assert any(x["code"] == "LIQUIDITY" and x["level"] == "critique" for x in r["risks"])
    assert r["scores"]["verdict"] == "AVOID"


def test_invalid_address_rejected():
    app = create_app(transport=Fake().transport(), db_path=":memory:", start_background=False)
    with TestClient(app) as c:
        r = c.post("/api/analyze", json={"mint": "0OIl-not-an-address"})
        assert r.status_code == 400 and "invalide" in r.json()["detail"]


def test_nonexistent_token_no_fake_analysis():
    c, r, ev, st = run_analysis(Fake(no_mint=True), False)
    assert ev[-1]["type"] == "error"
    assert r["status"] == "introuvable" and "scores" not in r


def test_provider_outage_is_partial_not_fabricated():
    c, r, ev, st = run_analysis(Fake(down=["dexscreener", "geckoterminal", "rugcheck"]), False)
    assert r["status"] in ("complète", "partielle")
    m = r["market"]
    # sans DEX, le prix vient de la bonding curve on-chain, marqué « estimé » avec sa source
    assert m.get("source_errors")
    assert r["holders"]["total"]["st"] == "indisponible"
    assert r["narrative"]["score"]["available"] is False


def test_concurrent_analyses():
    fake = Fake()
    app = create_app(transport=fake.transport(), db_path=":memory:", start_background=False)
    with TestClient(app) as c:
        ids = [c.post("/api/analyze", json={"mint": MINT}).json()["analysis_id"] for _ in range(3)]
        st = app.state.st
        c.portal.call(lambda: asyncio.gather(*[st.analyzer.live[i].done.wait() for i in ids]))
        res = [c.get(f"/api/analyses/{i}").json() for i in ids]
        assert all(x["status"] in ("complète", "partielle") for x in res)
        hist = c.get("/api/history").json()
        assert len(hist) == 3
        cmp_ = c.get(f"/api/compare?ids={','.join(map(str, ids))}").json()
        assert len(cmp_) == 3


def test_auth_token_required(monkeypatch):
    monkeypatch.setenv("ANALYST_TOKEN", "secret123")
    app = create_app(transport=Fake().transport(), db_path=":memory:", start_background=False)
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 401
        assert c.get("/api/health", headers={"x-analyst-token": "secret123"}).status_code == 200
