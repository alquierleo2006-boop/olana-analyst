import json

from analyst.config import DEFAULT_SETTINGS, Settings, deep_merge
from analyst.db import DB
from analyst.engines.scalp import checklist

S = deep_merge(DEFAULT_SETTINGS, {})


def base(**over):
    r = {
        "modules": {k: {"status": "terminé"} for k in ("market", "security", "holders", "clusters", "developer", "social", "liquidity")},
        "market": {"mcap": {"v": 9000}, "txns": {"m5": {"buys": 60, "sells": 30}},
                   "curve_activity": {"tx_per_min_5m": 18, "progress_per_min": 1.2}},
        "security": {"checks": [{"name": "MINT_AUTHORITY", "ok": True}]},
        "risks": [],
        "holders": {"concentration_excl_technical": {"top10": 18}, "top": [{"kind": "wallet", "pct": 3.1}]},
        "clusters": {"fresh_wallets": {"supply_pct": 6}, "clusters": []},
        "developer": {"identified": True, "current_holding_pct": {"v": 2.0}, "reputation": {"label": "neutre", "reasons": []},
                      "history_stats": {"count": 1}},
        "social": {"accounts": {"x": [{"status": "PROBABLEMENT AUTHENTIQUE"}]}},
        "liquidity": {"impact_tests": [{"size_sol": 0.25, "buy_impact_pct": 0.8, "sell_impact_pct": 0.8}]},
    }
    for k, v in over.items():
        r[k] = v
    return r


def test_green_light_in_zone():
    c = checklist(base(), S)
    assert c["decision"] == "ENTRÉE POSSIBLE", c
    p = c["plan"]
    assert p["target_mcap"] == 9000 * 1.4 and p["stop_mcap"] == 9000 * 0.8 and p["position_sol"] == 0.25
    assert abs(p["cost_pct"] - 3.6) < 1e-6 and p["gain_sol"] > 0 > p["loss_sol"]


def test_dev_holding_blocks():
    r = base(developer={"identified": True, "current_holding_pct": {"v": 22.0}, "reputation": {"label": "neutre"}})
    assert checklist(r, S)["decision"] == "NE PAS ENTRER"


def test_fresh_wallets_line():
    c = checklist(base(clusters={"fresh_wallets": {"supply_pct": 35, "count": 6, "of": 20}, "clusters": []}), S)
    fw = next(x for x in c["checks"] if x["name"] == "🌱 Fresh wallets")
    assert fw["status"] == "bloquant" and "6 nouveau(x) wallet(s) sur 20" in fw["detail"]
    assert c["decision"] == "NE PAS ENTRER"
    c = checklist(base(clusters={"fresh_wallets": {"supply_pct": 15, "count": 3, "of": 20}, "clusters": []}), S)
    assert next(x for x in c["checks"] if x["name"] == "🌱 Fresh wallets")["status"] == "attention"
    c = checklist(base(clusters={"fresh_wallets": {"supply_pct": 0, "count": 0, "of": 20}, "clusters": []}), S)
    assert next(x for x in c["checks"] if x["name"] == "🌱 Fresh wallets")["status"] == "ok"


def test_bundle_blocks():
    r = base(clusters={"fresh_wallets": {"supply_pct": 0}, "clusters": [{"supply_pct": 35, "wallets": ["a", "b", "c"]}]})
    c = checklist(r, S)
    assert next(x for x in c["checks"] if x["name"] == "Bundle / snipers")["status"] == "bloquant"
    assert c["decision"] == "NE PAS ENTRER"


def test_out_of_zone_and_weak_signals_wait():
    r = base(market={"mcap": {"v": 40000}, "txns": {"m5": {"buys": 20, "sells": 20}}},
             social={"accounts": {"x": [{"status": "NON VÉRIFIÉ"}]}})
    c = checklist(r, S)
    assert c["decision"] == "ATTENDRE", c


def test_sell_pressure_blocks():
    r = base(market={"mcap": {"v": 9000}, "txns": {"m5": {"buys": 10, "sells": 40}}})
    assert checklist(r, S)["decision"] == "NE PAS ENTRER"


