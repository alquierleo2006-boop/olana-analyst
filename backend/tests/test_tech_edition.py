"""Édition TECH. Ces tests tournent dans un processus séparé avec ANALYST_EDITION=tech (voir test_editions.py)."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ANALYST_EDITION") != "tech", reason="édition tech uniquement")


def _run(fake):
    from fastapi.testclient import TestClient

    from analyst.app import create_app
    from .fakes import MINT
    app = create_app(transport=fake.transport(), db_path=":memory:", start_background=False)
    with TestClient(app) as c:
        c.portal.call(app.state.st.narratives.refresh)
        aid = c.post("/api/analyze", json={"mint": MINT}).json()["analysis_id"]
        c.portal.call(app.state.st.analyzer.live[aid].done.wait)
        health = c.get("/api/health").json()
        return c.get(f"/api/analyses/{aid}").json(), health, c.get("/api/settings").json()["settings"]


def test_tech_edition_full_analysis():
    from .fakes import Fake
    r, health, settings = _run(Fake())
    assert health["edition"] == "tech"
    assert settings["shortcut"] == "CommandOrControl+Alt+Space"
    assert "project" in r["modules"] and "factcheck" in r["modules"]
    assert r["status"] == "complète", r["modules"]
    sc = r["scores"]
    assert sc["categories"]["credibility"]["weight"] == 25
    names = [c["name"] for c in sc["scalp"]["checks"]]
    assert "Produit réel (GitHub)" in names and "Zone de market cap" not in names
    gh = next(c for c in sc["scalp"]["checks"] if c["name"] == "Produit réel (GitHub)")
    assert gh["status"] == "ok" and "robocat/agent" in gh["detail"], gh
    assert r["project"]["github"]["stars"] == 120
    assert any("OpenAI" in c["text"] for c in r["factcheck"]["claims"])
    claims_check = next(c for c in sc["scalp"]["checks"] if c["name"] == "Affirmations")
    assert claims_check["status"] == "attention" and "OpenAI" in claims_check["detail"]
    assert r["probabilities"]["scalp"]["label"].endswith("(6 h)")
    names = [c["name"] for c in sc["scalp"]["checks"]]
    assert "Momentum 20 min" in names and "Momentum 1 h" not in names
    o = r["originality"]
    assert o["verdict"] == "peu originale", o
    assert "partnership" not in o["keywords"] and "openai" not in o["keywords"], o["keywords"]
    assert any("elizaOS/eliza" in x for x in o["reasons"]), o["reasons"]
    assert all(x["repo"] != "robocat/agent" for x in o["similar_repos"])  # son propre dépôt n'est pas un « concurrent »
    oc = next(c for c in sc["scalp"]["checks"] if c["name"] == "Originalité")
    assert oc["status"] == "attention"


def test_tech_copycat_blocks_entry():
    from .fakes import Fake
    r, _, _ = _run(Fake(copycat=True))
    o = r["originality"]
    assert o["verdict"] == "copie probable" and "copycat" in o["reasons"][0], o
    oc = next(c for c in r["scores"]["scalp"]["checks"] if c["name"] == "Originalité")
    assert oc["status"] == "bloquant"
    assert r["scores"]["scalp"]["decision"] == "NE PAS ENTRER"


def test_tech_fork_blocks_entry():
    from .fakes import Fake
    r, _, _ = _run(Fake(gh_fork=True))
    gh = next(c for c in r["scores"]["scalp"]["checks"] if c["name"] == "Produit réel (GitHub)")
    assert gh["status"] == "bloquant" and "famous/ai-agent" in gh["detail"]
    assert r["scores"]["scalp"]["decision"] == "NE PAS ENTRER"
    assert r["scores"]["verdict"] == "AVOID"
