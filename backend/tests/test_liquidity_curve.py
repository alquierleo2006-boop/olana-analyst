"""Le problème signalé : alerte « liquidité < 5 000 $ » sur des tokens Pump.fun à ~4 000 $ de market cap."""
from .test_end_to_end import run_analysis
from .fakes import Fake


def _liq_risks(r):
    return [x for x in r["risks"] if x["code"] == "LIQUIDITY" or "liquid" in x["message"].lower()]


def test_tiny_pumpfun_token_curve_read_ok():
    c, r, ev, st = run_analysis(Fake(tiny=True, curve_active=True), False)
    assert r["liquidity"]["mode"] == "bonding_curve"
    assert r["liquidity"]["risk_level"]["level"] == "faible"
    assert not _liq_risks(r), r["risks"]
    assert not any("5 000" in n for n in r["scores"]["negatives"])


def test_tiny_pumpfun_token_rpc_saturated_then_recovers():
    # Le RPC refuse 2 lectures de la curve (429) : la relecture doit finir par réussir.
    c, r, ev, st = run_analysis(Fake(tiny=True, curve_active=True, curve_fail=2), False)
    assert r["liquidity"]["mode"] == "bonding_curve"
    assert not _liq_risks(r), r["risks"]


def test_tiny_token_curve_unreadable_never_uses_5000_rule():
    # Curve illisible (RPC saturé en permanence) : la règle des 5 000 $ ne doit jamais s'appliquer.
    c, r, ev, st = run_analysis(Fake(tiny=True, curve_active=True, curve_fail=99), False)
    assert r["liquidity"]["mode"] == "bonding_curve_presumed", r["liquidity"]
    assert not any("5 000" in x for x in r["liquidity"]["risk_level"]["reasons"])
    assert not any(x["code"] == "LIQUIDITY" and x["level"] == "critique" for x in r["risks"]), r["risks"]