def test_settings_migration_applies_user_profile():
    db = DB(":memory:")
    old = {"trading_mode": "scalp", "scalp": {"auto_watch": True, "interval_s": 2, "target_multiple": 2.0,
                                              "stop_pct": 30, "position_sol": 0.5}}
    db.execute("INSERT INTO application_settings(key, value) VALUES('settings', ?)", (json.dumps(old),))
    sc = Settings(db).all()["scalp"]
    assert sc["position_sol"] == 0.25 and sc["stop_pct"] == 20 and sc["take_profit_pct"] == 40
    assert sc["interval_s"] == 2  # les autres réglages de l'utilisateur sont conservés


def test_old_modes_migrated_to_scalp_weights():
    db = DB(":memory:")
    old = {"trading_mode": "hold", "weights": {"onchain": 25, "momentum": 20, "narrative": 25, "social": 20,
                                               "credibility": 10, "smart_money": 0},
           "mode_weights": {"scalp": {"onchain": 30, "momentum": 45, "narrative": 10, "social": 10, "credibility": 0,
                                      "smart_money": 5}}}
    db.execute("INSERT INTO application_settings(key, value) VALUES('settings', ?)", (json.dumps(old),))
    s = Settings(db).all()
    assert "trading_mode" not in s and "mode_weights" not in s
    assert s["weights"]["momentum"] == 45  # les pondérations scalp personnalisées sont conservées


def test_scalp_outcome_replay():
    from analyst.engines.tracker import scalp_outcome, scalp_pnl
    t0 = 1_000_000
    def c(i, o, h, l, cl):
        return [t0 // 60 * 60 + i * 60, o, h, l, cl, 1]
    up = [c(0, 1.0, 1.05, 0.95, 1.02), c(1, 1.02, 1.2, 1.0, 1.15), c(2, 1.15, 1.45, 1.1, 1.4), c(3, 1.4, 1.4, 0.7, 0.75)]
    o = scalp_outcome(up, t0, 40, 20)
    assert o["outcome"] == "win" and o["minutes"] == 2
    assert scalp_pnl(o, 40, 20, 3.6) == 40 - 3.6
    down = [c(0, 1.0, 1.1, 0.95, 1.0), c(1, 1.0, 1.02, 0.79, 0.8), c(2, 0.8, 1.6, 0.8, 1.5)]
    assert scalp_outcome(down, t0, 40, 20)["outcome"] == "loss"
    both = [c(0, 1.0, 1.5, 0.7, 1.0)]
    assert scalp_outcome(both, t0, 40, 20)["outcome"] == "ambiguous"  # compté perdant (prudent)
    flat = [c(i, 1.0, 1.1, 0.9, 1.05) for i in range(5)]
    o = scalp_outcome(flat, t0, 40, 20)
    assert o["outcome"] == "open" and abs(o["final_change_pct"] - 5) < 1e-9


def test_scalp_report_by_score_and_decision():
    from analyst.engines.tracker import scalp_report
    db = DB(":memory:")
    for i, (score, dec, out, pnl) in enumerate([(8, "ENTRÉE POSSIBLE", "win", 36.4), (8.5, "ENTRÉE POSSIBLE", "loss", -23.6),
                                                 (5, "ATTENDRE", "loss", -23.6)]):
        aid = db.execute("INSERT INTO token_analyses(mint, created_at, status) VALUES(?,?,?)", (f"m{i}", 1.0 + i, "complète"))
        db.execute("INSERT INTO scalp_outcomes(analysis_id, due_at, status, outcome, pnl_pct, score, decision, minutes) "
                   "VALUES(?,?,?,?,?,?,?,?)", (aid, 0, "done", out, pnl, score, dec, 4))
    rep = scalp_report(db)
    assert rep["observations"] == 3
    assert rep["by_decision"]["ENTRÉE POSSIBLE"]["win_rate"] == 0.5
    assert rep["by_score"]["8–10"]["n"] == 2 and rep["by_score"]["4–6"]["wins"] == 0
