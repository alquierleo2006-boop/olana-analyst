from fastapi.testclient import TestClient

from analyst.app import create_app

from .fakes import MINT, Fake

TWEET = "https://x.com/robocatsol/status/1856319223127924736"


def _check(fake, url=TWEET, mint=None, analyze=False):
    app = create_app(transport=fake.transport(), db_path=":memory:", start_background=False)
    with TestClient(app) as c:
        r = c.post("/api/xcheck", json={"url": url, "mint": mint, "analyze": analyze})
        return r


def test_clean_project_from_tweet():
    r = _check(Fake(old_domain=True), analyze=True).json()
    st = {c["name"]: c["status"] for c in r["checks"]}
    assert r["cas_on_x"] == [MINT] and r["ca"] == MINT
    assert st["CA publié sur X"] == "ok" and st["CA identique X ↔ site"] == "ok" and st["Lien site → compte X"] == "ok"
    assert r["verdict"] == "CLEAN", r["checks"]
    assert r["analysis_id"]  # l'analyse complète du CA est lancée


def test_site_shows_other_ca_is_suspect():
    other = "So11111111111111111111111111111111111111112"
    r = _check(Fake(old_domain=True, site_ca=other)).json()
    assert r["verdict"] == "SUSPECT"
    assert any(c["name"] == "CA identique X ↔ site" and c["status"] == "bloquant" for c in r["checks"])


def test_entered_ca_not_matching_is_suspect():
    r = _check(Fake(old_domain=True), mint="So11111111111111111111111111111111111111112").json()
    assert r["verdict"] == "SUSPECT"
    assert any(c["name"] == "CA saisi" and c["status"] == "bloquant" for c in r["checks"])


def test_new_domain_needs_checking():
    r = _check(Fake(new_domain=True)).json()
    assert r["verdict"] == "À VÉRIFIER", r["checks"]
    assert any(c["name"] == "Site du projet" and c["status"] == "attention" for c in r["checks"])


def test_domain_younger_than_a_week_needs_checking():
    r = _check(Fake()).json()  # domaine enregistré il y a ~3 jours
    assert r["verdict"] == "À VÉRIFIER"


def test_profile_link_works_via_dexscreener():
    # Profil X illisible gratuitement : le CA et le site sont retrouvés via le token qui déclare ce compte.
    r = _check(Fake(old_domain=True, declared=True), url="https://x.com/robocatsol", analyze=True).json()
    st = {c["name"]: c["status"] for c in r["checks"]}
    assert r["ca"] == MINT and r["analysis_id"]
    assert st["Token lié à ce compte X"] == "ok" and st["Lien site → compte X"] == "ok"
    assert st["CA identique site ↔ DexScreener"] == "ok"
    assert r["verdict"] == "CLEAN", r["checks"]


def test_at_handle_input_accepted():
    r = _check(Fake(old_domain=True, declared=True), url="@robocatsol").json()
    assert r["kind"] == "profile" and r["ca"] == MINT


def test_copies_using_same_x_account_are_flagged():
    r = _check(Fake(old_domain=True, declared=True, impostor=True), url="https://x.com/robocatsol").json()
    assert r["ca"] == MINT  # le plus ancien est retenu comme original
    tl = next(c for c in r["checks"] if c["name"] == "Token lié à ce compte X")
    assert tl["status"] == "attention" and "2 tokens" in tl["detail"]
    assert r["verdict"] == "À VÉRIFIER"


def test_profile_link_limits_are_explained():
    r = _check(Fake(), url="https://x.com/robocatsol").json()
    assert r["kind"] == "profile" and r["limits"]
    assert r["verdict"] in ("À VÉRIFIER", "SUSPECT")


def test_rejects_non_x_links():
    assert _check(Fake(), url="https://example.com").status_code == 400
